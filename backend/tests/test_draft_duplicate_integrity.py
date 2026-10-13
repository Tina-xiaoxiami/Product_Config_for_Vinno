import json

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.models import ConfigDraft, ConfigValue, ConfigVersion, DraftBatch
from test_draft_safety import _draft_harness, _draft_payload, _seed_catalog


UNIQUE_INDEX = "uq_config_draft_business_key"


async def _allow_legacy_duplicates(session_factory):
    async with session_factory() as session:
        await session.execute(text(f"DROP INDEX IF EXISTS {UNIQUE_INDEX}"))
        await session.commit()


async def _seed_duplicate_updates(session_factory, *, conflict=False, batch_id="batch-1"):
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                DraftBatch(
                    id=batch_id,
                    series_id=1,
                    status="draft",
                    total_count=2,
                    update_count=2,
                ),
                ConfigValue(
                    item_id=100,
                    model_id=10,
                    selection_config="working",
                ),
                ConfigDraft(
                    series_id=1,
                    batch_id=batch_id,
                    change_type="update",
                    item_id=100,
                    model_id=10,
                    field_name="selection_config",
                    old_value="baseline",
                    new_value="working",
                ),
                ConfigDraft(
                    series_id=1,
                    batch_id=batch_id,
                    change_type="delete" if conflict else "update",
                    item_id=100,
                    model_id=10,
                    field_name="selection_config",
                    old_value="different-baseline" if conflict else "baseline",
                    new_value="different-working" if conflict else "working",
                ),
            ]
        )
        await session.commit()


async def _duplicate_state(session_factory, batch_id="batch-1"):
    async with session_factory() as session:
        drafts = list(
            (
                await session.execute(
                    select(ConfigDraft)
                    .where(ConfigDraft.batch_id == batch_id)
                    .order_by(ConfigDraft.id)
                )
            )
            .scalars()
            .all()
        )
        value = await session.scalar(
            select(ConfigValue).where(
                ConfigValue.item_id == 100,
                ConfigValue.model_id == 10,
            )
        )
        batch = await session.get(DraftBatch, batch_id)
        version_count = await session.scalar(
            select(func.count()).select_from(ConfigVersion)
        )
        return drafts, value.selection_config, batch, version_count


@pytest.mark.asyncio
async def test_return_to_baseline_restores_once_and_removes_all_identical_duplicates(tmp_path):
    client, sessions, engine = await _draft_harness(tmp_path)
    await _allow_legacy_duplicates(sessions)
    await _seed_duplicate_updates(sessions)

    async with client:
        response = await client.post(
            "/api/drafts/draft",
            json=_draft_payload(
                field_name="selection_config",
                new_value="baseline",
            ),
        )

    drafts, value, batch, _ = await _duplicate_state(sessions)
    await engine.dispose()
    assert response.status_code == 200, response.text
    assert response.json()["removed"] is True
    assert drafts == []
    assert value == "baseline"
    assert (batch.total_count, batch.update_count) == (0, 0)


