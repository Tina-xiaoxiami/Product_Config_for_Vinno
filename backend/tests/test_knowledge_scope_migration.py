"""Migrate only synthetic legacy stores; never touch the live product database."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.services.knowledge_scope_migration import (
    KnowledgeScopeMigrationError,
    migrate_knowledge_scopes,
)


def _legacy(path):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE knowledge_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_text TEXT NOT NULL,
                normalized_question TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                asked_count INTEGER NOT NULL DEFAULT 1,
                last_asked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE knowledge_question_phrasings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL REFERENCES knowledge_questions(id) ON DELETE CASCADE,
                phrasing_text TEXT NOT NULL,
                normalized_phrasing TEXT NOT NULL UNIQUE,
                phrasing_type TEXT NOT NULL DEFAULT 'alias',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE knowledge_answers (
                id INTEGER PRIMARY KEY, question_id INTEGER NOT NULL
                    REFERENCES knowledge_questions(id) ON DELETE CASCADE,
                answer_text TEXT NOT NULL
            );
            CREATE TABLE knowledge_answer_revisions (
                id INTEGER PRIMARY KEY, answer_id INTEGER NOT NULL
                    REFERENCES knowledge_answers(id) ON DELETE CASCADE,
                version INTEGER NOT NULL, answer_text TEXT NOT NULL
            );
            CREATE TABLE knowledge_answer_citations (
                id INTEGER PRIMARY KEY, answer_id INTEGER NOT NULL
                    REFERENCES knowledge_answers(id) ON DELETE CASCADE,
                document_id INTEGER NOT NULL
            );
            CREATE TABLE migration_audit (question_id INTEGER);
            CREATE INDEX idx_legacy_question_text ON knowledge_questions(question_text);
            CREATE TRIGGER legacy_question_update AFTER UPDATE ON knowledge_questions
                BEGIN INSERT INTO migration_audit VALUES (NEW.id); END;
            INSERT INTO knowledge_questions(id,question_text,normalized_question,status,asked_count,
                last_asked_at,created_at,updated_at)
                VALUES(5,'原问题','原问题','answered',8,'old asked','old created','old updated');
            INSERT INTO knowledge_question_phrasings(id,question_id,phrasing_text,normalized_phrasing)
                VALUES(9,5,'旧问法','旧问法');
            INSERT INTO knowledge_answers VALUES(11,5,'历史答案');
            INSERT INTO knowledge_answer_revisions VALUES(13,11,1,'历史修订');
            INSERT INTO knowledge_answer_citations VALUES(15,11,7);
            INSERT INTO knowledge_questions(id,question_text,normalized_question) VALUES(100,'删除项','deleted');
            DELETE FROM knowledge_questions WHERE id=100;
            INSERT INTO knowledge_question_phrasings(id,question_id,phrasing_text,normalized_phrasing)
                VALUES(200,5,'删除问法','deleted alias');
            DELETE FROM knowledge_question_phrasings WHERE id=200;
        """)


def _rows(path, table):
    with closing(sqlite3.connect(path)) as connection:
        return list(connection.execute(f'SELECT * FROM "{table}" ORDER BY id'))


def test_dry_run_is_read_only_and_reports_retained_counts(tmp_path):
    database = tmp_path / "legacy ?#.db"
    _legacy(database)
    before = database.read_bytes()
    report = migrate_knowledge_scopes(database)
    assert report["status"] == "ready"
    assert report["counts"]["knowledge_questions"] == 1
    assert report["counts"]["knowledge_answer_revisions"] == 1
    assert not report.get("backup")
    assert database.read_bytes() == before
    assert list(tmp_path.iterdir()) == [database]


def test_apply_preserves_rows_relations_indexes_triggers_and_sequence_high_water(tmp_path):
    database = tmp_path / "legacy.db"
    _legacy(database)
    retained = {table: _rows(database, table) for table in [
        "knowledge_answers", "knowledge_answer_revisions", "knowledge_answer_citations",
    ]}
    report = migrate_knowledge_scopes(database, apply=True)
    assert report["status"] == "applied"
    assert Path(report["backup"]).is_file()
    assert len(_rows(Path(report["backup"]), "knowledge_questions")[0]) == 9
    assert all(_rows(database, table) == rows for table, rows in retained.items())
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("PRAGMA foreign_keys=ON")
        question = connection.execute("SELECT * FROM knowledge_questions WHERE id=5").fetchone()
        assert question[:9] == (5, "原问题", "原问题", "answered", 8, "old asked", "old created", "old updated")
        assert question[9] == ""
        assert connection.execute("SELECT scope_key FROM knowledge_question_phrasings WHERE id=9").fetchone()[0] == ""
        assert list(connection.execute("PRAGMA foreign_key_check")) == []
        sequences = dict(connection.execute("SELECT name,seq FROM sqlite_sequence"))
        assert sequences["knowledge_questions"] == 100
        assert sequences["knowledge_question_phrasings"] == 200
        connection.execute("UPDATE knowledge_questions SET asked_count=9 WHERE id=5")
        assert connection.execute("SELECT question_id FROM migration_audit").fetchone()[0] == 5
        assert connection.execute("SELECT 1 FROM sqlite_master WHERE name='idx_legacy_question_text'").fetchone()


