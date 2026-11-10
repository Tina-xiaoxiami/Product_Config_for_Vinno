from hashlib import sha256
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.knowledge import KnowledgeFactImpact, KnowledgePublicFact
from app.services import knowledge_cart_facts as facts
from app.services.knowledge_content import extract_registered_document

HASH = "a" * 64
FACT = {
    "key": "example.assembly.identity", "market": "domestic", "status": "confirmed",
    "value": "9000000", "display_value": "9000000", "conditions": {"material_code": "EX-01"},
    "sources": [{"file_name": "fictional-source.xlsx", "version_id": HASH, "locator": "Example!A2:C2"}],
}


@pytest.mark.asyncio
async def test_public_fact_confirmation_and_source_change_refresh_in_same_transaction(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'facts.db'}")
    from test_knowledge_qa_api import _create_qa_database

    _create_qa_database(tmp_path / "facts.db")
    source = tmp_path / "fictional-source.txt"
    source.write_text("Before correction.", encoding="utf-8")
    old_hash = sha256(source.read_bytes()).hexdigest()
    input_fact = {**FACT, "sources": [{"file_name": source.name, "version_id": old_hash, "locator": "Example!A2:C2"}]}
    try:
        async with engine.begin() as conn:
            for model in (KnowledgePublicFact, KnowledgeFactImpact):
                await conn.run_sync(model.__table__.create)
            await conn.execute(text("""
                UPDATE knowledge_documents SET file_name=:name,file_path=:path,mime_type='text/plain',sha256=:hash WHERE id=1
            """), {"name": source.name, "path": str(source), "hash": old_hash})
        attempts = []
        fail = True

        async def refresh(db, keys):
            attempts.append(set(keys))
            fact = await facts.resolve_cart_fact(db, FACT["key"], "domestic", {"example": {"id": 12}})
            if fail:
                raise RuntimeError("candidate generation failed")
            if fact["issue"]:
                await facts.link_cart_fact_impact(db, fact["issue"]["root_key"],
                                                  {"market": "domestic", "pages": [2, 2], "archive_key": "example"})
            return [{"market": "domestic", "pages": [2], "archive_key": "example"}]

        monkeypatch.setattr(facts, "import_module", lambda _: SimpleNamespace(refresh_cart_for_facts=refresh))
        async with AsyncSession(engine) as db:
            with pytest.raises(RuntimeError, match="candidate generation failed"):
                async with db.begin():
                    await facts.apply_cart_facts(db, [input_fact])
            async with db.begin():
                assert await facts.resolve_cart_fact(db, FACT["key"], "domestic", {}) is None
            fail = False
            async with db.begin():
                result = await facts.apply_cart_facts(db, [input_fact])
                assert result["cart_impacts"][0]["pages"] == [2]
                assert (await facts.apply_cart_facts(db, [input_fact]))["changed_fact_keys"] == []
            async with db.begin():
                confirmed = await facts.resolve_cart_fact(db, FACT["key"], "domestic", {"example": {"id": 12}})
                assert confirmed["configuration_versions"]["example"]["id"] == 12
                assert confirmed["value"] == "9000000"
                assert confirmed["sources"][0]["locator"] == "Example!A2:C2"
            fail = True
            source.write_text("After correction.", encoding="utf-8")
            with pytest.raises(RuntimeError, match="candidate generation failed"):
                async with db.begin():
                    await extract_registered_document(db, 1)
            async with db.begin():
                assert (await facts.resolve_cart_fact(db, FACT["key"], "domestic", {}))["status"] == "confirmed"
                assert (await db.execute(text("SELECT sha256 FROM knowledge_documents WHERE id=1"))).scalar_one() == old_hash
            fail = False
            assert (await extract_registered_document(db, 1))["status"] == "completed"
            await db.rollback()
            async with db.begin():
                issue, = await facts.cart_fact_issues(db)
                assert issue["root_key"] == "source.changed:1"
                assert issue["impacts"][0]["pages"] == [2]
            assert attempts == [{FACT["key"]}] * 4
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reviewed_battery_identity_is_market_scoped_and_reuses_source_locator(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'identities.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(KnowledgePublicFact.__table__.create)
        async with AsyncSession(engine) as db, db.begin():
            fact = {**FACT, "key": "component.battery:9000000", "value": "V8BAT", "display_value": "V8BAT"}
            await facts.apply_cart_facts(db, [fact])
            assert await facts.reviewed_battery_identities(db, "overseas") == []
            identity, = await facts.reviewed_battery_identities(db, "domestic")
            assert identity["ipn"] == "9000000" and identity["name"] == "V8BAT"
            assert "Example!A2:C2" in identity["evidence_reference"]
            await facts.apply_cart_facts(db, [{**fact, "conditions": {**fact["conditions"], "model_ids": [12]}}])
            assert await facts.reviewed_battery_identities(db, "domestic", 13) == []
            assert await facts.reviewed_battery_identities(db, "domestic", 12) == [identity]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_configuration_issues_endpoint_merges_cart_and_answer_by_root(tmp_path):
    from app.models.knowledge import KnowledgeConfigurationAnswerRevision
    from test_knowledge_qa_api import _client_for, _create_qa_database

    path = tmp_path / "combined-issues.db"
    _create_qa_database(path)
    client, engine = await _client_for(path)
    try:
        async with engine.begin() as conn:
            for model in (KnowledgePublicFact, KnowledgeFactImpact, KnowledgeConfigurationAnswerRevision):
                await conn.run_sync(model.__table__.create)
            root = "component.identity:9000000"
            issue = {"root_key": root, "kind": "owner_decision", "detail": "确认示例部件身份"}
            snapshot = {"id": 7, "version_number": "EX-7"}
            payload = {"recipe": "runtime:v10", "model": {"id": 901, "name": "Example", "market": "domestic"},
                       "snapshot": snapshot, "review_items": [issue]}
            await conn.execute(text("""
                INSERT INTO knowledge_configuration_answer_revisions(recipe,model_id,config_version_id,payload_json)
                VALUES ('runtime:v10',901,7,:payload)
            """), {"payload": json.dumps(payload)})
        async with AsyncSession(engine) as db, db.begin():
            await facts.apply_cart_facts(db, [{**FACT, "status": "missing", "value": None, "display_value": None,
                                               "issue": issue}])
            await facts.link_cart_fact_impact(db, root, {"market": "domestic", "pages": [2], "archive_key": "example"})
        async with client:
            response = await client.get("/api/knowledge/questions/configuration-issues")
            assert response.status_code == 200, response.text
            group, = response.json()["items"]
            assert response.json()["source_gaps"] == []
            assert group["root_key"] == root and group["fact_keys"] == [FACT["key"]]
            assert group["answer_impacts"][0]["configuration_version"] == snapshot
            assert group["cart_impacts"][0]["pages"] == [2]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_single_identity_confirmation_refreshes_both_root_consumers(tmp_path, monkeypatch):
    from app.services import knowledge_configuration_answers

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'shared-resolution.db'}")
    refreshed = []

    async def refresh_answers(db, *, runtime):
        assert runtime
        refreshed.append("answers")

    async def refresh_cart(db, keys):
        refreshed.append(keys)
        return []

    monkeypatch.setattr(knowledge_configuration_answers, "refresh_configuration_answers", refresh_answers)
    monkeypatch.setattr(facts, "refresh_cart_impact", refresh_cart)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(KnowledgePublicFact.__table__.create)
        async with AsyncSession(engine) as db, db.begin():
            identity = {**FACT, "key": "component.battery:9000000", "value": "V8BAT", "display_value": "V8BAT"}
            await facts.apply_cart_facts(db, [{**FACT, "status": "missing", "value": None, "display_value": None,
                "issue": {"root_key": "component.identity:9000000", "kind": "owner_decision", "detail": "核实示例部件",
                          "resolution_fact_key": identity["key"]}}])
            refreshed.clear()
            await facts.apply_cart_facts(db, [identity])
            assert refreshed == ["answers", {identity["key"], FACT["key"]}]
            assert (await facts.resolve_cart_fact(db, FACT["key"], "domestic", {}))["value"] == "V8BAT"
            assert await facts.cart_fact_issues(db) == []
    finally:
        await engine.dispose()
