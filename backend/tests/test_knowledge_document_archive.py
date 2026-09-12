import sqlite3

import pytest

from test_knowledge_qa_api import _client_for, _create_qa_database


def _seed_extraction(database_path, source_path):
    """造出一份「已提取正文」的受控资料。"""

    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE knowledge_documents SET file_path = ?, file_name = ? WHERE id = 1",
        (str(source_path), source_path.name),
    )
    connection.execute(
        """
        INSERT INTO knowledge_document_extractions (
            document_id, extractor_version, source_sha256, status, chunk_count,
            extracted_at, updated_at
        ) VALUES (1, 'v1', 'sha', 'completed', 1, '2026-01-01', '2026-01-01')
        """
    )
    connection.execute(
        """
        INSERT INTO knowledge_document_chunks (
            document_id, chunk_index, page_number, section_name,
            source_ref, content, normalized_content, content_hash
        ) VALUES (1, 0, 1, '正文', '第1页', '支持 VINNO 10', '支持vinno10', 'hash')
        """
    )
    connection.commit()
    connection.close()


def _seed_citation(database_path, document_id):
    """让该资料成为某条正式答案的证据。"""

    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        INSERT INTO knowledge_questions (id, question_text, normalized_question)
        VALUES (1, '该功能是否标配？', '该功能是否标配')
        """
    )
    connection.execute(
        """
        INSERT INTO knowledge_answers (id, question_id, answer_text, review_status, version)
        VALUES (1, 1, '结论：标配。', 'published', 1)
        """
    )
    connection.execute(
        """
        INSERT INTO knowledge_answer_citations (
            answer_id, document_id, source_ref, excerpt, sort_order
        ) VALUES (1, ?, '第12页', '摘录', 0)
        """,
        (document_id,),
    )
    connection.commit()
    connection.close()


@pytest.mark.asyncio
async def test_archiving_a_document_retires_it_and_clears_derived_data(tmp_path):
    """退役资料：置为 archived 并清除派生数据，之后列表与提取都不再认它。"""

    source_path = tmp_path / "release.docx"
    source_path.write_bytes(b"controlled")
    database_path = tmp_path / "knowledge.db"
    _create_qa_database(database_path)
    _seed_extraction(database_path, source_path)
    client, engine = await _client_for(database_path)

    async with client:
        archived = await client.post("/api/knowledge/documents/1/archive")
        again = await client.post("/api/knowledge/documents/1/archive")
        documents = await client.get("/api/knowledge/documents")
        extracted = await client.post("/api/knowledge/documents/1/extract")
    await engine.dispose()

    assert archived.status_code == 200, archived.text
    assert archived.json() == {
        "document_id": 1,
        "status": "archived",
        "removed_chunks": 1,
        "removed_extractions": 1,
    }
    # 重复归档是幂等的
    assert again.status_code == 200
    assert again.json()["removed_chunks"] == 0

    connection = sqlite3.connect(database_path)
    assert connection.execute(
        "SELECT source_status FROM knowledge_documents WHERE id = 1"
    ).fetchone()[0] == "archived"
    assert connection.execute(
        "SELECT COUNT(*) FROM knowledge_document_chunks WHERE document_id = 1"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM knowledge_document_extractions WHERE document_id = 1"
    ).fetchone()[0] == 0
    connection.close()

    assert documents.status_code == 200
    assert all(item["id"] != 1 for item in documents.json()["items"])
    # 退役后不在 active 目录里，提取端点按「资料不存在」处理
    assert extracted.status_code == 404


@pytest.mark.asyncio
async def test_archiving_refuses_a_document_still_used_as_answer_evidence(tmp_path):
    """已被正式答案引用的资料不能退役，避免留下指向空文件的引文。"""

    source_path = tmp_path / "release.docx"
    source_path.write_bytes(b"controlled")
    database_path = tmp_path / "knowledge.db"
    _create_qa_database(database_path)
    _seed_extraction(database_path, source_path)
    _seed_citation(database_path, document_id=1)
    client, engine = await _client_for(database_path)

    async with client:
        refused = await client.post("/api/knowledge/documents/1/archive")
        missing = await client.post("/api/knowledge/documents/999/archive")
    await engine.dispose()

    assert refused.status_code == 409
    assert "引文" in refused.json()["detail"]
    assert missing.status_code == 404