def test_scoped_uniqueness_and_composite_foreign_keys_are_enforced(tmp_path):
    database = tmp_path / "legacy.db"
    _legacy(database)
    migrate_knowledge_scopes(database, apply=True)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO knowledge_questions(question_text,normalized_question,scope_key) VALUES('原问题','原问题','scope-a')"
        )
        question_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        assert question_id > 100
        connection.execute(
            "INSERT INTO knowledge_question_phrasings(question_id,phrasing_text,normalized_phrasing,scope_key) VALUES(?,?,?,?)",
            (question_id, "旧问法", "旧问法", "scope-a"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO knowledge_questions(question_text,normalized_question,scope_key) VALUES('duplicate','原问题','scope-a')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO knowledge_question_phrasings(question_id,phrasing_text,normalized_phrasing,scope_key) VALUES(?,?,?,?)",
                (question_id, "other", "other", "scope-b"),
            )
        connection.execute("DELETE FROM knowledge_questions WHERE id=?", (question_id,))
        assert connection.execute("SELECT COUNT(*) FROM knowledge_question_phrasings WHERE question_id=?", (question_id,)).fetchone()[0] == 0


def test_second_apply_is_idempotent_and_does_not_create_another_backup(tmp_path):
    database = tmp_path / "legacy.db"
    _legacy(database)
    migrate_knowledge_scopes(database, apply=True)
    before = database.read_bytes()
    files = set(tmp_path.iterdir())
    assert migrate_knowledge_scopes(database)["status"] == "already_current"
    assert migrate_knowledge_scopes(database, apply=True)["status"] == "already_current"
    assert database.read_bytes() == before
    assert set(tmp_path.iterdir()) == files


@pytest.mark.parametrize("alteration", [
    "ALTER TABLE knowledge_questions ADD COLUMN scope_key TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE knowledge_questions ADD COLUMN unknown_business_field TEXT",
    "CREATE TABLE _kh_scope_questions_new(id INTEGER)",
])
def test_partial_or_unknown_schema_is_blocked_without_writing(tmp_path, alteration):
    database = tmp_path / "legacy.db"
    _legacy(database)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(alteration)
    before = database.read_bytes()
    with pytest.raises(KnowledgeScopeMigrationError):
        migrate_knowledge_scopes(database, apply=True)
    assert database.read_bytes() == before


def test_existing_foreign_key_corruption_is_blocked(tmp_path):
    database = tmp_path / "legacy.db"
    _legacy(database)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("INSERT INTO knowledge_answers VALUES(99,999,'orphan')")
    before = database.read_bytes()
    with pytest.raises(KnowledgeScopeMigrationError, match="外键"):
        migrate_knowledge_scopes(database, apply=True)
    assert database.read_bytes() == before


def test_failed_post_copy_verification_rolls_back_original_schema_and_data(tmp_path, monkeypatch):
    from app.services import knowledge_scope_migration as migration

    database = tmp_path / "legacy.db"
    _legacy(database)
    before = _rows(database, "knowledge_questions")

    def fail(*args, **kwargs):
        raise KnowledgeScopeMigrationError("synthetic verification failure")

    monkeypatch.setattr(migration, "_verify_migration", fail)
    with pytest.raises(KnowledgeScopeMigrationError, match="synthetic"):
        migrate_knowledge_scopes(database, apply=True)
    assert _rows(database, "knowledge_questions") == before
    with closing(sqlite3.connect(database)) as connection:
        assert "scope_key" not in {row[1] for row in connection.execute("PRAGMA table_info(knowledge_questions)")}
        assert list(connection.execute("PRAGMA foreign_key_check")) == []


def test_missing_database_is_never_created(tmp_path):
    database = tmp_path / "missing.db"
    with pytest.raises(KnowledgeScopeMigrationError, match="不存在"):
        migrate_knowledge_scopes(database, apply=True)
    assert not database.exists()


def test_cli_requires_explicit_database_and_defaults_to_dry_run(tmp_path):
    database = tmp_path / "legacy.db"
    _legacy(database)
    script = Path(__file__).resolve().parents[1] / "scripts/migrate_knowledge_scopes.py"
    before = database.read_bytes()
    result = subprocess.run([sys.executable, str(script), "--database", str(database)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "ready"
    assert database.read_bytes() == before
    missing_argument = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert missing_argument.returncode != 0
