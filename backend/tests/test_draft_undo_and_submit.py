"""草稿撤销与提交的一致性。

两处缺陷：
1. ``DELETE /drafts/draft/by-key`` 被 ``/draft/{draft_id}`` 抢先匹配，永远 422；
   而且删除草稿不回退已写入 ``config_values`` 的新值 —— 界面以为撤销了，库里仍是改过的值。
2. 版本号重复时，提交路径在写操作之后才校验：单批次接口抛 IntegrityError（裸 500），
   批量接口返回失败但已经改掉配置值、删掉草稿，且没有版本记录。
"""

import json

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import drafts as drafts_api
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


async def _client_for(database_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(drafts_api.router, prefix="/api/drafts")

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    import httpx

    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=60
    )
    return client, engine, session_factory


async def _seed(session_factory, *, duplicate_drafts: bool = False, version_number=None):
    """一个系列/型号/配置项，草稿已把值改成「新值」，批次为待提交。"""

    async with session_factory() as session:
        series = ProductSeries(name="SeriesA")
        session.add(series)
        await session.flush()
        model = ProductModel(series_id=series.id, name="ModelA")
        item = ConfigItem(row_index=1, ipn="IPN-1", rd_name="项1")
        session.add_all([model, item])
        await session.flush()
        session.add(ConfigValue(item_id=item.id, model_id=model.id, final_config="新值"))
        if version_number:
            session.add(
                ConfigVersion(
                    series_id=series.id,
                    version_number=version_number,
                    snapshot_data=json.dumps({"models": [], "items": []}),
                    row_count=0,
                )
            )
        session.add(
            DraftBatch(
                id="B1",
                series_id=series.id,
                status="draft",
                total_count=2 if duplicate_drafts else 1,
                update_count=2 if duplicate_drafts else 1,
            )
        )
        for new_value in (["新值", "新值2"] if duplicate_drafts else ["新值"]):
            session.add(
                ConfigDraft(
                    series_id=series.id,
                    batch_id="B1",
                    change_type="update",
                    item_id=item.id,
                    model_id=model.id,
                    field_name="final_config",
                    old_value="旧值",
                    new_value=new_value,
                )
            )
        await session.commit()
        return int(item.id), int(model.id)


@pytest.mark.asyncio
async def test_delete_draft_by_key_is_reachable_and_reverts_the_value(tmp_path):
    """按条件撤销必须可达（曾经被动态路由遮蔽成 422），并把值改回旧值。"""

    database_path = tmp_path / "product_config.db"
    client, engine, session_factory = await _client_for(database_path)
    item_id, model_id = await _seed(session_factory)

    async with client:
        response = await client.delete(
            "/api/drafts/draft/by-key",
            params={
                "batch_id": "B1",
                "item_id": item_id,
                "model_id": model_id,
                "field_name": "final_config",
            },
        )
    await engine.dispose()

    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True
    async with session_factory() as session:
        from sqlalchemy import select

        value = (
            await session.execute(select(ConfigValue).where(ConfigValue.model_id == model_id))
        ).scalar_one()
        assert value.final_config == "旧值"
        drafts = (await session.execute(select(ConfigDraft))).scalars().all()
        assert drafts == []


@pytest.mark.asyncio
async def test_delete_draft_by_key_tolerates_duplicate_draft_rows(tmp_path):
    """同一格存在重复草稿行（历史并发写入留下）时，一次清掉且不报 500。"""

    database_path = tmp_path / "product_config.db"
    client, engine, session_factory = await _client_for(database_path)
    item_id, model_id = await _seed(session_factory, duplicate_drafts=True)

    async with client:
        response = await client.delete(
            "/api/drafts/draft/by-key",
            params={
                "batch_id": "B1",
                "item_id": item_id,
                "model_id": model_id,
                "field_name": "final_config",
            },
        )
    await engine.dispose()

    assert response.status_code == 200, response.text
    assert response.json()["removed"] == 2
    async with session_factory() as session:
        from sqlalchemy import select

        assert (await session.execute(select(ConfigDraft))).scalars().all() == []


