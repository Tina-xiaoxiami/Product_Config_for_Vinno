import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import knowledge
from app.database import get_db

TEST_QUERY_SCOPE = {"country": "CN", "market": "domestic", "product_model_id": 901,
                    "software_version": "1.14.80"}


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
            version, market, country, product_series, mime_type
        ) VALUES (
            1, 'whitepaper', 'V10 1.14.80 白皮书', 'V10.pdf',
            '/tmp/V10.pdf', '1.14.80', 'domestic', 'CN', 'VINNO 10', 'application/pdf'
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
        CREATE TABLE registration_packages (
            id INTEGER PRIMARY KEY,
            registration_number TEXT,
            display_name TEXT NOT NULL,
            country_code TEXT NOT NULL DEFAULT 'CN',
            unit_code TEXT NOT NULL,
            is_enabled INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE registration_package_versions (
            id INTEGER PRIMARY KEY,
            package_id INTEGER NOT NULL REFERENCES registration_packages(id),
            certificate_document_id INTEGER NOT NULL REFERENCES knowledge_documents(id),
            difference_document_id INTEGER NOT NULL REFERENCES knowledge_documents(id),
            status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE registration_package_version_models (
            id INTEGER PRIMARY KEY,
            version_id INTEGER NOT NULL REFERENCES registration_package_versions(id),
            model_name TEXT NOT NULL
        );
        """
    )
    connection.commit()
    connection.close()


async def _client_for(database_path, *, migrate_scope=True):
    if migrate_scope:
        from app.services.knowledge_scope_migration import migrate_knowledge_scopes
        migrate_knowledge_scopes(database_path, apply=True)
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS product_series (id INTEGER PRIMARY KEY,name TEXT);
        CREATE TABLE IF NOT EXISTS product_models (id INTEGER PRIMARY KEY,name TEXT,series_id INTEGER);
        INSERT OR IGNORE INTO product_series VALUES (901,'R&V10 series-China'),(902,'R&V10 series-Oversea');
        INSERT OR IGNORE INTO product_models VALUES
            (901,'VINNO 10',901),(902,'VINNO 10E',901),(903,'VINNO 10',902);
        """)
        connection.commit()
    finally:
        connection.close()
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
async def test_saved_draft_survives_restart_and_only_publication_advances_version(tmp_path):
    path = tmp_path / "persistent-draft.db"
    _create_qa_database(path)
    client, engine = await _client_for(path)
    question = {"scope": TEST_QUERY_SCOPE, "question": "针增益功能适用什么配置？"}
    async with client:
        asked = await client.post("/api/knowledge/questions/ask", json=question)
        url = f"/api/knowledge/questions/{asked.json()['question_id']}"
        original = await client.put(f"{url}/answer", json={
            "answer_text": "首次发布", "citations": [{"document_id": 1, "source_ref": "第2页"}],
        })
        assert original.json()["answer"]["version"] == 1
        form = {"expected_version": 1, "expected_draft_revision": 0, "answer_text": "修订一", "change_note": "核对原文"}
        first = await client.put(f"{url}/draft-answer", json=form)
        assert first.status_code == 200, first.text
        token = first.json()["draft"]["revision"]
        assert first.json()["answer"]["answer_text"] == "首次发布"
        assert (await client.put(f"{url}/draft-answer", json=form)).status_code == 409
        second = await client.put(f"{url}/draft-answer", json={
            **form, "expected_draft_revision": token, "answer_text": "修订二",
            "citations": [{"document_id": 1, "source_ref": "第3页"}],
        })
        assert second.status_code == 200, second.text
        token = second.json()["draft"]["revision"]
    await engine.dispose()

    client, engine = await _client_for(path)
    try:
        async with client:
            restored = (await client.get(url)).json()
            assert restored["answer"]["version"] == 1
            assert restored["draft"]["revision"] == token
            assert restored["draft"]["answer_text"] == "修订二"
            assert (await client.post("/api/knowledge/questions/ask", json=question)).json()["answer"]["version"] == 1
            for _ in range(2):
                published = await client.put(f"{url}/answer", json={"draft_revision": token})
                assert published.status_code == 200, published.text
                assert published.json()["answer"]["version"] == 2
                assert published.json()["answer"]["answer_text"] == "修订二"
                assert published.json()["draft"] is None
            history = (await client.get(f"{url}/history")).json()["items"]
            published = [row for row in history if row["review_status"] == "published"]
            assert [row["version"] for row in published] == [2, 1]
            assert published[0]["citations"][0]["source_ref"] == "第3页"
            assert published[1]["citations"][0]["source_ref"] == "第2页"
            assert [row["answer_text"] for row in history if row["review_status"] == "draft"] == ["修订二", "修订一"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_question_enters_pending_queue_and_repeated_ask_is_counted(tmp_path):
    database_path = tmp_path / "qa.db"
    _create_qa_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        first = await client.post(
            "/api/knowledge/questions/ask",
            json={"scope": TEST_QUERY_SCOPE, "question": "针增益调节是招标功能吗？"},
        )
        repeated = await client.post(
            "/api/knowledge/questions/ask",
            json={"scope": TEST_QUERY_SCOPE, "question": "针增益调节是招标功能吗"},
        )
        pending = await client.get(
            "/api/knowledge/questions", params={**TEST_QUERY_SCOPE, "status": "pending"}
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
            json={"scope": TEST_QUERY_SCOPE, "question": "针增益调节是招标功能吗？"},
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
            json={"scope": TEST_QUERY_SCOPE, "question": "针增益是不是招标功能？"},
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
            json={"scope": TEST_QUERY_SCOPE, "question": "环境光自动亮度调节是不是V10系列标配？"},
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
            json={"scope": TEST_QUERY_SCOPE, "question": "V10是否标配环境光自动调节亮度功能"},
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
            "/api/knowledge/questions/ask", json={"scope": TEST_QUERY_SCOPE, "question": "一个待确认问题"}
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
            "/api/knowledge/questions/ask", json={"scope": TEST_QUERY_SCOPE, "question": "功能是否支持？"}
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
async def test_pending_question_can_merge_into_published_question_without_losing_usage(
    tmp_path,
):
    database_path = tmp_path / "qa.db"
    _create_qa_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        target = await client.post(
            "/api/knowledge/questions/ask",
            json={"scope": TEST_QUERY_SCOPE, "question": "V10湘证和苏证如何区分？"},
        )
        target_id = target.json()["question_id"]
        await client.put(
            f"/api/knowledge/questions/{target_id}/answer",
            json={
                "answer_text": "两张证分别展示，不合并注册结论。",
                "alias_questions": [],
                "citations": [],
                "change_note": "首次确认",
            },
        )
        source = await client.post(
            "/api/knowledge/questions/ask",
            json={"scope": TEST_QUERY_SCOPE, "question": "同一个V10型号同时映射湘证和苏证时怎么查？"},
        )
        assert source.json()["status"] == "pending"
        source_id = source.json()["question_id"]
        await client.post(
            "/api/knowledge/questions/ask",
            json={"scope": TEST_QUERY_SCOPE, "question": "同一个V10型号同时映射湘证和苏证时怎么查？"},
        )
        merged = await client.post(
            f"/api/knowledge/questions/{source_id}/merge/{target_id}"
        )
        removed = await client.get(f"/api/knowledge/questions/{source_id}")
        reused = await client.post(
            "/api/knowledge/questions/ask",
            json={"scope": TEST_QUERY_SCOPE, "question": "同一个V10型号同时映射湘证和苏证时怎么查？"},
        )
    await engine.dispose()

    assert merged.status_code == 200
    assert merged.json()["id"] == target_id
    assert merged.json()["asked_count"] == 3
    assert removed.status_code == 404
    assert reused.json()["question_id"] == target_id
    assert reused.json()["match_type"] == "exact"


@pytest.mark.asyncio
async def test_merge_rejects_answered_source_and_keeps_both_questions(tmp_path):
    database_path = tmp_path / "qa.db"
    _create_qa_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        first = await client.post(
            "/api/knowledge/questions/ask", json={"scope": TEST_QUERY_SCOPE, "question": "第一个问题"}
        )
        second = await client.post(
            "/api/knowledge/questions/ask", json={"scope": TEST_QUERY_SCOPE, "question": "第二个问题"}
        )
        await client.put(
            f"/api/knowledge/questions/{first.json()['question_id']}/answer",
            json={
                "answer_text": "已发布答案",
                "alias_questions": [],
                "citations": [],
                "change_note": "首次确认",
            },
        )
        rejected = await client.post(
            f"/api/knowledge/questions/{first.json()['question_id']}/merge/"
            f"{second.json()['question_id']}"
        )
        first_after = await client.get(
            f"/api/knowledge/questions/{first.json()['question_id']}"
        )
        second_after = await client.get(
            f"/api/knowledge/questions/{second.json()['question_id']}"
        )
    await engine.dispose()

    assert rejected.status_code == 422
    assert first_after.status_code == 200
    assert second_after.status_code == 200


@pytest.mark.asyncio
async def test_similarity_never_crosses_product_model_or_negated_intent(tmp_path):
    database_path = tmp_path / "qa.db"
    _create_qa_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        asked = await client.post(
            "/api/knowledge/questions/ask",
            json={"scope": TEST_QUERY_SCOPE, "question": "V10是否标配环境光自动调节亮度功能？"},
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
            json={"scope": TEST_QUERY_SCOPE, "question": "V9是否标配环境光自动调节亮度功能？"},
        )
        negated = await client.post(
            "/api/knowledge/questions/ask",
            json={"scope": TEST_QUERY_SCOPE, "question": "V10是不是不支持环境光自动调节亮度功能？"},
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
            json={"scope": TEST_QUERY_SCOPE, "question": "环境光自动亮度调节是不是V10系列标配？"},
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
            "/api/knowledge/questions/ask", json={"scope": TEST_QUERY_SCOPE, "question": wording}
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


@pytest.mark.asyncio
async def test_merge_rejects_pending_source_with_answer_and_preserves_history(tmp_path):
    database = tmp_path / 'qa.db'
    _create_qa_database(database)
    client, engine = await _client_for(database)
    async with client:
        source = (await client.post('/api/knowledge/questions/ask', json={'scope': TEST_QUERY_SCOPE, 'question': '原有问题'})).json()['question_id']
        target = (await client.post('/api/knowledge/questions/ask', json={'scope': TEST_QUERY_SCOPE, 'question': '其他问题'})).json()['question_id']
        payload = {'answer_text': '保留原答案', 'citations': [{'document_id': 1, 'source_ref': '第1页', 'excerpt': '保留引文'}], 'change_note': '原审核'}
        await client.put(f'/api/knowledge/questions/{source}/answer', json=payload)
        await client.put(f'/api/knowledge/questions/{target}/answer', json={'answer_text': '目标答案'})
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE knowledge_answers SET review_status = 'source_changed' WHERE question_id = ?", (source,))
            connection.execute("UPDATE knowledge_questions SET status = 'pending' WHERE id = ?", (source,))
        rejected = await client.post(f'/api/knowledge/questions/{source}/merge/{target}')
        detail = await client.get(f'/api/knowledge/questions/{source}')
        history = await client.get(f'/api/knowledge/questions/{source}/history')
    await engine.dispose()
    assert rejected.status_code == 422
    assert detail.json()['answer']['answer_text'] == '保留原答案'
    assert detail.json()['answer']['citations'][0]['excerpt'] == '保留引文'
    assert history.json()['items'][0]['answer_text'] == '保留原答案'


@pytest.mark.asyncio
async def test_ask_does_not_return_answer_changed_during_lookup(tmp_path, monkeypatch):
    from sqlalchemy import text
    from app.services import knowledge_qa

    database = tmp_path / 'qa.db'
    _create_qa_database(database)
    client, engine = await _client_for(database)
    async with client:
        question_id = (await client.post('/api/knowledge/questions/ask', json={'scope': TEST_QUERY_SCOPE, 'question': '测试问题'})).json()['question_id']
        await client.put(f'/api/knowledge/questions/{question_id}/answer', json={'answer_text': '旧答案'})
        original = knowledge_qa._published_candidates
        async def changed_during_lookup(session, query_scope_key):
            candidates = await original(session, query_scope_key)
            await session.execute(text("UPDATE knowledge_answers SET review_status = 'source_changed' WHERE question_id = :id"), {'id': question_id})
            await session.execute(text("UPDATE knowledge_questions SET status = 'pending' WHERE id = :id"), {'id': question_id})
            await session.commit()
            return candidates
        monkeypatch.setattr(knowledge_qa, '_published_candidates', changed_during_lookup)
        response = await client.post('/api/knowledge/questions/ask', json={'scope': TEST_QUERY_SCOPE, 'question': '测试问题'})
    await engine.dispose()
    assert response.json()['status'] == 'pending'
    assert response.json()['answer'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("answer_status,revision_status,expected_version,http_status", [
    ("draft", "draft", 1, 204),
    ("draft", "draft", 2, 409),
    ("published", "published", 1, 409),
    ("draft", "published", 1, 409),
    (None, None, None, 204),
])
async def test_delete_pending_question_only_removes_unpublished_drafts(
    tmp_path, answer_status, revision_status, expected_version, http_status,
):
    database = tmp_path / "delete-question.db"
    _create_qa_database(database)
    client, engine = await _client_for(database)
    try:
        with sqlite3.connect(database) as db:
            db.execute("INSERT INTO knowledge_questions(id, question_text, normalized_question) VALUES (1,'测试草稿','测试草稿')")
            db.execute("INSERT INTO knowledge_questions(id, question_text, normalized_question) VALUES (2,'其他问题','其他问题')")
            db.execute("INSERT INTO knowledge_question_phrasings(question_id, phrasing_text, normalized_phrasing) VALUES (1,'另一个问法','另一个问法')")
            if answer_status:
                db.execute("INSERT INTO knowledge_answers(id, question_id, answer_text, review_status) VALUES (1,1,'内容',?)", (answer_status,))
                db.execute("INSERT INTO knowledge_answer_citations(answer_id, document_id) VALUES (1,1)")
                db.execute("INSERT INTO knowledge_answer_revisions(answer_id, version, answer_text, review_status) VALUES (1,1,'内容',?)", (revision_status,))
        async with client:
            result = await client.request("DELETE", "/api/knowledge/questions/1", json={
                "expected_question": "测试草稿", "expected_scope": None, "expected_answer_version": expected_version,
            })
            assert result.status_code == http_status, result.text
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT id FROM knowledge_questions ORDER BY id").fetchall() == (
                [(2,)] if http_status == 204 else [(1,), (2,)]
            )
            assert db.execute("SELECT id FROM knowledge_documents").fetchall() == [(1,)]
            assert db.execute("SELECT count(*) FROM knowledge_question_phrasings").fetchone()[0] == int(http_status != 204)
            for table in ("knowledge_answers", "knowledge_answer_citations", "knowledge_answer_revisions"):
                assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == int(http_status != 204 and bool(answer_status))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_revise_unscoped_draft_preserves_citations_and_rejects_stale_version(tmp_path):
    database = tmp_path / "draft-revision.db"
    _create_qa_database(database)
    client, engine = await _client_for(database)
    try:
        with sqlite3.connect(database) as db:
            db.execute("INSERT INTO knowledge_questions(id,question_text,normalized_question) VALUES (1,'续航多久','续航多久')")
            db.execute("INSERT INTO knowledge_answers(id,question_id,answer_text,review_status) VALUES (1,1,'旧草稿','draft')")
            db.execute("INSERT INTO knowledge_answer_citations(answer_id,document_id,source_ref) VALUES (1,1,'第2行')")
        async with client:
            url = "/api/knowledge/questions/1/draft-answer"
            body = {"answer_text": "45 分钟\n\nB 模式", "expected_version": 1, "change_note": "按原表修订"}
            saved = await client.put(url, json=body)
            assert saved.status_code == 200, saved.text
            data = saved.json()
            assert data["status"] == "pending" and data["scope"] is None
            assert data["answer"]["review_status"] == "draft" and data["answer"]["version"] == 2
            assert data["answer"]["answer_text"] == body["answer_text"]
            assert data["answer"]["citations"][0]["source_ref"] == "第2行"
            assert (await client.put(url, json=body)).status_code == 409
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT version,answer_text FROM knowledge_answer_revisions ORDER BY version").fetchall() == [
                (1, "旧草稿"), (2, body["answer_text"]),
            ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True], ids=["fresh-orm", "existing-scoped"])
@pytest.mark.parametrize("same_question", [True, False], ids=["same-question", "different-question"])
async def test_retired_question_id_cannot_mutate_recreated_question(tmp_path, monkeypatch, existing, same_question):
    from app.models.knowledge import KnowledgeQuestion, KnowledgeQuestionPhrasing
    from app.services.knowledge_scope_migration import migrate_knowledge_scopes

    database = tmp_path / "question-lifecycle.db"
    _create_qa_database(database)
    with sqlite3.connect(database) as conn:
        conn.executescript("DROP TABLE knowledge_question_phrasings; DROP TABLE knowledge_questions;")
    tables = [KnowledgeQuestion.__table__, KnowledgeQuestionPhrasing.__table__]
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    try:
        with monkeypatch.context() as patch:
            if existing:
                # Reproduce databases created by the ORM before the fix.
                patch.setitem(KnowledgeQuestion.__table__.dialect_options["sqlite"], "autoincrement", False)
            async with engine.begin() as conn:
                await conn.run_sync(lambda sync: KnowledgeQuestion.metadata.create_all(sync, tables=tables))
    finally:
        await engine.dispose()

    async def ask(client, question):
        response = await client.post("/api/knowledge/questions/ask", json={
            "scope": TEST_QUERY_SCOPE, "question": question,
        })
        assert response.status_code == 200, response.text
        return response.json()["question_id"]

    client, engine = await _client_for(database, migrate_scope=False)
    try:
        async with client:
            target_id = await ask(client, "已发布的目标问题")
            target_url = f"/api/knowledge/questions/{target_id}"
            published = await client.put(f"{target_url}/answer", json={
                "answer_text": "已发布答案", "alias_questions": ["已发布问题的别名"],
                "citations": [{"document_id": 1, "source_ref": "第12页"}],
            })
            assert published.status_code == 200, published.text
            old_id = await ask(client, "电池续航多久？")
            old_url = f"/api/knowledge/questions/{old_id}"
            with sqlite3.connect(database) as conn:
                conn.execute("""
                    INSERT INTO knowledge_answers(question_id,answer_text,review_status,version)
                    VALUES (?,'旧草稿','draft',1)
                """, (old_id,))
            old = (await client.get(old_url)).json()
            old_delete = {"expected_question": old["question_text"], "expected_scope": old["scope"],
                          "expected_answer_version": 1}
            if existing:
                # A pre-migration process must not delete IDs it cannot retire durably.
                blocked = await client.request("DELETE", old_url, json=old_delete)
                assert blocked.status_code == 409, blocked.text
                assert (await client.get(old_url)).json() == old
                assert migrate_knowledge_scopes(database)["status"] == "ready_question_ids"
                report = migrate_knowledge_scopes(database, apply=True)
                assert report["status"] == "applied"
                assert migrate_knowledge_scopes(database)["status"] == "already_current"
                assert (await client.get(old_url)).json() == old
                assert (await client.get(target_url)).json() == published.json()

            deleted = await client.request("DELETE", old_url, json=old_delete)
            assert deleted.status_code == 204, deleted.text
            replacement = old["question_text"] if same_question else "新问题的独立答案？"
            new_id = await ask(client, replacement)
            new_url = f"/api/knowledge/questions/{new_id}"
            with sqlite3.connect(database) as conn:
                conn.execute("""
                    INSERT INTO knowledge_answers(question_id,answer_text,review_status,version)
                    VALUES (?,'新草稿','draft',1)
                """, (new_id,))
            stale_delete = await client.request("DELETE", old_url, json=old_delete)
            stale_revision = {"answer_text": "过期请求", "expected_version": 1, "change_note": "旧表单"}
            stale_draft = await client.put(f"{old_url}/draft-answer", json=stale_revision)
            assert (stale_delete.status_code, stale_draft.status_code) == (404, 404)
            assert new_id > old_id
            assert (await client.put(f"{old_url}/answer", json={"answer_text": "过期发布"})).status_code == 404
            assert (await client.post(f"{old_url}/merge/{target_id}")).status_code == 404
            new = (await client.get(new_url)).json()
            assert new["answer"]["answer_text"] == "新草稿"
            assert new["answer"]["version"] == 1
            revised = await client.put(f"{new_url}/draft-answer", json={
                "answer_text": "修订的新草稿", "expected_version": 1, "change_note": "已核对",
            })
            assert revised.status_code == 200
            assert revised.json()["answer"]["version"] == 2
            assert (await client.get(f"{target_url}/history")).json()["items"][0]["answer_text"] == "已发布答案"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_draft_question_edit_rejects_same_scope_duplicates_and_records_old_wording(tmp_path):
    database = tmp_path / "draft-question.db"
    _create_qa_database(database)
    client, engine = await _client_for(database)
    try:
        with sqlite3.connect(database) as db:
            db.execute("INSERT INTO knowledge_questions(id,question_text,normalized_question) VALUES (1,'旧问题','旧问题'),(2,'另一个问题','另一个问题')")
            db.execute("INSERT INTO knowledge_question_phrasings(question_id,phrasing_text,normalized_phrasing) VALUES (2,'其他问法','其他问法')")
            db.execute("INSERT INTO knowledge_answers(id,question_id,answer_text,review_status) VALUES (1,1,'旧答案','draft')")
            db.execute("INSERT INTO knowledge_answer_citations(answer_id,document_id,source_ref) VALUES (1,1,'第2行')")
        async with client:
            url = "/api/knowledge/questions/1"
            body = {"answer_text": "| 模式 | 时长 |\n| --- | --- |\n| B | 45 分钟 |",
                    "expected_version": 1, "change_note": "按原表修订"}
            for name in ("另一个问题？", "其他问法？", "？？"):
                response = await client.put(f"{url}/draft-answer", json={**body, "question_text": name})
                assert response.status_code == 409, response.text
            before = (await client.get(url)).json()
            assert before["question_text"] == "旧问题" and before["answer"]["version"] == 1
            saved = await client.put(f"{url}/draft-answer", json={**body, "question_text": "V10 的续航是多少？"})
            assert saved.status_code == 200, saved.text
            saved = saved.json()
            assert saved["question_text"] == "V10 的续航是多少？"
            assert saved["answer"]["answer_text"] == body["answer_text"]
            assert saved["answer"]["citations"] == before["answer"]["citations"]
            history = (await client.get(f"{url}/history")).json()["items"]
            assert [r["version"] for r in history] == [2, 1]
            assert "旧问题" in history[0]["change_note"] and "V10 的续航是多少？" in history[0]["change_note"]
            assert history[0]["answer_text"] == body["answer_text"]
            assert (await client.put(f"{url}/draft-answer", json={**body, "question_text": "旧请求"})).status_code == 409
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_spreadsheet_citations_return_registered_header_exact_rows_and_hidden_flag(tmp_path):
    from hashlib import sha256
    from openpyxl import Workbook

    source = tmp_path / "runtime.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "实测"
    sheet.append(["机型", "模式", "探头", "放电时长"])
    sheet.append(["V10", "B", "S1-6PV", 52])
    sheet.append(["V10", "B", "S1-6PV", 60])
    sheet.row_dimensions[3].hidden = True
    sheet.append(["V6", "B", "X4-12L", 100])
    book.save(source)
    version = sha256(source.read_bytes()).hexdigest()
    database = tmp_path / "citation.db"
    _create_qa_database(database)
    client, engine = await _client_for(database)
    try:
        with sqlite3.connect(database) as db:
            db.execute("UPDATE knowledge_documents SET file_name=?,file_path=?,sha256=?,mime_type=NULL WHERE id=1",
                       (source.name, str(source), version))
            db.execute("INSERT INTO knowledge_questions(id,question_text,normalized_question) VALUES (1,'续航问题','续航问题')")
            db.execute("INSERT INTO knowledge_answers(id,question_id,answer_text,review_status) VALUES (1,1,'原答案','draft')")
            db.executemany("INSERT INTO knowledge_answer_citations(answer_id,document_id,source_ref) VALUES (1,1,?)",
                           [("工作表 实测 · 第 2 行",), ("工作表 实测 · 第 3 行（原表隐藏行）",)])
        async with client:
            url = "/api/knowledge/questions/1/spreadsheet-citations"
            assert (await client.get(url, params={"expected_version": 2})).status_code == 409
            result = await client.get(url, params={"expected_version": 1})
            assert result.status_code == 200, result.text
            group, = result.json()["tables"]
            assert group["columns"] == ["机型", "模式", "探头", "放电时长"]
            assert [(r["row_number"], r["hidden"], r["cells"][-1]) for r in group["rows"]] == [(2, False, "52"), (3, True, "60")]
            assert group["preview_url"].endswith(version)
            source.write_bytes(b"changed")
            assert (await client.get(url)).json()["warnings"]
            assert not (await client.get(url)).json()["tables"]
    finally:
        await engine.dispose()
