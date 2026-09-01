import hashlib
import sqlite3

import pytest

from test_knowledge_qa_api import _client_for, _create_qa_database


@pytest.mark.asyncio
async def test_document_extraction_is_idempotent_and_feeds_pending_question_candidates(
    tmp_path,
):
    database_path = tmp_path / "knowledge.db"
    source_path = tmp_path / "whitepaper.txt"
    source_path.write_text(
        "显示器功能\n环境光自动亮度调节在V10系列为标配。\n\n"
        "穿刺增强\n针增益调节属于招标支持功能。",
        encoding="utf-8",
    )
    _create_qa_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        UPDATE knowledge_documents
        SET file_path = ?, file_name = 'whitepaper.txt', mime_type = 'text/plain',
            sha256 = ?
        WHERE id = 1
        """,
        (str(source_path), hashlib.sha256(source_path.read_bytes()).hexdigest()),
    )
    connection.commit()
    connection.close()
    client, engine = await _client_for(database_path)

    async with client:
        extracted = await client.post("/api/knowledge/documents/1/extract")
        repeated = await client.post("/api/knowledge/documents/1/extract")
        asked = await client.post(
            "/api/knowledge/questions/ask",
            json={"question": "V10环境光自动亮度调节是标配吗？"},
        )
        candidates = await client.get(
            f"/api/knowledge/questions/{asked.json()['question_id']}/candidates"
        )
        documents = await client.get("/api/knowledge/documents")
    await engine.dispose()

    assert extracted.status_code == 200
    assert extracted.json()["status"] == "completed"
    assert extracted.json()["chunk_count"] >= 1
    assert extracted.json()["reused"] is False
    assert repeated.json()["reused"] is True
    assert asked.json()["status"] == "pending"
    assert asked.json()["answer"] is None
    assert asked.json()["candidates"][0]["document_title"] == "V10 1.14.80 白皮书"
    assert "环境光自动亮度调节" in asked.json()["candidates"][0]["excerpt"]
    assert candidates.json()["items"] == asked.json()["candidates"]
    assert documents.json()["items"][0]["extraction_status"] == "completed"
    assert documents.json()["items"][0]["chunk_count"] >= 1


@pytest.mark.asyncio
async def test_extraction_preserves_page_or_section_reference_and_rejects_missing_file(
    tmp_path,
):
    database_path = tmp_path / "knowledge.db"
    _create_qa_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE knowledge_documents SET file_path = ? WHERE id = 1",
        (str(tmp_path / "missing.pdf"),),
    )
    connection.commit()
    connection.close()
    client, engine = await _client_for(database_path)

    async with client:
        response = await client.post("/api/knowledge/documents/1/extract")
    await engine.dispose()

    assert response.status_code == 410

