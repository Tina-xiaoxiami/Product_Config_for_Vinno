import sqlite3

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.registration_migration import migrate_registration_schema
from app.services.registration_packages import (
    RegistrationPackageError,
    publish_registration_package_version,
    stage_registration_package_draft,
)
from app.services.registration_query import list_product_registration_probes
from test_registration_import import _create_database, _write_registration_workbook


def _stage(
    database_path,
    workbook_path,
    certificate_path,
    *,
    unit_code,
    registration_number,
    mappings,
):
    return stage_registration_package_draft(
        database_path,
        country_code="CN",
        unit_code=unit_code,
        display_name=f"{unit_code} 国内注册",
        product_series=unit_code,
        registration_number=registration_number,
        certificate_path=certificate_path,
        difference_path=workbook_path,
        certificate_version="20260902",
        difference_version="20260902",
        confirmed_by="product_owner",
        change_note="新增独立注册证",
        product_model_mappings=mappings,
    )


def test_pair_upload_stages_version_scoped_snapshot_and_mapping_review(tmp_path):
    database_path = tmp_path / "product_config.db"
    workbook_path = tmp_path / "registration.xlsx"
    certificate_path = tmp_path / "certificate.pdf"
    _create_database(database_path)
    _write_registration_workbook(workbook_path)
    certificate_path.write_bytes(b"%PDF-1.4 registration certificate")
    migrate_registration_schema(database_path)

    draft = _stage(
        database_path,
        workbook_path,
        certificate_path,
        unit_code="V10-A",
        registration_number="TEST-CN-001",
        mappings={1: "VINNO 10", 4: "VINNO 9"},
    )

    assert draft["status"] == "draft"
    assert draft["model_count"] == 3
    assert draft["probe_count"] == 3
    assert draft["matrix_count"] == 9
    assert draft["mapping_count"] == 2
    connection = sqlite3.connect(database_path)
    assert connection.execute(
        "SELECT COUNT(*) FROM registration_package_version_models WHERE version_id = ?",
        (draft["id"],),
    ).fetchone()[0] == 3
    assert connection.execute(
        "SELECT COUNT(*) FROM registration_package_version_probes WHERE version_id = ?",
        (draft["id"],),
    ).fetchone()[0] == 3
    assert connection.execute(
        "SELECT COUNT(*) FROM registration_package_version_model_probes "
        "WHERE version_id = ?",
        (draft["id"],),
    ).fetchone()[0] == 9
    assert connection.execute(
        "SELECT COUNT(*) FROM registration_package_version_product_mappings "
        "WHERE version_id = ? AND review_status = 'pending'",
        (draft["id"],),
    ).fetchone()[0] == 2
    assert connection.execute(
        "SELECT COUNT(*) FROM knowledge_documents "
        "WHERE document_type IN ('registration_certificate', 'registration_difference')"
    ).fetchone()[0] == 3
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_publish_keeps_registration_certificates_independent_and_scopes_links(tmp_path):
    database_path = tmp_path / "product_config.db"
    workbook_a = tmp_path / "registration-a.xlsx"
    workbook_b = tmp_path / "registration-b.xlsx"
    certificate_a = tmp_path / "certificate-a.pdf"
    certificate_b = tmp_path / "certificate-b.pdf"
    _create_database(database_path)
    _write_registration_workbook(workbook_a)
    _write_registration_workbook(workbook_b, vinno10_unsupported="F4-9E")
    certificate_a.write_bytes(b"%PDF-1.4 certificate A")
    certificate_b.write_bytes(b"%PDF-1.4 certificate B")
    migrate_registration_schema(database_path)

    draft_a = _stage(
        database_path,
        workbook_a,
        certificate_a,
        unit_code="V10-A",
        registration_number="TEST-CN-001",
        mappings={1: "VINNO 10"},
    )
    draft_b = _stage(
        database_path,
        workbook_b,
        certificate_b,
        unit_code="V10-B",
        registration_number="TEST-CN-002",
        mappings={2: "VINNO 10"},
    )
    published_a = publish_registration_package_version(
        database_path, version_id=draft_a["id"], confirmed_by="product_owner"
    )
    published_b = publish_registration_package_version(
        database_path, version_id=draft_b["id"], confirmed_by="product_owner"
    )

    assert published_a["status"] == "active"
    assert published_b["status"] == "active"
    connection = sqlite3.connect(database_path)
    assert connection.execute(
        "SELECT COUNT(*) FROM registration_package_versions WHERE status = 'active'"
    ).fetchone()[0] == 2
    links = connection.execute(
        """
        SELECT link.product_model_id, package.registration_number, model.model_name
        FROM product_registration_model_links link
        JOIN registration_packages package ON package.id = link.registration_package_id
        JOIN registration_models model ON model.id = link.registration_model_id
        ORDER BY link.product_model_id
        """
    ).fetchall()
    assert links == [
        (1, "TEST-CN-001", "VINNO 10"),
        (2, "TEST-CN-002", "VINNO 10"),
    ]
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


