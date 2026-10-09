import json

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import drafts
from app.database import Base, get_db
from app.models import (
    ConfigDraft,
    ConfigItem,
    ConfigValue,
    ConfigVersion,
    DraftBatch,
    ProductModel,
    ProductSeries,
)


async def _draft_harness(tmp_path):
    database_path = tmp_path / "draft-safety.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    app = FastAPI()
    app.include_router(drafts.router, prefix="/api/drafts")

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )
    return client, session_factory, engine


async def _seed_catalog(session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                ProductSeries(id=1, name="V Series"),
                ProductSeries(id=2, name="Other Series"),
                ProductModel(id=10, series_id=1, name="V10", status="生产中"),
                ProductModel(id=11, series_id=1, name="V11", status="生产中"),
                ProductModel(id=12, series_id=1, name="V-old", status="已合并"),
                ProductModel(id=20, series_id=2, name="X1", status="生产中"),
                ConfigItem(id=100, category="Main Unit", row_index=1, rd_name="CPU", ipn="IPN-100"),
                ConfigItem(id=101, category="Main Unit", row_index=2, rd_name="GPU", ipn="IPN-101"),
            ]
        )
        await session.commit()


def _draft_payload(**overrides):
    payload = {
        "series_id": 1,
        "batch_id": "batch-1",
        "change_type": "update",
        "item_id": 100,
        "model_id": 10,
        "field_name": "current_config",
        "old_value": "baseline",
        "new_value": "working",
    }
    payload.update(overrides)
    return payload


def _snapshot(*, cpu="baseline-cpu", gpu="baseline-gpu"):
    return {
        "models": [{"id": 10, "name": "V10"}, {"id": 11, "name": "V11"}],
        "items": [
            {
                "id": 100,
                "category": "Main Unit",
                "row_index": 1,
                "rd_name": "CPU",
                "ipn": "IPN-100",
                "values": {
                    "10": {
                        "current_config": cpu,
                        "final_config": None,
                        "selection_config": None,
                        "rd_status": None,
                    }
                },
            },
            {
                "id": 101,
                "category": "Main Unit",
                "row_index": 2,
                "rd_name": "GPU",
                "ipn": "IPN-101",
                "values": {
                    "10": {
                        "current_config": gpu,
                        "final_config": None,
                        "selection_config": None,
                        "rd_status": None,
                    }
                },
            },
        ],
    }


@pytest.mark.asyncio
async def test_batch_and_draft_creation_validate_series_model_status_and_fields(tmp_path):
    client, session_factory, engine = await _draft_harness(tmp_path)
    await _seed_catalog(session_factory)

    async with client:
        missing_series = await client.post("/api/drafts/batch", params={"series_id": 999})
        assert missing_series.status_code == 404

        created = await client.post("/api/drafts/batch", params={"series_id": 1})
        assert created.status_code == 200, created.text
        batch_id = created.json()["id"]

        wrong_series = await client.post(
            "/api/drafts/draft",
            json=_draft_payload(batch_id=batch_id, series_id=2),
        )
        assert wrong_series.status_code in {400, 422}

        foreign_model = await client.post(
            "/api/drafts/draft",
            json=_draft_payload(batch_id=batch_id, model_id=20),
        )
        assert foreign_model.status_code in {400, 422}

        merged_model = await client.post(
            "/api/drafts/draft",
            json=_draft_payload(batch_id=batch_id, model_id=12),
        )
        assert merged_model.status_code in {400, 422}

        invalid_field = await client.post(
            "/api/drafts/draft",
            json=_draft_payload(batch_id=batch_id, field_name="row_index"),
        )
        assert invalid_field.status_code == 422

        invalid_type = await client.post(
            "/api/drafts/draft",
            json=_draft_payload(batch_id=batch_id, change_type="publish"),
        )
        assert invalid_type.status_code == 422

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_draft_rejects_non_draft_batch(tmp_path):
    client, session_factory, engine = await _draft_harness(tmp_path)
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        session.add(DraftBatch(id="batch-1", series_id=1, status="submitted"))
        await session.commit()

    async with client:
        response = await client.post("/api/drafts/draft", json=_draft_payload())

    await engine.dispose()
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_submit_revalidates_legacy_draft_field_before_mutating_data(tmp_path):
    client, session_factory, engine = await _draft_harness(tmp_path)
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                DraftBatch(id="batch-1", series_id=1, status="draft", total_count=1, update_count=1),
                ConfigValue(item_id=100, model_id=10, current_config="baseline"),
                ConfigDraft(
                    series_id=1,
                    batch_id="batch-1",
                    change_type="update",
                    item_id=100,
                    model_id=10,
                    field_name="row_index",
                    old_value="baseline",
                    new_value="corrupt",
                ),
            ]
        )
        await session.commit()

    async with client:
        response = await client.post("/api/drafts/batch/batch-1/submit", json={})

    async with session_factory() as session:
        batch = await session.get(DraftBatch, "batch-1")
        version_count = await session.scalar(select(func.count()).select_from(ConfigVersion))
        draft_count = await session.scalar(select(func.count()).select_from(ConfigDraft))
    await engine.dispose()

    assert response.status_code == 400
    assert batch.status == "draft"
    assert version_count == 0
    assert draft_count == 1


