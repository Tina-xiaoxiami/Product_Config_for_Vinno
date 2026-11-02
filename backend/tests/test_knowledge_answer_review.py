"""In-app review is explicit, scoped, atomic and independent of source answer text."""

from contextlib import closing
import sqlite3

import pytest

from test_knowledge_qa_api import _client_for, _create_qa_database


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "review.db"
    _create_qa_database(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript("""
        INSERT INTO knowledge_questions (id,question_text,normalized_question,status,asked_count)
        VALUES (101,'历史功能说明','历史功能说明','answered',3),
               (102,'另一个待核对问题','另一个待核对问题','answered',0),
               (103,'已有文档的问题','已有文档的问题','answered',1);
        INSERT INTO knowledge_answers (id,question_id,answer_text,change_note)
        VALUES (201,101,'完整历史答案\n第二段原文','既有负责人确认'),
               (202,102,'另一个完整答案','既有确认'),(203,103,'文档答案','原文依据');
        INSERT INTO knowledge_answer_citations (answer_id,document_id,source_ref) VALUES (203,1,'第1页');
        CREATE TABLE knowledge_answer_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            answer_id INTEGER NOT NULL REFERENCES knowledge_answers(id) ON DELETE CASCADE,
            answer_version INTEGER NOT NULL, source_fingerprint TEXT NOT NULL,
            review_revision INTEGER NOT NULL, action TEXT NOT NULL,
            country TEXT, market TEXT, model_ids_json TEXT NOT NULL DEFAULT '[]',
            software_version TEXT, version_applicability TEXT NOT NULL,
            evidence_reference TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
            confirmed_by TEXT NOT NULL, target_question_ids_json TEXT NOT NULL DEFAULT '[]',
            request_fingerprint TEXT NOT NULL,
            reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(answer_id,review_revision)
        );
        """)
    return path


async def _payload(client, question_id=101, **extra):
    item = (await client.get(f"/api/knowledge/questions/{question_id}")).json()
    review = item["evidence_review"]
    return {
        "expected_answer_version": item["answer"]["version"],
        "expected_fingerprint": review["fingerprint"],
        "expected_review_revision": review["review_revision"],
        "action": "record_reference", "country": None, "market": None,
        "product_model_ids": [], "software_version": None,
        "version_applicability": "unknown", "evidence_reference": "2026-09-03历史确认记录",
        "note": "保留历史依据", "confirmed_by": "测试负责人", **extra,
    }


@pytest.mark.asyncio
async def test_queue_derived_from_evidence_and_counts_before_pagination(database):
    client, engine = await _client_for(database)
    before = database.read_bytes()
    async with client:
        result = await client.get("/api/knowledge/questions", params={"evidence_review": "needs_review", "status": "answered", "limit": 1})
        assert result.status_code == 200, result.text
        assert result.json()["total"] == 2
        assert len(result.json()["items"]) == 1
        item = (await client.get("/api/knowledge/questions/101")).json()
        assert item["answer"]["answer_text"] == "完整历史答案\n第二段原文"
        assert item["evidence_review"]["status"] == "needs_review"
        assert item["evidence_review"]["review_revision"] == 0
        assert len(item["evidence_review"]["fingerprint"]) == 64
    await engine.dispose()
    assert database.read_bytes() == before


@pytest.mark.asyncio
async def test_reference_review_does_not_republish_or_change_source_and_retry_is_idempotent(database):
    client, engine = await _client_for(database)
    async with client:
        payload = await _payload(client, version_applicability="not_applicable")
        saved = await client.post("/api/knowledge/questions/101/review", json=payload)
        repeated = await client.post("/api/knowledge/questions/101/review", json=payload)
        assert saved.status_code == repeated.status_code == 200, saved.text
        review = saved.json()["evidence_review"]
        assert review["status"] == "reviewed"
        assert review["review_revision"] == 1
        assert review["latest"]["confirmed_by"] == "测试负责人"
        assert review["latest"]["target_question_ids"] == []
        assert saved.json()["answer"]["version"] == 1
        assert saved.json()["answer"]["change_note"] == "既有负责人确认"
        assert saved.json()["scope"] is None
        remaining = await client.get("/api/knowledge/questions", params={"evidence_review": "needs_review"})
        reviewed = await client.get("/api/knowledge/questions", params={"evidence_review": "reviewed"})
        assert remaining.json()["total"] == reviewed.json()["total"] == 1
    await engine.dispose()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM knowledge_answer_reviews").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM knowledge_questions").fetchone()[0] == 3


@pytest.mark.asyncio
async def test_confirm_scope_creates_independent_query_answers_without_counting_asks(database):
    client, engine = await _client_for(database)
    async with client:
        payload = await _payload(client, action="confirm_scope", country="CN", market="domestic",
                                 product_model_ids=[901, 902], software_version="1.14.80", version_applicability="specific")
        response = await client.post("/api/knowledge/questions/101/review", json=payload)
        assert response.status_code == 200, response.text
        ids = response.json()["evidence_review"]["latest"]["target_question_ids"]
        assert len(ids) == len(set(ids)) == 2
        assert response.json()["scope"] is None
        for model in [901, 902]:
            scope = {"country": "CN", "market": "domestic", "product_model_id": model, "software_version": "1.14.80"}
            result = await client.get("/api/knowledge/questions", params=scope)
            assert result.json()["total"] == 1
            assert result.json()["items"][0]["asked_count"] == 0
            assert result.json()["items"][0]["answer"]["answer_text"] == "完整历史答案\n第二段原文"
        queue = await client.get("/api/knowledge/questions", params={"evidence_review": "needs_review"})
        reviewed = await client.get("/api/knowledge/questions", params={"evidence_review": "reviewed"})
        assert queue.json()["total"] == 1
        assert reviewed.json()["total"] == 3
        assert (await client.post("/api/knowledge/questions/101/review", json=payload)).status_code == 200
    await engine.dispose()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM knowledge_questions").fetchone()[0] == 5
        assert connection.execute("SELECT COUNT(*) FROM knowledge_answer_reviews").fetchone()[0] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["answer", "review", "citation"])
