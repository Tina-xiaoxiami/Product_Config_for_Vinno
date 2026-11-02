"""Country-neutral QA reads legacy provenance without rewriting or bypassing owners."""

from contextlib import closing
import sqlite3

import pytest

from app.services.knowledge_scope import scope_key, stored_scope
from app.services.knowledge_qa import normalize_question
from app.services.knowledge_qa_snapshot import export_knowledge_qa_snapshot, restore_knowledge_qa_snapshot
from test_knowledge_qa_api import _client_for, _create_qa_database
from test_knowledge_answer_review import database as review_database, _payload
from test_knowledge_scope_snapshot import _create


NEUTRAL = {"market": "overseas", "product_model_id": 903, "software_version": "1.14.80"}
QUESTION = "环境光自动亮度调节如何使用？"
ANSWER = "在设置中开启环境光自动亮度调节。"


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "country-free.db"
    _create_qa_database(path)
    return path


async def ask(client, question=QUESTION, scope=NEUTRAL):
    response = await client.post("/api/knowledge/questions/ask", json={"question": question, "scope": scope})
    assert response.status_code == 200, response.text
    return response.json()


async def publish(client, question_id, answer=ANSWER, aliases=None):
    return await client.put(f"/api/knowledge/questions/{question_id}/answer", json={
        "answer_text": answer, "alias_questions": aliases or [], "citations": [],
    })


async def legacy_answer(client, country="DE", answer=ANSWER, question=QUESTION, aliases=None):
    item = await ask(client, question, {**NEUTRAL, "country": country})
    response = await publish(client, item["question_id"], answer, aliases)
    assert response.status_code == 200, response.text
    return item["question_id"]


@pytest.mark.asyncio
async def test_three_field_ask_list_publish_and_scope_round_trip(database):
    client, engine = await _client_for(database)
    async with client:
        pending = await ask(client)
        assert pending["status"] == "pending"
        assert pending["scope"]["country"] is None
        saved = await publish(client, pending["question_id"])
        assert saved.status_code == 200, saved.text
        repeated = await ask(client)
        listed = await client.get("/api/knowledge/questions", params=NEUTRAL)
        assert repeated["status"] == "answered"
        assert listed.json()["total"] == 1
        assert stored_scope(scope_key(saved.json()["scope"])) == saved.json()["scope"]
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", list(NEUTRAL))
async def test_three_required_dimensions_clarify_without_writes(database, missing):
    client, engine = await _client_for(database)
    before = database.read_bytes()
    async with client:
        result = await ask(client, scope={k: v for k, v in NEUTRAL.items() if k != missing})
        assert result["status"] == "needs_clarification"
        assert result["missing_fields"] == [missing]
    await engine.dispose()
    assert database.read_bytes() == before


@pytest.mark.asyncio
async def test_legacy_answer_reused_with_observed_alias_on_its_raw_key(database):
    client, engine = await _client_for(database)
    async with client:
        question_id = await legacy_answer(client)
        with closing(sqlite3.connect(database)) as connection:
            old_key = connection.execute("SELECT scope_key FROM knowledge_questions WHERE id=?", (question_id,)).fetchone()[0]
        exact = await ask(client)
        assert exact["status"] == "answered"
        assert exact["question_id"] == question_id
        assert exact["scope"]["country"] is None
        assert exact["matched_scope"]["country"] == "DE"
        similar = await ask(client, "请问环境光自动亮度调节如何使用？")
        assert similar["question_id"] == question_id
        listed = await client.get("/api/knowledge/questions", params=NEUTRAL)
        assert listed.json()["total"] == 1
    await engine.dispose()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT scope_key FROM knowledge_questions WHERE id=?", (question_id,)).fetchone()[0] == old_key
        assert connection.execute("SELECT scope_key FROM knowledge_question_phrasings WHERE phrasing_type='observed'").fetchone()[0] == old_key


@pytest.mark.asyncio
@pytest.mark.parametrize("identical", [False, True])
async def test_country_ties_only_coalesce_identical_answer_and_question(database, identical):
    client, engine = await _client_for(database)
    async with client:
        german = await legacy_answer(client)
        french = await legacy_answer(client, "FR", ANSWER if identical else "此版本不支持该功能。")
        with closing(sqlite3.connect(database)) as connection:
            original = connection.execute("SELECT id,scope_key,question_text FROM knowledge_questions ORDER BY id").fetchall()
        result = await ask(client)
        assert result["status"] == ("answered" if identical else "pending")
        if identical:
            assert result["question_id"] == german
        else:
            assert result["question_id"] not in {german, french}
            assert result["answer"] is None
        explicit = await ask(client, scope={**NEUTRAL, "country": "FR"})
        assert explicit["question_id"] == french
    await engine.dispose()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT id,scope_key,question_text FROM knowledge_questions WHERE id IN (?,?) ORDER BY id", (german, french)).fetchall() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("collision", ["answer", "alias", "canonical_alias"])
