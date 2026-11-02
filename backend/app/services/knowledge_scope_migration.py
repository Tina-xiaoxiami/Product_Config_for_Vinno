"""Explicit, transactional migration of legacy Q&A identities to scoped identities."""

from __future__ import annotations

from collections import Counter
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import tempfile


QUESTIONS = "knowledge_questions"
PHRASINGS = "knowledge_question_phrasings"
QUESTION_COLUMNS = (
    "id", "question_text", "normalized_question", "status", "asked_count",
    "last_asked_at", "created_at", "updated_at",
)
PHRASING_COLUMNS = (
    "id", "question_id", "phrasing_text", "normalized_phrasing", "phrasing_type", "created_at",
)
TEMP_QUESTIONS = "_kh_scope_questions_new"
TEMP_PHRASINGS = "_kh_scope_phrasings_new"


class KnowledgeScopeMigrationError(ValueError):
    """The selected schema or records cannot be safely migrated automatically."""


def _identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _unique_keys(connection: sqlite3.Connection, table: str) -> set[tuple[str, ...]]:
    keys = set()
    for index in connection.execute(f"PRAGMA index_list({_identifier(table)})").fetchall():
        if index[2]:
            columns = tuple(row[2] for row in connection.execute(
                f"PRAGMA index_info({_identifier(index[1])})"
            ).fetchall())
            keys.add(columns)
    return keys


def _check_foreign_keys(connection: sqlite3.Connection) -> None:
    try:
        failures = connection.execute("PRAGMA foreign_key_check").fetchall()
    except sqlite3.Error as exc:
        raise KnowledgeScopeMigrationError("原库外键结构无法核验，已停止迁移") from exc
    if failures:
        raise KnowledgeScopeMigrationError("原库存在外键违规，已停止迁移")


def _related_tables(connection: sqlite3.Connection, tables: set[str]) -> list[str]:
    related = {QUESTIONS, PHRASINGS}
    while True:
        additions = {
            table for table in tables - related
            if any(row[2] in related for row in connection.execute(
                f"PRAGMA foreign_key_list({_identifier(table)})"
            ).fetchall())
        }
        if not additions:
            return sorted(related)
        related.update(additions)


def _inspect(connection: sqlite3.Connection) -> tuple[str, list[str]]:
    tables = _tables(connection)
    if not {QUESTIONS, PHRASINGS} <= tables:
        raise KnowledgeScopeMigrationError("数据库缺少问答或问法表")
    if {TEMP_QUESTIONS, TEMP_PHRASINGS} & tables:
        raise KnowledgeScopeMigrationError("迁移临时表已存在，请先人工核对来源")
    scope_flags = []
    for table, legacy in [(QUESTIONS, QUESTION_COLUMNS), (PHRASINGS, PHRASING_COLUMNS)]:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({_identifier(table)})")}
        if columns not in (set(legacy), set(legacy) | {"scope_key"}):
            raise KnowledgeScopeMigrationError(f"{table} 包含未知列或缺失列，不能自动重建")
        scope_flags.append("scope_key" in columns)
        sql = connection.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
        if re.search(r"\b(?:CHECK\s*\(|GENERATED\b|WITHOUT\s+ROWID\b)", sql, re.I):
            raise KnowledgeScopeMigrationError("存在额外表约束，需人工核对迁移方案")
    _check_foreign_keys(connection)
    if any(scope_flags) and not all(scope_flags):
        raise KnowledgeScopeMigrationError("范围迁移仅完成部分表，已停止")
    question_keys = _unique_keys(connection, QUESTIONS)
    phrasing_keys = _unique_keys(connection, PHRASINGS)
    fks = connection.execute(f"PRAGMA foreign_key_list({PHRASINGS})").fetchall()
    if all(scope_flags):
        expected_fk = {(QUESTIONS, "question_id", "id", "CASCADE"), (QUESTIONS, "scope_key", "scope_key", "CASCADE")}
        actual_fk = {(row[2], row[3], row[4], row[6]) for row in fks}
        if (question_keys != {("scope_key", "normalized_question"), ("id", "scope_key")}
                or phrasing_keys != {("scope_key", "normalized_phrasing")}
                or actual_fk != expected_fk or len({row[0] for row in fks}) != 1):
            raise KnowledgeScopeMigrationError("scope_key 已存在但唯一约束或外键未完成，已停止")
        return "already_current", _related_tables(connection, tables)
    if question_keys != {("normalized_question",)} or phrasing_keys != {("normalized_phrasing",)}:
        raise KnowledgeScopeMigrationError("发现未知唯一约束，不能自动重建")
    if {(row[2], row[3], row[4], row[6]) for row in fks} != {(QUESTIONS, "question_id", "id", "CASCADE")}:
        raise KnowledgeScopeMigrationError("原问法外键不符合预期，已停止")
    if connection.execute(f"PRAGMA foreign_key_list({QUESTIONS})").fetchall():
        raise KnowledgeScopeMigrationError("原问题表存在额外外键，已停止")
    return "ready", _related_tables(connection, tables)


def _snapshot(connection: sqlite3.Connection, tables: list[str]) -> dict[str, Counter]:
    result = {}
    for table in tables:
        columns = QUESTION_COLUMNS if table == QUESTIONS else PHRASING_COLUMNS if table == PHRASINGS else None
        select = ",".join(_identifier(column) for column in columns) if columns else "*"
        result[table] = Counter(connection.execute(f"SELECT {select} FROM {_identifier(table)}").fetchall())
    return result