async def test_stale_answer_citation_or_review_is_rejected(database, mutation):
    client, engine = await _client_for(database)
    async with client:
        payload = await _payload(client)
        if mutation == "review":
            assert (await client.post("/api/knowledge/questions/101/review", json={**payload, "note": "first"})).status_code == 200
        else:
            with closing(sqlite3.connect(database)) as connection, connection:
                if mutation == "answer":
                    connection.execute("UPDATE knowledge_answers SET answer_text='changed without version' WHERE id=201")
                else:
                    connection.execute("INSERT INTO knowledge_answer_citations (answer_id,document_id,source_ref) VALUES (201,1,'p2')")
        result = await client.post("/api/knowledge/questions/101/review", json=payload)
        assert result.status_code == 409, result.text
    await engine.dispose()


@pytest.mark.asyncio
async def test_defer_remains_pending_and_later_source_changes_make_confirmation_stale(database):
    client, engine = await _client_for(database)
    async with client:
        payload = await _payload(client, action="defer", note="需核实具体版本")
        saved = await client.post("/api/knowledge/questions/101/review", json=payload)
        assert saved.status_code == 200, saved.text
        assert saved.json()["evidence_review"]["status"] == "needs_review"
        current = await _payload(client)
        assert (await client.post("/api/knowledge/questions/101/review", json=current)).status_code == 200
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("UPDATE knowledge_answers SET version=2,answer_text='new' WHERE id=201")
        item = (await client.get("/api/knowledge/questions/101")).json()
        assert item["evidence_review"]["status"] == "needs_review"
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("models", [[901, 99999], [901, 903]])
async def test_multi_scope_validation_failure_rolls_back_everything(database, models):
    client, engine = await _client_for(database)
    async with client:
        payload = await _payload(client, action="confirm_scope", country="CN", market="domestic",
                                 product_model_ids=models, software_version="1.14.80", version_applicability="specific")
        result = await client.post("/api/knowledge/questions/101/review", json=payload)
        assert result.status_code == 422, result.text
    await engine.dispose()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM knowledge_questions").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM knowledge_answer_reviews").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_missing_review_table_keeps_readable_queue_and_refuses_writes(database):
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("DROP TABLE knowledge_answer_reviews")
    client, engine = await _client_for(database)
    async with client:
        payload = await _payload(client)
        item = (await client.get("/api/knowledge/questions/101")).json()
        assert item["evidence_review"]["available"] is False
        assert item["evidence_review"]["status"] == "needs_review"
        assert (await client.post("/api/knowledge/questions/101/review", json=payload)).status_code == 503
    await engine.dispose()


@pytest.mark.asyncio
async def test_existing_different_scoped_answer_prevents_all_partial_publications(database):
    client, engine = await _client_for(database)
    async with client:
        scope = {"country": "CN", "market": "domestic", "product_model_id": 902, "software_version": "1.14.80"}
        asked = (await client.post("/api/knowledge/questions/ask", json={"question": "历史功能说明", "scope": scope})).json()
        assert (await client.put(f"/api/knowledge/questions/{asked['question_id']}/answer", json={"answer_text": "不同的现行答案"})).status_code == 200
        payload = await _payload(client, action="confirm_scope", country="CN", market="domestic",
                                 product_model_ids=[901, 902], software_version="1.14.80", version_applicability="specific")
        refused = await client.post("/api/knowledge/questions/101/review", json=payload)
        assert refused.status_code == 409, refused.text
        first_scope = await client.get("/api/knowledge/questions", params={**scope, "product_model_id": 901})
        assert first_scope.json()["total"] == 0
    await engine.dispose()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM knowledge_answer_reviews").fetchone()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"confirmed_by": " "}, {"evidence_reference": " "}, {"action": "defer", "note": " "},
    {"country": "CHINA"}, {"country": "DE", "market": "domestic"},
    {"product_model_ids": [-1]},
    {"action": "confirm_scope", "version_applicability": "unknown"},
    {"action": "confirm_scope", "product_model_ids": [901], "version_applicability": "specific"},
])
async def test_incomplete_review_is_rejected_without_a_decision(database, changes):
    client, engine = await _client_for(database)
    async with client:
        payload = await _payload(client, **changes)
        result = await client.post("/api/knowledge/questions/101/review", json=payload)
        assert result.status_code == 422, result.text
    await engine.dispose()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM knowledge_answer_reviews").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_missing_answer_and_review_filter_validation(database):
    client, engine = await _client_for(database)
    async with client:
        payload = await _payload(client)
        assert (await client.post("/api/knowledge/questions/99999/review", json=payload)).status_code == 404
        assert (await client.get("/api/knowledge/questions", params={"evidence_review": "anything"})).status_code == 422
    await engine.dispose()
