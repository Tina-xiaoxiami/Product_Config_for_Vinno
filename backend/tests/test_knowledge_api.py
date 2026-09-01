import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import knowledge
from app.database import get_db
from app.services.feature_identity_migration import migrate_feature_identity_database


def _create_knowledge_database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE config_items (
            id INTEGER PRIMARY KEY,
            ipn TEXT,
            rd_name TEXT,
            zh_desc TEXT,
            en_desc TEXT
        );
        CREATE TABLE feature_groups (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            sort_order INTEGER
        );
        CREATE TABLE features (
            id INTEGER PRIMARY KEY,
            group_id INTEGER NOT NULL REFERENCES feature_groups(id),
            name TEXT NOT NULL,
            ipn TEXT,
            sort_order INTEGER
        );
        INSERT INTO config_items VALUES
            (1, '6000017', 'TView', '组织多普勒成像', 'Tissue Doppler Imaging'),
            (84, '6000273', 'SupportHSF【启用】', '超微细血流成像', 'SMF(Super Micro Flow)'),
            (96, '6000294', 'SupportVFetus【启用】', 'OB测量包', 'VMind OB(standard)'),
            (217, '6000415', 'SupportVFetus【启用】', 'VMind+：OB产筛精灵', 'VMind+：OB');
        INSERT INTO feature_groups VALUES
            (1, '基础功能', 1), (2, '智能血流', 2), (3, '产科', 3);
        INSERT INTO features VALUES
            (1, 1, 'TView', '', 1),
            (7, 2, 'SMF', '', 2),
            (31, 3, 'Vmind OB', '', 3);
        """
    )
    connection.commit()
    connection.close()
    migrate_feature_identity_database(
        path,
        confirmed_ipn_by_legacy_feature_id={7: "6000273"},
        confirmed_relations_by_legacy_feature_id={
            31: ("version_variant", ("6000294", "6000415"))
        },
    )


async def _client_for(database_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
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
async def test_feature_search_matches_alias_and_returns_primary_identity(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        response = await client.get("/api/knowledge/features", params={"q": "SupportHSF"})
    await engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == 7
    assert item["legacy_name"] == "SMF"
    assert item["group_name"] == "智能血流"
    assert item["identity_status"] == "confirmed"
    assert item["primary_cn_name"] == "超微细血流成像"
    assert item["primary_en_name"] == "SMF(Super Micro Flow)"
    assert item["ipns"] == [
        {
            "ipn": "6000273",
            "relation_type": "primary",
            "zh_desc": "超微细血流成像",
            "en_desc": "SMF(Super Micro Flow)",
        }
    ]
    assert {name["name"] for name in item["names"]} >= {
        "SMF",
        "SupportHSF【启用】",
        "超微细血流成像",
    }


@pytest.mark.asyncio
async def test_feature_search_keeps_version_ipns_and_supports_status_filter(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        response = await client.get(
            "/api/knowledge/features",
            params={"q": "VMind+", "identity_status": "related"},
        )
        stats_response = await client.get("/api/knowledge/stats")
    await engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["legacy_name"] == "Vmind OB"
    assert [(entry["ipn"], entry["relation_type"]) for entry in item["ipns"]] == [
        ("6000294", "version_variant"),
        ("6000415", "version_variant"),
    ]
    assert stats_response.json() == {
        "total_features": 3,
        "auto_matched": 1,
        "confirmed": 1,
        "related": 1,
        "pending": 0,
    }


@pytest.mark.asyncio
async def test_feature_detail_and_pagination_have_stable_contract(tmp_path):
    database_path = tmp_path / "knowledge.db"
    _create_knowledge_database(database_path)
    client, engine = await _client_for(database_path)

    async with client:
        first_page = await client.get(
            "/api/knowledge/features", params={"skip": 0, "limit": 2}
        )
        detail = await client.get("/api/knowledge/features/1")
        missing = await client.get("/api/knowledge/features/999")
    await engine.dispose()

    assert first_page.status_code == 200
    assert first_page.json()["total"] == 3
    assert len(first_page.json()["items"]) == 2
    assert detail.status_code == 200
    assert detail.json()["legacy_name"] == "TView"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "功能不存在"
