"""Versioned overseas country-model-probe registration history."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
import re
import sqlite3

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.overseas_registration_preview import (
    OverseasMasterDataMatchPreview,
    OverseasRegistrationPreview,
)
from app.services.registration_rules import normalize_business_name


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_snapshot_date(path: Path) -> str | None:
    match = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", path.stem)
    if match is None:
        return None
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def register_controlled_overseas_tracking_document(
    database_path: str | Path,
    file_path: str | Path,
    *,
    controlled_root: str | Path,
) -> dict[str, int | str]:
    """Register one controlled overseas tracking workbook without duplicating it."""

    source = Path(file_path).expanduser().resolve()
    root = Path(controlled_root).expanduser().resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise ValueError("海外注册跟踪表必须位于 Obsidian 受控材料目录") from exc
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.casefold() not in {".xls", ".xlsx"}:
        raise ValueError("海外注册跟踪材料必须是 Excel 文件")

    digest = _file_sha256(source)
    database = Path(database_path).expanduser().resolve()
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        by_path = connection.execute(
            "SELECT id, sha256 FROM knowledge_documents WHERE file_path = ?",
            (str(source),),
        ).fetchone()
        if by_path is not None:
            if str(by_path["sha256"] or "").lower() != digest:
                raise ValueError("受控路径已登记，但文件哈希发生变化")
            return {
                "document_id": int(by_path["id"]),
                "status": "unchanged",
                "file_path": str(source),
                "sha256": digest,
            }

        by_hash = connection.execute(
            "SELECT id, file_path FROM knowledge_documents WHERE sha256 = ? ORDER BY id",
            (digest,),
        ).fetchone()
        if by_hash is not None:
            connection.execute(
                """
                UPDATE knowledge_documents
                SET file_path = ?, file_name = ?, document_type = 'registration_tracking',
                    title = ?, version = ?, market = 'overseas', country = NULL,
                    product_series = NULL, mime_type = ?, source_status = 'active'
                WHERE id = ?
                """,
                (
                    str(source),
                    source.name,
                    source.stem,
                    _file_snapshot_date(source),
                    mimetypes.guess_type(source.name)[0]
                    or "application/octet-stream",
                    int(by_hash["id"]),
                ),
            )
            connection.commit()
            return {
                "document_id": int(by_hash["id"]),
                "status": "migrated_to_controlled_path",
                "file_path": str(source),
                "sha256": digest,
            }

        cursor = connection.execute(
            """
            INSERT INTO knowledge_documents (
                document_type, title, file_name, file_path, version, market,
                country, product_series, mime_type, sha256, source_status
            ) VALUES (
                'registration_tracking', ?, ?, ?, ?, 'overseas',
                NULL, NULL, ?, ?, 'active'
            )
            """,
            (
                source.stem,
                source.name,
                str(source),
                _file_snapshot_date(source),
                mimetypes.guess_type(source.name)[0]
                or "application/octet-stream",
                digest,
            ),
        )
        connection.commit()
        return {
            "document_id": int(cursor.lastrowid),
            "status": "inserted",
            "file_path": str(source),
            "sha256": digest,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def migrate_overseas_registration_history_schema(database_path: str | Path) -> None:
    """Create the isolated overseas history layer without changing config masters."""

    database = Path(database_path).expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS overseas_registration_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_document_id INTEGER NOT NULL
                    REFERENCES knowledge_documents(id),
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

            CREATE TABLE IF NOT EXISTS overseas_registration_relations (
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
                product_model_id INTEGER REFERENCES product_models(id),
                probe_match_status TEXT NOT NULL,
                probe_model_id INTEGER REFERENCES probe_models(id),
                UNIQUE (
                    snapshot_id, country_code, normalized_model,
                    normalized_probe, registration_status, address_version
                )
            );

            CREATE UNIQUE INDEX IF NOT EXISTS uq_overseas_registration_active
            ON overseas_registration_snapshots(status)
            WHERE status = 'active';
            CREATE INDEX IF NOT EXISTS ix_overseas_registration_country_model
            ON overseas_registration_relations(snapshot_id, country_code, normalized_model);
            CREATE INDEX IF NOT EXISTS ix_overseas_registration_probe
            ON overseas_registration_relations(snapshot_id, normalized_probe);
            COMMIT;
            """
        )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"海外注册历史层迁移引入外键异常：{violations}")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _controlled_document(
    connection: sqlite3.Connection,
    *,
    source_document_id: int,
    preview: OverseasRegistrationPreview,
) -> tuple[str, str]:
    row = connection.execute(
        "SELECT file_path, file_name, sha256 FROM knowledge_documents WHERE id = ?",
        (source_document_id,),
    ).fetchone()
    if row is None:
        raise ValueError("海外注册源文件尚未登记为受控材料")
    registered_path = Path(str(row[0])).expanduser().resolve()
    preview_path = Path(preview.source_file).expanduser().resolve()
    if registered_path != preview_path:
        raise ValueError("预览文件不是所选受控材料")
    if not registered_path.is_file():
        raise ValueError("受控海外注册原件不存在")
    registered_sha = str(row[2] or "").lower()
    digest = _file_sha256(registered_path)
    if registered_sha != preview.source_sha256.lower() or registered_sha != digest:
        raise ValueError("受控海外注册原件哈希与预览不一致")
    return str(row[1] or registered_path.name), registered_sha


