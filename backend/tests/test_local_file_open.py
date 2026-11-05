import hashlib
from pathlib import Path
import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import knowledge, registration
from app.database import get_db
from app.services.registration_import import import_domestic_registration_workbook
from app.services.registration_migration import migrate_registration_schema
from test_knowledge_qa_api import _create_qa_database
from test_registration_api import _activate_imported_package
from test_registration_import import _create_database as _create_registration_database
from test_registration_import import _write_registration_workbook


def _client_for(database_path, *, client_address):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/api/knowledge")
    app.include_router(registration.router, prefix="/api/registrations")

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=client_address),
        base_url="http://test",
    ), engine


def _point_document_at(database_path, source_path):
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        UPDATE knowledge_documents
        SET file_path = ?, file_name = ?, sha256 = ?
        WHERE id = 1
        """,
        (
            str(source_path),
            source_path.name,
            hashlib.sha256(source_path.read_bytes()).hexdigest(),
        ),
    )
    connection.commit()
    connection.close()


@pytest.mark.asyncio
async def test_knowledge_document_opens_locally_only_for_local_requests(tmp_path, monkeypatch):
    """本机打开只认本机请求，且路径只能来自登记记录。"""

    source_path = tmp_path / "release.xlsx"
    source_path.write_bytes(b"controlled")
    database_path = tmp_path / "knowledge.db"
    _create_qa_database(database_path)
    _point_document_at(database_path, source_path)

    opened = []
    monkeypatch.setattr(
        "app.api.knowledge.open_local_path",
        lambda path, *, reveal=False: opened.append((str(path), reveal)),
    )

    local_client, local_engine = _client_for(database_path, client_address=("127.0.0.1", 4000))
    remote_client, remote_engine = _client_for(database_path, client_address=("10.1.2.3", 4000))
    async with local_client:
        opened_ok = await local_client.post(
            "/api/knowledge/documents/1/open-locally", json={"mode": "open"}
        )
        revealed = await local_client.post(
            "/api/knowledge/documents/1/open-locally", json={"mode": "reveal"}
        )
        unknown = await local_client.post(
            "/api/knowledge/documents/999/open-locally", json={}
        )
        source_path.unlink()
        stale = await local_client.post(
            "/api/knowledge/documents/1/open-locally", json={}
        )
    async with remote_client:
        blocked = await remote_client.post(
            "/api/knowledge/documents/1/open-locally", json={}
        )
    await local_engine.dispose()
    await remote_engine.dispose()

    assert opened_ok.status_code == 200, opened_ok.text
    assert opened_ok.json() == {
        "file_name": "release.xlsx",
        "mode": "open",
        "file_path": str(source_path),
    }
    assert revealed.status_code == 200
    assert [(Path(path).resolve(), reveal) for path, reveal in opened] == [
        (source_path.resolve(), False),
        (source_path.resolve(), True),
    ]
    assert unknown.status_code == 404
    assert stale.status_code == 410
    assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_registration_artifact_opens_locally(tmp_path, monkeypatch):
    """注册资料包原件同样支持在本机打开，路径取自登记的原件记录。"""

    database_path = tmp_path / "product_config.db"
    workbook_path = tmp_path / "registration.xlsx"
    _create_registration_database(database_path)
    _write_registration_workbook(workbook_path)
    migrate_registration_schema(database_path)
    import_domestic_registration_workbook(
        database_path,
        workbook_path,
        source_document_id=1,
    )
    package = _activate_imported_package(database_path, workbook_path)

    opened = []
    monkeypatch.setattr(
        "app.api.registration.open_local_path",
        lambda path, *, reveal=False: opened.append((str(path), reveal)),
    )

    client, engine = _client_for(database_path, client_address=("127.0.0.1", 4000))
    async with client:
        response = await client.post(
            f"/api/registrations/package-versions/{package['id']}"
            "/artifacts/difference/open-locally",
            json={"mode": "reveal"},
        )
        unknown_type = await client.post(
            f"/api/registrations/package-versions/{package['id']}"
            "/artifacts/unknown/open-locally",
            json={},
        )
        missing = await client.post(
            "/api/registrations/package-versions/999"
            "/artifacts/difference/open-locally",
            json={},
        )
    await engine.dispose()

    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "reveal"
    assert len(opened) == 1
    assert Path(opened[0][0]).resolve() == workbook_path.resolve()
    assert opened[0][1] is True
    assert unknown_type.status_code == 404
    assert missing.status_code == 404
