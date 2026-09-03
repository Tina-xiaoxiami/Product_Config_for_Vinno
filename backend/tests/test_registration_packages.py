import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from app.services.registration_migration import migrate_registration_schema
from app.services.registration_packages import (
    RegistrationPackageError,
    compute_registration_snapshot_diff,
    migrate_existing_registration_package,
    record_registration_package_version,
)


def _snapshot(
    *,
    unsupported=(),
    extra_model=False,
    probe_ipn="1000784",
    channel_count=128,
):
    models = [
        {
            "model_name": "VINNO 10",
            "channel_count": channel_count,
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
    sources = path.parent / "sources"
    sources.mkdir(exist_ok=True)
    source_payloads = {
        24: ("difference.xlsx", b"difference-v1"),
        25: ("certificate.pdf", b"certificate-v1"),
        26: ("difference-v2.xlsx", b"difference-v2"),
        27: ("certificate-v2.pdf", b"certificate-v2"),
        28: ("wrong.pdf", b"wrong"),
    }
    documents = {}
    for document_id, (name, payload) in source_payloads.items():
        source_path = sources / name
        source_path.write_bytes(payload)
        documents[document_id] = {
            "path": str(source_path),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

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
        CREATE TABLE product_models (id INTEGER PRIMARY KEY);
        """
    )
    connection.executemany(
        """
        INSERT INTO knowledge_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                24,
                "registration_difference",
                "V10差异表",
                "difference.xlsx",
                documents[24]["path"],
                "20250729",
                "domestic",
                "CN",
                "V10",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                documents[24]["sha256"],
                "active",
            ),
            (
                25,
                "registration_certificate",
                "V10注册变更",
                "certificate.pdf",
                documents[25]["path"],
                "20260615",
                "domestic",
                "CN",
                "V10",
                "application/pdf",
                documents[25]["sha256"],
                "active",
            ),
            (
                26,
                "registration_difference",
                "V10差异表第二版",
                "difference-v2.xlsx",
                documents[26]["path"],
                "20260801",
                "domestic",
                "CN",
                "V10",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                documents[26]["sha256"],
                "active",
            ),
            (
                27,
                "registration_certificate",
                "V10注册变更第二版",
                "certificate-v2.pdf",
                documents[27]["path"],
                "20260801",
                "domestic",
                "CN",
                "V10",
                "application/pdf",
                documents[27]["sha256"],
                "active",
            ),
            (
                28,
                "whitepaper",
                "错误资料",
                "wrong.pdf",
                documents[28]["path"],
                "1",
                "domestic",
                "CN",
                "V10",
                "application/pdf",
                documents[28]["sha256"],
                "active",
            ),
        ),
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
        ) VALUES (1, 'CN', 24, '20250729', ?,
                  'snapshot-v1', ?, 1, 2, 2, 'active')
        """,
        (documents[24]["sha256"], baseline),
    )
    connection.execute(
        """
        INSERT INTO registration_import_batches (
            id, country_code, source_document_id, source_version, source_sha256,
            snapshot_hash, snapshot_json, model_count, probe_count, matrix_count, status
        ) VALUES (2, 'CN', 26, '20260801', ?,
                  'snapshot-v2', ?, 2, 2, 4, 'superseded')
        """,
        (documents[26]["sha256"], changed),
    )
    connection.commit()
    connection.close()


def _materialize_baseline_projection(path, *, include_product_link=False):
    connection = sqlite3.connect(path)
    if include_product_link:
        connection.execute("INSERT INTO product_models (id) VALUES (1)")
    connection.executescript(
        """
        INSERT INTO registration_models (
            id, country_code, model_name, normalized_name, channel_count,
            import_batch_id, source_document_id, source_ref, source_status
        ) VALUES (1, 'CN', 'VINNO 10', 'vinno 10', 128, 1, 24, '0729!4', 'active');
        INSERT INTO registration_probes (
            id, country_code, probe_model, normalized_model, ipn,
            import_batch_id, source_document_id, source_ref, source_status
        ) VALUES
            (1, 'CN', 'F4-9E', 'f4-9e', '1000784', 1, 24, 'Sheet1!2', 'active'),
            (2, 'CN', 'G1-4P', 'g1-4p', '1000744', 1, 24, 'Sheet1!3', 'active');
        INSERT INTO registration_model_probes (
            id, country_code, registration_model_id, registration_probe_id,
            registration_status, import_batch_id, source_document_id, source_ref
        ) VALUES
            (1, 'CN', 1, 1, 'registered', 1, 24, '0729!4'),
            (2, 'CN', 1, 2, 'registered', 1, 24, '0729!4');
        """
    )
    if include_product_link:
        connection.execute(
            """
            INSERT INTO product_registration_model_links (
                id, product_model_id, registration_model_id, mapping_type,
                source, review_status
            ) VALUES (1, 1, 1, 'direct', 'registration_import', 'approved')
            """
        )
    connection.commit()
    connection.close()


def test_registration_package_schema_migration_is_idempotent(tmp_path):
    database_path = tmp_path / "packages.db"
    _create_database(database_path)

    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE UNIQUE INDEX legacy_unique_registration_batch
        ON registration_package_versions(import_batch_id)
        """
    )
    connection.commit()
    connection.close()

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
    unique_import_batch_indexes = []
    for index in connection.execute(
        "PRAGMA index_list(registration_package_versions)"
    ):
        if index[2]:
            columns = [
                row[2]
                for row in connection.execute(f"PRAGMA index_info('{index[1]}')")
            ]
            if columns == ["import_batch_id"]:
                unique_import_batch_indexes.append(index[1])
    assert unique_import_batch_indexes == []
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
            channel_count=256,
        ),
        ensure_ascii=False,
    )

    result = compute_registration_snapshot_diff(
        previous,
        current,
        previous_documents={"certificate_sha256": "cert-v1", "difference_sha256": "diff-v1"},
        current_documents={"certificate_sha256": "cert-v2", "difference_sha256": "diff-v1"},
    )

    assert result["kind"] == "changes"
    assert result["summary"] == {
        "models_added": 1,
        "models_removed": 0,
        "probes_added": 0,
        "probes_removed": 0,
        "probe_ipn_changed": 1,
        "model_channel_count_changed": 1,
        "registration_status_changed": 1,
    }
    assert result["models"]["added"] == ["VINNO 10E"]
    assert result["probes"]["ipn_changed"] == [
        {"probe": "F4-9E", "from": "1000784", "to": "1000784-NEW"}
    ]
    assert result["models"]["channel_count_changed"] == [
        {"model": "VINNO 10", "from": 128, "to": 256}
    ]
    assert result["documents"] == {
        "certificate_changed": True,
        "difference_changed": False,
    }
    assert result["registration_status_changes"] == [
        {
            "model": "VINNO 10",
            "probe": "F4-9E",
            "from": "registered",
            "to": "unregistered",
        }
    ]


