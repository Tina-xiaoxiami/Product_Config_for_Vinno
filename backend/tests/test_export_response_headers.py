"""导出接口的响应头必须能被 latin-1 编码。

三个导出接口把文件名拼进 ``Content-Disposition``。Starlette 按 latin-1 编码响应头值，
未做百分号编码的中文文件名会抛 ``UnicodeEncodeError``，最终变成裸 500 —— 用户看到
的只是"导出失败"。这里对三个接口都断言 200，且响应头可被 latin-1 解码。
"""

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import config as config_api
from app.api import import_export, probe_config
from app.database import Base, get_db
from app.models import (
    ConfigItem,
    ConfigValue,
    Feature,
    FeatureGroup,
    ProbeCategory,
    ProbeModel,
    ProductModel,
    ProductProbeConfig,
    ProductProbeModel,
    ProductSeries,
)


async def _client_for(database_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(config_api.router, prefix="/api/config")
    app.include_router(import_export.router, prefix="/api/import-export")
    app.include_router(probe_config.router, prefix="/api/probes/config")

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    import httpx

    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        timeout=120,
    )
    return client, engine, session_factory


def _assert_header_is_ascii_safe(response):
    disposition = response.headers.get("content-disposition")
    assert disposition is not None
    # 未百分号编码的中文文件名会在这里失败（等价于线上抛 UnicodeEncodeError）
    disposition.encode("latin-1")
    assert "filename*=UTF-8''" in disposition


async def _seed(session_factory):
    """一个中文系列名 + 一条配置值 + 一条产品探头功能配置，覆盖三个导出的前置条件。"""

    async with session_factory() as session:
        series = ProductSeries(name="R&V10系列-国内")
        session.add(series)
        await session.flush()
        model = ProductModel(series_id=series.id, name="VINNO 10")
        other = ProductModel(series_id=series.id, name="VINNO 10E")
        session.add_all([model, other])
        await session.flush()
        item = ConfigItem(
            category="Optional Features",
            row_index=1,
            rd_name="TView",
            ipn="6000017",
            zh_desc="组织多普勒成像",
        )
        session.add(item)
        await session.flush()
        session.add_all(
            [
                ConfigValue(item_id=item.id, model_id=model.id, final_config="标配"),
                ConfigValue(item_id=item.id, model_id=other.id, final_config="选配"),
            ]
        )

        group = FeatureGroup(name="成像", sort_order=1)
        session.add(group)
        await session.flush()
        feature = Feature(group_id=group.id, name="组织多普勒成像", identity_status="confirmed")
        category = ProbeCategory(name="常规凸阵", sort_order=1)
        session.add_all([feature, category])
        await session.flush()
        probe = ProbeModel(category_id=category.id, model_number="F2-5C", sort_order=1)
        session.add(probe)
        await session.flush()
        session.add(ProductProbeModel(product_model_id=model.id, probe_model_id=probe.id))
        session.add(
            ProductProbeConfig(
                product_model_id=model.id,
                probe_model_id=probe.id,
                feature_id=feature.id,
                defined_status="supported",
                current_status="supported",
            )
        )
        await session.commit()
        return int(series.id), int(model.id), int(other.id)


@pytest.mark.asyncio
async def test_compare_export_keeps_a_chinese_filename_encodable(tmp_path):
    """配置对比导出的文件名是硬编码中文，曾经 100% 失败。"""

    database_path = tmp_path / "product_config.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()

    client, engine, session_factory = await _client_for(database_path)
    _series_id, model_id, other_id = await _seed(session_factory)
    async with client:
        response = await client.post(
            "/api/config/compare/export",
            json={
                "model_ids": [model_id, other_id],
                "compare_fields": ["final_config"],
                "show_only_diff": False,
            },
        )
    await engine.dispose()

    assert response.status_code == 200, response.text
    _assert_header_is_ascii_safe(response)
    assert response.content[:2] == b"PK"  # 确实是 xlsx


@pytest.mark.asyncio
async def test_series_export_keeps_a_chinese_series_name_encodable(tmp_path):
    """系列名可能是中文，导出文件名必须百分号编码。"""

    database_path = tmp_path / "product_config.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()

    client, engine, session_factory = await _client_for(database_path)
    series_id, _model_id, _other_id = await _seed(session_factory)
    async with client:
        response = await client.post(
            "/api/import-export/export", json={"series_id": series_id}
        )
    await engine.dispose()

    assert response.status_code == 200, response.text
    _assert_header_is_ascii_safe(response)
    assert response.content[:2] == b"PK"


@pytest.mark.asyncio
async def test_probe_config_export_keeps_a_chinese_filename_encodable(tmp_path):
    """探头配置导出的文件名含字面量「探头配置」，曾经 100% 失败。"""

    database_path = tmp_path / "product_config.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()

    client, engine, session_factory = await _client_for(database_path)
    _series_id, model_id, _other_id = await _seed(session_factory)
    async with client:
        matrix = await client.get(f"/api/probes/config/{model_id}")
        response = await client.get(f"/api/probes/config/{model_id}/export")
    await engine.dispose()

    # 旧实现里这个 GET 也 500：applications 注解是 List[dict]，实现给的是 dict
    assert matrix.status_code == 200, matrix.text
    assert response.status_code == 200, response.text
    _assert_header_is_ascii_safe(response)
    assert response.content[:2] == b"PK"
