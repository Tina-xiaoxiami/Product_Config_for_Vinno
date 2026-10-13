import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import config
from app.database import Base, get_db
from app.models import ConfigItem, ConfigValue, ProductModel, ProductSeries


async def _config_harness(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'config-compare.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    app = FastAPI()
    app.include_router(config.router, prefix="/api/config")

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )
    return client, session_factory, engine


async def _seed_compare_data(session_factory):
    async with session_factory() as session:
        item = ConfigItem(
            id=100,
            category="Optional",
            row_index=1,
            rd_name="Feature",
            ipn="IPN-100",
        )
        session.add_all(
            [
                ProductSeries(id=1, name="V Series"),
                ProductSeries(id=2, name="Other Series"),
                ProductModel(id=10, series_id=1, name="V10"),
                ProductModel(id=20, series_id=2, name="X1"),
                item,
            ]
        )
        await session.flush()
        session.add_all(
            [
                ConfigValue(item_id=item.id, model_id=10, current_config="V value"),
                ConfigValue(item_id=item.id, model_id=20, current_config="X value"),
            ]
        )
        await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/config/compare", "/api/config/compare/export"])
@pytest.mark.parametrize(
    "model_ids",
    [
        pytest.param([10, 10], id="duplicate"),
        pytest.param([10, 999], id="missing"),
    ],
)
async def test_compare_endpoints_reject_duplicate_or_missing_model_ids(
    tmp_path,
    path,
    model_ids,
):
    client, session_factory, engine = await _config_harness(tmp_path)
    await _seed_compare_data(session_factory)

    async with client:
        response = await client.post(path, json={"model_ids": model_ids})

    assert response.status_code == 400
    assert "型号" in response.json()["detail"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_compare_preserves_requested_cross_series_model_order(tmp_path):
    client, session_factory, engine = await _config_harness(tmp_path)
    await _seed_compare_data(session_factory)
    payload = {"model_ids": [20, 10], "show_only_diff": True}

    async with client:
        compared = await client.post("/api/config/compare", json=payload)

    assert compared.status_code == 200, compared.text
    assert compared.json()["items"][0]["model_id"] == 20
    assert compared.json()["items"][0]["model_name"] == "X1"
    await engine.dispose()
