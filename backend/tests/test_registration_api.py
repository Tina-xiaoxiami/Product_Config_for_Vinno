import hashlib
from pathlib import Path
import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import models, registration
from app.database import get_db
from app.services.registration_import import import_domestic_registration_workbook
from app.services.registration_migration import migrate_registration_schema
from app.services.registration_packages import migrate_existing_registration_package
from test_registration_import import _create_database, _write_registration_workbook
from test_registration_packages import (
    _create_database as _create_package_database,
    _materialize_baseline_projection,
)


async def _client_for(database_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(registration.router, prefix="/api/registrations")
    app.include_router(models.router, prefix="/api/models")

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )
    return client, engine


def _activate_imported_package(database_path, workbook_path):
    workbook_path = Path(workbook_path)
    certificate_path = workbook_path.parent / "certificate.pdf"
    certificate_path.write_bytes(b"registration-certificate")
    workbook_sha = hashlib.sha256(workbook_path.read_bytes()).hexdigest()
    certificate_sha = hashlib.sha256(certificate_path.read_bytes()).hexdigest()
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        UPDATE knowledge_documents
        SET file_path = ?, sha256 = ? WHERE id = 1
        """,
        (str(workbook_path), workbook_sha),
    )
    connection.execute(
        """
        INSERT INTO knowledge_documents (
            id, document_type, title, file_name, file_path, sha256, version,
            market, country, product_series, mime_type, source_status
        ) VALUES (
            2, 'registration_certificate', 'V10注册证', 'certificate.pdf', ?, ?,
            '20260615', 'domestic', 'CN', 'V10', 'application/pdf', 'active'
        )
        """,
        (str(certificate_path), certificate_sha),
    )
    connection.commit()
    connection.close()
    return migrate_existing_registration_package(
        database_path,
        certificate_document_id=2,
        difference_document_id=1,
        import_batch_id=1,
        country_code="CN",
        unit_code="V10",
        display_name="V10系列国内注册",
        product_series="V10",
        registration_number="湘械注准20222062053",
        identity_source="registration_certificate",
        confirmed_by="baseline_migration",
    )


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
    _activate_imported_package(database_path, workbook_path)
    client, engine = await _client_for(database_path)

    async with client:
        models_response = await client.get(
            "/api/registrations/configured-models",
            params={"country_code": "CN"},
        )
        probes_response = await client.get(
            "/api/registrations/probes",
            params={"product_model_id": 2},
        )
        product_models_response = await client.get(
            "/api/models",
            params={"series_id": 1, "limit": 100},
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
        "registration_package_id": 1,
        "registration_number": "湘械注准20222062053",
        "registration_package_name": "V10系列国内注册",
    }

    assert probes_response.status_code == 200
    assert product_models_response.status_code == 200
    vinno10e = next(
        item for item in product_models_response.json()["items"] if item["id"] == 2
    )
    assert vinno10e["registration_packages"] == [
        {
            "registration_package_id": 1,
            "country_code": "CN",
            "registration_number": "湘械注准20222062053",
            "registration_package_name": "V10系列国内注册",
            "registration_model_id": 2,
            "registration_model_name": "VINNO 10E",
            "mapping_type": "direct",
        }
    ]
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
        "probe_master_id": 21,
        "probe_master_model": "F2-5C",
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
    _activate_imported_package(database_path, workbook_path)
    client, engine = await _client_for(database_path)

    async with client:
        filtered = await client.get(
            "/api/registrations/probes",
            params={
                "product_model_id": 5,
                "q": "1000744",
                "registration_status": "unregistered",
                "effective_status": "#",
            },
        )
        registration_models = await client.get(
            "/api/registrations/models",
            params={"country_code": "CN", "q": "VINNO 10"},
        )
        empty_filtered = await client.get(
            "/api/registrations/probes",
            params={"product_model_id": 5, "q": "不存在的探头"},
        )
        missing = await client.get(
            "/api/registrations/probes",
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
    assert empty_filtered.status_code == 200
    assert empty_filtered.json()["items"] == []
    assert empty_filtered.json()["source_document_id"] == 1
    assert missing.status_code == 404
    assert missing.json()["detail"] == "产品型号尚未关联对应注册证及注册基础型号"


@pytest.mark.asyncio
async def test_registration_master_data_lists_source_rows_by_registration_model(tmp_path):
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
    _activate_imported_package(database_path, workbook_path)
    client, engine = await _client_for(database_path)

    async with client:
        models = await client.get(
            "/api/registrations/models",
            params={"country_code": "CN", "q": "VINNO 10"},
        )
        model_id = models.json()["items"][0]["id"]
        probes = await client.get(f"/api/registrations/models/{model_id}/probes")
    await engine.dispose()

    assert probes.status_code == 200
    body = probes.json()
    assert body["registration_model_id"] == model_id
    assert body["country_code"] == "CN"
    assert body["model_name"] == "VINNO 10"
    assert body["total"] == 3
    first = body["items"][0]
    assert set(first) == {
        "matrix_id",
        "probe_id",
        "probe_model",
        "ipn",
        "registration_status",
        "config_item_id",
        "config_name",
        "probe_master_id",
        "probe_master_model",
        "source_document_id",
        "source_ref",
    }


@pytest.mark.asyncio
async def test_product_query_only_uses_registration_certificate_mapped_to_model(tmp_path):
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
    package = _activate_imported_package(database_path, workbook_path)
    client, engine = await _client_for(database_path)

    connection = sqlite3.connect(database_path)
    mapped_package_id = connection.execute(
        """
        SELECT registration_package_id
        FROM product_registration_model_links WHERE product_model_id = 2
        """
    ).fetchone()[0]
    assert mapped_package_id == package["package_id"]
    connection.execute(
        "UPDATE product_registration_model_links SET registration_package_id = NULL "
        "WHERE product_model_id = 2"
    )
    connection.commit()
    connection.close()

    async with client:
        unmapped = await client.get(
            "/api/registrations/probes",
            params={"product_model_id": 2},
        )
    await engine.dispose()

    assert unmapped.status_code == 404
    assert unmapped.json()["detail"] == "产品型号尚未关联对应注册证及注册基础型号"


def test_legacy_country_wide_import_is_blocked_after_certificate_is_active(tmp_path):
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
    _activate_imported_package(database_path, workbook_path)

    with pytest.raises(ValueError, match="已有生效注册证"):
        import_domestic_registration_workbook(
            database_path,
            workbook_path,
            source_document_id=1,
        )


@pytest.mark.asyncio
async def test_registration_api_lists_paired_material_history_and_both_originals(tmp_path):
    database_path = tmp_path / "packages.db"
    _create_package_database(database_path)
    _materialize_baseline_projection(database_path)
    recorded = migrate_existing_registration_package(
        database_path,
        country_code="CN",
        unit_code="V10",
        display_name="V10系列国内注册",
        product_series="V10",
        certificate_document_id=25,
        difference_document_id=24,
        import_batch_id=1,
        registration_number="湘械注准20222062053",
        identity_source="registration_certificate",
        confirmed_by="baseline_migration",
        change_note="现有数据基线",
    )
    client, engine = await _client_for(database_path)

    async with client:
        packages = await client.get(
            "/api/registrations/packages",
            params={"country_code": "CN"},
        )
        versions = await client.get(
            f"/api/registrations/packages/{recorded['package_id']}/versions"
        )
        detail = await client.get(
            f"/api/registrations/package-versions/{recorded['id']}"
        )
        missing = await client.get("/api/registrations/package-versions/999")
        certificate_preview = await client.get(
            f"/api/registrations/package-versions/{recorded['id']}/artifacts/certificate"
        )
    await engine.dispose()

    assert packages.status_code == 200
    assert packages.json()["total"] == 1
    package = packages.json()["items"][0]
    assert package["unit_code"] == "V10"
    assert package["registration_number"] == "湘械注准20222062053"
    assert package["current_version"]["version_no"] == 1
    assert package["current_version"]["status"] == "active"

    assert versions.status_code == 200
    assert versions.json()["package"]["display_name"] == "V10系列国内注册"
    assert len(versions.json()["items"]) == 1
    assert detail.status_code == 200
    body = detail.json()
    assert body["diff"]["kind"] == "baseline"
    assert body["change_note"] == "现有数据基线"
    assert body["certificate"] == {
        "document_id": 25,
        "title": "V10注册变更",
        "version": "20260615",
        "sha256": body["certificate"]["sha256"],
        "preview_url": (
            f"/api/registrations/package-versions/{recorded['id']}"
            "/artifacts/certificate"
        ),
    }
    assert body["difference"] == {
        "document_id": 24,
        "title": "V10差异表",
        "version": "20250729",
        "sha256": body["difference"]["sha256"],
        "preview_url": (
            f"/api/registrations/package-versions/{recorded['id']}"
            "/artifacts/difference"
        ),
    }
    assert certificate_preview.status_code == 200
    assert certificate_preview.content == b"certificate-v1"
    assert missing.status_code == 404
