"""Series filtering and nonempty values precede count and pagination."""
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import config
from app.database import Base, get_db
from app.models import ConfigItem, ConfigValue, ProductModel, ProductSeries


@pytest_asyncio.fixture
async def client(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rows.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add_all([
            ProductSeries(id=1, name="Current"), ProductSeries(id=2, name="Other"),
            ProductModel(id=1, series_id=1, name="Enabled"),
            ProductModel(id=2, series_id=2, name="Other"),
            ProductModel(id=3, series_id=1, name="Disabled", is_enabled=False),
            ProductModel(id=4, series_id=1, name="Merged", status="已合并"),
            *[ConfigItem(id=i, row_index=i, category="Optional Features", rd_name=f"Item {i}") for i in range(1, 8)],
        ])
        await db.flush()
        db.add_all([
            ConfigValue(item_id=1, model_id=2, current_config="X"),
            ConfigValue(item_id=2, model_id=3, current_config="X"),
            ConfigValue(item_id=3, model_id=4, current_config="X"),
            ConfigValue(item_id=4, model_id=1, current_config=" N/A ", final_config="-", selection_config="None", rd_status="\t\n"),
            ConfigValue(item_id=5, model_id=1, current_config="X"),
            ConfigValue(item_id=6, model_id=1, rd_status="已完成"),
        ])
        await db.commit()
    app = FastAPI()
    app.include_router(config.router, prefix="/api/config")

    async def override_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield http
    await engine.dispose()


@pytest.mark.asyncio
async def test_series_nonempty_filter_applies_before_pagination_and_count(client):
    for skip, expected in [(0, [5]), (1, [6]), (2, [])]:
        response = await client.get("/api/config/rows", params={"series_id": 1, "skip": skip, "limit": 1})
        assert response.status_code == 200
        assert response.json()["total"] == 2
        assert [row["id"] for row in response.json()["items"]] == expected


@pytest.mark.asyncio
async def test_include_empty_preserves_global_item_directory_for_drafts(client):
    data = (await client.get("/api/config/rows", params={"series_id": 1, "include_empty": True})).json()
    assert data["total"] == 7
    assert [row["id"] for row in data["items"]] == list(range(1, 8))
    assert data["items"][0]["model_values"] == {}


@pytest.mark.asyncio
async def test_search_counts_only_matching_visible_rows_and_unknown_series_is_empty(client):
    data = (await client.get("/api/config/rows", params={"series_id": 1, "search": "Item 6"})).json()
    assert data["total"] == 1
    assert [row["id"] for row in data["items"]] == [6]
    data = (await client.get("/api/config/rows", params={"series_id": 999})).json()
    assert data == {"items": [], "total": 0}
