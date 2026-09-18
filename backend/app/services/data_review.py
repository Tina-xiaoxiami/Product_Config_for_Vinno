"""Generic review records for correcting extracted source rows without changing originals."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge_qa import normalize_question
from app.services.overseas_registration_preview import OverseasRegistrationPreview


DATA_TYPE_OVERSEAS_REGISTRATION = "overseas_registration_row"
DATA_TYPE_KNOWLEDGE_DOCUMENT_CHUNK = "knowledge_document_chunk"
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
_CHUNK_EDITABLE_FIELDS = {"content"}


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


_NON_FORMAL_NOTE = "注册状态非「已完成注册」，自动排除：仅保留记录，不作为正式数据"
# 逐状态的排除原因：把「该国无需注册」和「进行中」写成同一句话，
# 会让人误以为无需注册还是个待办事项。
_NARRATIVE_CONCLUSION_NOTE = (
    "整行是结论性说明（如「有证书即可销售，所有机型适用」），"
    "自动排除：仅保留记录，不作为正式数据"
)
_NON_FORMAL_NOTES = {
    "not_required": "该国无需注册，自动排除：仅保留记录，不作为正式数据",
    "failed": "注册未成功，自动排除：仅保留记录，不作为正式数据",
    "suspended": "注册已暂停或停止，自动排除：仅保留记录，不作为正式数据",
    "in_progress": "注册进行中（尚未拿证），自动排除：仅保留记录，不作为正式数据",
    "new_address_scope": "新地址登记（尚未拿证），自动排除：仅保留记录，不作为正式数据",
}


def _non_formal_note(status: object, issue_codes=()) -> str:
    if "narrative_conclusion" in tuple(issue_codes or ()):
        return _NARRATIVE_CONCLUSION_NOTE
    return _NON_FORMAL_NOTES.get(str(status or ""), _NON_FORMAL_NOTE)


def _overseas_review_status(record) -> str:
    """非「已完成注册」的行只作记录保留，不进待确认队列。

    这类行本来就不生成正式数据（关系数据只在 ``ready_for_import`` 时构建），
    再要求人工逐条确认没有意义，只会把待确认队列淹没。整行是结论性说明
    （如「有证书即可销售，所有机型适用」）的行同理。
    """

    if "narrative_conclusion" in tuple(getattr(record, "issue_codes", ()) or ()):
        return "excluded"
    if str(getattr(record, "registration_status", "") or "") != "completed":
        return "excluded"
    return "auto_ready" if record.ready_for_import else "needs_review"


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
            review_status = _overseas_review_status(record)
            connection.execute(
                """
                INSERT INTO data_review_items (
                    document_id, data_type, batch_id, source_record_key, source_ref,
                    raw_payload_json, effective_payload_json, issue_codes_json,
                    review_status, change_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    review_status,
                    (
                        _non_formal_note(
                            record.registration_status, record.issue_codes
                        )
                        if review_status == "excluded"
                        else None
                    ),
                ),
            )
        if owns_connection:
            connection.commit()
        return {
            "item_count": len(preview.records),
            "needs_review_count": sum(
                1
                for record in preview.records
                if _overseas_review_status(record) == "needs_review"
            ),
        }
    except Exception:
        if owns_connection:
            connection.rollback()
        raise
    finally:
        if owns_connection:
            connection.close()


def stage_knowledge_document_review_items(
    database_path: str | Path,
    *,
    document_id: int,
    _connection: sqlite3.Connection | None = None,
) -> dict[str, int]:
    """Stage every extracted body chunk of one controlled document for review."""

    database = Path(database_path).expanduser().resolve()
    if _connection is None:
        migrate_data_review_schema(database)
    connection = _connection or sqlite3.connect(database)
    owns_connection = _connection is None
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        document = connection.execute(
            "SELECT id FROM knowledge_documents WHERE id = ?", (document_id,)
        ).fetchone()
        if document is None:
            raise ValueError("待审核原件不存在")
        chunks = connection.execute(
            """
            SELECT id, source_ref, content
            FROM knowledge_document_chunks
            WHERE document_id = ?
            ORDER BY chunk_index, id
            """,
            (document_id,),
        ).fetchall()
        for chunk_id, source_ref, content in chunks:
            payload = {"content": content}
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
                    document_id,
                    DATA_TYPE_KNOWLEDGE_DOCUMENT_CHUNK,
                    document_id,
                    str(chunk_id),
                    source_ref,
                    _json_dump(payload),
                    _json_dump(payload),
                    _json_dump([]),
                    "auto_ready",
                ),
            )
        if owns_connection:
            connection.commit()
        return {"item_count": len(chunks), "needs_review_count": 0}
    except Exception:
        if owns_connection:
            connection.rollback()
        raise
    finally:
        if owns_connection:
            connection.close()


BATCH_REVIEW_LIMIT = 50
# 批量只允许「确认」和「排除」：改值必须逐条改，否则会把整类行写成同一个值。
_BATCH_REVIEW_STATUSES = ("confirmed", "excluded")


