"""Generic review records for correcting extracted source rows without changing originals."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.overseas_registration_preview import OverseasRegistrationPreview


DATA_TYPE_OVERSEAS_REGISTRATION = "overseas_registration_row"
REVIEW_STATUSES = {"auto_ready", "needs_review", "corrected", "confirmed", "excluded"}
_OVERSEAS_EDITABLE_FIELDS = {
    "jurisdiction_raw",
    "jurisdiction_name",
    "jurisdiction_code",
    "authority",
    "registration_status",
    "address_version",
    "model_raw",
    "probe_raw",
}


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    return json.loads(value)


def migrate_data_review_schema(database_path: str | Path) -> None:
    """Create the reusable review layer; existing business tables remain unchanged."""

    database = Path(database_path).expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS data_review_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL
                    REFERENCES knowledge_documents(id) ON DELETE CASCADE,
                data_type TEXT NOT NULL,
                batch_id INTEGER NOT NULL,
                source_record_key TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                raw_payload_json TEXT NOT NULL,
                effective_payload_json TEXT NOT NULL,
                issue_codes_json TEXT NOT NULL DEFAULT '[]',
                review_status TEXT NOT NULL DEFAULT 'auto_ready'
                    CHECK (review_status IN (
                        'auto_ready', 'needs_review', 'corrected', 'confirmed', 'excluded'
                    )),
                updated_by TEXT,
                change_note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (data_type, batch_id, source_record_key)
            );

            CREATE TABLE IF NOT EXISTS data_review_revisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_item_id INTEGER NOT NULL
                    REFERENCES data_review_items(id) ON DELETE CASCADE,
                revision_no INTEGER NOT NULL,
                before_payload_json TEXT NOT NULL,
                after_payload_json TEXT NOT NULL,
                action TEXT NOT NULL,
                change_note TEXT,
                changed_by TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (review_item_id, revision_no)
            );

            CREATE INDEX IF NOT EXISTS ix_data_review_batch
            ON data_review_items(data_type, batch_id);
            CREATE INDEX IF NOT EXISTS ix_data_review_status
            ON data_review_items(review_status);
            CREATE INDEX IF NOT EXISTS ix_data_review_document
            ON data_review_items(document_id);
            CREATE INDEX IF NOT EXISTS ix_data_review_revisions_item
            ON data_review_revisions(review_item_id);
            COMMIT;
            """
        )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"数据审核层迁移引入外键异常：{violations}")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _overseas_payload(record) -> dict[str, Any]:
    raw = asdict(record)
    return {key: raw.get(key) for key in _OVERSEAS_EDITABLE_FIELDS}