@pytest.mark.asyncio
async def test_submit_rejects_a_duplicate_version_number_without_touching_data(tmp_path):
    """界面用的单批次提交：版本号重复要给出 400，且草稿与配置值原样保留。"""

    database_path = tmp_path / "product_config.db"
    client, engine, session_factory = await _client_for(database_path)
    item_id, model_id = await _seed(session_factory, version_number="1.0.0")

    async with client:
        response = await client.post(
            "/api/drafts/batch/B1/submit", json={"version_number": "1.0.0"}
        )
    await engine.dispose()

    assert response.status_code == 400, response.text
    assert "已存在" in response.json()["detail"]
    async with session_factory() as session:
        from sqlalchemy import select

        assert len((await session.execute(select(ConfigDraft))).scalars().all()) == 1
        values = (await session.execute(select(ConfigValue))).scalars().all()
        assert [value.final_config for value in values] == ["新值"]


@pytest.mark.asyncio
async def test_batch_submit_keeps_the_draft_when_the_version_number_is_duplicated(tmp_path):
    """批量提交：版本号重复时不能在报失败的同时把草稿删掉。"""

    database_path = tmp_path / "product_config.db"
    client, engine, session_factory = await _client_for(database_path)
    await _seed(session_factory, version_number="1.0.0")

    async with client:
        response = await client.post(
            "/api/drafts/batch/submit",
            json={"batch_ids": ["B1"], "version_number": "1.0.0"},
        )
    await engine.dispose()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["submitted_count"] == 0
    assert "已存在" in body["results"][0]["message"]
    async with session_factory() as session:
        from sqlalchemy import select

        # 旧实现在这里会变成 0：草稿被删掉，改动永久留在库里却没有版本记录
        assert len((await session.execute(select(ConfigDraft))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_submit_still_creates_a_version_on_the_happy_path(tmp_path):
    """正常提交仍然要生效：应用改动、清空草稿、生成版本。"""

    database_path = tmp_path / "product_config.db"
    client, engine, session_factory = await _client_for(database_path)
    await _seed(session_factory)

    async with client:
        response = await client.post("/api/drafts/batch/B1/submit", json={})
    await engine.dispose()

    assert response.status_code == 200, response.text
    assert response.json()["version_number"] == "1.0.0"
    async with session_factory() as session:
        from sqlalchemy import select

        assert (await session.execute(select(ConfigDraft))).scalars().all() == []
        versions = (await session.execute(select(ConfigVersion))).scalars().all()
        assert [version.version_number for version in versions] == ["1.0.0"]
        values = (await session.execute(select(ConfigValue))).scalars().all()
        assert [value.final_config for value in values] == ["新值"]


@pytest.mark.asyncio
async def test_batch_submit_commits_each_batch_independently(tmp_path):
    """一个批次成功、另一个不存在时，成功的那批必须真的落库。"""

    database_path = tmp_path / "product_config.db"
    client, engine, session_factory = await _client_for(database_path)
    await _seed(session_factory)

    async with client:
        response = await client.post(
            "/api/drafts/batch/submit", json={"batch_ids": ["B1", "MISSING"]}
        )
    await engine.dispose()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["submitted_count"] == 1
    assert [result["success"] for result in body["results"]] == [True, False]
    async with session_factory() as session:
        from sqlalchemy import select

        versions = (await session.execute(select(ConfigVersion))).scalars().all()
        assert len(versions) == 1


@pytest.mark.asyncio
async def test_partial_submit_matching_nothing_does_not_create_an_empty_version(tmp_path):
    """部分提交筛选不到本批次的草稿时，不能凭空追加一条空版本。"""

    database_path = tmp_path / "product_config.db"
    client, engine, session_factory = await _client_for(database_path)
    item_id, _model_id = await _seed(session_factory)

    async with client:
        response = await client.post(
            "/api/drafts/batch/B1/submit",
            json={"item_ids": [item_id + 999]},  # 与任何草稿都不匹配
        )
    await engine.dispose()

    assert response.status_code == 400, response.text
    assert "没有匹配的待提交草稿" in response.json()["detail"]
    async with session_factory() as session:
        from sqlalchemy import select

        assert (await session.execute(select(ConfigVersion))).scalars().all() == []
        assert len((await session.execute(select(ConfigDraft))).scalars().all()) == 1