def _batchable(data_type: str) -> None:
    if data_type != DATA_TYPE_OVERSEAS_REGISTRATION:
        raise ValueError("当前材料类型尚未配置批量审核")


def _issue_codes_of(row) -> tuple[str, ...]:
    values = _json_load(row["issue_codes_json"], [])
    if not isinstance(values, list):
        return ()
    return tuple(str(value) for value in values if str(value).strip())


def _open_review_connection(database_path: str | Path, batch_id: int):
    """打开审核批次并确认它还能改：冻结批次直接拒绝，而不是让用户点了才报错。"""

    database = Path(database_path).expanduser().resolve()
    migrate_data_review_schema(database)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    snapshot = connection.execute(
        """
        SELECT id, status, snapshot_date FROM overseas_registration_snapshots
        WHERE id = ?
        """,
        (batch_id,),
    ).fetchone()
    if snapshot is None:
        connection.close()
        raise ValueError("审核批次不存在")
    if snapshot["status"] != "draft":
        connection.close()
        raise ValueError("该批次已发布冻结，不能批量审核；如需修订请更新源表后重新导入并发布新版本")
    return connection, snapshot


def summarize_data_review_issues(
    database_path: str | Path, *, data_type: str, batch_id: int
) -> dict[str, Any]:
    """按问题类型（issue_code）汇总一个批次的待修正条数。

    一个待修正行常常同时带多个问题码（例如「机型范围待展开 + 机型名称待修正」），
    所以同一行会在每个命中的问题码下各计一次，`issues` 的合计会大于
    `needs_review_total`，这是正常的。
    """

    _batchable(data_type)
    database = Path(database_path).expanduser().resolve()
    migrate_data_review_schema(database)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        snapshot = connection.execute(
            """
            SELECT id, status, snapshot_date FROM overseas_registration_snapshots
            WHERE id = ?
            """,
            (batch_id,),
        ).fetchone()
        if snapshot is None:
            raise ValueError("审核批次不存在")
        rows = connection.execute(
            """
            SELECT issue_codes_json, review_status FROM data_review_items
            WHERE data_type = ? AND batch_id = ?
            """,
            (data_type, batch_id),
        ).fetchall()
        counts: dict[str, int] = {}
        needs_review_total = 0
        for row in rows:
            if row["review_status"] != "needs_review":
                continue
            needs_review_total += 1
            for code in _issue_codes_of(row):
                counts[code] = counts.get(code, 0) + 1
        return {
            "data_type": data_type,
            "batch_id": batch_id,
            "batch_status": snapshot["status"],
            "snapshot_date": snapshot["snapshot_date"],
            "editable": snapshot["status"] == "draft",
            "needs_review_total": needs_review_total,
            "issues": [
                {"issue_code": code, "needs_review_count": counts[code]}
                for code in sorted(counts, key=lambda value: (-counts[value], value))
            ],
        }
    finally:
        connection.close()


def _batch_note(review_status: str, *, issue_codes, matched: int) -> str:
    label = "确认" if review_status == "confirmed" else "排除"
    codes = [str(code) for code in (issue_codes or []) if str(code).strip()]
    scope = "、".join(codes) if codes else "全部待修正行"
    return f"批量{label}｜问题类型：{scope}｜本次 {matched} 条"


def _preview_item(row) -> dict[str, Any]:
    payload = _json_load(row["effective_payload_json"], {})
    return {
        "id": int(row["id"]),
        "source_ref": row["source_ref"],
        "issue_codes": list(_issue_codes_of(row)),
        "review_status": row["review_status"],
        "jurisdiction_name": payload.get("jurisdiction_name"),
        "jurisdiction_code": payload.get("jurisdiction_code"),
        "registration_status": payload.get("registration_status"),
        "model_raw": payload.get("model_raw"),
        "probe_raw": payload.get("probe_raw"),
    }


