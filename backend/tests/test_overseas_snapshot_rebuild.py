"""基于现有快照重建草稿：给已发布数据留一条不丢历史、也不丢查询的修订路。

已发布快照是冻结的：关系查询只认 active，人工也不能再改审核结论。
原来同一份原件再次导入只会复用那条快照（source_sha256 唯一），
于是「原件没变、但代码或名称映射变了」时没有任何补救手段。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

import pytest

from app.services.overseas_registration_history import (
    migrate_overseas_registration_history_schema,
    publish_overseas_registration_snapshot,
    rebuild_overseas_registration_draft,
    stage_overseas_registration_snapshot,
)
from app.services.overseas_registration_preview import (
    MasterDataMatch,
    OverseasMasterDataMatchPreview,
    OverseasRegistrationPreview,
    OverseasRegistrationRecord,
    OverseasRegistrationRelation,
)

_OLD_SNAPSHOT_DDL = """
CREATE TABLE overseas_registration_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_document_id INTEGER NOT NULL REFERENCES knowledge_documents(id),
    source_file_name TEXT NOT NULL,
    source_sha256 TEXT NOT NULL UNIQUE,
    snapshot_date TEXT,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'superseded')),
    relation_count INTEGER NOT NULL,
    country_count INTEGER NOT NULL,
    model_count INTEGER NOT NULL,
    probe_count INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TEXT,
    confirmed_by TEXT
);
CREATE TABLE overseas_registration_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL
        REFERENCES overseas_registration_snapshots(id) ON DELETE CASCADE,
    country_code TEXT NOT NULL,
    model_name TEXT NOT NULL,
    normalized_model TEXT NOT NULL,
    probe_model TEXT NOT NULL,
    normalized_probe TEXT NOT NULL,
    registration_status TEXT NOT NULL,
    address_version TEXT NOT NULL,
    source_ref TEXT,
    model_match_status TEXT NOT NULL,
    product_model_id INTEGER,
    probe_match_status TEXT NOT NULL,
    probe_model_id INTEGER,
    UNIQUE (
        snapshot_id, country_code, normalized_model,
        normalized_probe, registration_status, address_version
    )
);
CREATE UNIQUE INDEX uq_overseas_registration_active
ON overseas_registration_snapshots(status) WHERE status = 'active';
"""


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
        CREATE TABLE product_series (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE product_models (
            id INTEGER PRIMARY KEY,
            series_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            config_group TEXT
        );
        CREATE TABLE probe_models (id INTEGER PRIMARY KEY, model_number TEXT NOT NULL);
        INSERT INTO product_series VALUES (1, 'R&V10 series-Oversea');
        INSERT INTO product_models VALUES (10, 1, 'VINNO 10', 'V10');
        INSERT INTO probe_models VALUES (20, 'S2-9C');
        """
    )
    connection.execute(
        """
        INSERT INTO knowledge_documents (id, title, file_path, file_name, sha256)
        VALUES (1, 'controlled', ?, ?, ?)
        """,
        (str(controlled_file), controlled_file.name, digest),
    )
    connection.commit()
    connection.close()


def _record(probe_model: str = "S2-9C") -> OverseasRegistrationRecord:
    return OverseasRegistrationRecord(
        sheet_name="已完成注册",
        source_row=2,
        source_ref="已完成注册!A2:C2",
        jurisdiction_raw="泰国",
        jurisdiction_name="泰国",
        jurisdiction_code="TH",
        authority=None,
        registration_status="completed",
        address_version="unspecified",
        model_raw="V10",
        probe_raw=probe_model,
        models=("V10",),
        probes=(probe_model,),
        ready_for_import=True,
        issue_codes=(),
    )


def _preview(controlled_file: Path, *, probe_model: str = "S2-9C"):
    digest = hashlib.sha256(controlled_file.read_bytes()).hexdigest()
    return OverseasRegistrationPreview(
        source_file=str(controlled_file),
        source_sha256=digest,
        snapshot_date="2026-08-19",
        records=(_record(probe_model),),
        relations=(
            OverseasRegistrationRelation(
                jurisdiction_code="TH",
                model_name="V10",
                probe_model=probe_model,
                registration_status="completed",
                address_version="unspecified",
                source_ref="已完成注册!A2:C2",
            ),
        ),
        summary={"normalized_relations": 1, "review_rows": 0},
    )


def _matches():
    return OverseasMasterDataMatchPreview(
        models=(MasterDataMatch("V10", "alias_candidate", ("VINNO 10",), (10,)),),
        probes=(MasterDataMatch("S2-9C", "direct", ("S2-9C",), (20,)),),
        summary={},
    )


