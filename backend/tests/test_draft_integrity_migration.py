import sqlite3

import pytest

from app.services.draft_integrity import (
    DraftIntegrityError,
    migrate_sqlite_draft_integrity,
)


def _legacy_database(path, *, conflict=False):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE draft_batches (
            id TEXT PRIMARY KEY,
            total_count INTEGER,
            create_count INTEGER,
            update_count INTEGER,
            delete_count INTEGER
        );
        CREATE TABLE config_drafts (
            id INTEGER PRIMARY KEY,
            series_id INTEGER NOT NULL,
            batch_id TEXT NOT NULL,
            change_type TEXT NOT NULL,
            item_id INTEGER,
            model_id INTEGER,
            field_name TEXT,
            old_value TEXT,
            new_value TEXT
        );
        INSERT INTO draft_batches
            (id, total_count, create_count, update_count, delete_count)
        VALUES ('batch-1', 3, 0, 3, 0);
        INSERT INTO config_drafts VALUES
            (1, 1, 'batch-1', 'update', 100, 10, 'selection_config', 'baseline', 'working'),
            (2, 1, 'batch-1', 'update', 100, 10, 'selection_config', 'baseline', 'working'),
            (3, 1, 'batch-1', 'update', 101, 10, 'selection_config', 'other', 'other-working');
        """
    )
    if conflict:
        connection.execute(
            "UPDATE config_drafts SET old_value = 'conflict' WHERE id = 2"
        )
    connection.commit()
    connection.close()


def _rows(path):
    connection = sqlite3.connect(path)
    try:
        drafts = connection.execute(
            "SELECT id, old_value, new_value FROM config_drafts ORDER BY id"
        ).fetchall()
        batch = connection.execute(
            "SELECT total_count, create_count, update_count, delete_count "
            "FROM draft_batches WHERE id = 'batch-1'"
        ).fetchone()
        indexes = connection.execute("PRAGMA index_list('config_drafts')").fetchall()
        return drafts, batch, indexes
    finally:
        connection.close()


def _add_invalid_drafts(path):
    connection = sqlite3.connect(path)
    connection.executemany(
        """
        INSERT INTO config_drafts
            (id, series_id, batch_id, change_type, item_id, model_id,
             field_name, old_value, new_value)
        VALUES (?, 1, 'batch-1', 'update', ?, ?, ?, 'old', 'new')
        """,
        [
            (4, None, 10, "selection_config"),
            (5, 102, None, "selection_config"),
            (6, 103, 10, ""),
        ],
    )
    connection.commit()
    connection.close()


def test_migration_is_dry_run_by_default_and_reports_exact_repair(tmp_path):
    database = tmp_path / "legacy.db"
    _legacy_database(database)

    report = migrate_sqlite_draft_integrity(database)

    drafts, batch, indexes = _rows(database)
    assert report.exact_groups[0].draft_ids == (1, 2)
    assert report.exact_groups[0].redundant_ids == (2,)
    assert report.conflict_groups == ()
    assert report.deleted_ids == ()
    assert report.batch_count_changes == {}
    assert [row[0] for row in drafts] == [1, 2, 3]
    assert batch == (3, 0, 3, 0)
    assert all(row[1] != "uq_config_draft_business_key" for row in indexes)


def test_apply_repairs_exact_duplicates_updates_counts_and_creates_index(tmp_path):
    database = tmp_path / "legacy.db"
    _legacy_database(database)

    report = migrate_sqlite_draft_integrity(database, apply=True)

    drafts, batch, indexes = _rows(database)
    assert report.deleted_ids == (2,)
    assert report.batch_count_changes == {
        "batch-1": {
            "before": {"total": 3, "create": 0, "update": 3, "delete": 0},
            "after": {"total": 2, "create": 0, "update": 2, "delete": 0},
        }
    }
    assert [row[0] for row in drafts] == [1, 3]
    assert batch == (2, 0, 2, 0)
    assert any(row[1] == "uq_config_draft_business_key" for row in indexes)


def test_apply_rejects_conflicts_and_rolls_back_all_changes(tmp_path):
    database = tmp_path / "legacy.db"
    _legacy_database(database, conflict=True)

    with pytest.raises(DraftIntegrityError, match="冲突"):
        migrate_sqlite_draft_integrity(database, apply=True)

    drafts, batch, indexes = _rows(database)
    assert [row[0] for row in drafts] == [1, 2, 3]
    assert batch == (3, 0, 3, 0)
    assert all(row[1] != "uq_config_draft_business_key" for row in indexes)


def test_dry_run_reports_invalid_draft_identities_without_writes(tmp_path):
    database = tmp_path / "legacy.db"
    _legacy_database(database)
    _add_invalid_drafts(database)

    report = migrate_sqlite_draft_integrity(database)

    drafts, batch, indexes = _rows(database)
    assert report.invalid_draft_ids == (4, 5, 6)
    assert report.invalid_reasons == {
        4: ("item_id 为 NULL",),
        5: ("model_id 为 NULL",),
        6: ("field_name 为空字符串",),
    }
    assert [row[0] for row in drafts] == [1, 2, 3, 4, 5, 6]
    assert batch == (3, 0, 3, 0)
    assert all(row[1] != "uq_config_draft_business_key" for row in indexes)


def test_apply_rejects_invalid_identities_before_exact_duplicate_repair(tmp_path):
    database = tmp_path / "legacy.db"
    _legacy_database(database)
    _add_invalid_drafts(database)

    with pytest.raises(
        DraftIntegrityError,
        match=r"无效草稿身份.*4.*item_id.*5.*model_id.*6.*field_name",
    ):
        migrate_sqlite_draft_integrity(database, apply=True)

    drafts, batch, indexes = _rows(database)
    assert [row[0] for row in drafts] == [1, 2, 3, 4, 5, 6]
    assert batch == (3, 0, 3, 0)
    assert all(row[1] != "uq_config_draft_business_key" for row in indexes)


def test_migration_requires_an_explicit_existing_database_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        migrate_sqlite_draft_integrity(tmp_path / "missing.db")
