"""Country/market/model/software isolation at the public Q&A boundary."""

from contextlib import closing
import sqlite3

import pytest

from test_knowledge_qa_api import _client_for, _create_qa_database


SCOPE = {"country": "CN", "market": "domestic", "product_model_id": 901,
         "software_version": "1.14.80"}


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "knowledge.db"
    _create_qa_database(path)
    return path


async def _ask(client, question="功能如何操作？", scope=SCOPE):
    return await client.post("/api/knowledge/questions/ask", json={"question": question, "scope": scope})


async def _publish(client, question_id, *, alias="功能操作步骤？"):
    response = await client.put(f"/api/knowledge/questions/{question_id}/answer", json={
        "answer_text": "Only valid for the selected scope", "alias_questions": [alias],
        "citations": [], "change_note": "Explicit synthetic owner confirmation",
    })
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_missing_scope_clarifies_without_writes_even_when_a_legacy_answer_exists(database):
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript("""
        INSERT INTO knowledge_questions (id,question_text,normalized_question,status)
        VALUES (71,'功能如何操作？','功能如何操作','answered');
        INSERT INTO knowledge_answers (question_id,answer_text) VALUES (71,'legacy answer');
        """)
    client, engine = await _client_for(database)
    before = database.read_bytes()
    async with client:
        missing = await _ask(client, scope=None)
        partial = await _ask(client, scope={"country": "CN"})
        legacy = await client.get("/api/knowledge/questions/71")
    await engine.dispose()
    assert missing.json()["status"] == "needs_clarification"
    assert missing.json()["question_id"] is None
    assert missing.json()["answer"] is None
    assert set(missing.json()["missing_fields"]) == set(SCOPE)
    assert set(partial.json()["missing_fields"]) == set(SCOPE) - {"country"}
    assert database.read_bytes() == before
    assert legacy.json()["scope"] is None
    assert legacy.json()["answer"]["answer_text"] == "legacy answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("other", [
    {**SCOPE, "software_version": "1.14.81"},
    {**SCOPE, "product_model_id": 902},
    {"country": "DE", "market": "overseas", "product_model_id": 903, "software_version": "1.14.80"},
])
async def test_same_question_and_alias_are_independent_across_scopes(database, other):
    client, engine = await _client_for(database)
    async with client:
        first = (await _ask(client)).json()
        await _publish(client, first["question_id"])
        second = (await _ask(client, scope=other)).json()
        assert second["status"] == "pending"
        assert second["question_id"] != first["question_id"]
        await _publish(client, second["question_id"])
        alias_first = (await _ask(client, "功能操作步骤？")).json()
        alias_second = (await _ask(client, "功能操作步骤？", other)).json()
        scoped = await client.get("/api/knowledge/questions", params=SCOPE)
        legacy = await client.get("/api/knowledge/questions")
    await engine.dispose()
    assert alias_first["question_id"] == first["question_id"]
    assert alias_second["question_id"] == second["question_id"]
    assert alias_first["scope"]["product_model_id"] == SCOPE["product_model_id"]
    assert scoped.json()["total"] == 1
    assert scoped.json()["items"][0]["id"] == first["question_id"]
    assert legacy.json()["total"] == 0


@pytest.mark.asyncio
async def test_country_isolation_within_overseas_and_numeric_version_normalization(database):
    client, engine = await _client_for(database)
    german = {**SCOPE, "country": "DE", "market": "overseas", "product_model_id": 903}
    async with client:
        first = (await _ask(client, scope=german)).json()
        await _publish(client, first["question_id"])
        french = (await _ask(client, scope={**german, "country": "FR"})).json()
        normalized = (await _ask(client, scope={**german, "country": "de", "software_version": "01.014.080"})).json()
    await engine.dispose()
    assert french["status"] == "pending"
    assert french["question_id"] != first["question_id"]
    assert normalized["question_id"] == first["question_id"]
    assert normalized["scope"]["software_version"] == "1.14.80"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_scope", [
    {**SCOPE, "country": "US"}, {**SCOPE, "market": "overseas"},
    {**SCOPE, "product_model_id": 999999}, {**SCOPE, "software_version": "1.14.XX"},
    {**SCOPE, "country": ""}, {**SCOPE, "extra_field": "ignored?"},
])
async def test_invalid_or_conflicting_scope_is_rejected_or_clarified_without_a_question(database, bad_scope):
    client, engine = await _client_for(database)
    async with client:
        result = await _ask(client, scope=bad_scope)
    await engine.dispose()
    assert result.status_code == 422 or result.json()["status"] == "needs_clarification"
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM knowledge_questions").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_legacy_answer_is_not_reused_for_a_complete_scope(database):
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript("""
        INSERT INTO knowledge_questions (question_text,normalized_question,status)
        VALUES ('功能如何操作？','功能如何操作','answered');
        INSERT INTO knowledge_answers (question_id,answer_text) VALUES (1,'legacy');
        """)
    client, engine = await _client_for(database)
    async with client:
        response = (await _ask(client)).json()
    await engine.dispose()
    assert response["status"] == "pending"
    assert response["question_id"] != 1


@pytest.mark.asyncio
async def test_scoped_candidates_and_direct_question_candidates_reject_unscoped_documents(database):
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript("""
        UPDATE knowledge_documents SET country='CN',product_series='VINNO 10',version='1.14.80' WHERE id=1;
        INSERT INTO knowledge_document_extractions
        (document_id,extractor_version,status,chunk_count) VALUES (1,'test','completed',1);
        INSERT INTO knowledge_document_chunks
        (document_id,chunk_index,source_ref,content,normalized_content,content_hash)
        VALUES (1,0,'p1','环境光自动亮度调节','环境光自动亮度调节','hash');
        """)
    client, engine = await _client_for(database)
    async with client:
        first = (await _ask(client, "环境光自动亮度调节")).json()
        other = (await _ask(client, "环境光自动亮度调节", {**SCOPE, "product_model_id": 902})).json()
        direct = await client.get(f"/api/knowledge/questions/{other['question_id']}/candidates")
        forbidden = await client.put(f"/api/knowledge/questions/{other['question_id']}/answer", json={
            "answer_text": "wrong source", "alias_questions": [],
            "citations": [{"document_id": 1, "source_ref": "p1"}], "change_note": "test",
        })
    await engine.dispose()
    assert first["candidates"]
    assert other["candidates"] == []
    assert direct.json()["items"] == []
    assert forbidden.status_code == 422


@pytest.mark.asyncio
async def test_cross_scope_merge_cannot_reassign_aliases_or_counts(database):
    client, engine = await _client_for(database)
    async with client:
        first = (await _ask(client, "操作说明怎么找？")).json()
        other = (await _ask(client, "功能操作步骤？", {**SCOPE, "software_version": "1.14.81"})).json()
        await _publish(client, first["question_id"], alias="查阅步骤")
        merged = await client.post(f"/api/knowledge/questions/{other['question_id']}/merge/{first['question_id']}")
    await engine.dispose()
    assert merged.status_code == 422
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM knowledge_questions").fetchone()[0] == 2