async def test_neutral_publication_cannot_bypass_historical_owners(database, collision):
    client, engine = await _client_for(database)
    async with client:
        # Establish neutral pending question before any legacy answer exists.
        neutral = await ask(client)
        assert neutral["status"] == "pending"
        if collision == "answer":
            await legacy_answer(client, answer="不同的国家答案")
            aliases = []
        elif collision == "alias":
            await legacy_answer(client, question="另一个完全不同的问题", aliases=["专属问法"])
            aliases = ["专属问法"]
        else:
            owner_id = await legacy_answer(client, question="另一个完全不同的问题")
            # A pre-existing historical alias may already overlap a newer pending record.
            with closing(sqlite3.connect(database)) as connection, connection:
                key = connection.execute("SELECT scope_key FROM knowledge_questions WHERE id=?", (owner_id,)).fetchone()[0]
                connection.execute(
                    "INSERT INTO knowledge_question_phrasings "
                    "(question_id,phrasing_text,normalized_phrasing,scope_key) VALUES (?,?,?,?)",
                    (owner_id, QUESTION, normalize_question(QUESTION), key))
            aliases = []
        refused = await publish(client, neutral["question_id"], aliases=aliases)
        assert refused.status_code == 422, refused.text
        unchanged = (await client.get(f"/api/knowledge/questions/{neutral['question_id']}")).json()
        assert unchanged["answer"] is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_neutral_answer_cannot_be_bypassed_by_country_specific_publication(database):
    client, engine = await _client_for(database)
    async with client:
        specific = await ask(client, scope={**NEUTRAL, "country": "DE"})
        neutral = await ask(client)
        assert (await publish(client, neutral["question_id"])).status_code == 200
        refused = await publish(client, specific["question_id"], "different")
        assert refused.status_code == 422, refused.text
    await engine.dispose()


@pytest.mark.asyncio
async def test_neutral_evidence_ignores_country_but_preserves_other_dimensions(database):
    client, engine = await _client_for(database)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript("""
        UPDATE knowledge_documents SET country='FR',market='overseas' WHERE id=1;
        INSERT INTO knowledge_document_extractions (document_id,extractor_version,status,chunk_count)
        VALUES (1,'test','completed',1);
        INSERT INTO knowledge_document_chunks
        (document_id,chunk_index,source_ref,content,normalized_content,content_hash)
        VALUES (1,0,'p1','环境光自动亮度调节','环境光自动亮度调节','hash');
        """)
    async with client:
        neutral = await ask(client)
        assert neutral["candidates"]
        explicit = await ask(client, scope={**NEUTRAL, "country": "DE"})
        assert explicit["candidates"] == []
        for changes in [{"software_version": "1.14.81"}, {"market": "domestic", "product_model_id": 901}]:
            wrong = await ask(client, scope={**NEUTRAL, **changes})
            assert wrong["candidates"] == []
        response = await client.put(f"/api/knowledge/questions/{neutral['question_id']}/answer", json={
            "answer_text": ANSWER, "citations": [{"document_id": 1, "source_ref": "p1"}],
        })
        assert response.status_code == 200, response.text
    await engine.dispose()


@pytest.mark.asyncio
async def test_confirm_scope_without_country_is_idempotent_and_preserves_source(review_database):
    client, engine = await _client_for(review_database)
    async with client:
        payload = await _payload(client, action="confirm_scope", market="domestic", product_model_ids=[901, 902],
                                 software_version="1.14.80", version_applicability="specific")
        first = await client.post("/api/knowledge/questions/101/review", json=payload)
        assert first.status_code == 200, first.text
        assert (await client.post("/api/knowledge/questions/101/review", json=payload)).json() == first.json()
        assert first.json()["scope"] is None
        ids = first.json()["evidence_review"]["latest"]["target_question_ids"]
        assert len(ids) == 2
        for question_id in ids:
            item = (await client.get(f"/api/knowledge/questions/{question_id}")).json()
            assert item["scope"]["country"] is None
            assert item["asked_count"] == 0
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("collision", ["answer", "alias"])
async def test_neutral_review_rolls_back_all_targets_on_historical_collision(review_database, collision):
    client, engine = await _client_for(review_database)
    async with client:
        owner = await ask(client, "历史功能说明" if collision == "answer" else "另一个完全不同的问题", {
            "country": "CN", "market": "domestic", "product_model_id": 902, "software_version": "1.14.80"})
        assert (await publish(client, owner["question_id"], "冲突答案", ["历史功能说明"] if collision == "alias" else [])).status_code == 200
        before = review_database.read_bytes()
        payload = await _payload(client, action="confirm_scope", market="domestic", product_model_ids=[901, 902],
                                 software_version="1.14.80", version_applicability="specific")
        refused = await client.post("/api/knowledge/questions/101/review", json=payload)
        assert refused.status_code == 409, refused.text
    await engine.dispose()
    assert review_database.read_bytes() == before


