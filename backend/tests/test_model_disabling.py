"""Disabling hides current models without destroying their configuration history."""
import io
import json

import httpx
import openpyxl
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import config, import_export, models, versions
from app.database import Base, get_db
from app.models import ConfigItem, ConfigValue, ConfigVersion, ProductModel, ProductSeries
from app.services.config_history import build_series_snapshot
from app.services.model_identity import resolve_import_model


@pytest_asyncio.fixture
async def harness(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'models.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add_all([
            ProductSeries(id=1, name="Tulip-Oversea"),
            ProductModel(id=84, series_id=1, name="ULTIMUS 8E-RUA", status="停产"),
            ProductModel(id=85, series_id=1, name="ULTIMUS 8P-RUA"),
            ConfigItem(id=1, row_index=1, category="Optional Features", ipn="100", rd_name="Feature"),
        ])
        await db.flush()
        db.add_all([
            ConfigValue(item_id=1, model_id=84, current_config="X"),
            ConfigValue(item_id=1, model_id=85, current_config="O"),
        ])
        await db.flush()
        snapshot = await build_series_snapshot(db, 1)
        db.add(ConfigVersion(id=1, series_id=1, version_number="1.0.0", snapshot_data=json.dumps(snapshot)))
        await db.commit()
    app = FastAPI()
    for module, prefix in [(models, "models"), (config, "config"), (versions, "versions"), (import_export, "import-export")]:
        app.include_router(module.router, prefix=f"/api/{prefix}")

    async def override_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_disable_preserves_values_and_status_hides_default_lists_and_can_reenable(harness):
    client, factory = harness
    response = await client.put("/api/models/84/enabled", json={"is_enabled": False})
    assert response.status_code == 200, response.text
    assert response.json()["is_enabled"] is False
    default = (await client.get("/api/models", params={"series_id": 1})).json()
    assert default["total"] == 1
    assert [row["id"] for row in default["items"]] == [85]
    including = (await client.get("/api/models", params={"include_disabled": True, "limit": 1})).json()
    assert including["total"] == 2
    assert including["items"][0]["is_enabled"] is False
    rows = (await client.get("/api/config/rows", params={"series_id": 1})).json()
    assert set(rows["items"][0]["model_values"]) == {"85"}
    async with factory() as db:
        assert (await db.get(ProductModel, 84)).status == "停产"
        assert (await db.scalar(select(ConfigValue).where(ConfigValue.model_id == 84))).current_config == "X"
        assert (await build_series_snapshot(db, 1))["models"][0]["id"] == 84
    response = await client.put("/api/models/84/enabled", json={"is_enabled": True})
    assert response.status_code == 200, response.text
    assert (await client.get("/api/models")).json()["total"] == 2


@pytest.mark.asyncio
async def test_legacy_delete_is_non_destructive_and_repeated_disable_is_safe(harness):
    client, factory = harness
    for _ in range(2):
        response = await client.delete("/api/models/84")
        assert response.status_code == 200, response.text
    async with factory() as db:
        model = await db.get(ProductModel, 84)
        assert model is not None
        assert model.is_enabled is False
        assert len((await db.scalars(select(ConfigValue))).all()) == 2
        assert await db.get(ConfigVersion, 1) is not None


@pytest.mark.asyncio
async def test_history_view_compare_and_rollback_preserve_disabled_identity_and_visibility(harness):
    client, factory = harness
    original = (await client.get("/api/versions/1")).json()["snapshot_data"]
    assert (await client.put("/api/models/84/enabled", json={"is_enabled": False})).status_code == 200
    async with factory() as db:
        value = await db.scalar(select(ConfigValue).where(ConfigValue.model_id == 84))
        value.current_config = "changed"
        await db.commit()
    assert (await client.get("/api/versions/1")).json()["snapshot_data"] == original
    rolled = await client.post("/api/versions/1/rollback")
    assert rolled.status_code == 200, rolled.text
    new_id = rolled.json()["new_version"]["id"]
    compared = await client.post("/api/versions/compare", json={"version_id_1": 1, "version_id_2": new_id})
    assert compared.status_code == 200, compared.text
    assert compared.json()["summary"] == {"added": 0, "modified": 0, "deleted": 0}
    async with factory() as db:
        assert (await db.get(ProductModel, 84)).is_enabled is False
        assert (await db.scalar(select(ConfigValue).where(ConfigValue.model_id == 84))).current_config == "X"
        assert (await db.scalar(select(ConfigValue).where(ConfigValue.model_id == 85))).current_config == "O"
    assert (await client.get("/api/models")).json()["total"] == 1


@pytest.mark.asyncio
async def test_default_export_hides_disabled_but_reimport_reuses_its_identity(harness):
    client, factory = harness
    assert (await client.put("/api/models/84/enabled", json={"is_enabled": False})).status_code == 200
    response = await client.post("/api/import-export/export", json={"series_id": 1})
    assert response.status_code == 200, response.text
    workbook = openpyxl.load_workbook(io.BytesIO(response.content))
    headers = [cell.value for row in workbook.active.iter_rows(min_row=1, max_row=2) for cell in row]
    assert "ULTIMUS 8E-RUA" not in headers
    assert "ULTIMUS 8P-RUA" in headers
    async with factory() as db:
        resolved = await resolve_import_model(db, 1, "ULTIMUS 8E-RUA", 6, 9, 0)
        assert resolved.id == 84
        assert resolved.is_enabled is False


@pytest.mark.asyncio
async def test_enable_api_rejects_missing_models_and_missing_boolean(harness):
    client, _ = harness
    assert (await client.put("/api/models/999/enabled", json={"is_enabled": False})).status_code == 404
    assert (await client.put("/api/models/84/enabled", json={})).status_code == 422


@pytest.mark.asyncio
async def test_startup_upgrades_legacy_database_idempotently(tmp_path, monkeypatch):
    from app import database
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    monkeypatch.setattr(database, "engine", engine)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE product_models (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"))
            await connection.execute(text("INSERT INTO product_models VALUES (84, 'ULTIMUS 8E-RUA', '停产')"))
        await database.init_db()
        await database.init_db()
        async with engine.connect() as connection:
            row = (await connection.execute(text("SELECT name, status, is_enabled FROM product_models"))).one()
            assert tuple(row) == ("ULTIMUS 8E-RUA", "停产", 1)
    finally:
        await engine.dispose()