def test_pair_version_record_creates_idempotent_draft_without_replacing_baseline(tmp_path):
    database_path = tmp_path / "packages.db"
    _create_database(database_path)
    _materialize_baseline_projection(database_path)

    baseline = migrate_existing_registration_package(
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
    repeated = record_registration_package_version(
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
        confirmed_by="product_owner",
    )
    certificate_only = record_registration_package_version(
        database_path,
        country_code="CN",
        unit_code="V10",
        display_name="V10系列国内注册",
        product_series="V10",
        certificate_document_id=27,
        difference_document_id=24,
        import_batch_id=1,
        registration_number="湘械注准20222062053",
        identity_source="registration_certificate",
        confirmed_by="product_owner",
        change_note="仅注册证换版，差异表沿用",
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
        registration_number="湘械注准20222062053",
        identity_source="registration_certificate",
        confirmed_by="product_owner",
        change_note="更新探头差异",
    )

    assert baseline["version_no"] == 1
    assert baseline["status"] == "active"
    assert baseline["diff"]["kind"] == "baseline"
    assert repeated["id"] == baseline["id"]
    assert repeated["reused"] is True
    assert certificate_only["version_no"] == 2
    assert certificate_only["status"] == "draft"
    assert certificate_only["diff"]["documents"] == {
        "certificate_changed": True,
        "difference_changed": False,
    }
    assert changed["version_no"] == 3
    assert changed["previous_version_id"] == baseline["id"]
    assert changed["status"] == "draft"
    assert changed["diff"]["summary"]["registration_status_changed"] == 1

    connection = sqlite3.connect(database_path)
    versions = connection.execute(
        """
        SELECT version_no, status FROM registration_package_versions
        ORDER BY version_no
        """
    ).fetchall()
    assert versions == [(1, "active"), (2, "draft"), (3, "draft")]
    assert connection.execute("SELECT COUNT(*) FROM registration_packages").fetchone()[0] == 1
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_registration_package_requires_registration_identity(tmp_path):
    database_path = tmp_path / "packages.db"
    _create_database(database_path)

    with pytest.raises(RegistrationPackageError, match="注册证号"):
        record_registration_package_version(
            database_path,
            country_code="CN",
            unit_code="V10",
            display_name="V10系列国内注册",
            product_series="V10",
            certificate_document_id=25,
            difference_document_id=24,
            import_batch_id=1,
        )


def test_baseline_migration_rejects_inactive_or_unmaterialized_batch(tmp_path):
    database_path = tmp_path / "packages.db"
    _create_database(database_path)

    with pytest.raises(RegistrationPackageError, match="不是当前生效批次"):
        migrate_existing_registration_package(
            database_path,
            country_code="CN",
            unit_code="V10",
            display_name="V10系列国内注册",
            product_series="V10",
            certificate_document_id=27,
            difference_document_id=26,
            import_batch_id=2,
            registration_number="湘械注准20222062053",
            identity_source="registration_certificate",
            confirmed_by="baseline_migration",
        )

    with pytest.raises(RegistrationPackageError, match="结构化投影不一致"):
        migrate_existing_registration_package(
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
        )


def test_version_artifacts_reference_the_registered_controlled_document(tmp_path):
    database_path = tmp_path / "packages.db"
    _create_database(database_path)
    _materialize_baseline_projection(database_path)
    connection = sqlite3.connect(database_path)
    source_path = connection.execute(
        "SELECT file_path FROM knowledge_documents WHERE id = 25"
    ).fetchone()[0]
    connection.close()

    result = migrate_existing_registration_package(
        database_path,
        certificate_document_id=25,
        difference_document_id=24,
        import_batch_id=1,
        country_code="CN",
        unit_code="V10",
        display_name="V10系列国内注册",
        product_series="V10",
        registration_number="湘械注准20222062053",
        identity_source="registration_certificate",
        confirmed_by="baseline_migration",
    )
    connection = sqlite3.connect(database_path)
    artifact_path = connection.execute(
        """
        SELECT certificate_artifact_path
        FROM registration_package_versions WHERE id = ?
        """,
        (result["id"],),
    ).fetchone()[0]
    connection.close()
    assert artifact_path == source_path
    assert Path(artifact_path).read_bytes() == b"certificate-v1"
    assert not (tmp_path / "registration_artifacts").exists()


def test_existing_pair_migration_preserves_projection_and_is_idempotent(tmp_path):
    database_path = tmp_path / "packages.db"
    _create_database(database_path)
    _materialize_baseline_projection(database_path, include_product_link=True)
    connection = sqlite3.connect(database_path)
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
        registration_number="湘械注准20222062053",
        identity_source="registration_certificate",
        confirmed_by="baseline_migration",
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
        registration_number="湘械注准20222062053",
        identity_source="registration_certificate",
        confirmed_by="baseline_migration",
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
    assert before == after == (1, 2, 2, 1)
    assert first["id"] == repeated["id"]
    assert repeated["reused"] is True
    assert connection.execute("SELECT COUNT(*) FROM registration_packages").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM registration_package_versions").fetchone()[0] == 1
    package = connection.execute(
        """
        SELECT registration_number, identity_source, confirmed_by
        FROM registration_packages
        """
    ).fetchone()
    assert package == (
        "湘械注准20222062053",
        "registration_certificate",
        "baseline_migration",
    )
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
