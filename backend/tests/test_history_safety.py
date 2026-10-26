import json

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.versions import create_version, rollback_version
from app.database import Base
from app.models import (
    ChangeLog,
    ConfigDraft,
    ConfigItem,
    ConfigValue,
    ConfigVersion,
    DraftBatch,
    ProductModel,
    ProductSeries,
)
from app.models.product_model import ProductModelIdentity
from app.schemas.version import ConfigVersionCreate
from app.services.config_history import build_series_snapshot, restore_series_snapshot


SOURCE_UUID = "c5ec14b2-5715-40e8-ac91-31e8507abf26"


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all(
            [
                ProductSeries(id=1, name="China"),
                ProductSeries(id=2, name="Oversea"),
            ]
        )
        await session.commit()
        yield session
    await engine.dispose()


async def seed_models(db):
    china = ProductModel(id=10, series_id=1, name="V10", sort_order=1)
    china_extra = ProductModel(id=12, series_id=1, name="V10 Pro", sort_order=2)
    archived = ProductModel(id=11, series_id=1, name="V10 Legacy", status="已合并")
    overseas = ProductModel(id=20, series_id=2, name="V10 Overseas")
    db.add_all([china, china_extra, archived, overseas])
    await db.flush()
    db.add(
        ProductModelIdentity(
            series_id=1,
            model_id=china.id,
            source_uuid=SOURCE_UUID,
            aliases_json=json.dumps(["V10 Legacy"]),
            historical_ids_json=json.dumps([99]),
        )
    )
    await db.flush()
    return china, china_extra, archived, overseas


@pytest.mark.asyncio
async def test_build_snapshot_contains_only_active_series_models_and_used_items(db):
    china, _, archived, overseas = await seed_models(db)
    shared = ConfigItem(id=1, category="Main", row_index=1, rd_name="Shared", ipn="IPN-1")
    other_only = ConfigItem(id=2, category="Main", row_index=2, rd_name="Other", ipn="IPN-2")
    no_ipn = ConfigItem(id=3, category="Optional", row_index=3, rd_name="Local only")
    db.add_all([shared, other_only, no_ipn])
    await db.flush()
    db.add_all(
        [
            ConfigValue(item_id=shared.id, model_id=china.id, current_config="china"),
            ConfigValue(item_id=shared.id, model_id=archived.id, current_config="archived"),
            ConfigValue(item_id=shared.id, model_id=overseas.id, current_config="overseas"),
            ConfigValue(item_id=other_only.id, model_id=overseas.id, current_config="other"),
            ConfigValue(item_id=no_ipn.id, model_id=china.id, final_config="X"),
        ]
    )
    await db.flush()

    snapshot = await build_series_snapshot(db, 1)

    assert snapshot["models"] == [
        {"id": 10, "name": "V10", "source_uuid": SOURCE_UUID},
        {"id": 12, "name": "V10 Pro"},
    ]
    assert [item["id"] for item in snapshot["items"]] == [1, 3]
    assert snapshot["items"][0]["values"] == {
        "10": {
            "current_config": "china",
            "final_config": None,
            "selection_config": None,
            "rd_status": None,
        }
    }