def test_snapshot_round_trip_preserves_old_and_neutral_keys(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "target.db"
    _create(source, populated=True)
    _create(target)
    with closing(sqlite3.connect(source)) as connection, connection:
        raw = connection.execute("SELECT scope_key FROM knowledge_questions WHERE id=2").fetchone()[0]
        neutral = {**stored_scope(raw), "country": None}
        connection.execute("UPDATE knowledge_questions SET scope_key=? WHERE id=2", (scope_key(neutral),))
        connection.execute("UPDATE knowledge_question_phrasings SET scope_key=? WHERE question_id=2", (scope_key(neutral),))
    snapshot = export_knowledge_qa_snapshot(source)
    assert {row["scope"]["country"] for row in snapshot["questions"]} == {"CN", None}
    assert restore_knowledge_qa_snapshot(target, snapshot, apply=True)["status"] == "restored"
    assert export_knowledge_qa_snapshot(target) == snapshot


@pytest.mark.asyncio
async def test_identical_ties_prefer_neutral_record_even_when_legacy_id_is_lower(database):
    client, engine = await _client_for(database)
    async with client:
        specific = await ask(client, scope={**NEUTRAL, "country": "DE"})
        neutral = await ask(client)
        assert specific["question_id"] < neutral["question_id"]
        assert (await publish(client, specific["question_id"], aliases=["环境光调节操作说明"])).status_code == 200
        assert (await publish(client, neutral["question_id"], aliases=["环境光调节操作说明"])).status_code == 200
        result = await ask(client, "环境光调节操作说明")
        assert result["question_id"] == neutral["question_id"]
        assert result["matched_scope"]["country"] is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_identical_answers_for_different_question_identities_still_require_review(database):
    client, engine = await _client_for(database)
    async with client:
        await legacy_answer(client, question="第一项独立功能", aliases=[QUESTION])
        await legacy_answer(client, "FR", question="第二项独立功能", aliases=[QUESTION])
        result = await ask(client)
        assert result["status"] == "pending"
        assert result["answer"] is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_neutral_reads_ignore_invalid_keys_and_wrong_model_identity(database):
    client, engine = await _client_for(database)
    async with client:
        question_id = await legacy_answer(client)
        with closing(sqlite3.connect(database)) as connection, connection:
            key = connection.execute("SELECT scope_key FROM knowledge_questions WHERE id=?", (question_id,)).fetchone()[0]
            wrong_identity = {**stored_scope(key), "model_name": "Another complete model"}
            for invalid_key in ["{broken", key.replace('"country":"DE"', '"country":"de"'), scope_key(wrong_identity)]:
                inserted = connection.execute(
                    "INSERT INTO knowledge_questions (question_text,normalized_question,status,scope_key) "
                    "VALUES (?,?,'answered',?)", (QUESTION, normalize_question(QUESTION), invalid_key))
                connection.execute("INSERT INTO knowledge_answers (question_id,answer_text) VALUES (?,?)", (inserted.lastrowid, "wrong"))
        result = await ask(client)
        assert result["status"] == "answered"
        assert result["question_id"] == question_id
        listed = await client.get("/api/knowledge/questions", params={**NEUTRAL, "q": "环境光", "evidence_review": "needs_review", "limit": 1})
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["id"] == question_id
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["alias", "similar", "explicit_ipn"])
async def test_country_conflict_blocks_unique_alias_and_ipn_filtered_matches(database, variant):
    client, engine = await _client_for(database)
    alias = "亮度自动适应的操作步骤"
    if variant == "explicit_ipn":
        alias += "（IPN 1234567）"
    query = "请问" + alias if variant == "similar" else alias
    async with client:
        german = await legacy_answer(client, answer="支持自动调节（IPN 1234567）。", aliases=[alias])
        french = await legacy_answer(client, "FR", "不支持自动调节（IPN 7654321）。")
        with closing(sqlite3.connect(database)) as connection:
            before = connection.execute(
                "SELECT id,scope_key,asked_count FROM knowledge_questions ORDER BY id").fetchall()
        result = await ask(client, query)
        assert result["status"] == "pending"
        assert result["question_id"] not in {german, french}
        assert result["answer"] is None
        assert result["scope"]["country"] is None
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute(
                "SELECT id,scope_key,asked_count FROM knowledge_questions WHERE id IN (?,?) ORDER BY id",
                (german, french)).fetchall() == before
            assert connection.execute(
                "SELECT COUNT(*) FROM knowledge_question_phrasings WHERE phrasing_type='observed'").fetchone()[0] == 0
        explicit = await ask(client, query, {**NEUTRAL, "country": "DE"})
        assert explicit["status"] == "answered"
        assert explicit["question_id"] == german
    await engine.dispose()