@pytest.mark.asyncio
async def test_product_query_reads_only_the_mapped_certificate_active_snapshot(tmp_path):
    database_path = tmp_path / "product_config.db"
    workbook_a = tmp_path / "registration-a.xlsx"
    workbook_b = tmp_path / "registration-b.xlsx"
    certificate_a = tmp_path / "certificate-a.pdf"
    certificate_b = tmp_path / "certificate-b.pdf"
    _create_database(database_path)
    _write_registration_workbook(workbook_a)
    _write_registration_workbook(workbook_b, vinno10_unsupported="F4-9E")
    certificate_a.write_bytes(b"%PDF-1.4 certificate A")
    certificate_b.write_bytes(b"%PDF-1.4 certificate B")
    migrate_registration_schema(database_path)
    draft_a = _stage(
        database_path,
        workbook_a,
        certificate_a,
        unit_code="V10-A",
        registration_number="TEST-CN-001",
        mappings={1: "VINNO 10"},
    )
    draft_b = _stage(
        database_path,
        workbook_b,
        certificate_b,
        unit_code="V10-B",
        registration_number="TEST-CN-002",
        mappings={2: "VINNO 10"},
    )
    publish_registration_package_version(
        database_path, version_id=draft_a["id"], confirmed_by="product_owner"
    )
    publish_registration_package_version(
        database_path, version_id=draft_b["id"], confirmed_by="product_owner"
    )

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await list_product_registration_probes(
            session,
            product_model_id=2,
            query=None,
            registration_status=None,
            effective_status=None,
            skip=0,
            limit=100,
        )
    await engine.dispose()

    assert result is not None
    assert result["registration_number"] == "TEST-CN-002"
    f4 = next(item for item in result["items"] if item["probe_model"] == "F4-9E")
    assert f4["registration_status"] == "unregistered"


def test_publish_rejects_product_model_already_bound_to_another_certificate(tmp_path):
    database_path = tmp_path / "product_config.db"
    workbook_path = tmp_path / "registration.xlsx"
    certificate_a = tmp_path / "certificate-a.pdf"
    certificate_b = tmp_path / "certificate-b.pdf"
    _create_database(database_path)
    _write_registration_workbook(workbook_path)
    certificate_a.write_bytes(b"%PDF-1.4 certificate A")
    certificate_b.write_bytes(b"%PDF-1.4 certificate B")
    migrate_registration_schema(database_path)
    draft_a = _stage(
        database_path,
        workbook_path,
        certificate_a,
        unit_code="V10-A",
        registration_number="TEST-CN-001",
        mappings={1: "VINNO 10"},
    )
    draft_b = _stage(
        database_path,
        workbook_path,
        certificate_b,
        unit_code="V10-B",
        registration_number="TEST-CN-002",
        mappings={1: "VINNO 10"},
    )
    publish_registration_package_version(
        database_path, version_id=draft_a["id"], confirmed_by="product_owner"
    )

    with pytest.raises(RegistrationPackageError, match="已绑定其他注册证"):
        publish_registration_package_version(
            database_path, version_id=draft_b["id"], confirmed_by="product_owner"
        )
