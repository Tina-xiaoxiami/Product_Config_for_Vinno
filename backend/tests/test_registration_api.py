import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import registration
from app.database import get_db
from app.services.registration_import import import_domestic_registration_workbook
from app.services.registration_migration import migrate_registration_schema
from test_registration_import import _create_database, _write_registration_workbook


async def _client_for(database_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(registration.router, prefix="/api/knowledge/registration")

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )
    return client, engine


@pytest.mark.asyncio
async def test_registration_api_combines_redline_formal_strategy_and_current_auxiliary(tmp_path):
    database_path = tmp_path / "product_config.db"
    workbook_path = tmp_path / "registration.xlsx"
    _create_database(database_path)
    _write_registration_workbook(workbook_path)
    migrate_registration_schema(database_path)
    import_domestic_registration_workbook(
        database_path,
        workbook_path,
        source_document_id=1,
    )
    client, engine = await _client_for(database_path)

    async with client:
        models_response = await client.get(
            "/api/knowledge/registration/configured-models",
            params={"country_code": "CN"},
        )
        probes_response = await client.get(
            "/api/knowledge/registration/probes",
            params={"product_model_id": 2},
        )
    await engine.dispose()

    assert models_response.status_code == 200
    assert [item["product_model_name"] for item in models_response.json()["items"]] == [
        "VINNO 10",
        "VINNO 10E",
        "VINNO 9",
        "VINNO 9_Private",
        "VINNO 9 综合版",
    ]
    assert models_response.json()["items"][-1] == {
        "product_model_id": 5,
        "product_model_name": "VINNO 9 综合版",
        "registration_model_id": 3,
        "registration_model_name": "VINNO 9",
        "mapping_type": "confirmed_derived",
        "channel_count": 128,
    }

    assert probes_response.status_code == 200
    body = probes_response.json()
    assert body["total"] == 3
    assert body["summary"] == {
        "registered": 2,
        "unregistered": 1,
        "standard": 0,
        "optional": 0,
        "tender": 0,
        "undefined": 2,
        "auxiliary": 0,
        "conflicts": 0,
    }
    f2 = next(item for item in body["items"] if item["probe_model"] == "F2-5C")
    assert f2 == {
        "probe_id": 1,
        "probe_model": "F2-5C",
        "ipn": "1000530",
        "registration_status": "unregistered",
        "registration_symbol": "#",
        "selection_config": "未定义",
        "current_config": "X",
        "effective_status": "#",
        "status_source": "registration_redline",
        "strategy_is_formal": True,
        "conflict": False,
        "config_item_id": 10,
        "config_name": "F2-5C探头",
        "source_document_id": 1,
    }


@pytest.mark.asyncio
async def test_registration_api_filters_and_derived_models_keep_base_redline(tmp_path):
    database_path = tmp_path / "product_config.db"
    workbook_path = tmp_path / "registration.xlsx"
    _create_database(database_path)
    _write_registration_workbook(workbook_path)
    migrate_registration_schema(database_path)
    import_domestic_registration_workbook(
        database_path,
        workbook_path,
        source_document_id=1,
    )
    client, engine = await _client_for(database_path)

    async with client:
        filtered = await client.get(
            "/api/knowledge/registration/probes",
            params={
                "product_model_id": 5,
                "q": "1000744",
                "registration_status": "unregistered",
                "effective_status": "#",
            },
        )
        registration_models = await client.get(
            "/api/knowledge/registration/models",
            params={"country_code": "CN", "q": "VINNO 10"},
        )
        missing = await client.get(
            "/api/knowledge/registration/probes",
            params={"product_model_id": 999},
        )
    await engine.dispose()

    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    item = filtered.json()["items"][0]
    assert item["probe_model"] == "G1-4P"
    assert item["registration_status"] == "unregistered"
    assert item["effective_status"] == "#"
    assert item["current_config"] == "Δ"
    assert registration_models.status_code == 200
    assert [item["model_name"] for item in registration_models.json()["items"]] == [
        "VINNO 10",
        "VINNO 10E",
    ]
    assert missing.status_code == 404
    assert missing.json()["detail"] == "产品型号尚未关联注册基础型号"