@pytest.mark.asyncio
async def test_current_batch_and_stats_use_actual_draft_counts(tmp_path):
    client, session_factory, engine = await _draft_harness(tmp_path)
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                DraftBatch(
                    id="batch-1",
                    series_id=1,
                    status="draft",
                    total_count=633,
                    create_count=211,
                    update_count=211,
                    delete_count=211,
                ),
                ConfigDraft(
                    series_id=1,
                    batch_id="batch-1",
                    change_type="update",
                    item_id=100,
                    model_id=10,
                    field_name="current_config",
                ),
                ConfigDraft(
                    series_id=1,
                    batch_id="batch-1",
                    change_type="delete",
                    item_id=101,
                    model_id=10,
                ),
            ]
        )
        await session.commit()

    async with client:
        current = await client.get("/api/drafts/batch/current/1")
        stats = await client.get("/api/drafts/batch/batch-1/stats")
    await engine.dispose()

    assert current.status_code == 200
    assert current.json()["batch"] | {} == current.json()["batch"]
    assert {
        key: current.json()["batch"][key]
        for key in ("total_count", "create_count", "update_count", "delete_count")
    } == {"total_count": 2, "create_count": 0, "update_count": 1, "delete_count": 1}
    assert stats.json() == {"total": 2, "create": 0, "update": 1, "delete": 1}


@pytest.mark.asyncio
async def test_empty_draft_batch_reports_zero_and_is_not_bulk_submitted(tmp_path):
    client, session_factory, engine = await _draft_harness(tmp_path)
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        session.add(DraftBatch(id="batch-1", series_id=1, status="draft", total_count=633))
        await session.commit()

    async with client:
        current = await client.get("/api/drafts/batch/current/1")
        bulk = await client.post("/api/drafts/batch/submit", json={"batch_ids": ["batch-1"]})
    await engine.dispose()

    assert current.json()["exists"] is True
    assert current.json()["drafts"] == []
    assert {
        key: current.json()["batch"][key]
        for key in ("total_count", "create_count", "update_count", "delete_count")
    } == {"total_count": 0, "create_count": 0, "update_count": 0, "delete_count": 0}
    assert bulk.status_code == 200
    assert bulk.json()["submitted_count"] == 0


@pytest.mark.asyncio
async def test_repeated_edit_keeps_original_baseline_and_cancel_restores_it(tmp_path):
    client, session_factory, engine = await _draft_harness(tmp_path)
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                DraftBatch(id="batch-1", series_id=1, status="draft"),
                ConfigValue(item_id=100, model_id=10, current_config="baseline"),
            ]
        )
        await session.commit()

    async with client:
        first = await client.post(
            "/api/drafts/draft",
            json=_draft_payload(old_value="untrusted-client-old", new_value="first edit"),
        )
        assert first.status_code == 200, first.text

        second = await client.post(
            "/api/drafts/draft",
            json=_draft_payload(old_value="first edit", new_value="second edit"),
        )
        assert second.status_code == 200, second.text
        assert second.json()["draft_id"] == first.json()["draft_id"]

        removed = await client.delete(f"/api/drafts/draft/{first.json()['draft_id']}")
        assert removed.status_code == 200, removed.text

    async with session_factory() as session:
        value = await session.scalar(
            select(ConfigValue).where(ConfigValue.item_id == 100, ConfigValue.model_id == 10)
        )
    await engine.dispose()

    assert value.current_config == "baseline"


