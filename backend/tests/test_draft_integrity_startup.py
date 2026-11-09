import sqlite3

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app import database
from app.services.draft_integrity import migrate_sqlite_draft_integrity


def _legacy_database(path, *, duplicate=False):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE draft_batches (
            id TEXT PRIMARY KEY,
            series_id INTEGER NOT NULL,
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
            (id, series_id, total_count, create_count, update_count, delete_count)
        VALUES ('batch-1', 1, 1, 0, 1, 0);
        INSERT INTO config_drafts VALUES
            (1, 1, 'batch-1', 'update', 100, 10, 'selection_config', 'old', 'new');
        """
    )
    if duplicate:
        connection.execute(
            """
            INSERT INTO config_drafts VALUES
                (2, 1, 'batch-1', 'update', 100, 10,
                 'selection_config', 'old', 'new')
            """
        )
        connection.execute(
            "UPDATE draft_batches SET total_count = 2, update_count = 2"
        )
    connection.commit()
    connection.close()


@pytest.mark.asyncio
async def test_init_db_is_idempotent_for_a_new_database(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'new.db'}")
    monkeypatch.setattr(database, "engine", engine)
    try:
        await database.init_db()
        await database.init_db()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_accepts_an_already_migrated_legacy_database(
    tmp_path, monkeypatch
):
    path = tmp_path / "migrated.db"
    _legacy_database(path)
    migrate_sqlite_draft_integrity(path, apply=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    monkeypatch.setattr(database, "engine", engine)
    try:
        await database.init_db()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_rejects_unmigrated_duplicates_with_repair_instructions(
    tmp_path, monkeypatch
):
    path = tmp_path / "duplicates.db"
    _legacy_database(path, duplicate=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    monkeypatch.setattr(database, "engine", engine)
    try:
        with pytest.raises(RuntimeError, match="migrate_draft_integrity.py"):
            await database.init_db()
    finally:
        await engine.dispose()
