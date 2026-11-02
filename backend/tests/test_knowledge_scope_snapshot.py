"""Scoped identities survive snapshots and cannot leak into legacy seed curation."""

from contextlib import closing
import sqlite3

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.knowledge_qa_snapshot import (
    KnowledgeQaSnapshotError, export_knowledge_qa_snapshot, restore_knowledge_qa_snapshot,
)
from app.services.knowledge_question_seed import SeedQuestionSpec, seed_pending_questions
from app.services.knowledge_scope import scope_key
from app.services.knowledge_scope_migration import migrate_knowledge_scopes
from test_knowledge_qa_api import _create_qa_database


def _create(path, *, populated=False, other_model=False):
    _create_qa_database(path)
    migrate_knowledge_scopes(path, apply=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript("""
        CREATE TABLE product_series (id INTEGER PRIMARY KEY,name TEXT);
        CREATE TABLE product_models (id INTEGER PRIMARY KEY,name TEXT,series_id INTEGER);
        INSERT INTO product_series VALUES (901,'R&V10 series-China');
        INSERT INTO product_models VALUES (901,'VINNO 10',901);
        """)
        if other_model:
            connection.execute("UPDATE product_models SET name='Different model' WHERE id=901")
        if populated:
            for i, version in enumerate(["1.14.80", "1.14.81"], 1):
                scope = scope_key({"country": "CN", "market": "domestic", "product_model_id": 901,
                                   "software_version": version, "model_name": "VINNO 10",
                                   "series_name": "R&V10 series-China"})
                connection.execute(
                    "INSERT INTO knowledge_questions (id,question_text,normalized_question,status,scope_key) "
                    "VALUES (?,'相同问题','相同问题','answered',?)", (i, scope),
                )
                connection.execute("INSERT INTO knowledge_answers (question_id,answer_text) VALUES (?,?)", (i, version))
                connection.execute(
                    "INSERT INTO knowledge_question_phrasings "
                    "(question_id,phrasing_text,normalized_phrasing,scope_key) VALUES (?,'同一别名','同一别名',?)", (i, scope),
                )


def test_scope_v2_snapshot_preserves_duplicate_wording_and_restores_idempotently(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "target.db"
    _create(source, populated=True)
    _create(target)
    snapshot = export_knowledge_qa_snapshot(source)
    assert snapshot["schema_version"] == 2
    assert {row["scope"]["software_version"] for row in snapshot["questions"]} == {"1.14.80", "1.14.81"}
    assert restore_knowledge_qa_snapshot(target, snapshot)["status"] == "ready"
    assert restore_knowledge_qa_snapshot(target, snapshot, apply=True)["status"] == "restored"
    assert export_knowledge_qa_snapshot(target) == snapshot
    assert restore_knowledge_qa_snapshot(target, snapshot, apply=True)["status"] == "already_current"


def test_scope_restore_rejects_same_numeric_model_id_with_different_identity(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "target.db"
    _create(source, populated=True)
    _create(target, other_model=True)
    before = target.read_bytes()
    with pytest.raises(KnowledgeQaSnapshotError, match="机型"):
        restore_knowledge_qa_snapshot(target, export_knowledge_qa_snapshot(source), apply=True)
    assert target.read_bytes() == before


@pytest.mark.asyncio
async def test_legacy_seed_is_not_covered_by_scoped_answers_with_the_same_wording(tmp_path):
    path = tmp_path / "seed.db"
    _create(path, populated=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    try:
        async with async_sessionmaker(engine)() as session:
            report = await seed_pending_questions(session, [SeedQuestionSpec(category="test", question="相同问题")], apply=False)
        assert report["items"][0]["action"] == "would_insert"
    finally:
        await engine.dispose()