def _match_map(items) -> dict[str, object]:
    return {
        normalize_business_name(item.source_name).casefold(): item
        for item in items
    }


def stage_overseas_registration_snapshot(
    database_path: str | Path,
    *,
    preview: OverseasRegistrationPreview,
    matches: OverseasMasterDataMatchPreview,
    source_document_id: int,
) -> dict[str, int | str]:
    """Persist an inert draft; only explicit publishing makes it queryable."""

    migrate_overseas_registration_history_schema(database_path)
    database = Path(database_path).expanduser().resolve()
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        file_name, source_sha = _controlled_document(
            connection,
            source_document_id=source_document_id,
            preview=preview,
        )
        existing = connection.execute(
            """
            SELECT id, status, relation_count, country_count, model_count, probe_count
            FROM overseas_registration_snapshots WHERE source_sha256 = ?
            """,
            (source_sha,),
        ).fetchone()
        if existing is not None:
            return {
                "snapshot_id": int(existing[0]),
                "status": str(existing[1]),
                "relation_count": int(existing[2]),
                "country_count": int(existing[3]),
                "model_count": int(existing[4]),
                "probe_count": int(existing[5]),
            }

        relations = tuple(dict.fromkeys(preview.relations))
        if not relations:
            raise ValueError("海外注册预览中没有可发布的国家－型号－探头关系")
        if any(item.registration_status != "completed" for item in relations):
            raise ValueError("只有已完成注册的数据可以进入海外注册历史层")
        countries = {item.jurisdiction_code for item in relations}
        models = {
            normalize_business_name(item.model_name).casefold() for item in relations
        }
        probes = {
            normalize_business_name(item.probe_model).casefold() for item in relations
        }
        cursor = connection.execute(
            """
            INSERT INTO overseas_registration_snapshots (
                source_document_id, source_file_name, source_sha256, snapshot_date,
                status, relation_count, country_count, model_count, probe_count
            ) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?)
            """,
            (
                source_document_id,
                file_name,
                source_sha,
                preview.snapshot_date,
                len(relations),
                len(countries),
                len(models),
                len(probes),
            ),
        )
        snapshot_id = int(cursor.lastrowid)
        model_matches = _match_map(matches.models)
        probe_matches = _match_map(matches.probes)
        for relation in relations:
            model_match = model_matches.get(
                normalize_business_name(relation.model_name).casefold()
            )
            probe_match = probe_matches.get(
                normalize_business_name(relation.probe_model).casefold()
            )
            connection.execute(
                """
                INSERT INTO overseas_registration_relations (
                    snapshot_id, country_code, model_name, normalized_model,
                    probe_model, normalized_probe, registration_status,
                    address_version, source_ref, model_match_status,
                    product_model_id, probe_match_status, probe_model_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    relation.jurisdiction_code,
                    relation.model_name,
                    normalize_business_name(relation.model_name).casefold(),
                    relation.probe_model,
                    normalize_business_name(relation.probe_model).casefold(),
                    relation.registration_status,
                    relation.address_version,
                    relation.source_ref,
                    getattr(model_match, "match_status", "unmatched"),
                    (getattr(model_match, "candidate_ids", ()) or (None,))[0],
                    getattr(probe_match, "match_status", "unmatched"),
                    (getattr(probe_match, "candidate_ids", ()) or (None,))[0],
                ),
            )
        connection.commit()
        return {
            "snapshot_id": snapshot_id,
            "status": "draft",
            "relation_count": len(relations),
            "country_count": len(countries),
            "model_count": len(models),
            "probe_count": len(probes),
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def publish_overseas_registration_snapshot(
    database_path: str | Path,
    *,
    snapshot_id: int,
    confirmed_by: str,
) -> dict[str, int | str]:
    """Publish one reviewed snapshot and retain the former one as history."""

    if not str(confirmed_by).strip():
        raise ValueError("发布人不能为空")
    migrate_overseas_registration_history_schema(database_path)
    connection = sqlite3.connect(Path(database_path).expanduser().resolve())
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        row = connection.execute(
            "SELECT status FROM overseas_registration_snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            raise ValueError("海外注册快照不存在")
        if row[0] == "superseded":
            raise ValueError("历史快照不能重新发布")
        connection.execute(
            "UPDATE overseas_registration_snapshots SET status = 'superseded' "
            "WHERE status = 'active' AND id <> ?",
            (snapshot_id,),
        )
        connection.execute(
            """
            UPDATE overseas_registration_snapshots
            SET status = 'active', published_at = CURRENT_TIMESTAMP, confirmed_by = ?
            WHERE id = ?
            """,
            (str(confirmed_by).strip(), snapshot_id),
        )
        connection.commit()
        return {"snapshot_id": snapshot_id, "status": "active"}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


async def list_overseas_registration_countries(
    session: AsyncSession,
) -> list[dict[str, int | str]]:
    result = await session.execute(
        text(
            """
            SELECT relation.country_code, COUNT(*) AS relation_count
            FROM overseas_registration_relations relation
            JOIN overseas_registration_snapshots snapshot
              ON snapshot.id = relation.snapshot_id AND snapshot.status = 'active'
            GROUP BY relation.country_code
            ORDER BY relation.country_code
            """
        )
    )
    return [dict(row._mapping) for row in result]


async def list_overseas_registration_relations(
    session: AsyncSession,
    *,
    country_code: str | None,
    query: str | None,
    skip: int,
    limit: int,
) -> tuple[list[dict], int]:
    cleaned_query = str(query or "").strip()
    params = {
        "country_code": country_code or None,
        "search_pattern": f"%{cleaned_query}%" if cleaned_query else None,
        "skip": skip,
        "limit": limit,
    }
    filters = """
        snapshot.status = 'active'
        AND (:country_code IS NULL OR relation.country_code = :country_code)
        AND (
            :search_pattern IS NULL
            OR relation.model_name LIKE :search_pattern
            OR relation.probe_model LIKE :search_pattern
        )
    """
    total_result = await session.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM overseas_registration_relations relation
            JOIN overseas_registration_snapshots snapshot ON snapshot.id = relation.snapshot_id
            WHERE {filters}
            """
        ),
        params,
    )
    result = await session.execute(
        text(
            f"""
            SELECT relation.id, relation.country_code, relation.model_name,
                   relation.probe_model, relation.registration_status,
                   relation.address_version, relation.source_ref,
                   relation.model_match_status, relation.product_model_id,
                   relation.probe_match_status, relation.probe_model_id,
                   snapshot.id AS snapshot_id, snapshot.snapshot_date,
                   snapshot.source_document_id,
                   'registration_history' AS data_scope,
                   0 AS visible_in_current_config
            FROM overseas_registration_relations relation
            JOIN overseas_registration_snapshots snapshot ON snapshot.id = relation.snapshot_id
            WHERE {filters}
            ORDER BY relation.country_code, relation.model_name, relation.probe_model
            LIMIT :limit OFFSET :skip
            """
        ),
        params,
    )
    items = []
    for row in result:
        item = dict(row._mapping)
        item["visible_in_current_config"] = bool(item["visible_in_current_config"])
        items.append(item)
    return items, int(total_result.scalar_one())
