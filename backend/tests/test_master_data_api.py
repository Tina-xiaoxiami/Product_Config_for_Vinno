import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import features, knowledge
from app.database import get_db
from test_knowledge_api import _create_knowledge_database


async def _client_for(database_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(features.router, prefix="/api/features")
    app.include_router(knowledge.router, prefix="/api/knowledge")

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
async def test_feature_management_updates_the_same_names_read_by_knowledge(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)

    payload = {
        "primary_cn_name": "超微细血流成像",
        "primary_en_name": "Super Micro Flow",
        "alias_cn_names": ["超微血流"],
        "alias_en_names": ["SMF"],
        "ipns": [{"ipn": "6000273", "relation_type": "primary"}],
    }
    async with client:
        before = await client.get("/api/features/7/master-data")
        updated = await client.put("/api/features/7/master-data", json=payload)
        searched = await client.get(
            "/api/knowledge/features", params={"q": "超微血流"}
        )
    await engine.dispose()

    assert before.status_code == 200
    assert before.json()["primary_en_name"] == "SMF(Super Micro Flow)"
    assert updated.status_code == 200
    body = updated.json()
    assert body["primary_cn_name"] == "超微细血流成像"
    assert body["primary_en_name"] == "Super Micro Flow"
    assert body["alias_cn_names"] == ["超微血流"]
    assert set(body["alias_en_names"]) == {"SMF", "SMF(Super Micro Flow)"}
    assert body["ipns"] == [
        {
            "config_item_id": 84,
            "ipn": "6000273",
            "relation_type": "primary",
            "zh_desc": "超微细血流成像",
            "en_desc": "SMF(Super Micro Flow)",
        }
    ]
    assert searched.status_code == 200
    assert searched.json()["items"][0]["id"] == 7
    assert searched.json()["items"][0]["primary_en_name"] == "Super Micro Flow"


@pytest.mark.asyncio
async def test_feature_management_rejects_unknown_ipn_without_partial_update(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)

    payload = {
        "primary_cn_name": "错误名称",
        "primary_en_name": "Invalid name",
        "alias_cn_names": [],
        "alias_en_names": [],
        "ipns": [{"ipn": "9999999", "relation_type": "primary"}],
    }
    async with client:
        rejected = await client.put("/api/features/7/master-data", json=payload)
        unchanged = await client.get("/api/features/7/master-data")
    await engine.dispose()

    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "未找到IPN对应的配置项：9999999"
    assert unchanged.json()["primary_cn_name"] == "超微细血流成像"
    assert unchanged.json()["primary_en_name"] == "SMF(Super Micro Flow)"


@pytest.mark.asyncio
async def test_feature_master_data_validates_identity_boundaries(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)
    valid_names = {
        "primary_cn_name": "超微细血流成像",
        "primary_en_name": "Super Micro Flow",
        "alias_cn_names": [],
        "alias_en_names": [],
    }

    async with client:
        missing_get = await client.get("/api/features/999/master-data")
        missing_put = await client.put(
            "/api/features/999/master-data",
            json={**valid_names, "ipns": []},
        )
        empty_name = await client.put(
            "/api/features/7/master-data",
            json={**valid_names, "primary_cn_name": "  ", "ipns": []},
        )
        blank_ipn = await client.put(
            "/api/features/7/master-data",
            json={
                **valid_names,
                "ipns": [{"ipn": " ", "relation_type": "primary"}],
            },
        )
        duplicate_ipn = await client.put(
            "/api/features/7/master-data",
            json={
                **valid_names,
                "ipns": [
                    {"ipn": "6000273", "relation_type": "primary"},
                    {"ipn": "6000273", "relation_type": "related"},
                ],
            },
        )
        multiple_primary = await client.put(
            "/api/features/31/master-data",
            json={
                **valid_names,
                "ipns": [
                    {"ipn": "6000294", "relation_type": "primary"},
                    {"ipn": "6000415", "relation_type": "primary"},
                ],
            },
        )

    assert missing_get.status_code == 404
    assert missing_put.status_code == 404
    assert empty_name.status_code == 422
    assert empty_name.json()["detail"] == "中文主名称和英文主名称不能为空"
    assert blank_ipn.status_code == 422
    assert blank_ipn.json()["detail"] == "IPN不能为空"
    assert duplicate_ipn.status_code == 422
    assert duplicate_ipn.json()["detail"] == "IPN重复：6000273"
    assert multiple_primary.status_code == 422
    assert multiple_primary.json()["detail"] == "一个功能只能设置一个主IPN"
    await engine.dispose()


@pytest.mark.asyncio
async def test_feature_master_data_preserves_old_primary_and_replaces_manual_aliases(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)

    first_payload = {
        "primary_cn_name": "超微细血流成像",
        "primary_en_name": "SMF(Super Micro Flow)",
        "alias_cn_names": ["临时中文名"],
        "alias_en_names": ["Temporary SMF"],
        "ipns": [{"ipn": "6000273", "relation_type": "primary"}],
    }
    second_payload = {
        "primary_cn_name": "超微血流成像",
        "primary_en_name": "Super Micro Flow",
        "alias_cn_names": ["超微血流成像【启用】", "超微细血流成像", "超微细血流成像"],
        "alias_en_names": ["SMF", "SMF"],
        "ipns": [],
    }
    async with client:
        first = await client.put("/api/features/7/master-data", json=first_payload)
        second = await client.put("/api/features/7/master-data", json=second_payload)
        same_primary = await client.put("/api/features/7/master-data", json=second_payload)
    await engine.dispose()

    assert first.status_code == 200
    assert second.status_code == 200
    assert same_primary.status_code == 200
    body = same_primary.json()
    assert body["primary_cn_name"] == "超微血流成像"
    assert body["primary_en_name"] == "Super Micro Flow"
    assert "临时中文名" not in body["alias_cn_names"]
    assert "Temporary SMF" not in body["alias_en_names"]
    assert body["alias_cn_names"].count("超微细血流成像") == 1
    assert set(body["alias_en_names"]) >= {"SMF", "SMF(Super Micro Flow)"}
    assert body["ipns"] == []


@pytest.mark.asyncio
async def test_feature_management_creates_master_data_atomically(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)
    payload = {
        "group_id": 1,
        "sort_order": 8,
        "primary_cn_name": "新功能",
        "primary_en_name": "New Feature",
        "alias_cn_names": ["新功能曾用名"],
        "alias_en_names": ["Former New Feature"],
        "ipns": [{"ipn": "6000017", "relation_type": "primary"}],
    }

    async with client:
        rejected = await client.post(
            "/api/features/master-data",
            json={
                **payload,
                "primary_cn_name": "不应创建",
                "ipns": [{"ipn": "9999999", "relation_type": "primary"}],
            },
        )
        created = await client.post("/api/features/master-data", json=payload)
        searched = await client.get(
            "/api/knowledge/features", params={"q": "Former New Feature"}
        )
    await engine.dispose()

    assert rejected.status_code == 422
    assert created.status_code == 200
    body = created.json()
    assert body["group_id"] == 1
    assert body["primary_cn_name"] == "新功能"
    assert body["ipns"][0]["ipn"] == "6000017"
    assert searched.json()["total"] == 1
    assert searched.json()["items"][0]["id"] == body["id"]