@pytest.mark.asyncio
async def test_restore_is_series_scoped_reuses_items_and_preserves_shared_metadata(db):
    china, china_extra, archived, overseas = await seed_models(db)
    shared = ConfigItem(
        id=1,
        category="Canonical",
        row_index=1,
        rd_name="Shared canonical name",
        ipn="IPN-1",
        zh_desc="keep me",
    )
    no_ipn = ConfigItem(id=2, category="Local", row_index=2, rd_name="No IPN canonical", v_code="LOCAL-2")
    other_only = ConfigItem(id=3, category="Other", row_index=3, rd_name="Other series", ipn="IPN-3")
    db.add_all([shared, no_ipn, other_only])
    await db.flush()
    db.add_all(
        [
            ConfigValue(item_id=shared.id, model_id=china.id, current_config="working"),
            ConfigValue(item_id=shared.id, model_id=china_extra.id, current_config="clear me"),
            ConfigValue(item_id=shared.id, model_id=archived.id, current_config="archived stays"),
            ConfigValue(item_id=shared.id, model_id=overseas.id, current_config="overseas stays"),
            ConfigValue(item_id=no_ipn.id, model_id=china.id, current_config="old no ipn"),
            ConfigValue(item_id=other_only.id, model_id=overseas.id, current_config="other stays"),
        ]
    )
    await db.flush()

    snapshot = {
        "models": [{"id": 99, "name": "V10 Legacy", "source_uuid": SOURCE_UUID}],
        "items": [
            {
                "id": 999,
                "category": "Historical",
                "row_index": 90,
                "rd_name": "Do not overwrite shared metadata",
                "ipn": "IPN-1",
                "zh_desc": "historical",
                "values": {"99": {"current_config": "restored"}},
            },
            {
                "id": 2,
                "category": "Historical local",
                "row_index": 2,
                "rd_name": "Do not overwrite no-IPN metadata",
                "v_code": "LOCAL-2",
                "ipn": None,
                "values": {"99": {"final_config": "restored local"}},
            },
            {
                "id": 404,
                "category": "Optional",
                "row_index": 4,
                "rd_name": "Missing item",
                "ipn": "IPN-NEW",
                "values": {"99": {"selection_config": "new"}},
            },
        ],
    }

    assert await restore_series_snapshot(db, 1, snapshot) == 3
    await db.flush()

    assert await db.scalar(select(func.count()).select_from(ConfigItem)) == 4
    await db.refresh(shared)
    await db.refresh(no_ipn)
    assert (shared.category, shared.row_index, shared.rd_name, shared.zh_desc) == (
        "Canonical",
        1,
        "Shared canonical name",
        "keep me",
    )
    assert (no_ipn.category, no_ipn.rd_name) == ("Local", "No IPN canonical")

    values = (
        await db.execute(select(ConfigValue).order_by(ConfigValue.model_id, ConfigValue.item_id))
    ).scalars().all()
    assert [(value.model_id, value.item_id, value.current_config, value.final_config) for value in values] == [
        (10, 1, "restored", None),
        (10, 2, None, "restored local"),
        (10, 4, None, None),
        (11, 1, "archived stays", None),
        (20, 1, "overseas stays", None),
        (20, 3, "other stays", None),
    ]

    canonical = await build_series_snapshot(db, 1)
    assert canonical["models"][0]["id"] == 10
    assert [item["id"] for item in canonical["items"]] == [1, 2, 4]


@pytest.mark.asyncio
async def test_restore_no_ipn_item_uses_unique_metadata_and_rejects_ambiguity(db):
    china, *_ = await seed_models(db)
    first = ConfigItem(id=1, category="Optional", row_index=7, rd_name="No IPN", v_code="V-7")
    db.add(first)
    await db.flush()
    snapshot = {
        "models": [{"id": china.id, "name": china.name}],
        "items": [
            {
                "id": 999,
                "category": "Optional",
                "row_index": 7,
                "rd_name": "No IPN",
                "v_code": "V-7",
                "ipn": None,
                "values": {str(china.id): {"current_config": "X"}},
            }
        ],
    }

    assert await restore_series_snapshot(db, 1, snapshot) == 1
    assert await db.scalar(select(func.count()).select_from(ConfigItem)) == 1
    db.add(ConfigItem(id=2, category="Optional", row_index=7, rd_name="No IPN", v_code="V-7"))
    await db.flush()

    with pytest.raises(ValueError, match="唯一|多个|冲突|无法确认"):
        await restore_series_snapshot(db, 1, snapshot)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "rollback"])
