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


@pytest.mark.asyncio
async def test_candidate_ranking_uses_confirmed_wording_and_centers_the_excerpt(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_qa_database(database_path)
    long_prefix = "产品概述" * 120
    whitepaper_content = f"{long_prefix}\n实时显示屏亮度调节"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        INSERT INTO knowledge_documents (
            id, document_type, title, file_name, file_path,
            version, market, product_series, mime_type
        ) VALUES (
            2, 'release_note', 'V系列 Release Note', 'release.pdf',
            '/tmp/release.pdf', '1.14.80', 'domestic', 'V series', 'application/pdf'
        );
        INSERT INTO knowledge_document_extractions (
            document_id, extractor_version, status, chunk_count, extracted_at
        ) VALUES
            (1, '1', 'completed', 1, CURRENT_TIMESTAMP),
            (2, '1', 'completed', 1, CURRENT_TIMESTAMP);
        """
    )
    connection.execute(
        """
        INSERT INTO knowledge_document_chunks (
            document_id, chunk_index, page_number, source_ref,
            content, normalized_content, content_hash
        ) VALUES (1, 0, 2, '第2页', ?, ?, 'whitepaper-hash')
        """,
        (whitepaper_content, whitepaper_content),
    )
    connection.execute(
        """
        INSERT INTO knowledge_document_chunks (
            document_id, chunk_index, page_number, source_ref,
            content, normalized_content, content_hash
        ) VALUES (
            2, 0, 4, '第4页', 'V10系列支持OS升级。',
            'v10系列支持os升级', 'release-hash'
        )
        """
    )
    connection.commit()
    connection.close()
    client, engine = await _client_for(database_path)

    async with client:
        asked = await client.post(
            "/api/knowledge/questions/ask",
            json={"question": "V10系列环境光自动调节亮度是标配吗？"},
        )
    await engine.dispose()

    candidate = asked.json()["candidates"][0]
    assert candidate["document_id"] == 1
    assert candidate["source_ref"] == "第2页"
    assert "实时显示屏亮度调节" in candidate["excerpt"]
    assert len(candidate["excerpt"]) <= 800
