import hashlib
from pathlib import Path
import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import registration
from app.database import get_db
from app.models.registration import (
    OverseasRegistrationRelation as OverseasRegistrationRelationModel,
    ProductRegistrationModelLink,
)
from app.services.overseas_registration_history import (
    list_overseas_registration_countries,
    list_overseas_registration_relations,
    migrate_overseas_registration_history_schema,
    publish_overseas_registration_snapshot,
    register_controlled_overseas_tracking_document,
    stage_overseas_registration_snapshot,
)
from app.services.overseas_registration_preview import (
    MasterDataMatch,
    OverseasMasterDataMatchPreview,
    OverseasRegistrationPreview,
    OverseasRegistrationRelation,
)


def _create_database(path: Path, controlled_file: Path) -> None:
    digest = hashlib.sha256(controlled_file.read_bytes()).hexdigest()
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE knowledge_documents (
            id INTEGER PRIMARY KEY,
            document_type TEXT NOT NULL DEFAULT 'registration_tracking',
            title TEXT NOT NULL DEFAULT '',
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            version TEXT,
            market TEXT NOT NULL DEFAULT 'overseas',
            country TEXT,
            product_series TEXT,
            mime_type TEXT,
            source_status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE product_series (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE product_models (
            id INTEGER PRIMARY KEY,
            series_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            config_group TEXT
        );
        CREATE TABLE probe_models (
            id INTEGER PRIMARY KEY,
            model_number TEXT NOT NULL
        );
        INSERT INTO product_series VALUES (1, 'R&V10 series-Oversea');
        INSERT INTO product_models VALUES (10, 1, 'VINNO 10', 'V10');
        INSERT INTO probe_models VALUES (20, 'S2-9C');
        """
    )
    connection.execute(
        """
        INSERT INTO knowledge_documents (
            id, title, file_path, file_name, sha256
        ) VALUES (1, 'controlled', ?, ?, ?)
        """,
        (str(controlled_file), controlled_file.name, digest),
    )
    connection.commit()
    connection.close()


def _preview(controlled_file: Path, *, probe_model: str = "S2-9C"):
    digest = hashlib.sha256(controlled_file.read_bytes()).hexdigest()
    return OverseasRegistrationPreview(
        source_file=str(controlled_file),
        source_sha256=digest,
        snapshot_date="2026-08-19",
        records=(),
        relations=(
            OverseasRegistrationRelation(
                jurisdiction_code="TH",
                model_name="V10",
                probe_model=probe_model,
                registration_status="completed",
                address_version="unspecified",
                source_ref="已完成注册!A2:C2",
            ),
            OverseasRegistrationRelation(
                jurisdiction_code="BR",
                model_name="A3",
                probe_model="A2-5C",
                registration_status="completed",
                address_version="new",
                source_ref="新地址注册!A3:C3",
            ),
        ),
        summary={"normalized_relations": 2, "review_rows": 0},
    )


def _matches():
    return OverseasMasterDataMatchPreview(
        models=(
            MasterDataMatch("V10", "alias_candidate", ("VINNO 10",), (10,)),
            MasterDataMatch("A3", "registration_only_candidate"),
        ),
        probes=(
            MasterDataMatch("S2-9C", "direct", ("S2-9C",), (20,)),
            MasterDataMatch("A2-5C", "registration_only_candidate"),
        ),
        summary={},
    )


def test_history_orm_does_not_take_columns_from_product_registration_links():
    product_link_columns = set(ProductRegistrationModelLink.__table__.columns.keys())
    history_columns = set(OverseasRegistrationRelationModel.__table__.columns.keys())

    assert {
        "product_model_id",
        "registration_model_id",
        "registration_package_id",
        "mapping_type",
        "source",
        "review_status",
    } <= product_link_columns
    assert "registration_model_id" not in history_columns
    assert "registration_package_id" not in history_columns


def test_registers_controlled_tracking_document_idempotently(tmp_path):
    controlled_root = tmp_path / "Obsidian" / "受控材料"
    controlled_file = controlled_root / "注册跟踪表" / "海外注册跟踪表-20260819.xls"
    controlled_file.parent.mkdir(parents=True)
    controlled_file.write_bytes(b"controlled overseas registration")
    database_path = tmp_path / "product_config.db"
    _create_database(database_path, controlled_file)
    connection = sqlite3.connect(database_path)
    connection.execute("DELETE FROM knowledge_documents")
    connection.commit()
    connection.close()

    first = register_controlled_overseas_tracking_document(
        database_path,
        controlled_file,
        controlled_root=controlled_root,
    )
    repeated = register_controlled_overseas_tracking_document(
        database_path,
        controlled_file,
        controlled_root=controlled_root,
    )

    assert first["document_id"] == repeated["document_id"]
    assert first["status"] == "inserted"
    assert repeated["status"] == "unchanged"
    connection = sqlite3.connect(database_path)
    row = connection.execute(
        """
        SELECT document_type, title, file_path, version, market, country,
               product_series, mime_type, source_status
        FROM knowledge_documents WHERE id = ?
        """,
        (first["document_id"],),
    ).fetchone()
    connection.close()
    assert row == (
        "registration_tracking",
        "海外注册跟踪表-20260819",
        str(controlled_file.resolve()),
        "2026-08-19",
        "overseas",
        None,
        None,
        "application/vnd.ms-excel",
        "active",
    )

    outside = tmp_path / "outside.xls"
    outside.write_bytes(b"outside")
    with pytest.raises(ValueError, match="受控材料目录"):
        register_controlled_overseas_tracking_document(
            database_path,
            outside,
            controlled_root=controlled_root,
        )


async def _client_for(database_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(registration.router, prefix="/api/registrations")

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    return (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ),
        engine,
    )


@pytest.mark.asyncio
async def test_history_layer_keeps_drafts_out_of_queries_and_master_data_unchanged(
    tmp_path,
):
    controlled_file = tmp_path / "controlled.xls"
    controlled_file.write_bytes(b"controlled overseas registration")
    database_path = tmp_path / "product_config.db"
    _create_database(database_path, controlled_file)

    migrate_overseas_registration_history_schema(database_path)
    migrate_overseas_registration_history_schema(database_path)
    staged = stage_overseas_registration_snapshot(
        database_path,
        preview=_preview(controlled_file),
        matches=_matches(),
        source_document_id=1,
    )

    assert staged == {
        "snapshot_id": 1,
        "status": "draft",
        "relation_count": 2,
        "country_count": 2,
        "model_count": 2,
        "probe_count": 2,
    }
    connection = sqlite3.connect(database_path)
    assert connection.execute("SELECT COUNT(*) FROM product_models").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM probe_models").fetchone()[0] == 1
    v10 = connection.execute(
        """
        SELECT model_name, model_match_status, product_model_id,
               probe_match_status, probe_model_id
        FROM overseas_registration_relations WHERE model_name = 'V10'
        """
    ).fetchone()
    assert v10 == ("V10", "alias_candidate", 10, "direct", 20)
    connection.close()

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        items, total = await list_overseas_registration_relations(
            session, country_code="TH", query=None, skip=0, limit=100
        )
    await engine.dispose()
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_publish_exposes_history_and_supersedes_previous_snapshot(tmp_path):
    controlled_file = tmp_path / "controlled.xls"
    controlled_file.write_bytes(b"first overseas registration")
    database_path = tmp_path / "product_config.db"
    _create_database(database_path, controlled_file)
    migrate_overseas_registration_history_schema(database_path)

    first = stage_overseas_registration_snapshot(
        database_path,
        preview=_preview(controlled_file),
        matches=_matches(),
        source_document_id=1,
    )
    publish_overseas_registration_snapshot(
        database_path, snapshot_id=first["snapshot_id"], confirmed_by="owner"
    )

    controlled_file.write_bytes(b"second overseas registration")
    digest = hashlib.sha256(controlled_file.read_bytes()).hexdigest()
    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE knowledge_documents SET sha256 = ? WHERE id = 1", (digest,)
    )
    connection.commit()
    connection.close()
    second = stage_overseas_registration_snapshot(
        database_path,
        preview=_preview(controlled_file, probe_model="S2-9CB"),
        matches=_matches(),
        source_document_id=1,
    )
    publish_overseas_registration_snapshot(
        database_path, snapshot_id=second["snapshot_id"], confirmed_by="owner"
    )

    connection = sqlite3.connect(database_path)
    assert connection.execute(
        "SELECT id, status FROM overseas_registration_snapshots ORDER BY id"
    ).fetchall() == [(1, "superseded"), (2, "active")]
    connection.close()

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        countries = await list_overseas_registration_countries(session)
        items, total = await list_overseas_registration_relations(
            session, country_code="TH", query="S2-9CB", skip=0, limit=100
        )
    await engine.dispose()

    assert countries == [
        {"country_code": "BR", "relation_count": 1},
        {"country_code": "TH", "relation_count": 1},
    ]
    assert total == 1
    assert items[0]["model_name"] == "V10"
    assert items[0]["probe_model"] == "S2-9CB"
    assert items[0]["data_scope"] == "registration_history"
    assert items[0]["visible_in_current_config"] is False
    assert items[0]["snapshot_date"] == "2026-08-19"


def test_stage_rejects_uncontrolled_or_changed_source(tmp_path):
    controlled_file = tmp_path / "controlled.xls"
    controlled_file.write_bytes(b"controlled overseas registration")
    database_path = tmp_path / "product_config.db"
    _create_database(database_path, controlled_file)
    migrate_overseas_registration_history_schema(database_path)

    controlled_file.write_bytes(b"changed after registration")
    with pytest.raises(ValueError, match="哈希"):
        stage_overseas_registration_snapshot(
            database_path,
            preview=_preview(controlled_file),
            matches=_matches(),
            source_document_id=1,
        )


@pytest.mark.asyncio
async def test_overseas_snapshot_api_stages_then_explicitly_publishes(
    tmp_path,
    monkeypatch,
):
    controlled_file = tmp_path / "controlled.xls"
    controlled_file.write_bytes(b"controlled overseas registration")
    database_path = tmp_path / "product_config.db"
    _create_database(database_path, controlled_file)
    migrate_overseas_registration_history_schema(database_path)
    monkeypatch.setattr(
        registration, "build_overseas_registration_preview", lambda _: _preview(controlled_file)
    )
    monkeypatch.setattr(
        registration,
        "match_overseas_registration_master_data",
        lambda *_: _matches(),
    )
    client, engine = await _client_for(database_path)

    async with client:
        staged = await client.post(
            "/api/registrations/overseas/snapshots/drafts",
            json={"source_document_id": 1},
        )
        hidden = await client.get("/api/registrations/overseas/relations")
        published = await client.post(
            "/api/registrations/overseas/snapshots/1/publish",
            json={"confirmed_by": "owner"},
        )
        visible = await client.get(
            "/api/registrations/overseas/relations",
            params={"country_code": "TH", "q": "V10"},
        )
    await engine.dispose()

    assert staged.status_code == 200
    assert staged.json()["status"] == "draft"
    assert hidden.json()["total"] == 0
    assert published.status_code == 200
    assert published.json() == {"snapshot_id": 1, "status": "active"}
    assert visible.status_code == 200
    assert visible.json()["total"] == 1
    assert visible.json()["items"][0]["visible_in_current_config"] is False