def stage_overseas_preview_review_items(
    database_path: str | Path,
    *,
    snapshot_id: int,
    source_document_id: int,
    preview: OverseasRegistrationPreview,
    _connection: sqlite3.Connection | None = None,
) -> dict[str, int]:
    """Stage every original workbook row, including rows excluded from projection."""

    database = Path(database_path).expanduser().resolve()
    if _connection is None:
        migrate_data_review_schema(database)
    connection = _connection or sqlite3.connect(database)
    owns_connection = _connection is None
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        snapshot = connection.execute(
            """
            SELECT source_document_id FROM overseas_registration_snapshots
            WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone()
        if snapshot is None or int(snapshot[0]) != source_document_id:
            raise ValueError("审核批次与受控原件不匹配")
        for record in preview.records:
            payload = _overseas_payload(record)
            connection.execute(
                """
                INSERT INTO data_review_items (
                    document_id, data_type, batch_id, source_record_key, source_ref,
                    raw_payload_json, effective_payload_json, issue_codes_json,
                    review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(data_type, batch_id, source_record_key) DO NOTHING
                """,
                (
                    source_document_id,
                    DATA_TYPE_OVERSEAS_REGISTRATION,
                    snapshot_id,
                    record.source_ref,
                    record.source_ref,
                    _json_dump(payload),
                    _json_dump(payload),
                    _json_dump(list(record.issue_codes)),
                    "auto_ready" if record.ready_for_import else "needs_review",
                ),
            )
        if owns_connection:
            connection.commit()
        return {
            "item_count": len(preview.records),
            "needs_review_count": sum(not record.ready_for_import for record in preview.records),
        }
    except Exception:
        if owns_connection:
            connection.rollback()
        raise
    finally:
        if owns_connection:
            connection.close()


def _item_from_mapping(row) -> dict[str, Any]:
    item = dict(row)
    item["raw_payload"] = _json_load(item.pop("raw_payload_json"), {})
    item["effective_payload"] = _json_load(item.pop("effective_payload_json"), {})
    item["issue_codes"] = _json_load(item.pop("issue_codes_json"), [])
    item["preview_url"] = f"/api/knowledge/documents/{item['document_id']}/preview"
    return item


async def list_data_review_batches(session: AsyncSession) -> list[dict[str, Any]]:
    result = await session.execute(
        text(
            """
            SELECT item.data_type, item.batch_id, item.document_id,
                   document.title AS document_title,
                   document.document_type, document.market,
                   snapshot.status AS batch_status, snapshot.snapshot_date,
                   COUNT(*) AS total_count,
                   SUM(CASE WHEN item.review_status = 'needs_review' THEN 1 ELSE 0 END)
                       AS needs_review_count,
                   SUM(CASE WHEN item.review_status = 'corrected' THEN 1 ELSE 0 END)
                       AS corrected_count,
                   SUM(CASE WHEN item.review_status = 'excluded' THEN 1 ELSE 0 END)
                       AS excluded_count
            FROM data_review_items item
            JOIN knowledge_documents document ON document.id = item.document_id
            LEFT JOIN overseas_registration_snapshots snapshot
              ON item.data_type = 'overseas_registration_row'
             AND snapshot.id = item.batch_id
            GROUP BY item.data_type, item.batch_id, item.document_id,
                     document.title, document.document_type, document.market,
                     snapshot.status, snapshot.snapshot_date
            ORDER BY MAX(item.created_at) DESC, item.batch_id DESC
            """
        )
    )
    items = [dict(row._mapping) for row in result]
    for item in items:
        item["preview_url"] = f"/api/knowledge/documents/{item['document_id']}/preview"
    return items


async def list_data_review_items(
    session: AsyncSession,
    *,
    data_type: str,
    batch_id: int,
    review_status: str | None,
    query: str | None,
    skip: int,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    cleaned_query = str(query or "").strip()
    params = {
        "data_type": data_type,
        "batch_id": batch_id,
        "review_status": review_status,
        "query": f"%{cleaned_query}%" if cleaned_query else None,
        "skip": skip,
        "limit": limit,
    }
    filters = """
        item.data_type = :data_type AND item.batch_id = :batch_id
        AND (:review_status IS NULL OR item.review_status = :review_status)
        AND (
            :query IS NULL OR item.source_ref LIKE :query
            OR item.raw_payload_json LIKE :query
            OR item.effective_payload_json LIKE :query
        )
    """
    total_result = await session.execute(
        text(f"SELECT COUNT(*) FROM data_review_items item WHERE {filters}"), params
    )
    result = await session.execute(
        text(
            f"""
            SELECT item.*, document.title AS document_title
            FROM data_review_items item
            JOIN knowledge_documents document ON document.id = item.document_id
            WHERE {filters}
            ORDER BY item.id
            LIMIT :limit OFFSET :skip
            """
        ),
        params,
    )
    return [_item_from_mapping(row._mapping) for row in result], int(total_result.scalar_one())


def _validate_payload(data_type: str, payload: dict[str, Any]) -> None:
    if data_type != DATA_TYPE_OVERSEAS_REGISTRATION:
        raise ValueError("当前材料类型尚未配置可编辑字段")
    unknown = set(payload) - _OVERSEAS_EDITABLE_FIELDS
    if unknown:
        raise ValueError(f"包含不可编辑字段：{', '.join(sorted(unknown))}")
    required = ("jurisdiction_code", "registration_status", "model_raw", "probe_raw")
    if any(not str(payload.get(field) or "").strip() for field in required):
        raise ValueError("国家、注册状态、机型和探头不能为空")


def revise_data_review_item(
    database_path: str | Path,
    *,
    item_id: int,
    effective_payload: dict[str, Any],
    review_status: str,
    changed_by: str,
    change_note: str | None,
) -> dict[str, Any]:
    """Append one correction revision while leaving the raw payload immutable."""

    if review_status not in {"corrected", "confirmed", "excluded"}:
        raise ValueError("修正状态必须为已修正、已确认或已排除")
    actor = str(changed_by or "").strip()
    if not actor:
        raise ValueError("修改人不能为空")
    note = str(change_note or "").strip() or None
    database = Path(database_path).expanduser().resolve()
    migrate_data_review_schema(database)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        row = connection.execute(
            "SELECT * FROM data_review_items WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise ValueError("待审核数据不存在")
        if row["data_type"] == DATA_TYPE_OVERSEAS_REGISTRATION:
            snapshot = connection.execute(
                "SELECT status FROM overseas_registration_snapshots WHERE id = ?",
                (row["batch_id"],),
            ).fetchone()
            if snapshot is None or snapshot[0] != "draft":
                raise ValueError("已发布数据需先创建新修订草稿")
        _validate_payload(str(row["data_type"]), effective_payload)
        before_json = str(row["effective_payload_json"])
        after_json = _json_dump(effective_payload)
        revision_no = int(
            connection.execute(
                """
                SELECT COALESCE(MAX(revision_no), 0) + 1
                FROM data_review_revisions WHERE review_item_id = ?
                """,
                (item_id,),
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO data_review_revisions (
                review_item_id, revision_no, before_payload_json,
                after_payload_json, action, change_note, changed_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                revision_no,
                before_json,
                after_json,
                review_status,
                note,
                actor,
            ),
        )
        connection.execute(
            """
            UPDATE data_review_items
            SET effective_payload_json = ?, review_status = ?, updated_by = ?,
                change_note = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (after_json, review_status, actor, note, item_id),
        )
        connection.commit()
        updated = connection.execute(
            """
            SELECT item.*, document.title AS document_title
            FROM data_review_items item
            JOIN knowledge_documents document ON document.id = item.document_id
            WHERE item.id = ?
            """,
            (item_id,),
        ).fetchone()
        return _item_from_mapping(updated)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_data_review_item_history(
    database_path: str | Path, *, item_id: int
) -> list[dict[str, Any]]:
    connection = sqlite3.connect(Path(database_path).expanduser().resolve())
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT revision_no, before_payload_json, after_payload_json,
                   action, change_note, changed_by, created_at
            FROM data_review_revisions
            WHERE review_item_id = ? ORDER BY revision_no DESC
            """,
            (item_id,),
        ).fetchall()
        return [
            {
                **dict(row),
                "before_payload": _json_load(row["before_payload_json"], {}),
                "after_payload": _json_load(row["after_payload_json"], {}),
            }
            for row in rows
        ]
    finally:
        connection.close()