def _setup(tmp_path: Path):
    controlled_root = tmp_path / "Obsidian" / "受控材料"
    controlled_file = controlled_root / "注册跟踪表" / "海外注册跟踪表-20260819.xls"
    controlled_file.parent.mkdir(parents=True)
    controlled_file.write_bytes(b"controlled overseas registration")
    database_path = tmp_path / "product_config.db"
    _create_database(database_path, controlled_file)
    return database_path, controlled_file


def _snapshot_row(database_path: Path, snapshot_id: int):
    connection = sqlite3.connect(database_path)
    try:
        return connection.execute(
            """
            SELECT status, revision, derived_from_snapshot_id, source_sha256,
                   relation_count, source_document_id
            FROM overseas_registration_snapshots WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone()
    finally:
        connection.close()


def _probes(database_path: Path, snapshot_id: int) -> set[str]:
    connection = sqlite3.connect(database_path)
    try:
        return {
            row[0]
            for row in connection.execute(
                "SELECT probe_model FROM overseas_registration_relations "
                "WHERE snapshot_id = ?",
                (snapshot_id,),
            )
        }
    finally:
        connection.close()


def test_rebuild_from_published_snapshot_creates_a_new_draft(tmp_path):
    database_path, controlled_file = _setup(tmp_path)
    staged = stage_overseas_registration_snapshot(
        database_path,
        preview=_preview(controlled_file),
        matches=_matches(),
        source_document_id=1,
    )
    publish_overseas_registration_snapshot(
        database_path, snapshot_id=staged["snapshot_id"], confirmed_by="本机操作"
    )

    rebuilt = rebuild_overseas_registration_draft(
        database_path,
        snapshot_id=staged["snapshot_id"],
        preview=_preview(controlled_file),
        matches=_matches(),
    )

    assert rebuilt["snapshot_id"] != staged["snapshot_id"]
    assert rebuilt["status"] == "draft"
    assert rebuilt["relation_count"] == 1
    row = _snapshot_row(database_path, rebuilt["snapshot_id"])
    assert row[0] == "draft"
    assert row[1] == 1
    assert row[2] == staged["snapshot_id"]
    assert row[3] == _snapshot_row(database_path, staged["snapshot_id"])[3]
    # 旧快照继续可查询，直到新草稿发布。
    assert _snapshot_row(database_path, staged["snapshot_id"])[0] == "active"


def test_rebuild_uses_the_regenerated_relations_not_the_stored_ones(tmp_path):
    database_path, controlled_file = _setup(tmp_path)
    staged = stage_overseas_registration_snapshot(
        database_path,
        preview=_preview(controlled_file, probe_model="S2-9C"),
        matches=_matches(),
        source_document_id=1,
    )
    publish_overseas_registration_snapshot(
        database_path, snapshot_id=staged["snapshot_id"], confirmed_by="本机操作"
    )

    rebuilt = rebuild_overseas_registration_draft(
        database_path,
        snapshot_id=staged["snapshot_id"],
        preview=_preview(controlled_file, probe_model="S3-9C"),
        matches=_matches(),
    )

    assert _probes(database_path, rebuilt["snapshot_id"]) == {"S3-9C"}
    assert _probes(database_path, staged["snapshot_id"]) == {"S2-9C"}


def test_rebuild_requires_a_published_snapshot(tmp_path):
    database_path, controlled_file = _setup(tmp_path)
    staged = stage_overseas_registration_snapshot(
        database_path,
        preview=_preview(controlled_file),
        matches=_matches(),
        source_document_id=1,
    )

    with pytest.raises(ValueError) as error:
        rebuild_overseas_registration_draft(
            database_path,
            snapshot_id=staged["snapshot_id"],
            preview=_preview(controlled_file),
            matches=_matches(),
        )

    assert "已发布" in str(error.value)


def test_rebuild_rejects_a_changed_source_file(tmp_path):
    database_path, controlled_file = _setup(tmp_path)
    staged = stage_overseas_registration_snapshot(
        database_path,
        preview=_preview(controlled_file),
        matches=_matches(),
        source_document_id=1,
    )
    publish_overseas_registration_snapshot(
        database_path, snapshot_id=staged["snapshot_id"], confirmed_by="本机操作"
    )
    controlled_file.write_bytes(b"changed overseas registration")

    with pytest.raises(ValueError):
        rebuild_overseas_registration_draft(
            database_path,
            snapshot_id=staged["snapshot_id"],
            preview=_preview(controlled_file),
            matches=_matches(),
        )


def test_publishing_the_rebuilt_draft_supersedes_the_previous_one(tmp_path):
    database_path, controlled_file = _setup(tmp_path)
    staged = stage_overseas_registration_snapshot(
        database_path,
        preview=_preview(controlled_file, probe_model="S2-9C"),
        matches=_matches(),
        source_document_id=1,
    )
    publish_overseas_registration_snapshot(
        database_path, snapshot_id=staged["snapshot_id"], confirmed_by="本机操作"
    )
    rebuilt = rebuild_overseas_registration_draft(
        database_path,
        snapshot_id=staged["snapshot_id"],
        preview=_preview(controlled_file, probe_model="S3-9C"),
        matches=_matches(),
    )

    publish_overseas_registration_snapshot(
        database_path, snapshot_id=rebuilt["snapshot_id"], confirmed_by="本机操作"
    )

    assert _snapshot_row(database_path, staged["snapshot_id"])[0] == "superseded"
    assert _snapshot_row(database_path, rebuilt["snapshot_id"])[0] == "active"


def test_review_items_are_staged_per_snapshot(tmp_path):
    database_path, controlled_file = _setup(tmp_path)
    staged = stage_overseas_registration_snapshot(
        database_path,
        preview=_preview(controlled_file),
        matches=_matches(),
        source_document_id=1,
    )
    publish_overseas_registration_snapshot(
        database_path, snapshot_id=staged["snapshot_id"], confirmed_by="本机操作"
    )
    rebuilt = rebuild_overseas_registration_draft(
        database_path,
        snapshot_id=staged["snapshot_id"],
        preview=_preview(controlled_file),
        matches=_matches(),
    )

    connection = sqlite3.connect(database_path)
    try:
        batches = dict(
            connection.execute(
                "SELECT batch_id, COUNT(*) FROM data_review_items "
                "WHERE data_type = 'overseas_registration' GROUP BY batch_id"
            )
        )
    finally:
        connection.close()

    assert batches[staged["snapshot_id"]] == 1
    assert batches[rebuilt["snapshot_id"]] == 1


def test_migration_upgrades_an_existing_snapshot_table(tmp_path):
    database_path, controlled_file = _setup(tmp_path)
    connection = sqlite3.connect(database_path)
    connection.executescript(_OLD_SNAPSHOT_DDL)
    connection.execute(
        """
        INSERT INTO overseas_registration_snapshots (
            id, source_document_id, source_file_name, source_sha256,
            snapshot_date, status, relation_count, country_count,
            model_count, probe_count, confirmed_by
        ) VALUES (1, 1, '海外注册跟踪表-20260819.xls', ?, '2026-08-19',
                  'active', 1, 1, 1, 1, '本机操作')
        """,
        (hashlib.sha256(controlled_file.read_bytes()).hexdigest(),),
    )
    connection.execute(
        """
        INSERT INTO overseas_registration_relations (
            snapshot_id, country_code, model_name, normalized_model,
            probe_model, normalized_probe, registration_status,
            address_version, source_ref, model_match_status,
            probe_match_status
        ) VALUES (1, 'TH', 'V10', 'v10', 'S2-9C', 's2-9c', 'completed',
                  'unspecified', '已完成注册!A2:C2', 'direct', 'direct')
        """
    )
    connection.commit()
    connection.close()

    migrate_overseas_registration_history_schema(database_path)

    columns = {
        row[1]
        for row in sqlite3.connect(database_path).execute(
            "PRAGMA table_info(overseas_registration_snapshots)"
        )
    }
    assert {"revision", "derived_from_snapshot_id"} <= columns
    row = _snapshot_row(database_path, 1)
    assert row[0] == "active" and row[1] == 0 and row[2] is None
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM overseas_registration_relations WHERE snapshot_id = 1"
        ).fetchone()[0] == 1
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()
    assert violations == []


def test_migration_allows_one_revision_per_source_and_no_more(tmp_path):
    database_path, controlled_file = _setup(tmp_path)
    migrate_overseas_registration_history_schema(database_path)
    digest = hashlib.sha256(controlled_file.read_bytes()).hexdigest()

    connection = sqlite3.connect(database_path)
    try:
        for revision in (0, 1):
            connection.execute(
                """
                INSERT INTO overseas_registration_snapshots (
                    source_document_id, source_file_name, source_sha256,
                    snapshot_date, status, relation_count, country_count,
                    model_count, probe_count, revision
                ) VALUES (1, 'f.xls', ?, '2026-08-19', 'draft', 1, 1, 1, 1, ?)
                """,
                (digest, revision),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO overseas_registration_snapshots (
                    source_document_id, source_file_name, source_sha256,
                    snapshot_date, status, relation_count, country_count,
                    model_count, probe_count, revision
                ) VALUES (1, 'f.xls', ?, '2026-08-19', 'draft', 1, 1, 1, 1, 1)
                """,
                (digest,),
            )
    finally:
        connection.close()
