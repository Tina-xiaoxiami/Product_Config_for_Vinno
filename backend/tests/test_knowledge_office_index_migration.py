"""Controlled migration contracts use synthetic Office files and temporary SQLite only."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import app.models  # noqa: F401 -- register the existing schema, never a parallel test ORM
import pytest
from app.database import Base
from app.services import knowledge_content
from docx import Document
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

IDS = [11, 19]
CLI = Path(__file__).resolve().parents[1] / "scripts/migrate_knowledge_office_index.py"


def migration():
    # Lazy import: absent implementation fails an executed behavior test, not collection.
    return importlib.import_module("app.services.knowledge_office_index_migration")


def connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def rows(path, scoped=False):
    with connect(path) as connection:
        result = {}
        tables = (
            [
                "knowledge_documents",
                "knowledge_document_extractions",
                "knowledge_document_chunks",
                "data_review_items",
            ]
            if scoped
            else [
                r[0]
                for r in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
        )
        for table in tables:
            columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            keys = [
                r["name"] for r in sorted(columns, key=lambda r: r["pk"]) if r["pk"]
            ]
            order = ",".join('"' + key + '"' for key in keys) or "rowid"
            condition = (
                (
                    " WHERE id IN (11,19)"
                    if table == "knowledge_documents"
                    else " WHERE document_id IN (11,19)"
                )
                if scoped
                else ""
            )
            result[table] = [
                dict(r)
                for r in connection.execute(
                    f'SELECT * FROM "{table}"{condition} ORDER BY {order}'
                )
            ]
        return result


@pytest.fixture
def case(tmp_path):
    database = tmp_path / "synthetic.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    engine.dispose()
    paths = {11: tmp_path / "first.docx", 19: tmp_path / "second.xlsx"}
    document = Document()
    document.add_paragraph("合成第一段：仅用于程序验证。")
    document.add_paragraph("合成第二段：不构成产品结论。")
    document.save(paths[11])
    workbook = Workbook()
    workbook.active["A1"] = "合成规格"
    workbook.active["C1"] = "100 mAh"
    workbook.active["A2"] = "合成限制"
    workbook.active["C2"] = "仅作测试"
    workbook.save(paths[19])
    workbook.close()
    expectations = []
    with connect(database) as connection:
        for ident in IDS:
            path = paths[ident]
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            connection.execute(
                "INSERT INTO knowledge_documents(id,document_type,title,file_name,file_path,sha256,source_status,version,market) VALUES(?, 'manual','合成资料',?,?,?,'active',?,'domestic')",
                (
                    ident,
                    path.name,
                    str(path),
                    sha,
                    None if ident == 11 else "synthetic-edition",
                ),
            )
            blocks = knowledge_content.extract_office_blocks(
                path.read_bytes(), path.suffix
            )
            chunks = knowledge_content.build_document_chunks(blocks)
            assert len(chunks) == 2
            connection.execute(
                "INSERT INTO knowledge_document_extractions(document_id,extractor_version,source_sha256,status,chunk_count,extracted_at) VALUES(?,'2',?,'completed',2,'2000-01-01')",
                (ident, sha),
            )
            for index, chunk in enumerate(chunks):
                cid = (10 if ident == 11 else 20) + index
                connection.execute(
                    "INSERT INTO knowledge_document_chunks(id,document_id,chunk_index,source_ref,content,normalized_content,content_hash,created_at) VALUES(?,?,?,?,?,?,?,'2000-01-01')",
                    (
                        cid,
                        ident,
                        index,
                        f"legacy row {index}",
                        chunk["content"],
                        chunk["normalized_content"],
                        chunk["content_hash"],
                    ),
                )
                payload = json.dumps({"content": chunk["content"]}, ensure_ascii=False)
                rid = (3 if ident == 11 else 5) + index
                connection.execute(
                    "INSERT INTO data_review_items(id,document_id,data_type,batch_id,source_record_key,source_ref,raw_payload_json,effective_payload_json,review_status) VALUES(?,?,'knowledge_document_chunk',?,?,?, ?,?,'auto_ready')",
                    (
                        rid,
                        ident,
                        ident,
                        str(cid),
                        f"legacy row {index}",
                        payload,
                        payload,
                    ),
                )
            expectations.append(
                {
                    "document_id": ident,
                    "sha256": sha,
                    "extractor_version": "2",
                    "chunk_count": 2,
                }
            )
        connection.execute(
            "INSERT INTO knowledge_documents(id,document_type,title,file_name,file_path,sha256,source_status,market) VALUES(99,'manual','unrelated','other.txt','/unused/synthetic-only',?,'active','domestic')",
            ("f" * 64,),
        )
        connection.execute(
            "INSERT INTO knowledge_document_chunks(id,document_id,chunk_index,source_ref,content,normalized_content,content_hash) VALUES(999,99,0,'untouched','unrelated','unrelated',?)",
            (hashlib.sha256(b"unrelated").hexdigest(),),
        )
    return SimpleNamespace(
        database=database,
        paths=paths,
        expectations=expectations,
        plan_path=tmp_path / "plan.json",
        manifest=tmp_path / "migration.json",
    )


def planned(case):
    service = migration()
    plan = service.build_plan(case.database, case.expectations)
    service.write_plan(plan, case.plan_path)
    return service, plan


async def applied(case):
    service, plan = planned(case)
    report = await service.apply_plan(
        case.database, case.plan_path, case.manifest, document_ids=IDS
    )
    assert report["status"] == "applied"
    return service, plan


def test_plan_has_no_database_or_source_side_effects(case):
    before = rows(case.database)
    files = {p: p.read_bytes() for p in case.paths.values()}
    database_bytes = case.database.read_bytes()
    service = migration()
    plan = service.build_plan(case.database, case.expectations)
    assert plan["document_ids"] == IDS and plan["plan_id"] and plan["before_digest"]
    assert plan["schema_version"] == 1
    assert (
        rows(case.database) == before and case.database.read_bytes() == database_bytes
    )
    assert all(p.read_bytes() == data for p, data in files.items())
    assert not case.manifest.exists() and not case.plan_path.exists()


def test_unknown_database_never_gets_created(tmp_path):
    path = tmp_path / "missing.db"
    service = migration()
    with pytest.raises(service.OfficeIndexMigrationError):
        service.build_plan(path, [])
    assert not path.exists()


@pytest.mark.asyncio
async def test_success_rebuilds_caches_without_rebinding_old_ids_and_rollback_preserves_other_concurrency(
    case,
):
    before = rows(case.database, True)
    old_ids = {r["id"] for r in before["knowledge_document_chunks"]}
    old_review_ids = {r["id"] for r in before["data_review_items"]}
    service, _ = await applied(case)
    after = rows(case.database, True)
    assert after["knowledge_documents"] == before["knowledge_documents"]
    assert all(
        r["extractor_version"] == "office-locator-v1"
        for r in after["knowledge_document_extractions"]
    )
    assert len(after["knowledge_document_chunks"]) == 4 and not old_ids & {
        r["id"] for r in after["knowledge_document_chunks"]
    }
    assert not old_review_ids & {r["id"] for r in after["data_review_items"]}
    chunks = {r["id"]: r for r in after["knowledge_document_chunks"]}
    for review in after["data_review_items"]:
        chunk = chunks[int(review["source_record_key"])]
        assert (
            review["document_id"] == chunk["document_id"]
            and review["source_ref"] == chunk["source_ref"]
        )
        assert (
            json.loads(review["effective_payload_json"])["content"] == chunk["content"]
        )
    assert (
        service.inspect_manifest(case.database, case.manifest, document_ids=IDS)[
            "state"
        ]
        == "new"
    )
    with connect(case.database) as connection:
        connection.execute(
            "INSERT INTO product_series(name) VALUES('unrelated concurrent row')"
        )
    result = await service.rollback_manifest(
        case.database, case.manifest, document_ids=IDS
    )
    assert result["status"] == "rolled_back" and rows(case.database, True) == before
    assert (
        service.inspect_manifest(case.database, case.manifest, document_ids=IDS)[
            "state"
        ]
        == "old"
    )
    with connect(case.database) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM product_series WHERE name='unrelated concurrent row'"
            ).fetchone()[0]
            == 1
        )
    assert case.manifest.stat().st_mode & 0o077 == 0
    assert case.plan_path.stat().st_mode & 0o077 == 0


@pytest.mark.asyncio
async def test_second_document_failure_is_batch_atomic(case, monkeypatch):
    service, _ = planned(case)
    before = rows(case.database)
    original = knowledge_content.extract_document_blocks

    def fail(path, mime):
        if Path(path) == case.paths[19]:
            raise knowledge_content.KnowledgeContentError(
                "synthetic second-file failure"
            )
        return original(path, mime)

    monkeypatch.setattr(knowledge_content, "extract_document_blocks", fail)
    with pytest.raises(service.OfficeIndexMigrationError):
        await service.apply_plan(
            case.database, case.plan_path, case.manifest, document_ids=IDS
        )
    assert rows(case.database) == before
    if case.manifest.exists():
        assert (
            service.inspect_manifest(case.database, case.manifest, document_ids=IDS)[
                "state"
            ]
            == "old"
        )


@pytest.mark.asyncio
async def test_raw_per_document_service_is_not_batch_atomic(case, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{case.database}")
    original = knowledge_content.extract_document_blocks

    def fail(path, mime):
        if Path(path) == case.paths[19]:
            raise knowledge_content.KnowledgeContentError(
                "synthetic second-file failure"
            )
        return original(path, mime)

    monkeypatch.setattr(knowledge_content, "extract_document_blocks", fail)
    try:
        async with AsyncSession(engine) as session:
            await knowledge_content.extract_registered_document(session, 11)
            with pytest.raises(knowledge_content.KnowledgeContentError):
                await knowledge_content.extract_registered_document(session, 19)
            await session.rollback()
        with connect(case.database) as connection:
            assert dict(
                connection.execute(
                    "SELECT document_id,extractor_version FROM knowledge_document_extractions WHERE document_id IN (11,19)"
                )
            ) == {11: "office-locator-v1", 19: "2"}
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE knowledge_documents SET sha256='changed' WHERE id=11",
        "UPDATE knowledge_document_extractions SET extractor_version='changed' WHERE document_id=11",
        "UPDATE knowledge_document_extractions SET chunk_count=7 WHERE document_id=11",
        "UPDATE data_review_items SET effective_payload_json='{}' WHERE id=3",
        "INSERT INTO data_review_revisions(review_item_id,revision_no,before_payload_json,after_payload_json,action,changed_by) VALUES(3,1,'{}','{}','confirmed','synthetic')",
        "INSERT INTO knowledge_answer_citations(answer_id,document_id,source_ref,excerpt,sort_order) VALUES(999,11,'synthetic','synthetic reference',0)",
    ],
)
@pytest.mark.asyncio
async def test_drift_after_plan_refuses_without_overwriting_current_rows(
    case, mutation
):
    service, _ = planned(case)
    with connect(case.database) as connection:
        connection.execute(mutation)
    before = rows(case.database)
    with pytest.raises(service.OfficeIndexMigrationError):
        await service.apply_plan(
            case.database, case.plan_path, case.manifest, document_ids=IDS
        )
    assert rows(case.database) == before


@pytest.mark.asyncio
async def test_changed_source_sha_refuses_without_writing_index(case):
    service, _ = planned(case)
    before = rows(case.database)
    case.paths[19].write_bytes(case.paths[19].read_bytes() + b"synthetic drift")
    with pytest.raises(service.OfficeIndexMigrationError):
        await service.apply_plan(
            case.database, case.plan_path, case.manifest, document_ids=IDS
        )
    assert rows(case.database) == before


@pytest.mark.parametrize("kind", ["target", "history", "reference", "old_id_collision"])
@pytest.mark.asyncio
async def test_rollback_rejects_drift_and_preserves_it(case, kind):
    before = rows(case.database, True)
    service, _ = await applied(case)
    with connect(case.database) as connection:
        if kind == "target":
            connection.execute(
                "UPDATE knowledge_document_extractions SET error_message='concurrent' WHERE document_id=11"
            )
        elif kind == "history":
            rid = connection.execute(
                "SELECT min(id) FROM data_review_items WHERE document_id=11"
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO data_review_revisions(review_item_id,revision_no,before_payload_json,after_payload_json,action,changed_by) VALUES(?,1,'{}','{}','confirmed','synthetic')",
                (rid,),
            )
        elif kind == "reference":
            connection.execute(
                "INSERT INTO knowledge_answer_citations(answer_id,document_id,source_ref,excerpt,sort_order) VALUES(999,11,'synthetic','new reference',0)"
            )
        else:
            old_id = before["knowledge_document_chunks"][0]["id"]
            connection.execute(
                "INSERT INTO knowledge_document_chunks(id,document_id,chunk_index,source_ref,content,normalized_content,content_hash) VALUES(?,99,1,'collision','unrelated new data','new',?)",
                (old_id, "e" * 64),
            )
    current = rows(case.database)
    with pytest.raises(service.OfficeIndexMigrationError):
        await service.rollback_manifest(case.database, case.manifest, document_ids=IDS)
    assert rows(case.database) == current


@pytest.mark.asyncio
async def test_commit_followed_by_manifest_update_failure_is_resolved_read_only_not_reapplied(
    case, monkeypatch
):
    service, _ = planned(case)
    original = service._write_json

    def fail(path, payload, **kwargs):
        if payload.get("phase") == "applied":
            raise OSError("synthetic final state-file failure")
        return original(path, payload, **kwargs)

    monkeypatch.setattr(service, "_write_json", fail)
    with pytest.raises(service.OfficeIndexMigrationError):
        await service.apply_plan(
            case.database, case.plan_path, case.manifest, document_ids=IDS
        )
    current = rows(case.database)
    assert (
        service.inspect_manifest(case.database, case.manifest, document_ids=IDS)[
            "state"
        ]
        == "new"
    )
    with pytest.raises(service.OfficeIndexMigrationError):
        await service.apply_plan(
            case.database, case.plan_path, case.manifest, document_ids=IDS
        )
    assert rows(case.database) == current


@pytest.mark.asyncio
async def test_status_reports_unknown_without_changing_ambiguous_state(case):
    service, _ = await applied(case)
    with connect(case.database) as connection:
        connection.execute(
            "UPDATE knowledge_document_chunks SET source_ref='unknown generation' WHERE document_id=11"
        )
    before = rows(case.database)
    assert (
        service.inspect_manifest(case.database, case.manifest, document_ids=IDS)[
            "state"
        ]
        == "unknown"
    )
    assert rows(case.database) == before


@pytest.mark.parametrize("destination", ["database", "source", "missing_parent"])
@pytest.mark.asyncio
async def test_manifest_destination_never_clobbers_inputs_or_creates_unknown_paths(
    case, destination
):
    service, _ = planned(case)
    before = rows(case.database)
    target = (
        case.database
        if destination == "database"
        else case.paths[11]
        if destination == "source"
        else case.database.parent / "unknown" / "manifest.json"
    )
    source_bytes = case.paths[11].read_bytes()
    with pytest.raises(service.OfficeIndexMigrationError):
        await service.apply_plan(
            case.database, case.plan_path, target, document_ids=IDS
        )
    assert rows(case.database) == before and case.paths[11].read_bytes() == source_bytes
    assert not (case.database.parent / "unknown").exists()


def test_plan_output_cannot_overwrite_source_or_database(case):
    service = migration()
    plan = service.build_plan(case.database, case.expectations)
    source = case.paths[11].read_bytes()
    before = case.database.read_bytes()
    for destination in [case.database, case.paths[11]]:
        with pytest.raises(service.OfficeIndexMigrationError):
            service.write_plan(plan, destination)
    assert (
        case.database.read_bytes() == before and case.paths[11].read_bytes() == source
    )


@pytest.mark.asyncio
async def test_scope_mismatch_cannot_apply_a_reviewed_plan(case):
    service, _ = planned(case)
    before = rows(case.database)
    with pytest.raises(service.OfficeIndexMigrationError):
        await service.apply_plan(
            case.database, case.plan_path, case.manifest, document_ids=[11]
        )
    assert rows(case.database) == before


def cli(case, *arguments):
    environment = dict(os.environ)
    environment["DATABASE_URL"] = (
        f"sqlite+aiosqlite:///{case.database.parent / 'must-not-create.db'}"
    )
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, arguments)],
        cwd=case.database.parent,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def test_cli_requires_explicit_database_and_defaults_to_read_only_plan(case):
    no_db = cli(case)
    assert no_db.returncode != 0
    args = ["--database", case.database]
    for item in case.expectations:
        args += ["--document", f"{item['document_id']}:{item['sha256']}:2:2"]
    before = rows(case.database)
    result = cli(case, *args)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["document_ids"] == IDS
    assert (
        rows(case.database) == before
        and not (case.database.parent / "must-not-create.db").exists()
    )


def test_cli_plan_apply_status_and_rollback_end_to_end(case):
    args = ["--database", case.database, "--output", case.plan_path]
    for item in case.expectations:
        args += ["--document", f"{item['document_id']}:{item['sha256']}:2:2"]
    before = rows(case.database, True)
    result = cli(case, *args)
    assert result.returncode == 0, result.stderr
    common = [
        "--database",
        case.database,
        "--ids",
        "11,19",
        "--manifest",
        case.manifest,
    ]
    result = cli(case, *common, "--action", "apply", "--plan", case.plan_path)
    assert result.returncode == 0, result.stderr
    result = cli(case, *common, "--action", "status")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["state"] == "new"
    result = cli(case, *common, "--action", "rollback")
    assert result.returncode == 0, result.stderr
    assert rows(case.database, True) == before


@pytest.mark.parametrize("tamper", ["checksum", "scope", "snapshot"])
@pytest.mark.asyncio
async def test_tampered_manifest_refuses_status_and_rollback_without_writes(
    case, tamper
):
    service, _ = await applied(case)
    payload = json.loads(case.manifest.read_text())
    if tamper == "checksum":
        payload["phase"] = "untrusted"
        case.manifest.write_text(json.dumps(payload))
    else:
        if tamper == "scope":
            payload["document_ids"] = [11]
        else:
            payload["before"]["knowledge_document_chunks"][0]["content"] = (
                "tampered rollback content"
            )
        service._write_json(
            case.manifest,
            payload,
            expected=hashlib.sha256(case.manifest.read_bytes()).hexdigest(),
        )
    before = rows(case.database)
    manifest_bytes = case.manifest.read_bytes()
    with pytest.raises(service.OfficeIndexMigrationError):
        service.inspect_manifest(case.database, case.manifest, document_ids=IDS)
    with pytest.raises(service.OfficeIndexMigrationError):
        await service.rollback_manifest(case.database, case.manifest, document_ids=IDS)
    assert (
        rows(case.database) == before and case.manifest.read_bytes() == manifest_bytes
    )


@pytest.mark.asyncio
async def test_retired_review_id_occupied_by_same_document_other_data_type_is_preserved(
    case,
):
    old_id = rows(case.database, True)["data_review_items"][0]["id"]
    service, _ = await applied(case)
    with connect(case.database) as connection:
        connection.execute(
            "INSERT INTO data_review_items(id,document_id,data_type,batch_id,source_record_key,source_ref,raw_payload_json,effective_payload_json,review_status) VALUES(?,11,'other_kind',11,'new unrelated','unrelated','{}','{}','auto_ready')",
            (old_id,),
        )
    before = rows(case.database)
    with pytest.raises(service.OfficeIndexMigrationError):
        await service.rollback_manifest(case.database, case.manifest, document_ids=IDS)
    assert rows(case.database) == before


@pytest.mark.parametrize(
    "table",
    [
        "knowledge_document_extractions",
        "knowledge_document_chunks",
        "data_review_items",
    ],
)
def test_unexpected_mutable_columns_refuse_plan(case, table):
    with connect(case.database) as connection:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN synthetic_extra TEXT")
    before = rows(case.database)
    service = migration()
    with pytest.raises(service.OfficeIndexMigrationError):
        service.build_plan(case.database, case.expectations)
    assert rows(case.database) == before and not case.plan_path.exists()


@pytest.mark.asyncio
async def test_status_is_read_only_and_missing_database_apply_status_never_create(case):
    service, _ = await applied(case)
    before = rows(case.database)
    database_bytes = case.database.read_bytes()
    manifest_bytes = case.manifest.read_bytes()
    files = set(case.database.parent.iterdir())
    assert (
        service.inspect_manifest(case.database, case.manifest, document_ids=IDS)[
            "state"
        ]
        == "new"
    )
    assert (
        rows(case.database) == before and case.database.read_bytes() == database_bytes
    )
    assert (
        case.manifest.read_bytes() == manifest_bytes
        and set(case.database.parent.iterdir()) == files
    )
    missing = case.database.parent / "missing-explicit.db"
    with pytest.raises(service.OfficeIndexMigrationError):
        service.inspect_manifest(missing, case.manifest, document_ids=IDS)
    with pytest.raises(service.OfficeIndexMigrationError):
        await service.apply_plan(
            missing,
            case.plan_path,
            case.database.parent / "new-manifest.json",
            document_ids=IDS,
        )
    assert not missing.exists() and rows(case.database) == before


def test_initial_manifest_directory_fsync_observes_single_link_no_temporary_alias(
    case, monkeypatch
):
    service = migration()
    plan = service.build_plan(case.database, case.expectations)
    original = os.fsync
    observations = []

    def checked(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            observations.append(
                (
                    case.plan_path.stat().st_nlink,
                    list(case.database.parent.glob(".office-index-*")),
                )
            )
        return original(fd)

    monkeypatch.setattr(os, "fsync", checked)
    service.write_plan(plan, case.plan_path)
    assert observations == [(1, [])]


@pytest.mark.asyncio
async def test_manifest_replaced_after_load_cannot_commit_rollback(case, monkeypatch):
    service, _ = await applied(case)
    before = rows(case.database)
    original = service._engine

    async def replaced(path):
        payload = json.loads(case.manifest.read_text())
        payload["concurrent_note"] = "another operator"
        service._write_json(
            case.manifest,
            payload,
            expected=hashlib.sha256(case.manifest.read_bytes()).hexdigest(),
        )
        return await original(path)

    monkeypatch.setattr(service, "_engine", replaced)
    with pytest.raises(service.OfficeIndexMigrationError, match="concurrent"):
        await service.rollback_manifest(case.database, case.manifest, document_ids=IDS)
    assert rows(case.database) == before
    assert (
        json.loads(case.manifest.read_text())["concurrent_note"] == "another operator"
    )


@pytest.mark.asyncio
async def test_identical_database_copy_replacing_bound_path_cannot_apply(
    case, monkeypatch
):
    service, _ = planned(case)
    before = rows(case.database)
    original = service._engine

    async def replaced(path):
        replacement = case.database.parent / "replacement.db"
        replacement.write_bytes(case.database.read_bytes())
        os.replace(replacement, case.database)
        return await original(path)

    monkeypatch.setattr(service, "_engine", replaced)
    with pytest.raises(service.OfficeIndexMigrationError, match="identity"):
        await service.apply_plan(
            case.database, case.plan_path, case.manifest, document_ids=IDS
        )
    assert rows(case.database) == before and not case.manifest.exists()


@pytest.mark.asyncio
async def test_precommit_manifest_failure_rolls_back_and_remains_inspectable(
    case, monkeypatch
):
    service, _ = planned(case)
    before = rows(case.database)
    original = service._write_json

    def fail(path, payload, **kwargs):
        if payload.get("phase") == "commit_prepared":
            raise OSError("synthetic durable write failure")
        return original(path, payload, **kwargs)

    monkeypatch.setattr(service, "_write_json", fail)
    with pytest.raises(service.OfficeIndexMigrationError):
        await service.apply_plan(
            case.database, case.plan_path, case.manifest, document_ids=IDS
        )
    assert rows(case.database) == before
    assert (
        service.inspect_manifest(case.database, case.manifest, document_ids=IDS)[
            "state"
        ]
        == "old"
    )


@pytest.mark.asyncio
async def test_rollback_final_manifest_failure_reports_old_and_cannot_replay(
    case, monkeypatch
):
    service, _ = await applied(case)
    original = service._write_json

    def fail(path, payload, **kwargs):
        if payload.get("phase") == "rolled_back":
            raise OSError("synthetic rollback final write failure")
        return original(path, payload, **kwargs)

    monkeypatch.setattr(service, "_write_json", fail)
    with pytest.raises(service.OfficeIndexMigrationError):
        await service.rollback_manifest(case.database, case.manifest, document_ids=IDS)
    before = rows(case.database)
    assert (
        service.inspect_manifest(case.database, case.manifest, document_ids=IDS)[
            "state"
        ]
        == "old"
    )
    with pytest.raises(service.OfficeIndexMigrationError):
        await service.rollback_manifest(case.database, case.manifest, document_ids=IDS)
    assert rows(case.database) == before
