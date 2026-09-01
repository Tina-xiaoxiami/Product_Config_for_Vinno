import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import knowledge
from app.database import get_db


def _create_qa_database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE knowledge_documents (
            id INTEGER PRIMARY KEY,
            document_type TEXT NOT NULL,
            title TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            version TEXT,
            market TEXT NOT NULL DEFAULT 'domestic',
            country TEXT,
            product_series TEXT,
            mime_type TEXT,
            sha256 TEXT,
            source_status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO knowledge_documents (
            id, document_type, title, file_name, file_path,
            version, market, product_series, mime_type
        ) VALUES (
            1, 'whitepaper', 'V10 1.14.80 白皮书', 'V10.pdf',
            '/tmp/V10.pdf', '1.14.80', 'domestic', 'V10', 'application/pdf'
        );

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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL UNIQUE REFERENCES knowledge_questions(id) ON DELETE CASCADE,
            answer_text TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'published',
            version INTEGER NOT NULL DEFAULT 1,
            change_note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE knowledge_answer_citations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            answer_id INTEGER NOT NULL REFERENCES knowledge_answers(id) ON DELETE CASCADE,
            document_id INTEGER NOT NULL REFERENCES knowledge_documents(id),
            source_ref TEXT,
            excerpt TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE knowledge_answer_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            answer_id INTEGER NOT NULL REFERENCES knowledge_answers(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            answer_text TEXT NOT NULL,
            review_status TEXT NOT NULL,
            change_note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(answer_id, version)
        );
        CREATE TABLE knowledge_document_extractions (
            document_id INTEGER PRIMARY KEY REFERENCES knowledge_documents(id) ON DELETE CASCADE,
            extractor_version TEXT NOT NULL,
            source_sha256 TEXT,
            status TEXT NOT NULL,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            extracted_at TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE knowledge_document_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            page_number INTEGER,
            section_name TEXT,
            source_ref TEXT NOT NULL,
            content TEXT NOT NULL,
            normalized_content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(document_id, chunk_index)
        );
        """
    )
    connection.commit()
    connection.close()


async def _client_for(database_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/api/knowledge")

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ), engine


@pytest.mark.asyncio
async def test_unknown_question_enters_pending_queue_and_repeated_ask_is_counted(tmp_path):
    database_path = tmp_path / "qa.db"
    _create_qa_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        first = await client.post(
            "/api/knowledge/questions/ask",
            json={"question": "针增益调节是招标功能吗？"},
        )
        repeated = await client.post(
            "/api/knowledge/questions/ask",
            json={"question": "针增益调节是招标功能吗"},
        )
        pending = await client.get(
            "/api/knowledge/questions", params={"status": "pending"}
        )
    await engine.dispose()

    assert first.status_code == 200
    assert first.json()["status"] == "pending"
    assert first.json()["answer"] is None
    assert first.json()["candidates"] == []
    assert repeated.json()["question_id"] == first.json()["question_id"]
    assert pending.json()["total"] == 1
    assert pending.json()["items"][0]["asked_count"] == 2


@pytest.mark.asyncio
async def test_confirmed_answer_is_reused_by_alias_and_returns_source_citation(tmp_path):
    database_path = tmp_path / "qa.db"
    _create_qa_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        asked = await client.post(
            "/api/knowledge/questions/ask",
            json={"question": "针增益调节是招标功能吗？"},
        )
        question_id = asked.json()["question_id"]
        published = await client.put(
            f"/api/knowledge/questions/{question_id}/answer",
            json={
                "answer_text": "是，针增益调节属于招标支持功能。",
                "alias_questions": ["针增益是不是招标功能"],
                "citations": [
                    {
                        "document_id": 1,
                        "source_ref": "第12页",
                        "excerpt": "针增益调节：招标支持",
                    }
                ],
                "change_note": "首次确认",
            },
        )
        answered = await client.post(
            "/api/knowledge/questions/ask",
            json={"question": "针增益是不是招标功能？"},
        )
    await engine.dispose()

    assert published.status_code == 200
    assert published.json()["status"] == "answered"
    assert published.json()["answer"]["version"] == 1
    assert answered.json()["status"] == "answered"
    assert answered.json()["match_type"] == "exact"
    assert answered.json()["answer"]["answer_text"] == "是，针增益调节属于招标支持功能。"
    citation = answered.json()["answer"]["citations"][0]
    assert citation["document_title"] == "V10 1.14.80 白皮书"
    assert citation["source_ref"] == "第12页"
    assert citation["preview_url"] == "/api/knowledge/documents/1/preview"


@pytest.mark.asyncio
async def test_similar_question_reuses_only_published_answer(tmp_path):
    database_path = tmp_path / "qa.db"
    _create_qa_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        asked = await client.post(
            "/api/knowledge/questions/ask",
            json={"question": "环境光自动亮度调节是不是V10系列标配？"},
        )
        await client.put(
            f"/api/knowledge/questions/{asked.json()['question_id']}/answer",
            json={
                "answer_text": "是，V10系列均为标配。",
                "alias_questions": [],
                "citations": [{"document_id": 1, "source_ref": "显示器章节"}],
                "change_note": "产品经理确认",
            },
        )
        similar = await client.post(
            "/api/knowledge/questions/ask",
            json={"question": "V10是否标配环境光自动调节亮度功能"},
        )
    await engine.dispose()

    assert similar.json()["status"] == "answered"
    assert similar.json()["match_type"] == "similar"
    assert similar.json()["similarity"] >= 0.72


@pytest.mark.asyncio
async def test_invalid_citation_does_not_publish_partial_answer(tmp_path):
    database_path = tmp_path / "qa.db"
    _create_qa_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        asked = await client.post(
            "/api/knowledge/questions/ask", json={"question": "一个待确认问题"}
        )
        question_id = asked.json()["question_id"]
        rejected = await client.put(
            f"/api/knowledge/questions/{question_id}/answer",
            json={
                "answer_text": "不应保存",
                "alias_questions": [],
                "citations": [{"document_id": 999, "source_ref": "第1页"}],
                "change_note": "无效来源",
            },
        )
        pending = await client.get(f"/api/knowledge/questions/{question_id}")
    await engine.dispose()

    assert rejected.status_code == 422
    assert pending.json()["status"] == "pending"
    assert pending.json()["answer"] is None


@pytest.mark.asyncio
async def test_answer_updates_keep_version_history(tmp_path):
    database_path = tmp_path / "qa.db"
    _create_qa_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        asked = await client.post(
            "/api/knowledge/questions/ask", json={"question": "功能是否支持？"}
        )
        question_id = asked.json()["question_id"]
        await client.put(
            f"/api/knowledge/questions/{question_id}/answer",
            json={
                "answer_text": "旧答案",
                "alias_questions": [],
                "citations": [],
                "change_note": "首次确认",
            },
        )
        updated = await client.put(
            f"/api/knowledge/questions/{question_id}/answer",
            json={
                "answer_text": "新答案",
                "alias_questions": ["是否支持该功能"],
                "citations": [],
                "change_note": "依据新版本修订",
            },
        )
        history = await client.get(
            f"/api/knowledge/questions/{question_id}/history"
        )
    await engine.dispose()

    assert updated.json()["answer"]["version"] == 2
    assert [item["version"] for item in history.json()["items"]] == [2, 1]
    assert history.json()["items"][0]["change_note"] == "依据新版本修订"


@pytest.mark.asyncio
async def test_similarity_never_crosses_product_model_or_negated_intent(tmp_path):
    database_path = tmp_path / "qa.db"
    _create_qa_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        asked = await client.post(
            "/api/knowledge/questions/ask",
            json={"question": "V10是否标配环境光自动调节亮度功能？"},
        )
        await client.put(
            f"/api/knowledge/questions/{asked.json()['question_id']}/answer",
            json={
                "answer_text": "是，V10系列均为标配。",
                "alias_questions": [],
                "citations": [],
                "change_note": "产品经理确认",
            },
        )
        other_model = await client.post(
            "/api/knowledge/questions/ask",
            json={"question": "V9是否标配环境光自动调节亮度功能？"},
        )
        negated = await client.post(
            "/api/knowledge/questions/ask",
            json={"question": "V10是不是不支持环境光自动调节亮度功能？"},
        )
    await engine.dispose()

    assert other_model.json()["status"] == "pending"
    assert negated.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_observed_similar_wording_can_be_promoted_to_confirmed_alias(tmp_path):
    database_path = tmp_path / "qa.db"
    _create_qa_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        asked = await client.post(
            "/api/knowledge/questions/ask",
            json={"question": "环境光自动亮度调节是不是V10系列标配？"},
        )
        question_id = asked.json()["question_id"]
        await client.put(
            f"/api/knowledge/questions/{question_id}/answer",
            json={
                "answer_text": "是，V10系列均为标配。",
                "alias_questions": [],
                "citations": [],
                "change_note": "首次确认",
            },
        )
        wording = "V10是否标配环境光自动调节亮度功能"
        similar = await client.post(
            "/api/knowledge/questions/ask", json={"question": wording}
        )
        promoted = await client.put(
            f"/api/knowledge/questions/{question_id}/answer",
            json={
                "answer_text": "是，V10系列均为标配。",
                "alias_questions": [wording],
                "citations": [],
                "change_note": "确认常用问法",
            },
        )
    await engine.dispose()

    assert similar.json()["match_type"] == "similar"
    assert promoted.status_code == 200
    assert promoted.json()["alias_questions"] == [wording]
