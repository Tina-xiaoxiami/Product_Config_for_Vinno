"""Explicit-database Office derived-index maintenance; never initializes a database.

Plans are read-only. Apply/rollback own one outer transaction; existing extraction
and staging services keep their business rules and join that transaction.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace


class OfficeIndexMigrationError(ValueError):
    """A precondition failed; inspect the durable manifest before retrying."""


TABLES = {
    "knowledge_document_extractions": [
        "document_id",
        "extractor_version",
        "source_sha256",
        "status",
        "chunk_count",
        "error_message",
        "extracted_at",
        "updated_at",
    ],
    "knowledge_document_chunks": [
        "id",
        "document_id",
        "chunk_index",
        "page_number",
        "section_name",
        "source_ref",
        "content",
        "normalized_content",
        "content_hash",
        "created_at",
    ],
    "data_review_items": [
        "id",
        "document_id",
        "data_type",
        "batch_id",
        "source_record_key",
        "source_ref",
        "raw_payload_json",
        "effective_payload_json",
        "issue_codes_json",
        "review_status",
        "updated_by",
        "change_note",
        "created_at",
        "updated_at",
    ],
}
CACHE = "knowledge_document_chunk"
MAX_JSON = 64 * 1024 * 1024


def _require(condition, message):
    if not condition:
        raise OfficeIndexMigrationError(message)


def _json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _seal(payload):
    return {
        **payload,
        "checksum": _digest({k: v for k, v in payload.items() if k != "checksum"}),
    }


def _database(database):
    path = Path(database).expanduser().resolve(strict=True)
    _require(path.is_file(), "Explicit existing SQLite database required")
    with path.open("rb") as stream:
        _require(stream.read(16) == b"SQLite format 3\x00", "Not a SQLite database")
    info = path.stat()
    return path, {"path": str(path), "device": info.st_dev, "inode": info.st_ino}


def _same_database(path, identity):
    _require(_database(path)[1] == identity, "Database path identity changed")


@contextmanager
def _readonly(database):
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        yield connection
    finally:
        connection.close()


def _rows(connection, sql, parameters=()):
    cursor = connection.execute(sql, parameters)
    if hasattr(cursor, "mappings"):
        return [dict(row) for row in cursor.mappings().all()]
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _marks(ids):
    return ",".join("?" for _ in ids)


def _ids(values):
    _require(
        isinstance(values, list)
        and values
        and all(type(v) is int and v > 0 for v in values),
        "Nonempty positive document IDs required",
    )
    _require(len(set(values)) == len(values), "Duplicate document IDs")
    return sorted(values)


def _schema(connection):
    for table, columns in TABLES.items():
        actual = _rows(connection, f'PRAGMA table_info("{table}")')
        _require(
            {row["name"] for row in actual} == set(columns),
            "Unsupported mutable table schema",
        )
    return _digest(
        _rows(
            connection,
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name",
        )
    )


def _capture(connection, ids):
    scope = _marks(ids)
    result = {"schema": _schema(connection)}
    result["knowledge_documents"] = _rows(
        connection,
        f"SELECT * FROM knowledge_documents WHERE id IN ({scope}) ORDER BY id",
        tuple(ids),
    )
    for table in TABLES:
        condition = (
            " AND data_type='knowledge_document_chunk'"
            if table == "data_review_items"
            else ""
        )
        key = "document_id" if table == "knowledge_document_extractions" else "id"
        result[table] = _rows(
            connection,
            f"SELECT * FROM {table} WHERE document_id IN ({scope}){condition} ORDER BY {key}",
            tuple(ids),
        )
    return result


def _outside(connection, ids):
    """Hash current unrelated state, including triggers/schema and other counters."""
    result = []
    schema = _rows(
        connection,
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name",
    )
    result.append(schema)
    for table in sorted(row["name"] for row in schema if row["type"] == "table"):
        quoted = '"' + table.replace('"', '""') + '"'
        rows = _rows(connection, f"SELECT * FROM {quoted}")
        if table in TABLES:
            rows = [
                r
                for r in rows
                if r["document_id"] not in ids
                or (table == "data_review_items" and r["data_type"] != CACHE)
            ]
        if table == "sqlite_sequence":
            rows = [
                r
                for r in rows
                if r["name"] not in {"knowledge_document_chunks", "data_review_items"}
            ]
        safe = [
            {
                k: {"blob_sha256": hashlib.sha256(v).hexdigest(), "length": len(v)}
                if isinstance(v, bytes)
                else v
                for k, v in r.items()
            }
            for r in rows
        ]
        result.append((table, sorted(_json(r) for r in safe)))
    return _digest(result)


def _references(connection, ids, review_ids):
    for table, column in [
        ("knowledge_answer_citations", "document_id"),
        ("feature_versions", "evidence_document_id"),
    ]:
        _require(
            not _rows(
                connection,
                f"SELECT 1 FROM {table} WHERE {column} IN ({_marks(ids)}) LIMIT 1",
                tuple(ids),
            ),
            "Document has answer or feature references",
        )
    if review_ids:
        _require(
            not _rows(
                connection,
                f"SELECT 1 FROM data_review_revisions WHERE review_item_id IN ({_marks(review_ids)}) LIMIT 1",
                tuple(review_ids),
            ),
            "Human review history exists",
        )


def _cache_guard(state):
    chunks = {str(row["id"]): row for row in state["knowledge_document_chunks"]}
    caches = state["data_review_items"]
    _require(len(caches) == len(chunks), "Chunk cache is incomplete or duplicated")
    seen = set()
    for row in caches:
        chunk = chunks.get(row["source_record_key"])
        if chunk is None or row["source_record_key"] in seen:
            raise OfficeIndexMigrationError("Cache does not map one-to-one to chunks")
        seen.add(row["source_record_key"])
        _require(
            row["data_type"] == CACHE
            and row["batch_id"] == row["document_id"] == chunk["document_id"]
            and row["source_ref"] == chunk["source_ref"],
            "Cache identity drift",
        )
        _require(
            row["review_status"] == "auto_ready"
            and row["updated_by"] is None
            and row["change_note"] is None,
            "Human-modified cache cannot be migrated",
        )
        _require(
            json.loads(row["issue_codes_json"]) == []
            and json.loads(row["raw_payload_json"])
            == json.loads(row["effective_payload_json"])
            == {"content": chunk["content"]},
            "Cache payload drift",
        )


def _sources(state, expectations):
    _require(len(state["knowledge_documents"]) == len(expectations), "Missing document")
    extracts = {r["document_id"]: r for r in state["knowledge_document_extractions"]}
    expected = {r["document_id"]: r for r in expectations}
    sources = []
    for doc in state["knowledge_documents"]:
        item = expected[doc["id"]]
        path = Path(doc["file_path"])
        _require(
            doc["source_status"] == "active"
            and path.is_absolute()
            and path.suffix.lower() in {".docx", ".xlsx"}
            and Path(doc["file_name"]).suffix.lower() == path.suffix.lower(),
            "Active registered DOCX/XLSX required",
        )
        extract = extracts.get(doc["id"])
        if extract is None:
            raise OfficeIndexMigrationError("Missing extraction state")
        _require(
            extract["status"] == "completed"
            and extract["extractor_version"] == item["extractor_version"]
            and extract["chunk_count"] == item["chunk_count"],
            "Extraction profile or count drift",
        )
        _require(
            doc["sha256"] == extract["source_sha256"] == item["sha256"],
            "Registered source hash drift",
        )
        _require(
            sum(
                r["document_id"] == doc["id"]
                for r in state["knowledge_document_chunks"]
            )
            == item["chunk_count"],
            "Stored chunk count drift",
        )
        source = {
            "document_id": doc["id"],
            "path": str(path.resolve(strict=True)),
            "sha256": item["sha256"],
        }
        sources.append(source)
    _check_files(sources)
    return sources


def _check_files(sources):
    from app.services.knowledge_content import MAX_SOURCE_BYTES

    for source in sources:
        with Path(source["path"]).open("rb") as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
        _require(
            len(data) <= MAX_SOURCE_BYTES
            and hashlib.sha256(data).hexdigest() == source["sha256"],
            "Source bytes changed or exceed size limit",
        )


def _expectations(values):
    _require(isinstance(values, list), "Document expectations required")
    ids = _ids([v["document_id"] for v in values])
    for value in values:
        _require(
            set(value) == {"document_id", "sha256", "extractor_version", "chunk_count"},
            "Unexpected expectation fields",
        )
        _require(
            isinstance(value["sha256"], str)
            and re.fullmatch("[0-9a-f]{64}", value["sha256"])
            and value["extractor_version"] == "2"
            and type(value["chunk_count"]) is int
            and value["chunk_count"] > 0,
            "Expected legacy profile 2, SHA256 and positive count required",
        )
    return ids


def build_plan(database: str | Path, expectations: list[dict]) -> dict:
    """Read-only snapshot binding; no extraction, schema migration or output writes."""
    try:
        path, identity = _database(database)
        ids = _expectations(expectations)
        with _readonly(path) as connection:
            _same_database(path, identity)
            before = _capture(connection, ids)
            sources = _sources(before, expectations)
            _cache_guard(before)
            _references(connection, ids, [r["id"] for r in before["data_review_items"]])
            _same_database(path, identity)
        plan = {
            "schema_version": 1,
            "kind": "office_index_plan",
            "database": identity,
            "document_ids": ids,
            "expectations": sorted(expectations, key=lambda r: r["document_id"]),
            "sources": sources,
            "before_digest": _digest(before),
            "ready_for_production_apply": False,
        }
        plan["plan_id"] = _digest(plan)
        return _seal(plan)
    except OfficeIndexMigrationError:
        raise
    except Exception as error:
        raise OfficeIndexMigrationError(
            "Cannot build a safe plan; check explicit database and preconditions"
        ) from error


def _output(path, protected=()):
    path = Path(path).expanduser().absolute()
    _require(
        path.parent.is_dir() and not path.is_symlink(),
        "Output parent must exist; symlink outputs refused",
    )
    _require(
        not path.exists(), "Output already exists; inspect it instead of replaying"
    )
    _require(
        all(path.resolve() != Path(item).resolve() for item in protected),
        "Output aliases a protected input",
    )
    return path


def _private_bytes(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        _require(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and info.st_mode & 0o077 == 0,
            "Plan/manifest must be a private regular file without aliases",
        )
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(MAX_JSON + 1)
        _require(len(data) <= MAX_JSON, "Plan/manifest exceeds size limit")
        return data
    finally:
        os.close(fd)


def _read_json(path):
    encoded = _private_bytes(path)
    value = json.loads(encoded)
    _require(
        isinstance(value, dict)
        and value.get("schema_version") == 1
        and value.get("checksum") == _seal(value)["checksum"],
        "Invalid plan/manifest checksum or schema",
    )
    _require(encoded == _json(value).encode(), "Plan/manifest must use canonical JSON")
    return value


def _write_json(path, payload, *, expected=None):
    """Durable private install; initial file never clobbers, updates use CAS token."""
    path = Path(path)
    encoded = _json(_seal(payload)).encode()
    _require(len(encoded) <= MAX_JSON, "Manifest exceeds size limit")
    if expected is None:
        _output(path)
    else:
        _require(
            hashlib.sha256(_private_bytes(path)).hexdigest() == expected,
            "Manifest changed concurrently",
        )
    fd, temporary = tempfile.mkstemp(prefix=".office-index-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if expected is None:
            os.link(temporary, path)
            # Persist removal of the temporary hardlink before database writes.
            os.unlink(temporary)
        else:
            _require(
                hashlib.sha256(_private_bytes(path)).hexdigest() == expected,
                "Manifest changed concurrently",
            )
            os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _phase(path, manifest, phase, token):
    manifest["phase"] = phase
    _write_json(path, manifest, expected=token)
    return _digest(_seal(manifest))


def _protected(plan, plan_path=None):
    db = plan["database"]["path"]
    return [
        db,
        db + "-wal",
        db + "-shm",
        db + "-journal",
        *[r["path"] for r in plan["sources"]],
        *([plan_path] if plan_path else []),
    ]


def write_plan(plan: dict, path: str | Path) -> None:
    _require(
        plan.get("checksum") == _seal(plan)["checksum"]
        and plan.get("kind") == "office_index_plan",
        "Invalid plan",
    )
    try:
        _write_json(_output(path, _protected(plan)), plan)
    except OfficeIndexMigrationError:
        raise
    except Exception as error:
        raise OfficeIndexMigrationError("Cannot write private plan") from error


def _binding(database, record, ids):
    path, identity = _database(database)
    _require(
        record["database"] == identity and _ids(ids) == record["document_ids"],
        "Database identity or explicit scope mismatch",
    )
    _require(
        record.get("ready_for_production_apply") is False, "Invalid readiness flag"
    )
    return path


def _adapter(connection):
    return SimpleNamespace(execute=connection.exec_driver_sql)


def _validate_state(state, ids):
    _require(
        set(state) == {"schema", "knowledge_documents", *TABLES},
        "Invalid rollback state",
    )
    _require(
        sorted(r["id"] for r in state["knowledge_documents"]) == ids,
        "Invalid document scope",
    )
    for table, columns in TABLES.items():
        rows = state[table]
        _require(
            all(set(r) == set(columns) and r["document_id"] in ids for r in rows),
            "Invalid rollback rows",
        )
        key = "document_id" if table == "knowledge_document_extractions" else "id"
        _require(
            len({r[key] for r in rows}) == len(rows),
            "Duplicate rollback row identities",
        )
    _require(
        sorted(r["document_id"] for r in state["knowledge_document_extractions"])
        == ids,
        "Incomplete extraction state",
    )
    _cache_guard(state)


def _manifest(database, manifest_path, ids):
    value = _read_json(manifest_path)
    _require(
        value.get("kind") == "office_index_manifest", "Expected migration manifest"
    )
    path = _binding(database, value, ids)
    _require(
        Path(manifest_path).resolve()
        not in [Path(p).resolve() for p in _protected(value)],
        "Manifest aliases protected input",
    )
    for name in ["before", "after"]:
        if value.get(name) is not None:
            _validate_state(value[name], value["document_ids"])
            _require(
                _digest(value[name]) == value[name + "_digest"],
                "Rollback state digest mismatch",
            )
    _require(value.get("before") is not None, "Missing rollback state")
    return path, value


def inspect_manifest(
    database: str | Path, manifest_path: str | Path, *, document_ids: list[int]
) -> dict:
    """Readonly old/new/unknown classification from a consistent DB snapshot."""
    try:
        path, manifest = _manifest(database, manifest_path, document_ids)
        with _readonly(path) as connection:
            _same_database(path, manifest["database"])
            current = _digest(_capture(connection, manifest["document_ids"]))
            _same_database(path, manifest["database"])
        _check_files(manifest["sources"])
        state = (
            "old"
            if current == manifest["before_digest"]
            else "new"
            if current == manifest.get("after_digest")
            else "unknown"
        )
        return {
            "state": state,
            "phase": manifest["phase"],
            "plan_id": manifest["plan_id"],
            "ready_for_production_apply": False,
        }
    except OfficeIndexMigrationError:
        raise
    except Exception as error:
        raise OfficeIndexMigrationError("Cannot inspect manifest safely") from error


async def _engine(path):
    from sqlalchemy.ext.asyncio import create_async_engine

    # URI mode=rw prevents a database appearing if the explicit file vanishes.
    return create_async_engine(
        "sqlite+aiosqlite:///" + path.as_uri() + "?mode=rw&uri=true"
    )


async def _begin(connection):
    await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    await connection.commit()
    await connection.exec_driver_sql("BEGIN IMMEDIATE")


async def apply_plan(
    database: str | Path,
    plan_path: str | Path,
    manifest_path: str | Path,
    *,
    document_ids: list[int],
) -> dict:
    """Apply only a reviewed matching snapshot, with a durable recovery record."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services import knowledge_content, knowledge_sources
    from app.services.data_review import stage_knowledge_document_review_items

    engine = None
    try:
        plan = _read_json(plan_path)
        _require(
            plan.get("kind") == "office_index_plan"
            and plan.get("plan_id")
            == _digest(
                {k: v for k, v in plan.items() if k not in {"plan_id", "checksum"}}
            ),
            "Invalid plan identity",
        )
        path = _binding(database, plan, document_ids)
        _expectations(plan["expectations"])
        output = _output(manifest_path, _protected(plan, plan_path))
        engine = await _engine(path)
        async with engine.connect() as connection:
            await _begin(connection)
            _same_database(path, plan["database"])
            before = await connection.run_sync(
                lambda c: _capture(_adapter(c), plan["document_ids"])
            )
            _require(_digest(before) == plan["before_digest"], "Reviewed plan is stale")
            sources = _sources(before, plan["expectations"])
            _require(sources == plan["sources"], "Source binding drift")
            _cache_guard(before)
            await connection.run_sync(
                lambda c: _references(
                    _adapter(c),
                    plan["document_ids"],
                    [r["id"] for r in before["data_review_items"]],
                )
            )
            outside = await connection.run_sync(
                lambda c: _outside(_adapter(c), plan["document_ids"])
            )
            manifest = {
                **{k: v for k, v in plan.items() if k != "checksum"},
                "kind": "office_index_manifest",
                "phase": "prepared",
                "before": before,
                "after": None,
            }
            _write_json(output, manifest)
            token = _digest(_seal(manifest))
            order = sorted(
                plan["document_ids"],
                key=lambda i: max(
                    r["id"]
                    for r in before["knowledge_document_chunks"]
                    if r["document_id"] == i
                ),
            )
            async with AsyncSession(
                bind=connection, join_transaction_mode="create_savepoint"
            ) as session:
                for ident in order:
                    result = await knowledge_content.extract_registered_document(
                        session, ident
                    )
                    _require(
                        result
                        and result["extractor_version"]
                        == knowledge_content.OFFICE_EXTRACTOR_VERSION
                        and not result.get("reused"),
                        "Expected fresh Office extraction",
                    )
                await session.close()
            for ident in order:
                await connection.run_sync(
                    lambda c, ident=ident: stage_knowledge_document_review_items(
                        path, document_id=ident, _connection=_adapter(c)
                    )
                )
            old_reviews = [r["id"] for r in before["data_review_items"]]
            await connection.exec_driver_sql(
                f"DELETE FROM data_review_items WHERE id IN ({_marks(old_reviews)})",
                tuple(old_reviews),
            )
            after = await connection.run_sync(
                lambda c: _capture(_adapter(c), plan["document_ids"])
            )
            for table in ["knowledge_document_chunks", "data_review_items"]:
                _require(
                    not {r["id"] for r in before[table]}
                    & {r["id"] for r in after[table]},
                    "Old identities reused; migration refused",
                )
            _require(
                after["knowledge_documents"] == before["knowledge_documents"],
                "Source metadata changed",
            )
            _cache_guard(after)
            for chunk in after["knowledge_document_chunks"]:
                sha = next(
                    s["sha256"]
                    for s in sources
                    if s["document_id"] == chunk["document_id"]
                )
                evidence = await knowledge_sources.citation_evidence(
                    connection, chunk["document_id"], sha, chunk_id=chunk["id"]
                )
                _require(
                    evidence["page"] is None
                    and evidence.get("model_answer_eligible") is False
                    and evidence["verification"].get("structure") == "matched"
                    and evidence["verification"].get("visual") == "not_checked"
                    and evidence["verification"].get("human") == "not_reviewed",
                    "Office evidence verification failed",
                )
                await knowledge_sources.verified_original(
                    connection, chunk["document_id"], sha
                )
            _check_files(sources)
            _require(
                outside
                == await connection.run_sync(
                    lambda c: _outside(_adapter(c), plan["document_ids"])
                ),
                "Unrelated database state changed",
            )
            manifest.update(after=after, after_digest=_digest(after))
            token = _phase(output, manifest, "commit_prepared", token)
            # A COMMIT error is ambiguous. Durable before+after allow readonly status.
            _same_database(path, plan["database"])
            await connection.commit()
            _phase(output, manifest, "applied", token)
        return {
            "status": "applied",
            "plan_id": plan["plan_id"],
            "ready_for_production_apply": False,
        }
    except OfficeIndexMigrationError:
        raise
    except Exception as error:
        raise OfficeIndexMigrationError(
            "Apply did not complete cleanly; inspect manifest before any retry"
        ) from error
    finally:
        if engine is not None:
            await engine.dispose()


