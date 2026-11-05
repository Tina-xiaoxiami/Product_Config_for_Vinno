from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from app.services.knowledge_document_removal import (
    KnowledgeDocumentRemovalError,
    remove_knowledge_documents,
)


def _create_database(path: Path) -> None:
    """Mirror the production schema for the tables this removal touches."""

    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE knowledge_documents (
                id INTEGER PRIMARY KEY,
                title TEXT,
                source_status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE knowledge_document_chunks (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES knowledge_documents (id)
                    ON DELETE CASCADE
            );
            CREATE TABLE knowledge_document_extractions (
                document_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES knowledge_documents (id)
                    ON DELETE CASCADE
            );
            CREATE TABLE knowledge_answer_citations (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL,
                FOREIGN KEY(document_id) REFERENCES knowledge_documents (id)
            );
            """
        )
        connection.commit()
    finally:
        connection.close()


def _insert_document(
    database: Path, *, document_id: int, title: str, source_status: str
) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO knowledge_documents (id, title, source_status) VALUES (?, ?, ?)",
            (document_id, title, source_status),
        )
        connection.commit()
    finally:
        connection.close()


def _seed_derived_rows(
    database: Path, *, document_id: int, chunks: int, extracted: bool = True
) -> None:
    connection = sqlite3.connect(database)
    try:
        for index in range(chunks):
            connection.execute(
                """
                INSERT INTO knowledge_document_chunks (document_id, chunk_index, content)
                VALUES (?, ?, ?)
                """,
                (document_id, index, f"chunk {index}"),
            )
        if extracted:
            connection.execute(
                """
                INSERT INTO knowledge_document_extractions (document_id, status)
                VALUES (?, 'completed')
                """,
                (document_id,),
            )
        connection.commit()
    finally:
        connection.close()


def _seed_citation(database: Path, *, document_id: int) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO knowledge_answer_citations (document_id) VALUES (?)",
            (document_id,),
        )
        connection.commit()
    finally:
        connection.close()


def _count(database: Path, table: str, document_id: int) -> int:
    connection = sqlite3.connect(database)
    try:
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE document_id = ?",  # noqa: S608
                (document_id,),
            ).fetchone()[0]
        )
    finally:
        connection.close()


def _document_ids(database: Path) -> list[int]:
    connection = sqlite3.connect(database)
    try:
        return [
            int(row[0])
            for row in connection.execute(
                "SELECT id FROM knowledge_documents ORDER BY id"
            ).fetchall()
        ]
    finally:
        connection.close()


def test_removal_deletes_derived_rows_before_the_document(tmp_path: Path) -> None:
    """显式清理 chunks/extractions，再删资料行；本项目 CASCADE 不生效。"""

    database = tmp_path / "knowledge.db"
    _create_database(database)
    _insert_document(database, document_id=19, title="V series Release Note", source_status="archived")
    _insert_document(database, document_id=20, title="V series Release Note", source_status="active")
    _seed_derived_rows(database, document_id=19, chunks=3)

    result = remove_knowledge_documents(database, document_ids=(19,), apply=True)

    assert result.counts["removed"] == 1
    assert result.counts["removed_chunks"] == 3
    assert result.counts["removed_extractions"] == 1
    assert _document_ids(database) == [20]
    assert _count(database, "knowledge_document_chunks", 19) == 0
    assert _count(database, "knowledge_document_extractions", 19) == 0
    # 相邻的 active 同类资料不受影响
    assert _count(database, "knowledge_document_chunks", 20) == 0


def test_removal_leaves_no_orphan_chunks(tmp_path: Path) -> None:
    """删除后不得留下孤儿 chunk —— CASCADE 关闭时静默孤儿是主要风险。"""

    database = tmp_path / "knowledge.db"
    _create_database(database)
    _insert_document(database, document_id=21, title="V系列 Release Note", source_status="archived")
    _seed_derived_rows(database, document_id=21, chunks=2)
    assert _count(database, "knowledge_document_chunks", 21) == 2

    remove_knowledge_documents(database, document_ids=(21,), apply=True)

    connection = sqlite3.connect(database)
    try:
        orphans = connection.execute(
            """
            SELECT COUNT(*) FROM knowledge_document_chunks chunk
            WHERE NOT EXISTS (
                SELECT 1 FROM knowledge_documents document
                WHERE document.id = chunk.document_id
            )
            """
        ).fetchone()[0]
    finally:
        connection.close()
    assert orphans == 0


def test_dry_run_reports_without_writing(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.db"
    _create_database(database)
    _insert_document(database, document_id=19, title="V series Release Note", source_status="archived")
    _seed_derived_rows(database, document_id=19, chunks=2)

    result = remove_knowledge_documents(database, document_ids=(19,), apply=False)

    assert result.apply is False
    assert result.counts["removable"] == 1
    assert result.items[0].chunk_count == 2
    assert _document_ids(database) == [19]
    assert _count(database, "knowledge_document_chunks", 19) == 2


def test_removal_refuses_a_document_still_used_as_answer_evidence(tmp_path: Path) -> None:
    """已被正式答案引用的资料拒绝删除，避免留下指向空文件的引文。"""

    database = tmp_path / "knowledge.db"
    _create_database(database)
    _insert_document(database, document_id=19, title="V series Release Note", source_status="archived")
    _seed_citation(database, document_id=19)

    with pytest.raises(KnowledgeDocumentRemovalError) as error:
        remove_knowledge_documents(database, document_ids=(19,), apply=True)

    assert "引文" in str(error.value)
    assert _document_ids(database) == [19]


def test_removal_refuses_an_active_document(tmp_path: Path) -> None:
    """只允许删除已退役资料，active 资料必须走退役流程。"""

    database = tmp_path / "knowledge.db"
    _create_database(database)
    _insert_document(database, document_id=20, title="V series Release Note", source_status="active")

    with pytest.raises(KnowledgeDocumentRemovalError) as error:
        remove_knowledge_documents(database, document_ids=(20,), apply=True)

    assert "archived" in str(error.value)
    assert _document_ids(database) == [20]


def test_removal_refuses_a_missing_document(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.db"
    _create_database(database)
    _insert_document(database, document_id=19, title="V series Release Note", source_status="archived")

    with pytest.raises(KnowledgeDocumentRemovalError):
        remove_knowledge_documents(database, document_ids=(19, 999), apply=True)

    # 一条不合格就整体不动，避免只删一半
    assert _document_ids(database) == [19]