@pytest.mark.asyncio
async def test_return_to_baseline_rejects_conflicting_duplicates_without_changes(tmp_path):
    client, sessions, engine = await _draft_harness(tmp_path)
    await _allow_legacy_duplicates(sessions)
    await _seed_duplicate_updates(sessions, conflict=True)

    async with client:
        response = await client.post(
            "/api/drafts/draft",
            json=_draft_payload(
                field_name="selection_config",
                new_value="baseline",
            ),
        )

    drafts, value, batch, _ = await _duplicate_state(sessions)
    await engine.dispose()
    assert response.status_code == 409, response.text
    assert len(drafts) == 2
    assert value == "working"
    assert (batch.total_count, batch.update_count) == (2, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("route_kind", ["by-key", "by-id"])
async def test_draft_undo_removes_all_identical_duplicates_and_is_idempotent(
    tmp_path, route_kind
):
    client, sessions, engine = await _draft_harness(tmp_path)
    await _allow_legacy_duplicates(sessions)
    await _seed_duplicate_updates(sessions)
    drafts, _, _, _ = await _duplicate_state(sessions)
    draft_id = drafts[0].id

    async with client:
        if route_kind == "by-key":
            route = "/api/drafts/draft/by-key"
            kwargs = {
                "params": {
                    "batch_id": "batch-1",
                    "item_id": 100,
                    "model_id": 10,
                    "field_name": "selection_config",
                }
            }
        else:
            route = f"/api/drafts/draft/{draft_id}"
            kwargs = {}
        first = await client.delete(route, **kwargs)
        repeated = await client.delete(route, **kwargs)

    remaining, value, batch, _ = await _duplicate_state(sessions)
    await engine.dispose()
    assert first.status_code == 200, first.text
    assert first.json()["deleted"] is True
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["deleted"] is False
    assert remaining == []
    assert value == "baseline"
    assert (batch.total_count, batch.update_count) == (0, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("route_kind", ["by-key", "by-id"])
async def test_draft_undo_rejects_conflicting_duplicates_without_changes(
    tmp_path, route_kind
):
    client, sessions, engine = await _draft_harness(tmp_path)
    await _allow_legacy_duplicates(sessions)
    await _seed_duplicate_updates(sessions, conflict=True)
    drafts, _, _, _ = await _duplicate_state(sessions)

    async with client:
        if route_kind == "by-key":
            response = await client.delete(
                "/api/drafts/draft/by-key",
                params={
                    "batch_id": "batch-1",
                    "item_id": 100,
                    "model_id": 10,
                    "field_name": "selection_config",
                },
            )
        else:
            response = await client.delete(f"/api/drafts/draft/{drafts[0].id}")

    remaining, value, batch, _ = await _duplicate_state(sessions)
    await engine.dispose()
    assert response.status_code == 409, response.text
    assert len(remaining) == 2
    assert value == "working"
    assert (batch.total_count, batch.update_count) == (2, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["preview", "single-submit", "batch-submit"])
async def test_publication_rejects_duplicate_keys_without_side_effects(
    tmp_path, operation
):
    client, sessions, engine = await _draft_harness(tmp_path)
    await _allow_legacy_duplicates(sessions)
    await _seed_duplicate_updates(sessions)

    async with client:
        if operation == "preview":
            response = await client.post(
                "/api/drafts/batch/batch-1/submit-preview", json={}
            )
            assert response.status_code == 409, response.text
        elif operation == "single-submit":
            response = await client.post(
                "/api/drafts/batch/batch-1/submit", json={}
            )
            assert response.status_code == 409, response.text
        else:
            response = await client.post(
                "/api/drafts/batch/submit", json={"batch_ids": ["batch-1"]}
            )
            assert response.status_code == 200, response.text
            assert response.json()["submitted_count"] == 0
            assert response.json()["results"][0]["success"] is False

    drafts, value, batch, version_count = await _duplicate_state(sessions)
    await engine.dispose()
    assert len(drafts) == 2
    assert value == "working"
    assert batch.status == "draft"
    assert version_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("field_name,item_id", [("selection_config", 100), (None, 101)])
async def test_clean_schema_rejects_duplicate_business_keys_including_null_fields(
    tmp_path, field_name, item_id
):
    _, sessions, engine = await _draft_harness(tmp_path)
    await _seed_catalog(sessions)
    async with sessions() as session:
        session.add(DraftBatch(id="batch-1", series_id=1, status="draft"))
        session.add(
            ConfigDraft(
                series_id=1,
                batch_id="batch-1",
                change_type="update" if field_name else "create",
                item_id=item_id,
                model_id=10,
                field_name=field_name,
                old_value="baseline",
                new_value="working",
            )
        )
        await session.commit()
        session.add(
            ConfigDraft(
                series_id=1,
                batch_id="batch-1",
                change_type="update" if field_name else "create",
                item_id=item_id,
                model_id=10,
                field_name=field_name,
                old_value="baseline",
                new_value="working",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
    await engine.dispose()