async def rollback_manifest(
    database: str | Path, manifest_path: str | Path, *, document_ids: list[int]
) -> dict:
    """Compare-and-restore exact scoped rows; preserve current unrelated changes."""
    engine = None
    try:
        path, manifest = _manifest(database, manifest_path, document_ids)
        _require(
            manifest.get("after") is not None, "No complete post-state; inspect instead"
        )
        ids = manifest["document_ids"]
        token = _digest(manifest)
        engine = await _engine(path)
        async with engine.connect() as connection:
            await _begin(connection)
            _same_database(path, manifest["database"])
            current = await connection.run_sync(lambda c: _capture(_adapter(c), ids))
            _require(
                _digest(current) == manifest["after_digest"],
                "Post-state changed; rollback refused",
            )
            _check_files(manifest["sources"])
            review_ids = [
                r["id"]
                for state in [manifest["before"], current]
                for r in state["data_review_items"]
            ]
            await connection.run_sync(
                lambda c: _references(_adapter(c), ids, review_ids)
            )
            for table in ["knowledge_document_chunks", "data_review_items"]:
                old_ids = [r["id"] for r in manifest["before"][table]]
                occupied = await connection.exec_driver_sql(
                    f"SELECT 1 FROM {table} WHERE id IN ({_marks(old_ids)}) LIMIT 1",
                    tuple(old_ids),
                )
                _require(
                    occupied.first() is None,
                    "Retired row identity occupied; rollback refused",
                )
            outside = await connection.run_sync(lambda c: _outside(_adapter(c), ids))
            token = _phase(manifest_path, manifest, "rollback_prepared", token)
            await connection.exec_driver_sql(
                f"DELETE FROM data_review_items WHERE document_id IN ({_marks(ids)}) AND data_type=?",
                (*ids, CACHE),
            )
            await connection.exec_driver_sql(
                f"DELETE FROM knowledge_document_chunks WHERE document_id IN ({_marks(ids)})",
                tuple(ids),
            )
            for row in manifest["before"]["knowledge_document_extractions"]:
                keys = [
                    k
                    for k in TABLES["knowledge_document_extractions"]
                    if k != "document_id"
                ]
                await connection.exec_driver_sql(
                    "UPDATE knowledge_document_extractions SET "
                    + ",".join(k + "=?" for k in keys)
                    + " WHERE document_id=?",
                    (*[row[k] for k in keys], row["document_id"]),
                )
            for table in ["knowledge_document_chunks", "data_review_items"]:
                columns = TABLES[table]
                for row in manifest["before"][table]:
                    await connection.exec_driver_sql(
                        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({_marks(columns)})",
                        tuple(row[k] for k in columns),
                    )
            restored = await connection.run_sync(lambda c: _capture(_adapter(c), ids))
            _require(
                _digest(restored) == manifest["before_digest"],
                "Restored rows do not match before-state",
            )
            _require(
                outside
                == await connection.run_sync(lambda c: _outside(_adapter(c), ids)),
                "Rollback altered unrelated state",
            )
            _check_files(manifest["sources"])
            _same_database(path, manifest["database"])
            await connection.commit()
            _phase(manifest_path, manifest, "rolled_back", token)
        return {
            "status": "rolled_back",
            "plan_id": manifest["plan_id"],
            "ready_for_production_apply": False,
        }
    except OfficeIndexMigrationError:
        raise
    except Exception as error:
        raise OfficeIndexMigrationError(
            "Rollback did not complete cleanly; inspect manifest before any retry"
        ) from error
    finally:
        if engine is not None:
            await engine.dispose()