@pytest.mark.asyncio
async def test_full_submit_clears_counts_and_marks_batch_submitted(tmp_path):
    client, session_factory, engine = await _draft_harness(tmp_path)
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                DraftBatch(id="batch-1", series_id=1, status="draft", total_count=1, update_count=1),
                ConfigValue(item_id=100, model_id=10, current_config="working"),
                ConfigDraft(
                    series_id=1,
                    batch_id="batch-1",
                    change_type="update",
                    item_id=100,
                    model_id=10,
                    field_name="current_config",
                    old_value="baseline",
                    new_value="working",
                ),
            ]
        )
        await session.commit()

    async with client:
        response = await client.post("/api/drafts/batch/batch-1/submit", json={})

    async with session_factory() as session:
        batch = await session.get(DraftBatch, "batch-1")
    await engine.dispose()

    assert response.status_code == 200, response.text
    assert batch.status == "submitted"
    assert batch.submitted_at is not None
    assert (batch.total_count, batch.create_count, batch.update_count, batch.delete_count) == (0, 0, 0, 0)


@pytest.mark.asyncio
async def test_partial_submit_snapshot_excludes_remaining_drafts_and_discard_restores_latest_baseline(tmp_path):
    client, session_factory, engine = await _draft_harness(tmp_path)
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                ConfigVersion(
                    series_id=1,
                    version_number="1.0.0",
                    snapshot_data=json.dumps(_snapshot()),
                    row_count=2,
                ),
                DraftBatch(id="batch-1", series_id=1, status="draft", total_count=2, update_count=2),
                ConfigValue(item_id=100, model_id=10, current_config="working-cpu"),
                ConfigValue(item_id=101, model_id=10, current_config="working-gpu"),
                ConfigDraft(
                    series_id=1,
                    batch_id="batch-1",
                    change_type="update",
                    item_id=100,
                    model_id=10,
                    field_name="current_config",
                    old_value="baseline-cpu",
                    new_value="working-cpu",
                ),
                ConfigDraft(
                    series_id=1,
                    batch_id="batch-1",
                    change_type="update",
                    item_id=101,
                    model_id=10,
                    field_name="current_config",
                    old_value="baseline-gpu",
                    new_value="working-gpu",
                ),
            ]
        )
        await session.commit()

    async with client:
        submitted = await client.post(
            "/api/drafts/batch/batch-1/submit",
            json={"item_ids": [100], "version_number": "1.1.0"},
        )
        assert submitted.status_code == 200, submitted.text

        async with session_factory() as session:
            version = await session.scalar(
                select(ConfigVersion).where(ConfigVersion.version_number == "1.1.0")
            )
            version_snapshot = json.loads(version.snapshot_data)
            by_ipn = {item["ipn"]: item for item in version_snapshot["items"]}
            assert by_ipn["IPN-100"]["values"]["10"]["current_config"] == "working-cpu"
            assert by_ipn["IPN-101"]["values"]["10"]["current_config"] == "baseline-gpu"

            live_gpu = await session.scalar(
                select(ConfigValue).where(ConfigValue.item_id == 101, ConfigValue.model_id == 10)
            )
            batch = await session.get(DraftBatch, "batch-1")
            assert live_gpu.current_config == "working-gpu"
            assert batch.status == "draft"
            assert (batch.total_count, batch.update_count) == (1, 1)

        discarded = await client.delete("/api/drafts/batch/batch-1")
        assert discarded.status_code == 200, discarded.text

    async with session_factory() as session:
        cpu = await session.scalar(
            select(ConfigValue).where(ConfigValue.item_id == 100, ConfigValue.model_id == 10)
        )
        gpu = await session.scalar(
            select(ConfigValue).where(ConfigValue.item_id == 101, ConfigValue.model_id == 10)
        )
    await engine.dispose()

    assert cpu.current_config == "working-cpu"
    assert gpu.current_config == "baseline-gpu"


