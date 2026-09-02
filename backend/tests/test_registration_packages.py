import json
import sqlite3

import pytest

from app.services.registration_migration import migrate_registration_schema
from app.services.registration_packages import (
    RegistrationPackageError,
    compute_registration_snapshot_diff,
    migrate_existing_registration_package,
    record_registration_package_version,
)


def _snapshot(*, unsupported=(), extra_model=False, probe_ipn="1000784"):
    models = [
        {
            "model_name": "VINNO 10",
            "channel_count": 128,
            "unsupported_probes": list(unsupported),
        }
    ]
    if extra_model:
        models.append(
            {
                "model_name": "VINNO 10E",
                "channel_count": 128,
                "unsupported_probes": [],
            }
        )
    return {
        "models": models,
        "probes": [
            {"probe_model": "F4-9E", "ipn": probe_ipn},
            {"probe_model": "G1-4P", "ipn": "1000744"},
        ],
    }


def _create_database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE knowledge_documents (
            id INTEGER PRIMARY KEY,
            document_type TEXT NOT NULL,
            title TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            version TEXT,
            market TEXT NOT NULL,
            country TEXT,
            product_series TEXT,
            mime_type TEXT,
            sha256 TEXT,
            source_status TEXT NOT NULL DEFAULT 'active'
        );
        INSERT INTO knowledge_documents VALUES
            (24, 'registration_difference', 'V10差异表', 'difference.xlsx',
             '/tmp/difference.xlsx', '20250729', 'domestic', 'CN', 'V10',
             'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
             'difference-sha-v1', 'active'),
            (25, 'registration_certificate', 'V10注册变更', 'certificate.pdf',
             '/tmp/certificate.pdf', '20260615', 'domestic', 'CN', 'V10',
             'application/pdf', 'certificate-sha-v1', 'active'),
            (26, 'registration_difference', 'V10差异表第二版', 'difference-v2.xlsx',
             '/tmp/difference-v2.xlsx', '20260801', 'domestic', 'CN', 'V10',
             'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
             'difference-sha-v2', 'active'),
            (27, 'registration_certificate', 'V10注册变更第二版', 'certificate-v2.pdf',
             '/tmp/certificate-v2.pdf', '20260801', 'domestic', 'CN', 'V10',
             'application/pdf', 'certificate-sha-v2', 'active'),
            (28, 'whitepaper', '错误资料', 'wrong.pdf', '/tmp/wrong.pdf',
             '1', 'domestic', 'CN', 'V10', 'application/pdf', 'wrong-sha', 'active');

        CREATE TABLE product_models (id INTEGER PRIMARY KEY);
        """
    )
    connection.commit()
    connection.close()
    migrate_registration_schema(path)

    baseline = json.dumps(_snapshot(), ensure_ascii=False, sort_keys=True)
    changed = json.dumps(
        _snapshot(
            unsupported=("F4-9E",),
            extra_model=True,
            probe_ipn="1000784-NEW",
        ),
        ensure_ascii=False,
        sort_keys=True,
    )
    connection = sqlite3.connect(path)
    connection.execute(
        """
        INSERT INTO registration_import_batches (
            id, country_code, source_document_id, source_version, source_sha256,
            snapshot_hash, snapshot_json, model_count, probe_count, matrix_count, status
        ) VALUES (1, 'CN', 24, '20250729', 'difference-sha-v1',
                  'snapshot-v1', ?, 1, 2, 2, 'active')
        """,
        (baseline,),
    )
    connection.execute(
        """
        INSERT INTO registration_import_batches (
            id, country_code, source_document_id, source_version, source_sha256,
            snapshot_hash, snapshot_json, model_count, probe_count, matrix_count, status
        ) VALUES (2, 'CN', 26, '20260801', 'difference-sha-v2',
                  'snapshot-v2', ?, 2, 2, 4, 'superseded')
        """,
        (changed,),
    )
    connection.commit()
    connection.close()


def test_registration_package_schema_migration_is_idempotent(tmp_path):
    database_path = tmp_path / "packages.db"
    _create_database(database_path)

    migrate_registration_schema(database_path)

    connection = sqlite3.connect(database_path)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    indexes = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }
    assert "registration_packages" in tables
    assert "registration_package_versions" in tables
    assert "uq_registration_package_active" in indexes
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_registration_pair_validation_rejects_missing_or_wrong_material(tmp_path):
    database_path = tmp_path / "packages.db"
    _create_database(database_path)

    with pytest.raises(RegistrationPackageError, match="注册证资料类型不正确"):
        record_registration_package_version(
            database_path,
            country_code="CN",
            unit_code="V10",
            display_name="V10系列国内注册",
            product_series="V10",
            certificate_document_id=28,
            difference_document_id=24,
            import_batch_id=1,
        )

    with pytest.raises(RegistrationPackageError, match="导入批次未关联所选差异表"):
        record_registration_package_version(
            database_path,
            country_code="CN",
            unit_code="V10",
            display_name="V10系列国内注册",
            product_series="V10",
            certificate_document_id=25,
            difference_document_id=26,
            import_batch_id=1,
        )


def test_registration_snapshot_diff_reports_meaningful_changes():
    previous = json.dumps(_snapshot(), ensure_ascii=False)
    current = json.dumps(
        _snapshot(
            unsupported=("F4-9E",),
            extra_model=True,
            probe_ipn="1000784-NEW",
        ),
        ensure_ascii=False,
    )

    result = compute_registration_snapshot_diff(previous, current)

    assert result["kind"] == "changes"
    assert result["summary"] == {
        "models_added": 1,
        "models_removed": 0,
        "probes_added": 0,
        "probes_removed": 0,
        "probe_ipn_changed": 1,
        "registration_status_changed": 1,
    }
    assert result["models"]["added"] == ["VINNO 10E"]
    assert result["probes"]["ipn_changed"] == [
        {"probe": "F4-9E", "from": "1000784", "to": "1000784-NEW"}
    ]
    assert result["registration_status_changes"] == [
        {
            "model": "VINNO 10",
            "probe": "F4-9E",
            "from": "registered",
            "to": "unregistered",
        }
    ]


def test_pair_version_record_is_atomic_idempotent_and_keeps_history(tmp_path):
    database_path = tmp_path / "packages.db"
    _create_database(database_path)

    baseline = record_registration_package_version(
        database_path,
        country_code="CN",
        unit_code="V10",
        display_name="V10系列国内注册",
        product_series="V10",
        certificate_document_id=25,
        difference_document_id=24,
        import_batch_id=1,
        change_note="现有数据基线",
    )
    repeated = record_registration_package_version(
        database_path,
        country_code="CN",
        unit_code="V10",
        display_name="V10系列国内注册",
        product_series="V10",
        certificate_document_id=25,
        difference_document_id=24,
        import_batch_id=1,
    )
    changed = record_registration_package_version(
        database_path,
        country_code="CN",
        unit_code="V10",
        display_name="V10系列国内注册",
        product_series="V10",
        certificate_document_id=27,
        difference_document_id=26,
        import_batch_id=2,
        change_note="更新探头差异",
    )

    assert baseline["version_no"] == 1
    assert baseline["status"] == "active"
    assert baseline["diff"]["kind"] == "baseline"
    assert repeated["id"] == baseline["id"]
    assert repeated["reused"] is True
    assert changed["version_no"] == 2
    assert changed["previous_version_id"] == baseline["id"]
    assert changed["diff"]["summary"]["registration_status_changed"] == 1

    connection = sqlite3.connect(database_path)
    versions = connection.execute(
        """
        SELECT version_no, status FROM registration_package_versions
        ORDER BY version_no
        """
    ).fetchall()
    assert versions == [(1, "superseded"), (2, "active")]
    assert connection.execute("SELECT COUNT(*) FROM registration_packages").fetchone()[0] == 1
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_existing_pair_migration_preserves_projection_and_is_idempotent(tmp_path):
    database_path = tmp_path / "packages.db"
    _create_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        INSERT INTO product_models (id) VALUES (1);
        INSERT INTO registration_models (
            id, country_code, model_name, normalized_name, channel_count,
            import_batch_id, source_document_id, source_ref, source_status
        ) VALUES (1, 'CN', 'VINNO 10', 'vinno10', 128, 1, 24, '0729!4', 'active');
        INSERT INTO registration_probes (
            id, country_code, probe_model, normalized_model, ipn,
            import_batch_id, source_document_id, source_ref, source_status
        ) VALUES (1, 'CN', 'F4-9E', 'f4-9e', '1000784', 1, 24, 'Sheet1!2', 'active');
        INSERT INTO registration_model_probes (
            id, country_code, registration_model_id, registration_probe_id,
            registration_status, import_batch_id, source_document_id, source_ref
        ) VALUES (1, 'CN', 1, 1, 'registered', 1, 24, '0729!4');
        INSERT INTO product_registration_model_links (
            id, product_model_id, registration_model_id, mapping_type,
            source, review_status
        ) VALUES (1, 1, 1, 'direct', 'registration_import', 'approved');
        """
    )
    before = tuple(
        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "registration_models",
            "registration_probes",
            "registration_model_probes",
            "product_registration_model_links",
        )
    )
    connection.commit()
    connection.close()

    first = migrate_existing_registration_package(
        database_path,
        certificate_document_id=25,
        difference_document_id=24,
        import_batch_id=1,
        country_code="CN",
        unit_code="V10",
        display_name="V10系列国内注册",
        product_series="V10",
    )
    repeated = migrate_existing_registration_package(
        database_path,
        certificate_document_id=25,
        difference_document_id=24,
        import_batch_id=1,
        country_code="CN",
        unit_code="V10",
        display_name="V10系列国内注册",
        product_series="V10",
    )

    connection = sqlite3.connect(database_path)
    after = tuple(
        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "registration_models",
            "registration_probes",
            "registration_model_probes",
            "product_registration_model_links",
        )
    )
    assert before == after == (1, 1, 1, 1)
    assert first["id"] == repeated["id"]
    assert repeated["reused"] is True
    assert connection.execute("SELECT COUNT(*) FROM registration_packages").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM registration_package_versions").fetchone()[0] == 1
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
