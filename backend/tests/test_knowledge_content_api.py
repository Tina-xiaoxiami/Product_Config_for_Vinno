import hashlib
import sqlite3

import pytest

from app.services import knowledge_content
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


@pytest.mark.asyncio
async def test_candidate_prefilter_skips_irrelevant_chunks_before_python_scoring(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "knowledge.db"
    _create_qa_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        INSERT INTO knowledge_document_extractions (
            document_id, extractor_version, status, chunk_count, extracted_at
        ) VALUES (1, '1', 'completed', 201, CURRENT_TIMESTAMP)
        """
    )
    connection.executemany(
        """
        INSERT INTO knowledge_document_chunks (
            document_id, chunk_index, source_ref,
            content, normalized_content, content_hash
        ) VALUES (1, ?, ?, ?, ?, ?)
        """,
        [
            (
                index,
                f"无关段落{index}",
                f"这是与查询无关的材料内容编号{index}",
                f"这是与查询无关的材料内容编号{index}",
                f"irrelevant-{index}",
            )
            for index in range(200)
        ]
        + [
            (
                200,
                "相关段落",
                "V10系列支持环境光自动亮度调节。",
                "v10系列支持环境光自动亮度调节",
                "relevant",
            )
        ],
    )
    connection.commit()
    connection.close()

    original_score = knowledge_content._candidate_score
    scored_chunks = 0

    def counting_score(question, content, document_context):
        nonlocal scored_chunks
        scored_chunks += 1
        return original_score(question, content, document_context)

    monkeypatch.setattr(knowledge_content, "_candidate_score", counting_score)
    client, engine = await _client_for(database_path)
    async with client:
        asked = await client.post(
            "/api/knowledge/questions/ask",
            json={"question": "V10环境光自动亮度调节是标配吗？"},
        )
    await engine.dispose()

    assert asked.status_code == 200
    assert asked.json()["candidates"][0]["source_ref"] == "相关段落"
    assert scored_chunks < 10


@pytest.mark.asyncio
async def test_candidate_ranking_prefers_the_requested_software_version(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_qa_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        INSERT INTO knowledge_documents (
            id, document_type, title, file_name, file_path,
            version, market, product_series, mime_type
        ) VALUES
            (2, 'release_note', 'V10 Release Note 1.14.21', '1.14.21.pdf',
             '/tmp/1.14.21.pdf', '1.14.21', 'domestic', 'V10', 'application/pdf'),
            (3, 'release_note', 'V10 Release Note 1.14.80', '1.14.80.pdf',
             '/tmp/1.14.80.pdf', '1.14.80', 'domestic', 'V10', 'application/pdf');
        INSERT INTO knowledge_document_extractions (
            document_id, extractor_version, status, chunk_count, extracted_at
        ) VALUES
            (2, '2', 'completed', 1, CURRENT_TIMESTAMP),
            (3, '2', 'completed', 1, CURRENT_TIMESTAMP);
        INSERT INTO knowledge_document_chunks (
            document_id, chunk_index, source_ref, content,
            normalized_content, content_hash
        ) VALUES
            (2, 0, '第2页', 'V10系列本版本发布了以下功能和变更。',
             'v10系列本版本发布了以下功能和变更', 'version-21'),
            (3, 0, '第2页', 'V10系列本版本发布了以下功能和变更。',
             'v10系列本版本发布了以下功能和变更', 'version-80');
        """
    )
    connection.commit()
    connection.close()
    client, engine = await _client_for(database_path)

    async with client:
        asked = await client.post(
            "/api/knowledge/questions/ask",
            json={"question": "V10系列1.14.80版本发布了哪些功能和变更？"},
        )
    await engine.dispose()

    assert asked.json()["candidates"][0]["document_id"] == 3


@pytest.mark.asyncio
async def test_candidate_ranking_prefers_registration_sources_for_registration_intent(
    tmp_path,
):
    database_path = tmp_path / "knowledge.db"
    _create_qa_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        INSERT INTO knowledge_documents (
            id, document_type, title, file_name, file_path,
            version, market, product_series, mime_type
        ) VALUES
            (2, 'registration_certificate', 'V10湘证注册证', 'certificate.pdf',
             '/tmp/certificate.pdf', '20260615', 'domestic', 'V10', 'application/pdf'),
            (3, 'registration_difference', 'V10湘证注册差异表', 'difference.xlsx',
             '/tmp/difference.xlsx', '20250729', 'domestic', 'V10',
             'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
        INSERT INTO knowledge_document_extractions (
            document_id, extractor_version, status, chunk_count, extracted_at
        ) VALUES
            (2, '2', 'completed', 1, CURRENT_TIMESTAMP),
            (3, '2', 'completed', 1, CURRENT_TIMESTAMP);
        INSERT INTO knowledge_document_chunks (
            document_id, chunk_index, source_ref, content,
            normalized_content, content_hash
        ) VALUES
            (2, 0, '第2页', 'VINNO 10E湘证注册支持I4-11T探头。',
             'vinno10e湘证注册支持i411t探头', 'certificate'),
            (3, 0, '型号差异!第3行', 'VINNO 10E | I4-11T不适用',
             'vinno10ei411t不适用', 'difference');
        """
    )
    connection.commit()
    connection.close()
    client, engine = await _client_for(database_path)

    async with client:
        asked = await client.post(
            "/api/knowledge/questions/ask",
            json={"question": "VINNO 10E在湘证下是否支持I4-11T探头？"},
        )
    await engine.dispose()

    assert asked.json()["candidates"][0]["document_id"] == 3