async def test_version_write_refuses_to_publish_pending_draft(db, operation):
    china, *_ = await seed_models(db)
    item = ConfigItem(id=1, category="Main", row_index=1, rd_name="Feature", ipn="IPN-1")
    db.add(item)
    await db.flush()
    db.add(ConfigValue(item_id=item.id, model_id=china.id, current_config="working draft"))
    target = ConfigVersion(
        series_id=1,
        version_number="1.0.0",
        snapshot_data=json.dumps(
            {
                "models": [{"id": china.id, "name": china.name}],
                "items": [
                    {
                        "id": item.id,
                        "category": item.category,
                        "row_index": item.row_index,
                        "rd_name": item.rd_name,
                        "ipn": item.ipn,
                        "values": {str(china.id): {"current_config": "published"}},
                    }
                ],
            }
        ),
    )
    batch = DraftBatch(id="pending", series_id=1, status="draft")
    db.add_all([target, batch])
    await db.flush()
    db.add(
        ConfigDraft(
            series_id=1,
            batch_id=batch.id,
            item_id=item.id,
            model_id=china.id,
            change_type="update",
            field_name="current_config",
            old_value="published",
            new_value="working draft",
        )
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        if operation == "create":
            await create_version(ConfigVersionCreate(series_id=1), db)
        else:
            await rollback_version(target.id, db)

    assert exc_info.value.status_code == 400
    assert "提交" in exc_info.value.detail
    assert await db.scalar(select(func.count()).select_from(ConfigVersion)) == 1
    assert (await db.scalar(select(ConfigValue))).current_config == "working draft"
    assert await db.scalar(select(func.count()).select_from(ConfigDraft)) == 1


@pytest.mark.asyncio
async def test_rollback_stores_restored_snapshot_with_canonical_ids_and_preserves_history(db):
    china, _, archived, overseas = await seed_models(db)
    shared = ConfigItem(id=1, category="Canonical", row_index=1, rd_name="Shared", ipn="IPN-1")
    db.add(shared)
    await db.flush()
    db.add_all(
        [
            ConfigValue(item_id=shared.id, model_id=china.id, current_config="current"),
            ConfigValue(item_id=shared.id, model_id=archived.id, current_config="archived"),
            ConfigValue(item_id=shared.id, model_id=overseas.id, current_config="overseas"),
        ]
    )
    target = ConfigVersion(
        series_id=1,
        version_number="1.0.0",
        snapshot_data=json.dumps(
            {
                "models": [{"id": 99, "name": "V10 Legacy", "source_uuid": SOURCE_UUID}],
                "items": [
                    {
                        "id": 999,
                        "category": "Historical",
                        "row_index": 99,
                        "rd_name": "Historical name",
                        "ipn": "IPN-1",
                        "values": {"99": {"current_config": "rolled back"}},
                    }
                ],
            }
        ),
    )
    db.add(target)
    await db.flush()
    log = ChangeLog(
        series_id=1,
        version_id=target.id,
        change_type="update",
        item_id=shared.id,
        model_id=china.id,
        field_name="current_config",
    )
    db.add(log)
    await db.commit()

    result = await rollback_version(target.id, db)

    assert result["message"] == "回滚成功"
    assert await db.get(ConfigVersion, target.id) is target
    assert await db.get(ChangeLog, log.id) is log
    assert await db.get(ConfigItem, shared.id) is shared
    await db.refresh(shared)
    assert (shared.category, shared.row_index, shared.rd_name) == ("Canonical", 1, "Shared")
    assert (await db.get(ConfigValue, 2)).current_config == "archived"
    assert (await db.get(ConfigValue, 3)).current_config == "overseas"

    new_version = result["new_version"]
    restored_snapshot = json.loads(new_version.snapshot_data)
    assert restored_snapshot["models"][0]["id"] == china.id
    assert restored_snapshot["models"][0]["source_uuid"] == SOURCE_UUID
    assert restored_snapshot["items"][0]["id"] == shared.id
    assert restored_snapshot["items"][0]["values"] == {
        str(china.id): {
            "current_config": "rolled back",
            "final_config": None,
            "selection_config": None,
            "rd_status": None,
        }
    }


@pytest.mark.asyncio
async def test_restore_rejects_recycled_no_ipn_id_with_conflicting_feature_identity(db):
    china, *_ = await seed_models(db)
    unrelated = ConfigItem(id=1, category='Optional', row_index=100, rd_name='Unrelated feature', v_code='VNEW')
    db.add(unrelated)
    await db.flush()
    db.add(ConfigValue(item_id=1, model_id=china.id, current_config='keep'))
    await db.flush()
    snapshot = {'models': [{'id': china.id, 'name': china.name}], 'items': [{'id': 1, 'category': 'Optional', 'row_index': 5, 'rd_name': 'Old feature', 'v_code': 'VOLD', 'ipn': None, 'values': {str(china.id): {'current_config': 'X'}}}]}
    with pytest.raises(ValueError, match='身份|冲突|无法确认'):
        await restore_series_snapshot(db, 1, snapshot)
    assert (await db.scalar(select(ConfigValue).where(ConfigValue.item_id == 1, ConfigValue.model_id == china.id))).current_config == 'keep'


@pytest.mark.asyncio
@pytest.mark.parametrize('registered', [True, False])
async def test_restore_rejects_recycled_model_id_without_matching_identity(db, registered):
    model = ProductModel(id=10, series_id=1, name='Unrelated new model')
    item = ConfigItem(id=1, category='Main', row_index=1, rd_name='Feature', ipn='IPN-1')
    db.add_all([model, item])
    await db.flush()
    if registered:
        db.add(ProductModelIdentity(series_id=1, model_id=10, source_uuid=SOURCE_UUID, aliases_json='[]', historical_ids_json='[]'))
    db.add(ConfigValue(item_id=1, model_id=10, current_config='keep'))
    await db.flush()
    snapshot = {'models': [{'id': 10, 'name': 'Deleted old model'}], 'items': [{'id': 1, 'ipn': 'IPN-1', 'values': {'10': {'current_config': 'wrong'}}}]}
    with pytest.raises(ValueError, match='身份|冲突|无法确认'):
        await restore_series_snapshot(db, 1, snapshot)
    assert (await db.scalar(select(ConfigValue))).current_config == 'keep'


@pytest.mark.asyncio
async def test_restore_prefers_stable_source_uuid_over_recycled_model_id(db):
    china, _, _, _ = await seed_models(db)
    second_uuid = '11111111-1111-4111-8111-111111111111'
    db.add(ProductModelIdentity(series_id=1, model_id=12, source_uuid=second_uuid, aliases_json='[]', historical_ids_json='[]'))
    item = ConfigItem(id=1, category='Main', row_index=1, rd_name='Feature', ipn='IPN-1')
    db.add(item)
    await db.flush()
    snapshot = {'models': [{'id': 12, 'name': 'V10 Legacy', 'source_uuid': SOURCE_UUID}], 'items': [{'id': 1, 'ipn': 'IPN-1', 'values': {'12': {'current_config': 'restored'}}}]}
    assert await restore_series_snapshot(db, 1, snapshot) == 1
    value = await db.scalar(select(ConfigValue))
    assert (value.model_id, value.current_config) == (china.id, 'restored')


@pytest.mark.asyncio
async def test_restore_resolves_unregistered_legacy_model_by_unique_name(db):
    await seed_models(db)
    item = ConfigItem(id=1, category='Main', row_index=1, rd_name='Feature', ipn='IPN-1')
    db.add(item)
    await db.flush()
    snapshot = {'models': [{'id': 999, 'name': 'V10 Pro'}], 'items': [{'id': 1, 'ipn': 'IPN-1', 'values': {'999': {'current_config': 'restored'}}}]}
    assert await restore_series_snapshot(db, 1, snapshot) == 1
    assert (await db.scalar(select(ConfigValue))).model_id == 12