@pytest.mark.asyncio
async def test_partial_snapshot_rewinds_cell_create_without_removing_published_pair(tmp_path):
    client, session_factory, engine = await _draft_harness(tmp_path)
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                ConfigVersion(
                    series_id=1,
                    version_number="1.0.0",
                    snapshot_data=json.dumps(_snapshot()),
                    row_count=2,
                ),
                DraftBatch(id="batch-1", series_id=1, status="draft", total_count=2, update_count=1, create_count=1),
                ConfigValue(item_id=100, model_id=10, current_config="working-cpu"),
                ConfigValue(
                    item_id=101,
                    model_id=10,
                    current_config="baseline-gpu",
                    final_config="new cell",
                ),
                ConfigDraft(
                    series_id=1,
                    batch_id="batch-1",
                    change_type="update",
                    item_id=100,
                    model_id=10,
                    field_name="current_config",
                    old_value="baseline-cpu",
                    new_value="working-cpu",
                ),
                ConfigDraft(
                    series_id=1,
                    batch_id="batch-1",
                    change_type="create",
                    item_id=101,
                    model_id=10,
                    field_name="final_config",
                    old_value=None,
                    new_value="new cell",
                ),
            ]
        )
        await session.commit()

    async with client:
        response = await client.post(
            "/api/drafts/batch/batch-1/submit",
            json={"item_ids": [100], "version_number": "1.1.0"},
        )
    assert response.status_code == 200, response.text

    async with session_factory() as session:
        version = await session.scalar(
            select(ConfigVersion).where(ConfigVersion.version_number == "1.1.0")
        )
        snapshot = json.loads(version.snapshot_data)
        gpu = next(item for item in snapshot["items"] if item["ipn"] == "IPN-101")
    await engine.dispose()

    assert gpu["values"]["10"]["current_config"] == "baseline-gpu"
    assert gpu["values"]["10"]["final_config"] is None


@pytest.mark.asyncio
async def test_delete_single_update_draft_restores_old_field_value(tmp_path):
    client, session_factory, engine = await _draft_harness(tmp_path)
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        batch = DraftBatch(id="batch-1", series_id=1, status="draft", total_count=1, update_count=1)
        draft = ConfigDraft(
            series_id=1,
            batch_id="batch-1",
            change_type="update",
            item_id=100,
            model_id=10,
            field_name="current_config",
            old_value="baseline",
            new_value="working",
        )
        session.add_all([batch, ConfigValue(item_id=100, model_id=10, current_config="working"), draft])
        await session.commit()
        draft_id = draft.id

    async with client:
        response = await client.delete(f"/api/drafts/draft/{draft_id}")

    async with session_factory() as session:
        value = await session.scalar(
            select(ConfigValue).where(ConfigValue.item_id == 100, ConfigValue.model_id == 10)
        )
    await engine.dispose()

    assert response.status_code == 200, response.text
    assert value.current_config == "baseline"


@pytest.mark.asyncio
async def test_delete_by_key_static_route_restores_value(tmp_path):
    client, session_factory, engine = await _draft_harness(tmp_path)
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                DraftBatch(id="batch-1", series_id=1, status="draft", total_count=1, update_count=1),
                ConfigValue(item_id=100, model_id=10, current_config="working"),
                ConfigDraft(
                    series_id=1,
                    batch_id="batch-1",
                    change_type="update",
                    item_id=100,
                    model_id=10,
                    field_name="current_config",
                    old_value="baseline",
                    new_value="working",
                ),
            ]
        )
        await session.commit()

    async with client:
        response = await client.delete(
            "/api/drafts/draft/by-key",
            params={
                "batch_id": "batch-1",
                "item_id": 100,
                "model_id": 10,
                "field_name": "current_config",
            },
        )

    async with session_factory() as session:
        value = await session.scalar(
            select(ConfigValue).where(ConfigValue.item_id == 100, ConfigValue.model_id == 10)
        )
    await engine.dispose()

    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True
    assert value.current_config == "baseline"


@pytest.mark.asyncio
async def test_cancel_create_draft_removes_only_its_item_model_pair(tmp_path):
    client, session_factory, engine = await _draft_harness(tmp_path)
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        draft = ConfigDraft(
            series_id=1,
            batch_id="batch-1",
            change_type="create",
            item_id=100,
            model_id=10,
        )
        session.add_all(
            [
                DraftBatch(id="batch-1", series_id=1, status="draft", total_count=1, create_count=1),
                ConfigValue(item_id=100, model_id=10, current_config="new pair"),
                ConfigValue(item_id=100, model_id=11, current_config="same series peer"),
                ConfigValue(item_id=100, model_id=20, current_config="other series peer"),
                draft,
            ]
        )
        await session.commit()
        draft_id = draft.id

    async with client:
        response = await client.delete(f"/api/drafts/draft/{draft_id}")

    async with session_factory() as session:
        values = (
            await session.execute(
                select(ConfigValue).where(ConfigValue.item_id == 100).order_by(ConfigValue.model_id)
            )
        ).scalars().all()
    await engine.dispose()

    assert response.status_code == 200, response.text
    assert [(value.model_id, value.current_config) for value in values] == [
        (11, "same series peer"),
        (20, "other series peer"),
    ]


