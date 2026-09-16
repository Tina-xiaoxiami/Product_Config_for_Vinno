"""版本回滚只能影响本系列。

``config_items`` 是所有系列共用的配置项主数据。旧实现用 ``delete(ConfigItem)``
（无 WHERE，等于 ``DELETE FROM config_items``）清空全表再按快照重建，导致回滚
一个系列会删掉所有其他系列的配置项，其他系列的配置值随即变成孤儿行、在界面上
直接消失。
"""

import json

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import config as config_api
from app.api import versions
from app.database import Base, get_db
from app.models import ConfigItem, ConfigValue, ConfigVersion, ProductModel, ProductSeries


async def _client_for(database_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(versions.router, prefix="/api/versions")
    app.include_router(config_api.router, prefix="/api/config")

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    import httpx

    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=60
    )
    return client, engine, session_factory


async def _seed_two_series(session_factory, *, extra_model: bool = False):
    """两个系列，各自一个型号和一条配置；A 系列有一条已发布版本快照。"""

    async with session_factory() as session:
        series_a = ProductSeries(name="SeriesA")
        series_b = ProductSeries(name="SeriesB")
        session.add_all([series_a, series_b])
        await session.flush()
        model_a = ProductModel(series_id=series_a.id, name="ModelA")
        model_b = ProductModel(series_id=series_b.id, name="ModelB")
        session.add_all([model_a, model_b])
        await session.flush()
        extra = None
        if extra_model:
            extra = ProductModel(series_id=series_a.id, name="RemovedModel")
            session.add(extra)
            await session.flush()
        item_a = ConfigItem(row_index=1, ipn="IPN-A", rd_name="A项")
        item_b = ConfigItem(row_index=2, ipn="IPN-B", rd_name="B项")
        session.add_all([item_a, item_b])
        await session.flush()
        session.add_all(
            [
                ConfigValue(item_id=item_a.id, model_id=model_a.id, final_config="A快照值"),
                ConfigValue(item_id=item_b.id, model_id=model_b.id, final_config="B值"),
            ]
        )
        if extra is not None:
            session.add(
                ConfigValue(item_id=item_a.id, model_id=extra.id, final_config="将被丢弃")
            )
        snapshot = {
            "models": [{"id": model_a.id, "name": "ModelA"}]
            + ([{"id": extra.id, "name": "RemovedModel"}] if extra is not None else []),
            "items": [
                {
                    "id": item_a.id,
                    "category": "Optional Features",
                    "row_index": 1,
                    "rd_name": "A项",
                    "v_code": None,
                    "ipn": "IPN-A",
                    "zh_desc": None,
                    "en_desc": None,
                    "values": {
                        str(model_a.id): {
                            "current_config": None,
                            "final_config": "A快照值",
                            "selection_config": None,
                            "rd_status": None,
                        }
                    },
                }
            ],
        }
        version = ConfigVersion(
            series_id=series_a.id,
            version_number="1.0.0",
            snapshot_data=json.dumps(snapshot),
            row_count=1,
        )
        session.add(version)
        await session.commit()
        return {
            "series_a": int(series_a.id),
            "series_b": int(series_b.id),
            "model_a": int(model_a.id),
            "model_b": int(model_b.id),
            "version_id": int(version.id),
        }


@pytest.mark.asyncio
async def test_rollback_keeps_other_series_config_items_and_values(tmp_path):
    """回滚 A 系列不能删除 B 系列的配置项与配置值。"""

    database_path = tmp_path / "product_config.db"
    client, engine, session_factory = await _client_for(database_path)
    ids = await _seed_two_series(session_factory)

    async with client:
        before = await client.get(
            "/api/config/rows",
            params={"series_id": ids["series_b"], "include_empty": True, "limit": 999},
        )
        rolled = await client.post(f"/api/versions/{ids['version_id']}/rollback")
        after = await client.get(
            "/api/config/rows",
            params={"series_id": ids["series_b"], "include_empty": True, "limit": 999},
        )
    await engine.dispose()

    assert rolled.status_code == 200, rolled.text
    assert sorted(row["ipn"] for row in before.json()["items"]) == ["IPN-A", "IPN-B"]
    # 旧实现在这里会变成 ["IPN-A"]：B 的配置项被删掉，B 的配置值成了孤儿
    assert sorted(row["ipn"] for row in after.json()["items"]) == ["IPN-A", "IPN-B"]

    async with session_factory() as session:
        from sqlalchemy import select

        items = (await session.execute(select(ConfigItem))).scalars().all()
        assert sorted(item.ipn for item in items) == ["IPN-A", "IPN-B"]
        values = (await session.execute(select(ConfigValue))).scalars().all()
        # 两条配置值都还在，且都指向仍然存在的配置项
        assert len(values) == 2
        assert {value.item_id for value in values} <= {item.id for item in items}



@pytest.mark.asyncio
async def test_rollback_restores_the_target_snapshot_values(tmp_path):
    """回滚本身要生效：本系列的配置值回到快照里的值。"""

    database_path = tmp_path / "product_config.db"
    client, engine, session_factory = await _client_for(database_path)
    ids = await _seed_two_series(session_factory)

    async with session_factory() as session:
        from sqlalchemy import select

        value = (
            await session.execute(
                select(ConfigValue).where(ConfigValue.model_id == ids["model_a"])
            )
        ).scalar_one()
        value.final_config = "被改过的值"
        await session.commit()

    async with client:
        rolled = await client.post(f"/api/versions/{ids['version_id']}/rollback")
    await engine.dispose()

    assert rolled.status_code == 200, rolled.text
    async with session_factory() as session:
        from sqlalchemy import select

        values = (
            await session.execute(
                select(ConfigValue).where(ConfigValue.model_id == ids["model_a"])
            )
        ).scalars().all()
        assert len(values) == 1
        assert values[0].final_config == "A快照值"


@pytest.mark.asyncio
async def test_rollback_reuses_existing_items_by_ipn_and_reports_missing_models(tmp_path):
    """配置项按 IPN 复用（ID 不变），快照里已不存在的机型要给出告警而不是静默丢值。"""

    database_path = tmp_path / "product_config.db"
    client, engine, session_factory = await _client_for(database_path)
    ids = await _seed_two_series(session_factory, extra_model=True)

    async with session_factory() as session:
        from sqlalchemy import delete as sqla_delete
        from sqlalchemy import select

        item_id_before = (
            await session.execute(select(ConfigItem).where(ConfigItem.ipn == "IPN-A"))
        ).scalar_one().id
        # 快照里有、当前系列已不存在的机型：它的配置值无法恢复，必须告警而非静默丢弃
        removed = (
            await session.execute(
                select(ProductModel).where(ProductModel.name == "RemovedModel")
            )
        ).scalar_one()
        await session.execute(
            sqla_delete(ConfigValue).where(ConfigValue.model_id == removed.id)
        )
        await session.execute(
            sqla_delete(ProductModel).where(ProductModel.id == removed.id)
        )
        await session.commit()

    async with client:
        rolled = await client.post(f"/api/versions/{ids['version_id']}/rollback")
    await engine.dispose()

    assert rolled.status_code == 200, rolled.text
    body = rolled.json()
    assert body["warnings"], "机型缺失时必须有告警"
    assert "RemovedModel" in " ".join(body["warnings"])

    async with session_factory() as session:
        from sqlalchemy import select

        item = (
            await session.execute(select(ConfigItem).where(ConfigItem.ipn == "IPN-A"))
        ).scalar_one()
        # 按 IPN 复用而不是删表重建，所以 ID 保持稳定
        assert item.id == item_id_before