def batch_revise_data_review_items(
    database_path: str | Path,
    *,
    data_type: str,
    batch_id: int,
    review_status: str,
    changed_by: str | None = None,
    change_note: str | None = None,
    issue_codes: list[str] | None = None,
    item_ids: list[int] | None = None,
    source_refs: list[str] | None = None,
    confirm_count: int | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """按问题类型批量确认或排除待修正行，并逐条留痕。

    与逐条修正同一套纪律，只是把动作放大到一类行：

    - 只处理 `needs_review` 行，自动可用 / 已排除 / 已确认的记录不会被覆盖；
    - 默认只预览（`dry_run=True`），显式落库才写；
    - 预览不要求填修改人，落库必填并写进每一条留痕；
    - 每条仍写一行 `data_review_revisions`，`change_note` 带上批量口径，
      因此「这一行是哪一次批量动作改的」永远可查；
    - 命中条数超过 `BATCH_REVIEW_LIMIT` 时必须回传相同数字的 `confirm_count`。
    """

    _batchable(data_type)
    status = str(review_status or "").strip()
    if status not in _BATCH_REVIEW_STATUSES:
        raise ValueError("批量状态只支持已确认或已排除；改值仍需逐条修正")

    # 先判批次能不能改：冻结批次要报「已发布冻结」，而不是先报缺修改人，
    # 否则用户填完修改人才知道这一批根本改不了。
    connection, snapshot = _open_review_connection(database_path, batch_id)
    try:
        actor = str(changed_by or "").strip()
        if not actor and not dry_run:
            raise ValueError("修改人不能为空")
        rows = connection.execute(
            """
            SELECT * FROM data_review_items
            WHERE data_type = ? AND batch_id = ? AND review_status = 'needs_review'
            ORDER BY id
            """,
            (data_type, batch_id),
        ).fetchall()
        codes = {str(code) for code in (issue_codes or []) if str(code).strip()}
        wanted_ids = {int(value) for value in (item_ids or [])}
        wanted_refs = {str(value) for value in (source_refs or []) if str(value).strip()}
        matched = []
        for row in rows:
            if wanted_ids and int(row["id"]) not in wanted_ids:
                continue
            if wanted_refs and row["source_ref"] not in wanted_refs:
                continue
            if codes and not codes & set(_issue_codes_of(row)):
                continue
            matched.append(row)

        by_issue: dict[str, int] = {}
        for row in matched:
            for code in _issue_codes_of(row):
                if codes and code not in codes:
                    continue
                by_issue[code] = by_issue.get(code, 0) + 1

        count = len(matched)
        note = str(change_note or "").strip() or _batch_note(
            status, issue_codes=sorted(codes) or None, matched=count
        )
        result: dict[str, Any] = {
            "data_type": data_type,
            "batch_id": batch_id,
            "batch_status": snapshot["status"],
            "editable": True,
            "applied": False,
            "dry_run": bool(dry_run),
            "review_status": status,
            "action": f"batch_{status}",
            "change_note": note,
            "matched": count,
            "limit": BATCH_REVIEW_LIMIT,
            "requires_confirm_count": count > BATCH_REVIEW_LIMIT,
            "needs_review_total": len(rows),
            "by_issue": [
                {"issue_code": code, "matched": by_issue[code]}
                for code in sorted(by_issue, key=lambda value: (-by_issue[value], value))
            ],
            "items": [_preview_item(row) for row in matched],
        }
        if count > BATCH_REVIEW_LIMIT and confirm_count != count:
            raise ValueError(
                f"本次将影响 {count} 条记录，超过 {BATCH_REVIEW_LIMIT} 条，"
                f"需要回传确认条数 confirm_count={count} 才能执行"
            )
        if dry_run or not matched:
            return result

        for row in matched:
            item_id = int(row["id"])
            before_json = str(row["effective_payload_json"])
            revision_no = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(revision_no), 0) + 1
                    FROM data_review_revisions WHERE review_item_id = ?
                    """,
                    (item_id,),
                ).fetchone()[0]
            )
            # 留痕的 action 沿用审核状态本身（与逐条修正同一口径），
            # 「这一次是批量动作」由 change_note 里的「批量确认｜问题类型：…」标明。
            connection.execute(
                """
                INSERT INTO data_review_revisions (
                    review_item_id, revision_no, before_payload_json,
                    after_payload_json, action, change_note, changed_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (item_id, revision_no, before_json, before_json, status, note, actor),
            )
            connection.execute(
                """
                UPDATE data_review_items
                SET review_status = ?, updated_by = ?, change_note = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, actor, note, item_id),
            )
        connection.commit()
        stored = connection.execute(
            """
            SELECT * FROM data_review_items WHERE id IN ({})
            ORDER BY id
            """.format(",".join("?" for _ in matched)),
            [int(row["id"]) for row in matched],
        ).fetchall()
        result["items"] = [_preview_item(row) for row in stored]
        result["applied"] = True
        result["dry_run"] = False
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
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
    if data_type == DATA_TYPE_KNOWLEDGE_DOCUMENT_CHUNK:
        unknown = set(payload) - _CHUNK_EDITABLE_FIELDS
        if unknown:
            raise ValueError(f"包含不可编辑字段：{', '.join(sorted(unknown))}")
        if not str(payload.get("content") or "").strip():
            raise ValueError("识别正文不能为空")
        return
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
        if row["data_type"] == DATA_TYPE_KNOWLEDGE_DOCUMENT_CHUNK:
            corrected_content = str(effective_payload.get("content") or "")
            connection.execute(
                """
                UPDATE knowledge_document_chunks
                SET content = ?, normalized_content = ?, content_hash = ?
                WHERE id = ? AND document_id = ?
                """,
                (
                    corrected_content,
                    normalize_question(corrected_content),
                    hashlib.sha256(corrected_content.encode("utf-8")).hexdigest(),
                    int(row["source_record_key"]),
                    int(row["document_id"]),
                ),
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
