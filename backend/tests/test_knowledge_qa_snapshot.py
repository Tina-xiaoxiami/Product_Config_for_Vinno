import copy
import sqlite3

import pytest

from app.services.knowledge_qa_snapshot import (
    KnowledgeQaSnapshotError,
    export_knowledge_qa_snapshot,
    restore_knowledge_qa_snapshot,
)


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE knowledge_documents (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    sha256 TEXT,
    source_status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE knowledge_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_text TEXT NOT NULL,
    normalized_question TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    asked_count INTEGER NOT NULL,
    last_asked_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE knowledge_question_phrasings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES knowledge_questions(id) ON DELETE CASCADE,
    phrasing_text TEXT NOT NULL,
    normalized_phrasing TEXT NOT NULL UNIQUE,
    phrasing_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE knowledge_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL UNIQUE REFERENCES knowledge_questions(id) ON DELETE CASCADE,
    answer_text TEXT NOT NULL,
    review_status TEXT NOT NULL,
    version INTEGER NOT NULL,
    change_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE knowledge_answer_citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_id INTEGER NOT NULL REFERENCES knowledge_answers(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES knowledge_documents(id),
    source_ref TEXT,
    excerpt TEXT,
    sort_order INTEGER NOT NULL
);
CREATE TABLE knowledge_answer_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_id INTEGER NOT NULL REFERENCES knowledge_answers(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    answer_text TEXT NOT NULL,
    review_status TEXT NOT NULL,
    change_note TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(answer_id, version)
);
"""


def _create_database(path, *, with_qa):
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    connection.execute(
        "INSERT INTO knowledge_documents (id, title, sha256) VALUES (?, ?, ?)",
        (7, "V10受控说明书", "a" * 64),
    )
    if with_qa:
        connection.executescript(
            """
            INSERT INTO knowledge_questions (
                id, question_text, normalized_question, status, asked_count,
                last_asked_at, created_at, updated_at
            ) VALUES (
                3, 'V10如何调节亮度？', 'v10如何调节亮度', 'answered', 4,
                '2026-09-03 10:00:00', '2026-09-01 10:00:00',
                '2026-09-03 10:00:00'
            );
            INSERT INTO knowledge_question_phrasings (
                question_id, phrasing_text, normalized_phrasing,
                phrasing_type, created_at
            ) VALUES (
                3, 'V10怎么把屏幕调亮', 'v10怎么把屏幕调亮', 'alias',
                '2026-09-03 10:00:00'
            );
            INSERT INTO knowledge_answers (
                id, question_id, answer_text, review_status, version,
                change_note, created_at, updated_at
            ) VALUES (
                5, 3, '进入显示设置调节。', 'published', 1,
                '首次发布', '2026-09-03 10:00:00', '2026-09-03 10:00:00'
            );
            INSERT INTO knowledge_answer_citations (
                answer_id, document_id, source_ref, excerpt, sort_order
            ) VALUES (5, 7, '第50页', '显示器背光调节', 0);
            INSERT INTO knowledge_answer_revisions (
                answer_id, version, answer_text, review_status,
                change_note, created_at
            ) VALUES (
                5, 1, '进入显示设置调节。', 'published',
                '首次发布', '2026-09-03 10:00:00'
            );
            """
        )
    connection.commit()
    connection.close()


def test_snapshot_round_trip_is_deterministic_and_restore_is_idempotent(tmp_path):
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    _create_database(source_path, with_qa=True)
    _create_database(target_path, with_qa=False)

    snapshot = export_knowledge_qa_snapshot(source_path)
    dry_run = restore_knowledge_qa_snapshot(target_path, snapshot, apply=False)

    assert dry_run == {
        "status": "ready",
        "question_count": 1,
        "answer_count": 1,
        "citation_count": 1,
    }
    connection = sqlite3.connect(target_path)
    assert connection.execute("SELECT COUNT(*) FROM knowledge_questions").fetchone()[0] == 0
    connection.close()

    restored = restore_knowledge_qa_snapshot(target_path, snapshot, apply=True)
    assert restored["status"] == "restored"
    assert export_knowledge_qa_snapshot(target_path) == snapshot
    assert restore_knowledge_qa_snapshot(target_path, snapshot, apply=True)["status"] == "already_current"


def test_restore_rejects_missing_controlled_document_without_partial_write(tmp_path):
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    _create_database(source_path, with_qa=True)
    _create_database(target_path, with_qa=False)
    connection = sqlite3.connect(target_path)
    connection.execute("DELETE FROM knowledge_documents")
    connection.commit()
    connection.close()

    snapshot = export_knowledge_qa_snapshot(source_path)
    with pytest.raises(KnowledgeQaSnapshotError, match="受控材料"):
        restore_knowledge_qa_snapshot(target_path, snapshot, apply=True)

    connection = sqlite3.connect(target_path)
    assert connection.execute("SELECT COUNT(*) FROM knowledge_questions").fetchone()[0] == 0
    connection.close()


def test_restore_rejects_tampered_snapshot(tmp_path):
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    _create_database(source_path, with_qa=True)
    _create_database(target_path, with_qa=False)
    snapshot = export_knowledge_qa_snapshot(source_path)
    tampered = copy.deepcopy(snapshot)
    tampered["questions"][0]["answer"]["answer_text"] = "被篡改的答案"

    with pytest.raises(KnowledgeQaSnapshotError, match="校验"):
        restore_knowledge_qa_snapshot(target_path, tampered, apply=False)
