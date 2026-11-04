"""Explicit, reversible retirement of unscoped historical questions only.

The ordinary QA snapshot preserves content but remaps IDs and omits review rows.
This maintenance archive keeps exact target rows so restoring retired records
never requires replacing a whole database that may contain later business work.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any


TABLES = ('knowledge_questions', 'knowledge_question_phrasings', 'knowledge_answers',
          'knowledge_answer_citations', 'knowledge_answer_revisions', 'knowledge_answer_reviews')
REQUIRED = set(TABLES) - {'knowledge_answer_reviews'}


class RetirementError(ValueError):
    """A maintenance precondition failed; no records may be silently widened."""


def _hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _connect(database: str | Path, *, write: bool = False) -> sqlite3.Connection:
    path = Path(database).expanduser().resolve()
    if not path.is_file():
        raise RetirementError('数据库不存在，请明确指定现用数据库')
    connection = sqlite3.connect(path.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    return connection


def _schema(connection: sqlite3.Connection) -> dict:
    names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    question_columns = {row[1] for row in connection.execute('PRAGMA table_info(knowledge_questions)')}
    if 'scope_key' not in question_columns:
        raise RetirementError('缺少scope_key，不能将所有问题假定为旧历史数据')
    if not REQUIRED <= names:
        raise RetirementError('问答表结构不完整，不能清理')
    for name in names:
        # Table names come only from SQLite metadata, not user request text.
        escaped = name.replace('"', '""')
        if name not in TABLES and any(row[2] in {'knowledge_questions', 'knowledge_answers'}
                                     for row in connection.execute(f'PRAGMA foreign_key_list("{escaped}")')):
            raise RetirementError('存在未支持的问答依赖表：' + name)
    return {table: [dict(row) for row in connection.execute(f'PRAGMA table_info({table})')]
            for table in TABLES if table in names}


def _manifest(connection: sqlite3.Connection, database: str | Path) -> dict:
    schema = _schema(connection)
    rows: dict[str, list[dict]] = {}
    for table in schema:
        if table == 'knowledge_questions':
            where = "scope_key=''"
        elif table == 'knowledge_question_phrasings':
            where = "question_id IN (SELECT id FROM knowledge_questions WHERE scope_key='')"
        elif table == 'knowledge_answers':
            where = "question_id IN (SELECT id FROM knowledge_questions WHERE scope_key='')"
        else:
            where = "answer_id IN (SELECT a.id FROM knowledge_answers a JOIN knowledge_questions q ON q.id=a.question_id WHERE q.scope_key='')"
        rows[table] = [dict(row) for row in connection.execute(f'SELECT * FROM {table} WHERE {where} ORDER BY id')]
    body = {'format': 'legacy-qa-retirement-v1', 'database': str(Path(database).expanduser().resolve()),
            'schema': schema, 'tables': rows}
    return {**body, 'fingerprint': _hash(body)}


def _summary(manifest: dict, status: str) -> dict:
    return {'status': status, 'fingerprint': manifest['fingerprint'],
            'question_ids': [row['id'] for row in manifest['tables']['knowledge_questions']],
            'counts': {table: len(rows) for table, rows in manifest['tables'].items()}}


def preview_retirement(database: str | Path) -> dict:
    connection = _connect(database)
    try:
        connection.execute('BEGIN')
        return _summary(_manifest(connection, database), 'ready')
    finally:
        connection.close()


def _destinations(database: str | Path, archive: str | Path | None, backup: str | Path | None) -> tuple[Path, Path]:
    if archive is None or backup is None:
        raise RetirementError('执行清理必须指定新的归档和整库备份路径')
    source = Path(database).expanduser().resolve()
    raw = [Path(path).expanduser() for path in (archive, backup)]
    paths = [path.resolve() for path in raw]
    if source in paths or paths[0] == paths[1] or any(path.exists() or path.is_symlink() for path in raw):
        raise RetirementError('归档/备份路径不能覆盖数据库、已有文件或彼此重叠')
    return paths[0], paths[1]


def _archive(manifest: dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf-8') as output:
        json.dump(manifest, output, ensure_ascii=False, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())


def _backup(database: str | Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    # Use another read connection: backing up a connection inside its own write
    # transaction would wait on itself. BEGIN IMMEDIATE still excludes writers.
    source = _connect(database)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RetirementError('整库备份完整性检查失败')
    finally:
        target.close()
        source.close()


def retire_legacy_qa(database: str | Path, *, expected_fingerprint: str | None = None,
                     archive_path: str | Path | None = None, backup_path: str | Path | None = None,
                     apply: bool = False) -> dict:
    if not apply:
        return preview_retirement(database)
    if not expected_fingerprint:
        raise RetirementError('执行清理必须提供预览指纹')
    archive, backup = _destinations(database, archive_path, backup_path)
    connection = _connect(database, write=True)
    try:
        connection.execute('BEGIN IMMEDIATE')
        manifest = _manifest(connection, database)
        if manifest['fingerprint'] != expected_fingerprint:
            raise RetirementError('旧历史问答已变化，请重新预览')
        if connection.execute('PRAGMA foreign_key_check').fetchone():
            raise RetirementError('数据库已有外键异常，请先核查，未清理任何数据')
        _archive(manifest, archive)
        _backup(database, backup)
        ids = [row['id'] for row in manifest['tables']['knowledge_questions']]
        # Delete only approved question identities. Existing foreign keys cascade
        # dependent answers, aliases, citations, revisions and review records.
        connection.executemany("DELETE FROM knowledge_questions WHERE id=? AND scope_key=''", [(value,) for value in ids])
        if connection.execute('PRAGMA foreign_key_check').fetchone():
            raise RetirementError('清理产生外键异常，已回滚')
        connection.commit()
        return {**_summary(manifest, 'retired'), 'archive_path': str(archive), 'backup_path': str(backup)}
    except (OSError, sqlite3.Error) as error:
        connection.rollback()
        raise RetirementError('清理未完成，数据库事务已回滚：' + str(error)) from error
    finally:
        connection.close()


def _read_archive(path: str | Path, database: str | Path) -> dict:
    source = Path(path).expanduser()
    if source.resolve() == Path(database).expanduser().resolve():
        raise RetirementError('归档路径不能是数据库原件')
    try:
        manifest = json.loads(source.read_text(encoding='utf-8'))
        body = {key: value for key, value in manifest.items() if key != 'fingerprint'}
        if (manifest['format'] != 'legacy-qa-retirement-v1' or _hash(body) != manifest['fingerprint']
                or manifest['database'] != str(Path(database).expanduser().resolve())):
            raise RetirementError('归档校验失败或不属于所选数据库')
        tables = manifest['tables']
        if not REQUIRED <= tables.keys() or not set(tables) <= set(TABLES):
            raise RetirementError('归档表范围无效')
        if any(row['scope_key'] != '' for row in tables['knowledge_questions']):
            raise RetirementError('归档包含非旧历史问题，拒绝恢复')
        return manifest
    except (OSError, ValueError, KeyError, TypeError) as error:
        if isinstance(error, RetirementError):
            raise
        raise RetirementError('无法读取或校验归档') from error


def restore_legacy_qa(database: str | Path, archive_path: str | Path, *, apply: bool = False) -> dict:
    manifest = _read_archive(archive_path, database)
    connection = _connect(database, write=apply)
    try:
        connection.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        if _schema(connection) != manifest['schema']:
            raise RetirementError('问答表结构已变化，不能原始行恢复')
        for table, rows in manifest['tables'].items():
            columns = [row['name'] for row in manifest['schema'][table]]
            for row in rows:
                if set(row) != set(columns):
                    raise RetirementError('归档原始列校验失败')
                if connection.execute(f'SELECT 1 FROM {table} WHERE id=?', (row['id'],)).fetchone():
                    raise RetirementError('恢复身份冲突，不能覆盖现有记录')
        if apply:
            for table in TABLES:
                if table not in manifest['tables']:
                    continue
                columns = [row['name'] for row in manifest['schema'][table]]
                connection.executemany(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                                       [[row[column] for column in columns] for row in manifest['tables'][table]])
            if connection.execute('PRAGMA foreign_key_check').fetchone():
                raise RetirementError('恢复数据外键异常，已回滚')
            connection.commit()
        return _summary(manifest, 'restored' if apply else 'ready')
    except sqlite3.Error as error:
        connection.rollback()
        raise RetirementError('恢复数据冲突或来源缺失，已回滚：' + str(error)) from error
    finally:
        connection.close()
