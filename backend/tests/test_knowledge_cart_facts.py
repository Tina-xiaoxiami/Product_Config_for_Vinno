from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.knowledge import KnowledgeFactImpact, KnowledgePublicFact
from app.services import knowledge_cart_facts as facts
from app.services.knowledge_content import _record_source_observation

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
    try:
        async with engine.begin() as conn:
            for model in (KnowledgePublicFact, KnowledgeFactImpact):
                await conn.run_sync(model.__table__.create)
            await conn.execute(text("UPDATE knowledge_documents SET file_name='fictional-source.xlsx', sha256=:hash WHERE id=1"), {"hash": HASH})
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
                    await facts.apply_cart_facts(db, [FACT])
            async with db.begin():
                assert await facts.resolve_cart_fact(db, FACT["key"], "domestic", {}) is None
            fail = False
            async with db.begin():
                result = await facts.apply_cart_facts(db, [FACT])
                assert result["cart_impacts"][0]["pages"] == [2]
                assert (await facts.apply_cart_facts(db, [FACT]))["changed_fact_keys"] == []
            async with db.begin():
                confirmed = await facts.resolve_cart_fact(db, FACT["key"], "domestic", {"example": {"id": 12}})
                assert confirmed["configuration_versions"]["example"]["id"] == 12
                assert confirmed["value"] == "9000000"
                assert confirmed["sources"][0]["locator"] == "Example!A2:C2"
            fail = True
            with pytest.raises(RuntimeError, match="candidate generation failed"):
                async with db.begin():
                    await _record_source_observation(db, 1, HASH, "b" * 64)
            async with db.begin():
                assert (await facts.resolve_cart_fact(db, FACT["key"], "domestic", {}))["status"] == "confirmed"
                assert (await db.execute(text("SELECT sha256 FROM knowledge_documents WHERE id=1"))).scalar_one() == HASH
            fail = False
            async with db.begin():
                await _record_source_observation(db, 1, HASH, "b" * 64)
                issue, = await facts.cart_fact_issues(db)
                assert issue["root_key"] == "source.changed:1"
                assert issue["impacts"][0]["pages"] == [2]
            assert attempts == [{FACT["key"]}] * 4
    finally:
        await engine.dispose()