@pytest.mark.asyncio
async def test_cancel_delete_draft_restores_pair_from_latest_published_snapshot(tmp_path):
    client, session_factory, engine = await _draft_harness(tmp_path)
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        draft = ConfigDraft(
            series_id=1,
            batch_id="batch-1",
            change_type="delete",
            item_id=100,
            model_id=10,
        )
        session.add_all(
            [
                ConfigVersion(
                    series_id=1,
                    version_number="1.0.0",
                    snapshot_data=json.dumps(_snapshot()),
                    row_count=2,
                ),
                DraftBatch(id="batch-1", series_id=1, status="draft", total_count=1, delete_count=1),
                ConfigValue(item_id=100, model_id=11, current_config="same series peer"),
                ConfigValue(item_id=100, model_id=20, current_config="other series peer"),
                draft,
            ]
        )
        await session.commit()
        draft_id = draft.id

    async with client:
        response = await client.delete(f"/api/drafts/draft/{draft_id}")

    async with session_factory() as session:
        restored = await session.scalar(
            select(ConfigValue).where(ConfigValue.item_id == 100, ConfigValue.model_id == 10)
        )
        peers = (
            await session.execute(
                select(ConfigValue).where(
                    ConfigValue.item_id == 100,
                    ConfigValue.model_id.in_([11, 20]),
                )
            )
        ).scalars().all()
    await engine.dispose()

    assert response.status_code == 200, response.text
    assert restored.current_config == "baseline-cpu"
    assert {value.model_id: value.current_config for value in peers} == {
        11: "same series peer",
        20: "other series peer",
    }


@pytest.mark.asyncio
async def test_submit_delete_affects_only_target_model_pair(tmp_path):
    client, session_factory, engine = await _draft_harness(tmp_path)
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                DraftBatch(id="batch-1", series_id=1, status="draft", total_count=1, delete_count=1),
                ConfigValue(item_id=100, model_id=10, current_config="delete me"),
                ConfigValue(item_id=100, model_id=11, current_config="same series peer"),
                ConfigValue(item_id=100, model_id=20, current_config="other series peer"),
                ConfigDraft(
                    series_id=1,
                    batch_id="batch-1",
                    change_type="delete",
                    item_id=100,
                    model_id=10,
                ),
            ]
        )
        await session.commit()

    async with client:
        response = await client.post("/api/drafts/batch/batch-1/submit", json={})

    async with session_factory() as session:
        values = (
            await session.execute(
                select(ConfigValue).where(ConfigValue.item_id == 100).order_by(ConfigValue.model_id)
            )
        ).scalars().all()
    await engine.dispose()

    assert response.status_code == 200, response.text
    assert [(value.model_id, value.current_config) for value in values] == [
        (10, None),
        (11, "same series peer"),
        (20, "other series peer"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("bulk", [False, True])
async def test_discard_without_published_version_restores_values_only_and_preserves_item_metadata(
    tmp_path, bulk
):
    client, session_factory, engine = await _draft_harness(tmp_path)
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                DraftBatch(id="batch-1", series_id=1, status="draft", total_count=1, create_count=1),
                ConfigValue(item_id=100, model_id=10, current_config="unpublished"),
                ConfigDraft(
                    series_id=1,
                    batch_id="batch-1",
                    change_type="create",
                    item_id=100,
                    model_id=10,
                ),
            ]
        )
        await session.commit()

    async with client:
        if bulk:
            response = await client.post(
                "/api/drafts/batch/discard", json={"batch_ids": ["batch-1"]}
            )
        else:
            response = await client.delete("/api/drafts/batch/batch-1")

    async with session_factory() as session:
        item = await session.get(ConfigItem, 100)
        value = await session.scalar(
            select(ConfigValue).where(ConfigValue.item_id == 100, ConfigValue.model_id == 10)
        )
        batch = await session.get(DraftBatch, "batch-1")
    await engine.dispose()

    assert response.status_code == 200, response.text
    assert item is not None
    assert item.rd_name == "CPU"
    assert value is None
    assert batch.status == "discarded"
    assert (batch.total_count, batch.create_count, batch.update_count, batch.delete_count) == (0, 0, 0, 0)