def _backup(database: Path) -> Path:
    with tempfile.NamedTemporaryFile(prefix=database.name + ".knowledge-scope-", suffix=".db", dir=database.parent, delete=False) as reserved:
        destination = Path(reserved.name)
    try:
        # The writer holds BEGIN IMMEDIATE before this reader opens, so no writer
        # can change the source between the online backup and the schema copy.
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(destination)) as target:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise KnowledgeScopeMigrationError("在线备份完整性核验失败")
        return destination
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def _rebuild(connection: sqlite3.Connection) -> None:
    objects = connection.execute(
        "SELECT sql FROM sqlite_master WHERE tbl_name IN (?,?) "
        "AND type IN ('index','trigger') AND sql IS NOT NULL ORDER BY type,name",
        (QUESTIONS, PHRASINGS),
    ).fetchall()
    sequences = {}
    if "sqlite_sequence" in _tables(connection):
        sequences = dict(connection.execute(
            "SELECT name,seq FROM sqlite_sequence WHERE name IN (?,?)", (QUESTIONS, PHRASINGS)
        ).fetchall())
    connection.execute(f"""CREATE TABLE {TEMP_QUESTIONS} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_text TEXT NOT NULL, normalized_question TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', asked_count INTEGER NOT NULL DEFAULT 1,
        last_asked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        scope_key TEXT NOT NULL DEFAULT '',
        UNIQUE(scope_key, normalized_question), UNIQUE(id, scope_key)
    )""")
    connection.execute(f"""CREATE TABLE {TEMP_PHRASINGS} (
        id INTEGER PRIMARY KEY AUTOINCREMENT, question_id INTEGER NOT NULL,
        phrasing_text TEXT NOT NULL, normalized_phrasing TEXT NOT NULL,
        phrasing_type TEXT NOT NULL DEFAULT 'alias',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        scope_key TEXT NOT NULL DEFAULT '',
        UNIQUE(scope_key, normalized_phrasing),
        FOREIGN KEY(question_id,scope_key) REFERENCES {QUESTIONS}(id,scope_key) ON DELETE CASCADE
    )""")
    for old, new, columns in [(QUESTIONS, TEMP_QUESTIONS, QUESTION_COLUMNS), (PHRASINGS, TEMP_PHRASINGS, PHRASING_COLUMNS)]:
        fields = ",".join(_identifier(column) for column in columns)
        connection.execute(f"INSERT INTO {new} ({fields}) SELECT {fields} FROM {old}")
    connection.execute(f"DROP TABLE {PHRASINGS}")
    connection.execute(f"DROP TABLE {QUESTIONS}")
    connection.execute(f"ALTER TABLE {TEMP_QUESTIONS} RENAME TO {QUESTIONS}")
    connection.execute(f"ALTER TABLE {TEMP_PHRASINGS} RENAME TO {PHRASINGS}")
    for (sql,) in objects:
        connection.execute(sql)
    for table, sequence in sequences.items():
        connection.execute("UPDATE sqlite_sequence SET seq=? WHERE name=?", (sequence, table))


def _verify_migration(connection: sqlite3.Connection, before: dict[str, Counter]) -> None:
    status, _ = _inspect(connection)
    if status != "already_current" or _snapshot(connection, list(before)) != before:
        raise KnowledgeScopeMigrationError("迁移后内容或关系核验不一致，已回滚")
    for table in (QUESTIONS, PHRASINGS):
        if connection.execute(f"SELECT COUNT(*) FROM {table} WHERE scope_key != ''").fetchone()[0]:
            raise KnowledgeScopeMigrationError("存量范围不应被推断或赋值")


def migrate_knowledge_scopes(database_path: str | Path, *, apply: bool = False) -> dict:
    """Inspect or migrate the explicitly selected store; legacy scopes remain empty.

    This function never runs at application startup. Every apply first locks out
    concurrent writers, makes an online backup, then rebuilds in one transaction.
    """
    database = Path(database_path).expanduser().resolve()
    if not database.is_file():
        raise KnowledgeScopeMigrationError("数据库不存在；未创建新文件")
    connection = sqlite3.connect(database.as_uri() + ("?mode=rw" if apply else "?mode=ro"), uri=True)
    backup = None
    try:
        connection.execute("PRAGMA foreign_keys=OFF" if apply else "PRAGMA query_only=ON")
        connection.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        status, tables = _inspect(connection)
        before = _snapshot(connection, tables)
        report = {"status": status, "counts": {table: sum(rows.values()) for table, rows in before.items()}, "backup": None}
        if not apply or status == "already_current":
            connection.rollback()
            return report
        backup = _backup(database)
        _rebuild(connection)
        _verify_migration(connection, before)
        connection.commit()
        report.update(status="applied", backup=str(backup))
        return report
    except (sqlite3.Error, OSError) as exc:
        connection.rollback()
        suffix = f"；备份保留于 {backup}" if backup else ""
        raise KnowledgeScopeMigrationError("迁移未完成，原事务已回滚" + suffix) from exc
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.execute("PRAGMA foreign_keys=ON")
        connection.close()
