import sqlite3

import pytest

from app.services.feature_identity import IdentityValidationError
from app.services.feature_identity_migration import migrate_feature_identity_database


def _create_legacy_database(path):
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
            name TEXT NOT NULL
        );
        CREATE TABLE features (
            id INTEGER PRIMARY KEY,
            group_id INTEGER NOT NULL REFERENCES feature_groups(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            ipn TEXT,
            sort_order INTEGER
        );
        CREATE TABLE product_probe_configs (
            id INTEGER PRIMARY KEY,
            feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE
        );
        CREATE TABLE template_features (
            id INTEGER PRIMARY KEY,
            feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE
        );
        CREATE TABLE probe_config_versions (
            id INTEGER PRIMARY KEY,
            snapshot_data TEXT NOT NULL
        );

        INSERT INTO config_items VALUES
            (1, '6000017', 'TView', '组织多普勒成像', 'Tissue Doppler Imaging'),
            (59, '6000034', 'Needle enhancement【启用】', '穿刺增强', 'Needle enhancement');
        INSERT INTO feature_groups VALUES (1, '基础功能'), (2, '穿刺');
        INSERT INTO features VALUES
            (1, 1, 'TView', '', 1),
            (4, 2, '穿刺引导&穿刺增强', '', 2);
        INSERT INTO product_probe_configs VALUES (10, 1), (11, 4);
        INSERT INTO template_features VALUES (20, 1), (21, 4);
        INSERT INTO probe_config_versions VALUES (30, '{"features":[1,4]}');
        """
    )
    connection.commit()
    connection.close()


def _table_count(connection, table):
    return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_migration_backfills_exact_ipn_identity_and_keeps_unmatched_feature_pending(
    tmp_path,
):
    database_path = tmp_path / "product_config_copy.db"
    _create_legacy_database(database_path)

    report = migrate_feature_identity_database(database_path)

    assert report.feature_count_before == report.feature_count_after == 2
    assert report.auto_matched_count == 1
    assert report.pending_count == 1
    assert report.pending_names == ("穿刺引导&穿刺增强",)

    connection = sqlite3.connect(database_path)
    matched = connection.execute(
        """
        SELECT id, config_item_id, ipn, primary_cn_name, primary_en_name,
               identity_status
        FROM features WHERE id = 1
        """
    ).fetchone()
    assert matched == (
        1,
        1,
        "6000017",
        "组织多普勒成像",
        "Tissue Doppler Imaging",
        "auto_matched",
    )
    pending = connection.execute(
        """
        SELECT config_item_id, ipn, primary_cn_name, primary_en_name,
               identity_status
        FROM features WHERE id = 4
        """
    ).fetchone()
    assert pending == (None, "", None, None, "pending")

    names = connection.execute(
        """
        SELECT language, name, name_type, source
        FROM feature_names WHERE feature_id = 1
        ORDER BY id
        """
    ).fetchall()
    assert names == [
        ("cn", "组织多普勒成像", "primary", "config_items.zh_desc"),
        ("en", "Tissue Doppler Imaging", "primary", "config_items.en_desc"),
        ("en", "TView", "alias", "config_items.rd_name"),
    ]
    connection.close()


def test_migration_preserves_feature_ids_foreign_keys_and_version_rows(tmp_path):
    database_path = tmp_path / "product_config_copy.db"
    _create_legacy_database(database_path)

    connection = sqlite3.connect(database_path)
    baseline = {
        table: _table_count(connection, table)
        for table in (
            "features",
            "product_probe_configs",
            "template_features",
            "probe_config_versions",
        )
    }
    feature_links = connection.execute(
        "SELECT id, feature_id FROM product_probe_configs ORDER BY id"
    ).fetchall()
    connection.close()

    report = migrate_feature_identity_database(database_path)

    connection = sqlite3.connect(database_path)
    assert {
        table: _table_count(connection, table) for table in baseline
    } == baseline
    assert connection.execute(
        "SELECT id, feature_id FROM product_probe_configs ORDER BY id"
    ).fetchall() == feature_links
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert report.foreign_key_violation_count == 0
    connection.close()


def test_migration_is_idempotent_and_normalized_ipn_is_unique(tmp_path):
    database_path = tmp_path / "product_config_copy.db"
    _create_legacy_database(database_path)

    first_report = migrate_feature_identity_database(database_path)
    second_report = migrate_feature_identity_database(database_path)

    assert second_report == first_report
    connection = sqlite3.connect(database_path)
    assert _table_count(connection, "feature_names") == 3
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            UPDATE features
            SET ipn = ' 6000017 ', identity_status = 'reviewed'
            WHERE id = 4
            """
        )
    connection.close()


def test_invalid_config_item_ipns_roll_back_the_schema_change(tmp_path):
    database_path = tmp_path / "product_config_copy.db"
    _create_legacy_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        INSERT INTO config_items
            (id, ipn, rd_name, zh_desc, en_desc)
        VALUES (60, ' 6000034 ', 'Duplicate', '重复功能', 'Duplicate')
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(IdentityValidationError, match="重复IPN"):
        migrate_feature_identity_database(database_path)

    connection = sqlite3.connect(database_path)
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(features)").fetchall()
    }
    assert "config_item_id" not in columns
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE name = 'feature_names'"
    ).fetchone() is None
    connection.close()
