"""功能版本与发布介绍的服务层。

对外回答两类问题：

1. 某个功能在哪个版本发布（`first_release`，由已确认的功能版本按版本键排序得出）；
2. 某个版本发布了哪些功能（`list_versions_by_software_version`）。

所有候选行先以 `pending` 落库，人工确认（`confirmed`）后才进入正式结论；
`earliest_ingested_version` 用来提示「已纳管 Release Note 的最早版本」，
避免把「资料中最早出现」误读成「首发」。
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import unicodedata
import uuid
from pathlib import Path

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.release import (
    FEATURE_VERSION_CHANGE_TYPES,
    FEATURE_VERSION_LIFECYCLE_STATUSES,
    FEATURE_VERSION_REVIEW_STATUSES,
    RELEASE_INTRODUCTION_REVIEW_STATUSES,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
RELEASE_ATTACHMENT_ROOT = BACKEND_ROOT / "release_attachments"

_NUMERIC_VERSION = re.compile(r"^\d+(?:\.\d+)*$")
_NUMERIC_UNSORTED = "0"
_TEXT_UNSORTED = "1"


class FeatureReleaseError(ValueError):
    """Raised when a release row or introduction violates the release rules."""


class FeatureReleaseNotFoundError(FeatureReleaseError):
    """Raised when the requested feature, version or attachment does not exist."""


class FeatureReleaseAttachmentError(FeatureReleaseError):
    """Raised when an attachment path escapes the release attachment root."""


def version_sort_key(version: str | None) -> str:
    """Return a lexicographically sortable key for a software version.

    Numeric software versions sort numerically ("1.4.80" < "1.14.20" < "1.14.100");
    anything that is not a dotted number (manual revisions such as "R10", empty
    values) sorts after every numeric version so it never becomes a "first release".
    """

    cleaned = unicodedata.normalize("NFKC", str(version or "")).strip()
    if _NUMERIC_VERSION.match(cleaned):
        parts = cleaned.split(".")
        return _NUMERIC_UNSORTED + ".".join(f"{int(part):05d}" for part in parts)
    return _TEXT_UNSORTED + cleaned.casefold()


def _normalize_scope(value: str | None) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _clean_required(value: str | None, field: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise FeatureReleaseError(f"{field} 不能为空")
    return cleaned


def _clean_release_date(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", cleaned):
        raise FeatureReleaseError("发布日期必须写成 YYYY-MM-DD")
    return cleaned


def _validate_change_type(value: str | None) -> str:
    cleaned = str(value or "").strip() or "unknown"
    if cleaned not in FEATURE_VERSION_CHANGE_TYPES:
        raise FeatureReleaseError(f"未知的变更类型：{cleaned}")
    return cleaned


def _validate_choice(value: str | None, allowed: tuple[str, ...], field: str) -> str:
    cleaned = str(value or "").strip()
    if cleaned not in allowed:
        raise FeatureReleaseError(f"{field} 取值非法：{cleaned}")
    return cleaned


_ROW_COLUMNS = """
    version.id, version.feature_id, version.software_version,
    version.version_sort_key, version.product_series, version.market,
    version.release_date, version.change_type, version.configuration_status,
    version.evidence_document_id, version.evidence_source_ref,
    version.evidence_excerpt, version.evidence_kind, version.matched_by,
    version.lifecycle_status, version.source, version.review_status,
    version.change_note, version.created_at, version.updated_at,
    document.title AS evidence_document_title,
    document.version AS evidence_document_version,
    introduction.id AS introduction_id,
    introduction.version AS introduction_version,
    introduction.review_status AS introduction_review_status,
    SUBSTR(COALESCE(introduction.summary, ''), 1, 200) AS introduction_preview
"""


def _row_payload(row) -> dict:
    return {
        "id": int(row.id),
        "feature_id": int(row.feature_id),
        "software_version": row.software_version,
        "version_sort_key": row.version_sort_key,
        "product_series": row.product_series or "",
        "market": row.market,
        "release_date": row.release_date,
        "change_type": row.change_type,
        "configuration_status": row.configuration_status,
        "lifecycle_status": row.lifecycle_status,
        "evidence_document_id": (
            int(row.evidence_document_id) if row.evidence_document_id else None
        ),
        "evidence_document_title": row.evidence_document_title,
        "evidence_document_version": row.evidence_document_version,
        "evidence_source_ref": row.evidence_source_ref,
        "evidence_excerpt": row.evidence_excerpt,
        "evidence_kind": row.evidence_kind,
        "matched_by": row.matched_by,
        "source": row.source,
        "review_status": row.review_status,
        "change_note": row.change_note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "introduction_id": int(row.introduction_id) if row.introduction_id else None,
        "introduction_version": (
            int(row.introduction_version) if row.introduction_version else None
        ),
        "introduction_review_status": row.introduction_review_status,
        "introduction_preview": row.introduction_preview,
        "preview_url": (
            f"/api/knowledge/documents/{int(row.evidence_document_id)}/preview"
            if row.evidence_document_id
            else None
        ),
    }


# 留痕快照只记录功能版本自身的字段：联表带出的文档标题、发布介绍摘要属于派生
# 信息，放进快照会让 diff 出现与本次修改无关的噪声。
_AUDIT_FIELDS = (
    "feature_id",
    "software_version",
    "version_sort_key",
    "product_series",
    "market",
    "release_date",
    "change_type",
    "configuration_status",
    "lifecycle_status",
    "evidence_document_id",
    "evidence_source_ref",
    "evidence_excerpt",
    "evidence_kind",
    "matched_by",
    "source",
    "review_status",
    "change_note",
)

# 超过这个条数的批量复核必须回传确认条数，避免手滑一次改掉整库。
BATCH_REVIEW_LIMIT = 50


def _json_load(value: str | None) -> dict:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except ValueError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _audit_snapshot(item: dict) -> str:
    return json.dumps(
        {field: item.get(field) for field in _AUDIT_FIELDS},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _revision_action(current: dict, updated: dict) -> str:
    """只改复核状态时按状态命名动作，其余一律记为单条修改。"""

    changed = {
        field for field in _AUDIT_FIELDS if current.get(field) != updated.get(field)
    }
    if changed == {"review_status"} and updated.get("review_status") in (
        "confirmed",
        "rejected",
    ):
        return str(updated["review_status"])
    return "updated"


async def _next_revision_numbers(
    session: AsyncSession, version_ids: list[int]
) -> dict[int, int]:
    """一次查出多条记录的最大留痕序号，批量确认时不必逐条查询。"""

    if not version_ids:
        return {}
    result = await session.execute(
        text(
            """
            SELECT feature_version_id, COALESCE(MAX(revision_no), 0) AS last_no
            FROM feature_version_revisions
            WHERE feature_version_id IN :version_ids
            GROUP BY feature_version_id
            """
        ).bindparams(bindparam("version_ids", expanding=True)),
        {"version_ids": version_ids},
    )
    return {int(row.feature_version_id): int(row.last_no) for row in result}


async def _append_revisions(
    session: AsyncSession,
    *,
    entries: list[dict],
    action: str,
    change_note: str | None,
    changed_by: str | None,
) -> int:
    """为每条记录追加一条不可变快照，返回写入条数。"""

    if not entries:
        return 0
    numbers = await _next_revision_numbers(
        session, [int(entry["id"]) for entry in entries]
    )
    for entry in entries:
        version_id = int(entry["id"])
        numbers[version_id] = numbers.get(version_id, 0) + 1
        await session.execute(
            text(
                """
                INSERT INTO feature_version_revisions (
                    feature_version_id, revision_no, action,
                    before_json, after_json, change_note, changed_by
                ) VALUES (
                    :feature_version_id, :revision_no, :action,
                    :before_json, :after_json, :change_note, :changed_by
                )
                """
            ),
            {
                "feature_version_id": version_id,
                "revision_no": numbers[version_id],
                "action": action,
                "before_json": entry.get("before_json"),
                "after_json": entry["after_json"],
                "change_note": change_note,
                "changed_by": changed_by,
            },
        )
    return len(entries)


async def list_feature_version_revisions(
    session: AsyncSession, version_id: int
) -> list[dict]:
    """一条功能版本的全部留痕，最新在前。"""

    await get_feature_version(session, version_id)
    result = await session.execute(
        text(
            """
            SELECT revision_no, action, before_json, after_json,
                   change_note, changed_by, created_at
            FROM feature_version_revisions
            WHERE feature_version_id = :version_id
            ORDER BY revision_no DESC
            """
        ),
        {"version_id": version_id},
    )
    return [
        {
            "revision_no": int(row.revision_no),
            "action": row.action,
            "before": _json_load(row.before_json),
            "after": _json_load(row.after_json),
            "change_note": row.change_note,
            "changed_by": row.changed_by,
            "created_at": row.created_at,
        }
        for row in result
    ]


async def _feature_row(session: AsyncSession, feature_id: int):
    result = await session.execute(
        text(
            """
            SELECT feature.id, feature.name, feature.primary_cn_name,
                   feature.primary_en_name, feature.ipn, feature.identity_status
            FROM features feature
            WHERE feature.id = :feature_id
            """
        ),
        {"feature_id": feature_id},
    )
    return result.one_or_none()


async def _feature_versions(session: AsyncSession, feature_id: int) -> list[dict]:
    result = await session.execute(
        text(
            f"""
            SELECT {_ROW_COLUMNS}
            FROM feature_versions version
            LEFT JOIN knowledge_documents document
              ON document.id = version.evidence_document_id
            LEFT JOIN release_introductions introduction
              ON introduction.feature_version_id = version.id
            WHERE version.feature_id = :feature_id
            ORDER BY version.version_sort_key, version.id
            """
        ),
        {"feature_id": feature_id},
    )
    return [_row_payload(row) for row in result]


async def _earliest_ingested_version(
    session: AsyncSession,
    *,
    product_series: str | None = None,
) -> str | None:
    """已纳管 Release Note 中最早的软件版本，用于提示覆盖边界。"""

    result = await session.execute(
        text(
            """
            SELECT DISTINCT version
            FROM knowledge_documents
            WHERE document_type = 'release_note'
              AND source_status = 'active'
              AND version IS NOT NULL
              AND (:product_series = '' OR product_series = :product_series)
            """
        ),
        {"product_series": _normalize_scope(product_series)},
    )
    versions = [row.version for row in result if row.version]
    if not versions:
        return None
    return min(versions, key=version_sort_key)


async def get_feature_release_timeline(
    session: AsyncSession,
    feature_id: int,
    *,
    product_series: str | None = None,
) -> dict | None:
    """Return one feature's release timeline plus its first release version."""

    feature = await _feature_row(session, feature_id)
    if feature is None:
        return None

    scope = _normalize_scope(product_series)
    items = await _feature_versions(session, feature_id)
    if scope:
        items = [
            item
            for item in items
            if item["product_series"] in ("", scope)
        ]

    confirmed = [item for item in items if item["review_status"] == "confirmed"]
    pending = [item for item in items if item["review_status"] == "pending"]
    first_release = confirmed[0] if confirmed else None
    first_candidate = None
    if first_release is None and pending:
        first_candidate = min(pending, key=lambda item: item["version_sort_key"])

    series_for_coverage = scope or (first_release or {}).get("product_series") or ""
    earliest = await _earliest_ingested_version(
        session, product_series=series_for_coverage
    )
    coverage_note = ""
    if earliest:
        coverage_note = (
            f"已纳管 Release Note 最早版本为 {earliest}；"
            f"该版本之前的既有功能无法判定首发版本。"
        )

    return {
        "feature": {
            "id": int(feature.id),
            "legacy_name": feature.name,
            "ipn": feature.ipn,
            "primary_cn_name": feature.primary_cn_name,
            "primary_en_name": feature.primary_en_name,
            "identity_status": feature.identity_status,
        },
        "first_release": first_release,
        "first_release_candidate": first_candidate,
        "earliest_ingested_version": earliest,
        "coverage_note": coverage_note,
        "confirmed_count": len(confirmed),
        "pending_count": len(pending),
        "items": items,
    }


async def list_versions_by_software_version(
    session: AsyncSession,
    *,
    software_version: str | None = None,
    product_series: str | None = None,
    market: str | None = None,
    review_status: str | None = None,
    query: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    """Return「某个版本发布了哪些功能」的清单。"""

    params = {
        "software_version": _normalize_scope(software_version) or None,
        "product_series": _normalize_scope(product_series),
        "market": _normalize_scope(market) or None,
        "review_status": _normalize_scope(review_status) or None,
        "search_pattern": f"%{_normalize_scope(query)}%" if _normalize_scope(query) else None,
        "skip": skip,
        "limit": limit,
    }
    filters = """
        (:software_version IS NULL OR version.software_version = :software_version)
        AND (:product_series = '' OR version.product_series = :product_series)
        AND (:market IS NULL OR version.market = :market)
        AND (:review_status IS NULL OR version.review_status = :review_status)
        AND (
            :search_pattern IS NULL
            OR feature.name LIKE :search_pattern
            OR COALESCE(feature.primary_cn_name, '') LIKE :search_pattern
            OR COALESCE(feature.primary_en_name, '') LIKE :search_pattern
            OR COALESCE(feature.ipn, '') LIKE :search_pattern
        )
    """
    total_result = await session.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM feature_versions version
            JOIN features feature ON feature.id = version.feature_id
            WHERE {filters}
            """
        ),
        params,
    )
    result = await session.execute(
        text(
            f"""
            SELECT {_ROW_COLUMNS}, feature.name AS feature_name,
                   feature.primary_cn_name AS feature_primary_cn_name,
                   feature.primary_en_name AS feature_primary_en_name,
                   feature.ipn AS feature_ipn
            FROM feature_versions version
            JOIN features feature ON feature.id = version.feature_id
            LEFT JOIN knowledge_documents document
              ON document.id = version.evidence_document_id
            LEFT JOIN release_introductions introduction
              ON introduction.feature_version_id = version.id
            WHERE {filters}
            ORDER BY version.version_sort_key DESC, feature.sort_order, feature.id
            LIMIT :limit OFFSET :skip
            """
        ),
        params,
    )
    items = []
    for row in result:
        payload = _row_payload(row)
        payload["feature_name"] = row.feature_name
        payload["feature_primary_cn_name"] = row.feature_primary_cn_name
        payload["feature_primary_en_name"] = row.feature_primary_en_name
        payload["feature_ipn"] = row.feature_ipn
        items.append(payload)
    return items, int(total_result.scalar_one())


async def list_release_versions_overview(session: AsyncSession) -> list[dict]:
    """按软件版本汇总功能版本数量，供版本选择器与覆盖度检查使用。"""

    result = await session.execute(
        text(
            """
            SELECT version.software_version,
                   MIN(version.version_sort_key) AS version_sort_key,
                   COUNT(*) AS total,
                   SUM(CASE WHEN version.review_status = 'confirmed' THEN 1 ELSE 0 END)
                       AS confirmed,
                   SUM(CASE WHEN version.review_status = 'pending' THEN 1 ELSE 0 END)
                       AS pending,
                   MIN(version.release_date) AS release_date
            FROM feature_versions version
            GROUP BY version.software_version
            ORDER BY version_sort_key DESC, version.software_version DESC
            """
        )
    )
    return [
        {
            "software_version": row.software_version,
            "version_sort_key": row.version_sort_key,
            "total": int(row.total),
            "confirmed": int(row.confirmed or 0),
            "pending": int(row.pending or 0),
            "release_date": row.release_date,
        }
        for row in result
    ]


async def create_feature_version(
    session: AsyncSession,
    feature_id: int,
    *,
    software_version: str,
    product_series: str | None = None,
    market: str | None = None,
    release_date: str | None = None,
    change_type: str | None = None,
    configuration_status: str | None = None,
    lifecycle_status: str | None = None,
    evidence_document_id: int | None = None,
    evidence_source_ref: str | None = None,
    evidence_excerpt: str | None = None,
    evidence_kind: str | None = None,
    matched_by: str | None = None,
    source: str | None = None,
    review_status: str | None = None,
    change_note: str | None = None,
    changed_by: str | None = None,
) -> dict:
    feature = await _feature_row(session, feature_id)
    if feature is None:
        raise FeatureReleaseNotFoundError("功能不存在")

    version = _clean_required(software_version, "软件版本")
    scope_series = _normalize_scope(product_series)
    scope_market = _normalize_scope(market) or "domestic"
    status = _validate_choice(
        review_status or "pending", FEATURE_VERSION_REVIEW_STATUSES, "复核状态"
    )
    existing = await session.execute(
        text(
            """
            SELECT id FROM feature_versions
            WHERE feature_id = :feature_id
              AND software_version = :software_version
              AND product_series = :product_series
              AND market = :market
            """
        ),
        {
            "feature_id": feature_id,
            "software_version": version,
            "product_series": scope_series,
            "market": scope_market,
        },
    )
    if existing.one_or_none() is not None:
        raise FeatureReleaseError("该功能在此版本与系列下已有记录")

    result = await session.execute(
        text(
            """
            INSERT INTO feature_versions (
                feature_id, software_version, version_sort_key, product_series,
                market, release_date, change_type, configuration_status,
                lifecycle_status, evidence_document_id, evidence_source_ref,
                evidence_excerpt, evidence_kind, matched_by, source,
                review_status, change_note
            ) VALUES (
                :feature_id, :software_version, :version_sort_key, :product_series,
                :market, :release_date, :change_type, :configuration_status,
                :lifecycle_status,
                :evidence_document_id, :evidence_source_ref, :evidence_excerpt,
                :evidence_kind, :matched_by, :source, :review_status, :change_note
            )
            RETURNING id
            """
        ),
        {
            "feature_id": feature_id,
            "software_version": version,
            "version_sort_key": version_sort_key(version),
            "product_series": scope_series,
            "market": scope_market,
            "release_date": _clean_release_date(release_date),
            "change_type": _validate_change_type(change_type),
            "configuration_status": (
                str(configuration_status).strip() or None if configuration_status else None
            ),
            "lifecycle_status": _validate_choice(
                lifecycle_status or "undefined",
                FEATURE_VERSION_LIFECYCLE_STATUSES,
                "生命周期状态",
            ),
            "evidence_document_id": evidence_document_id,
            "evidence_source_ref": evidence_source_ref,
            "evidence_excerpt": evidence_excerpt,
            "evidence_kind": _normalize_scope(evidence_kind) or "manual",
            "matched_by": _normalize_scope(matched_by) or None,
            "source": _normalize_scope(source) or "manual",
            "review_status": status,
            "change_note": change_note,
        },
    )
    version_id = int(result.scalar_one())
    created = await get_feature_version(session, version_id)
    await _append_revisions(
        session,
        entries=[
            {
                "id": version_id,
                "before_json": None,
                "after_json": _audit_snapshot(created),
            }
        ],
        action="created",
        change_note=change_note,
        changed_by=changed_by,
    )
    await session.commit()
    return created


async def get_feature_version(session: AsyncSession, version_id: int) -> dict:
    result = await session.execute(
        text(
            f"""
            SELECT {_ROW_COLUMNS}
            FROM feature_versions version
            LEFT JOIN knowledge_documents document
              ON document.id = version.evidence_document_id
            LEFT JOIN release_introductions introduction
              ON introduction.feature_version_id = version.id
            WHERE version.id = :version_id
            """
        ),
        {"version_id": version_id},
    )
    row = result.one_or_none()
    if row is None:
        raise FeatureReleaseNotFoundError("功能版本不存在")
    return _row_payload(row)


async def update_feature_version(
    session: AsyncSession,
    version_id: int,
    *,
    software_version: str | None = None,
    product_series: str | None = None,
    market: str | None = None,
    release_date: str | None = None,
    change_type: str | None = None,
    configuration_status: str | None = None,
    lifecycle_status: str | None = None,
    review_status: str | None = None,
    change_note: str | None = None,
    changed_by: str | None = None,
    fields_set: set[str] | None = None,
) -> dict:
    """Update one row. Only the fields present in the request are changed."""

    current = await get_feature_version(session, version_id)
    provided = fields_set if fields_set is not None else set()
    assignments: dict[str, object] = {}

    if software_version is not None or "software_version" in provided:
        cleaned = _clean_required(software_version, "软件版本")
        assignments["software_version"] = cleaned
        assignments["version_sort_key"] = version_sort_key(cleaned)
    if product_series is not None or "product_series" in provided:
        assignments["product_series"] = _normalize_scope(product_series)
    if market is not None or "market" in provided:
        assignments["market"] = _normalize_scope(market) or "domestic"
    if "release_date" in provided:
        assignments["release_date"] = _clean_release_date(release_date)
    if change_type is not None or "change_type" in provided:
        assignments["change_type"] = _validate_change_type(change_type)
    if "configuration_status" in provided:
        assignments["configuration_status"] = (
            str(configuration_status).strip() or None if configuration_status else None
        )
    if lifecycle_status is not None or "lifecycle_status" in provided:
        assignments["lifecycle_status"] = _validate_choice(
            lifecycle_status, FEATURE_VERSION_LIFECYCLE_STATUSES, "生命周期状态"
        )
    if review_status is not None or "review_status" in provided:
        assignments["review_status"] = _validate_choice(
            review_status, FEATURE_VERSION_REVIEW_STATUSES, "复核状态"
        )
    if "change_note" in provided:
        assignments["change_note"] = change_note

    if not assignments:
        return current

    clause = ", ".join(f"{column} = :{column}" for column in assignments)
    await session.execute(
        text(
            f"""
            UPDATE feature_versions
            SET {clause}, updated_at = CURRENT_TIMESTAMP
            WHERE id = :version_id
            """
        ),
        {**assignments, "version_id": version_id},
    )
    updated = await get_feature_version(session, version_id)
    # 值没有实际变化时不写留痕：否则每次「打开又保存」都会堆一条噪声快照。
    if _audit_snapshot(current) != _audit_snapshot(updated):
        await _append_revisions(
            session,
            entries=[
                {
                    "id": version_id,
                    "before_json": _audit_snapshot(current),
                    "after_json": _audit_snapshot(updated),
                }
            ],
            action=_revision_action(current, updated),
            change_note=updated.get("change_note"),
            changed_by=changed_by,
        )
    await session.commit()
    return updated


async def _pending_review_rows(
    session: AsyncSession,
    *,
    feature_id: int | None = None,
    software_version: str | None = None,
    product_series: str | None = None,
    market: str | None = None,
    change_type: str | None = None,
    evidence_kind: str | None = None,
    version_ids: list[int] | None = None,
) -> list[dict]:
    """待复核（pending）记录，按可选范围过滤。"""

    ids = [int(value) for value in version_ids] if version_ids else None
    params: dict[str, object] = {
        "feature_id": feature_id,
        "software_version": _normalize_scope(software_version) or None,
        "product_series": _normalize_scope(product_series) or None,
        "market": _normalize_scope(market) or None,
        "change_type": _normalize_scope(change_type) or None,
        "evidence_kind": _normalize_scope(evidence_kind) or None,
        "version_ids": ids,
    }
    filters = """
        version.review_status = 'pending'
        AND (:feature_id IS NULL OR version.feature_id = :feature_id)
        AND (:software_version IS NULL OR version.software_version = :software_version)
        AND (:product_series IS NULL OR version.product_series = :product_series)
        AND (:market IS NULL OR version.market = :market)
        AND (:change_type IS NULL OR version.change_type = :change_type)
        AND (:evidence_kind IS NULL OR version.evidence_kind = :evidence_kind)
    """
    if ids is not None:
        filters += " AND version.id IN :version_ids"
    statement = text(
        f"""
        SELECT {_ROW_COLUMNS}
        FROM feature_versions version
        LEFT JOIN knowledge_documents document
          ON document.id = version.evidence_document_id
        LEFT JOIN release_introductions introduction
          ON introduction.feature_version_id = version.id
        WHERE {filters}
        ORDER BY version.version_sort_key, version.feature_id, version.id
        """
    )
    if ids is not None:
        statement = statement.bindparams(bindparam("version_ids", expanding=True))
    result = await session.execute(statement, params)
    return [_row_payload(row) for row in result]


async def _review_rows_by_ids(session: AsyncSession, version_ids: list[int]) -> list[dict]:
    """按 id 读回记录（不限状态）：批量动作落库后刷新返回值用。"""

    if not version_ids:
        return []
    result = await session.execute(
        text(
            f"""
            SELECT {_ROW_COLUMNS}
            FROM feature_versions version
            LEFT JOIN knowledge_documents document
              ON document.id = version.evidence_document_id
            LEFT JOIN release_introductions introduction
              ON introduction.feature_version_id = version.id
            WHERE version.id IN :version_ids
            ORDER BY version.version_sort_key, version.feature_id, version.id
            """
        ).bindparams(bindparam("version_ids", expanding=True)),
        {"version_ids": [int(value) for value in version_ids]},
    )
    return [_row_payload(row) for row in result]


def _first_release_candidate_ids(items: list[dict]) -> set[int]:
    """每个功能 + 系列范围内最早一条「配置变更表 + 新增」证据的 id。

    与回填预览的 `is_first_release_candidate` 同一口径：只有配置变更表里的
    「新增」才算首发证据，正文里的「优化」只说明该版本涉及该功能。
    """

    def is_candidate(item: dict) -> bool:
        return (
            item["change_type"] == "added"
            and item["evidence_kind"] == "configuration_change"
        )

    earliest: dict[tuple[int, str], str] = {}
    for item in items:
        if not is_candidate(item):
            continue
        scope = (int(item["feature_id"]), item["product_series"] or "")
        current = earliest.get(scope)
        if current is None or item["version_sort_key"] < current:
            earliest[scope] = item["version_sort_key"]
    return {
        int(item["id"])
        for item in items
        if is_candidate(item)
        and earliest.get((int(item["feature_id"]), item["product_series"] or ""))
        == item["version_sort_key"]
    }


def _count_by(items: list[dict], field: str, label: str) -> list[dict]:
    counts: dict[str, int] = {}
    for item in items:
        key = str(item.get(field) or "")
        counts[key] = counts.get(key, 0) + 1
    return [
        {label: key, "matched": counts[key]}
        for key in sorted(counts, key=lambda value: (-counts[value], value))
    ]


def _batch_review_note(
    review_status: str,
    *,
    matched: int,
    first_candidate_only: bool,
    change_type: str | None,
    software_version: str | None,
    evidence_kind: str | None,
) -> str:
    """批量动作写进每一行的口径：以后看单条记录也能知道它属于哪一次批量。"""

    scope: list[str] = []
    if first_candidate_only:
        scope.append("首发候选")
    if software_version:
        scope.append(f"版本 {software_version}")
    if change_type:
        scope.append(f"变更类型 {change_type}")
    if evidence_kind:
        scope.append(f"证据类型 {evidence_kind}")
    label = "确认" if review_status == "confirmed" else "驳回"
    scope_text = "、".join(scope) if scope else "全部待复核记录"
    return f"批量{label}｜口径：{scope_text}｜本次 {matched} 条"


async def batch_review_feature_versions(
    session: AsyncSession,
    *,
    review_status: str,
    changed_by: str | None = None,
    change_note: str | None = None,
    feature_id: int | None = None,
    software_version: str | None = None,
    product_series: str | None = None,
    market: str | None = None,
    change_type: str | None = None,
    evidence_kind: str | None = None,
    first_candidate_only: bool = False,
    version_ids: list[int] | None = None,
    confirm_count: int | None = None,
    dry_run: bool = True,
) -> dict:
    """按范围批量确认或驳回待复核记录，并逐条留痕。

    与候选回填同一条纪律：默认只预览（`dry_run=True`），显式落库才写；只处理
    `pending` 行，已确认或已驳回的记录不会被批量动作覆盖。预览不要求填操作人，
    落库时必填并写进每一条留痕。
    """

    status = _validate_choice(review_status, ("confirmed", "rejected"), "批量复核状态")
    actor = str(changed_by or "").strip()
    if not actor and not dry_run:
        raise FeatureReleaseError("批量复核需要填写操作人")

    items = await _pending_review_rows(
        session,
        feature_id=feature_id,
        software_version=software_version,
        product_series=product_series,
        market=market,
        change_type=change_type,
        evidence_kind=evidence_kind,
        version_ids=version_ids,
    )
    if first_candidate_only:
        keep = _first_release_candidate_ids(items)
        items = [item for item in items if int(item["id"]) in keep]
    candidate_ids = _first_release_candidate_ids(items)
    for item in items:
        item["is_first_release_candidate"] = int(item["id"]) in candidate_ids

    matched = len(items)
    note = str(change_note or "").strip() or _batch_review_note(
        status,
        matched=matched,
        first_candidate_only=first_candidate_only,
        change_type=change_type,
        software_version=software_version,
        evidence_kind=evidence_kind,
    )
    if matched > BATCH_REVIEW_LIMIT and confirm_count != matched:
        raise FeatureReleaseError(
            f"本次将影响 {matched} 条记录，超过 {BATCH_REVIEW_LIMIT} 条，"
            f"需要回传确认条数 confirm_count={matched} 才能执行"
        )

    result = {
        "applied": False,
        "dry_run": bool(dry_run),
        "review_status": status,
        "action": f"batch_{status}",
        "change_note": note,
        "matched": matched,
        "limit": BATCH_REVIEW_LIMIT,
        "requires_confirm_count": matched > BATCH_REVIEW_LIMIT,
        "by_change_type": _count_by(items, "change_type", "change_type"),
        "by_software_version": _count_by(items, "software_version", "software_version"),
        "items": items,
    }
    if dry_run or not items:
        return result

    before = {int(item["id"]): _audit_snapshot(item) for item in items}
    identifiers = [int(item["id"]) for item in items]
    await session.execute(
        text(
            """
            UPDATE feature_versions
            SET review_status = :review_status, change_note = :change_note,
                updated_at = CURRENT_TIMESTAMP
            WHERE id IN :version_ids
            """
        ).bindparams(bindparam("version_ids", expanding=True)),
        {"review_status": status, "change_note": note, "version_ids": identifiers},
    )
    for item in items:
        item["review_status"] = status
        item["change_note"] = note
    await _append_revisions(
        session,
        entries=[
            {
                "id": int(item["id"]),
                "before_json": before[int(item["id"])],
                "after_json": _audit_snapshot(item),
            }
            for item in items
        ],
        action=f"batch_{status}",
        change_note=note,
        changed_by=actor,
    )
    await session.commit()

    refreshed = await _review_rows_by_ids(session, identifiers)
    result["items"] = refreshed
    result["applied"] = True
    result["dry_run"] = False
    return result


async def delete_feature_version(session: AsyncSession, version_id: int) -> None:
    """Delete one row plus the attachment files it owned.

    A 侧删除发布介绍时不回收物理文件，磁盘孤儿文件会持续累积；
    这里先收集附件路径，删除成功后再回收，避免同样的泄漏。
    """

    attachment_rows = await session.execute(
        text(
            """
            SELECT attachment.file_path
            FROM release_introduction_attachments attachment
            JOIN release_introductions introduction
              ON introduction.id = attachment.introduction_id
            WHERE introduction.feature_version_id = :version_id
            """
        ),
        {"version_id": version_id},
    )
    file_paths = [row.file_path for row in attachment_rows]

    result = await session.execute(
        text("DELETE FROM feature_versions WHERE id = :version_id"),
        {"version_id": version_id},
    )
    if result.rowcount == 0:
        raise FeatureReleaseNotFoundError("功能版本不存在")
    await session.commit()
    _remove_attachment_files(file_paths)


def _remove_attachment_files(file_paths: list[str]) -> None:
    root = RELEASE_ATTACHMENT_ROOT.resolve()
    for stored in file_paths:
        resolved = Path(stored).resolve()
        if resolved != root and root in resolved.parents and resolved.is_file():
            resolved.unlink()


def _applications_to_json(applications) -> str:
    """适用范围按行保存；字符串按换行拆分，列表原样收敛。"""

    if applications is None:
        return "[]"
    if isinstance(applications, str):
        items = applications.splitlines()
    else:
        items = [str(item) for item in applications]
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    return json.dumps(cleaned, ensure_ascii=False)


def _applications_from_json(value) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


async def _introduction_attachments(session: AsyncSession, introduction_id: int) -> list[dict]:
    result = await session.execute(
        text(
            """
            SELECT id, file_name, file_path, sha256, mime_type, file_size, sort_order
            FROM release_introduction_attachments
            WHERE introduction_id = :introduction_id
            ORDER BY sort_order, id
            """
        ),
        {"introduction_id": introduction_id},
    )
    return [
        {
            "id": int(item.id),
            "file_name": item.file_name,
            "file_path": item.file_path,
            "sha256": item.sha256,
            "mime_type": item.mime_type,
            "file_size": int(item.file_size or 0),
            "sort_order": int(item.sort_order),
        }
        for item in result
    ]


async def get_introduction(session: AsyncSession, version_id: int) -> dict | None:
    result = await session.execute(
        text(
            """
            SELECT introduction.id, introduction.feature_version_id,
                   introduction.summary, introduction.clinical_significance,
                   introduction.workflow, introduction.applications_json,
                   introduction.version, introduction.review_status,
                   introduction.change_note, introduction.created_at,
                   introduction.updated_at
            FROM release_introductions introduction
            WHERE introduction.feature_version_id = :version_id
            """
        ),
        {"version_id": version_id},
    )
    row = result.one_or_none()
    if row is None:
        return None
    return {
        "id": int(row.id),
        "feature_version_id": int(row.feature_version_id),
        "summary": row.summary,
        "clinical_significance": row.clinical_significance,
        "workflow": row.workflow,
        "applications": _applications_from_json(row.applications_json),
        "version": int(row.version),
        "review_status": row.review_status,
        "change_note": row.change_note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "attachments": await _introduction_attachments(session, int(row.id)),
    }


async def save_introduction(
    session: AsyncSession,
    version_id: int,
    *,
    summary: str | None = None,
    clinical_significance: str | None = None,
    workflow: str | None = None,
    applications=None,
    review_status: str | None = None,
    change_note: str | None = None,
    fields_set: set[str] | None = None,
) -> dict:
    """Create or update the introduction; the previous revision is snapshotted first.

    两点与 A 侧不同：未传的字段保持原值（A 是整篇覆盖），
    且主表改动与历史快照在同一个事务里提交，
    `(introduction_id, version)` 的唯一约束保证并发保存不会写出两个同号版本。
    """

    status = _validate_choice(
        review_status or "draft", RELEASE_INTRODUCTION_REVIEW_STATUSES, "发布介绍状态"
    )
    await get_feature_version(session, version_id)
    current = await get_introduction(session, version_id)
    provided = fields_set if fields_set is not None else None
    if provided is not None and not (
        provided & {"summary", "clinical_significance", "workflow", "applications"}
    ):
        raise FeatureReleaseError("没有需要保存的发布介绍字段")

    def _incoming(field: str, value) -> bool:
        if provided is None:
            return True
        return field in provided

    values = {
        "summary": (
            (summary or "").strip() or None
            if _incoming("summary", summary)
            else (current or {}).get("summary")
        ),
        "clinical_significance": (
            (clinical_significance or "").strip() or None
            if _incoming("clinical_significance", clinical_significance)
            else (current or {}).get("clinical_significance")
        ),
        "workflow": (
            (workflow or "").strip() or None
            if _incoming("workflow", workflow)
            else (current or {}).get("workflow")
        ),
        "applications_json": (
            _applications_to_json(applications)
            if _incoming("applications", applications)
            else json.dumps((current or {}).get("applications") or [], ensure_ascii=False)
        ),
    }
    if not any(
        [
            values["summary"],
            values["clinical_significance"],
            values["workflow"],
            _applications_from_json(values["applications_json"]),
        ]
    ):
        raise FeatureReleaseError("发布介绍内容不能全部为空")

    if current is None:
        await session.execute(
            text(
                """
                INSERT INTO release_introductions (
                    feature_version_id, summary, clinical_significance, workflow,
                    applications_json, version, review_status, change_note
                ) VALUES (
                    :feature_version_id, :summary, :clinical_significance, :workflow,
                    :applications_json, 1, :review_status, :change_note
                )
                """
            ),
            {"feature_version_id": version_id, **values, "review_status": status,
             "change_note": change_note},
        )
    else:
        await session.execute(
            text(
                """
                INSERT INTO release_introduction_revisions (
                    introduction_id, version, summary, clinical_significance,
                    workflow, applications_json, review_status, change_note
                ) VALUES (
                    :introduction_id, :version, :summary, :clinical_significance,
                    :workflow, :applications_json, :review_status, :change_note
                )
                """
            ),
            {
                "introduction_id": int(current["id"]),
                "version": int(current["version"]),
                "summary": current["summary"],
                "clinical_significance": current["clinical_significance"],
                "workflow": current["workflow"],
                "applications_json": json.dumps(current["applications"], ensure_ascii=False),
                "review_status": current["review_status"],
                "change_note": current["change_note"],
            },
        )
        await session.execute(
            text(
                """
                UPDATE release_introductions
                SET summary = :summary,
                    clinical_significance = :clinical_significance,
                    workflow = :workflow,
                    applications_json = :applications_json,
                    version = :version,
                    review_status = :review_status,
                    change_note = :change_note,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :introduction_id
                """
            ),
            {
                **values,
                "version": int(current["version"]) + 1,
                "review_status": status,
                "change_note": change_note,
                "introduction_id": int(current["id"]),
            },
        )
    await session.commit()
    return await get_introduction(session, version_id)


async def list_introduction_history(session: AsyncSession, version_id: int) -> list[dict]:
    """Return every saved version, current one included and marked."""

    introduction = await get_introduction(session, version_id)
    if introduction is None:
        raise FeatureReleaseNotFoundError("该功能版本还没有发布介绍")

    result = await session.execute(
        text(
            """
            SELECT version, summary, clinical_significance, workflow,
                   applications_json, review_status, change_note, created_at
            FROM release_introduction_revisions
            WHERE introduction_id = :introduction_id
            ORDER BY version DESC
            """
        ),
        {"introduction_id": introduction["id"]},
    )
    history = [
        {
            "version": int(row.version),
            "summary": row.summary,
            "clinical_significance": row.clinical_significance,
            "workflow": row.workflow,
            "applications": _applications_from_json(row.applications_json),
            "review_status": row.review_status,
            "change_note": row.change_note,
            "created_at": row.created_at,
            "is_current": False,
        }
        for row in result
    ]
    history.insert(
        0,
        {
            "version": introduction["version"],
            "summary": introduction["summary"],
            "clinical_significance": introduction["clinical_significance"],
            "workflow": introduction["workflow"],
            "applications": introduction["applications"],
            "review_status": introduction["review_status"],
            "change_note": introduction["change_note"],
            "created_at": introduction["updated_at"],
            "is_current": True,
        },
    )
    return history


def resolve_release_attachment_path(file_name: str) -> Path:
    """Resolve one attachment file name inside the release attachment root.

    Mirrors the path-traversal fix required by the merge handover: reject
    separators, parent references and empty names, then confirm the resolved
    path really sits inside the attachment root.
    """

    raw = str(file_name or "")
    if not raw or raw in (".", ".."):
        raise FeatureReleaseAttachmentError("附件文件名不合法")
    if any(marker in raw for marker in ("/", "\\", "\x00")):
        raise FeatureReleaseAttachmentError("附件文件名不合法")
    if raw != Path(raw).name:
        raise FeatureReleaseAttachmentError("附件文件名不合法")

    root = RELEASE_ATTACHMENT_ROOT.resolve()
    candidate = (root / raw).resolve()
    if candidate != root and root not in candidate.parents:
        raise FeatureReleaseAttachmentError("附件路径越界")
    return candidate


async def add_introduction_attachment(
    session: AsyncSession,
    version_id: int,
    *,
    file_name: str,
    payload: bytes,
    sort_order: int = 0,
    overwrite: bool = False,
) -> dict:
    """Store one attachment under a generated name, keeping the original as display text.

    与原文件名同名的落盘文件名在 macOS（NFD 归一化）和重名场景下都不可靠，
    因此磁盘名用 uuid + 后缀，`file_name` 只用于展示与同名判定；
    传入的文件名仍要走 `resolve_release_attachment_path` 的路径穿越校验。
    """

    introduction = await get_introduction(session, version_id)
    if introduction is None:
        raise FeatureReleaseError("请先保存发布介绍再上传附件")

    display_name = resolve_release_attachment_path(file_name).name
    same_name = [
        item
        for item in introduction["attachments"]
        if item["file_name"] == display_name
    ]
    if same_name and not overwrite:
        raise FeatureReleaseAttachmentError("同名附件已存在")

    suffix = Path(display_name).suffix[:20]
    if suffix and not re.fullmatch(r"\.[A-Za-z0-9]{1,20}", suffix):
        suffix = ""
    RELEASE_ATTACHMENT_ROOT.mkdir(parents=True, exist_ok=True)
    target = RELEASE_ATTACHMENT_ROOT.resolve() / f"{uuid.uuid4().hex}{suffix}"
    target.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    for item in same_name:
        await delete_introduction_attachment(session, item["id"], remove_file=True)

    await session.execute(
        text(
            """
            INSERT INTO release_introduction_attachments (
                introduction_id, file_name, file_path, sha256,
                mime_type, file_size, sort_order
            ) VALUES (
                :introduction_id, :file_name, :file_path, :sha256,
                :mime_type, :file_size, :sort_order
            )
            """
        ),
        {
            "introduction_id": introduction["id"],
            "file_name": display_name,
            "file_path": str(target),
            "sha256": digest,
            "mime_type": mimetypes.guess_type(display_name)[0],
            "file_size": len(payload),
            "sort_order": sort_order,
        },
    )
    await session.commit()
    refreshed = await get_introduction(session, version_id)
    return refreshed["attachments"][-1] if refreshed["attachments"] else {}


async def delete_introduction_attachment(
    session: AsyncSession,
    attachment_id: int,
    *,
    remove_file: bool = True,
) -> None:
    result = await session.execute(
        text(
            """
            SELECT id, file_path FROM release_introduction_attachments
            WHERE id = :attachment_id
            """
        ),
        {"attachment_id": attachment_id},
    )
    row = result.one_or_none()
    if row is None:
        raise FeatureReleaseNotFoundError("附件不存在")
    await session.execute(
        text("DELETE FROM release_introduction_attachments WHERE id = :attachment_id"),
        {"attachment_id": attachment_id},
    )
    await session.commit()
    if remove_file:
        path = Path(row.file_path)
        root = RELEASE_ATTACHMENT_ROOT.resolve()
        resolved = path.resolve()
        if resolved != root and root in resolved.parents and resolved.is_file():
            resolved.unlink()


async def list_evidence_documents(session: AsyncSession, version: str | None = None) -> list[dict]:
    """Release Note documents available as evidence, newest version first."""

    result = await session.execute(
        text(
            """
            SELECT id, title, version, product_series, market
            FROM knowledge_documents
            WHERE document_type = 'release_note'
              AND source_status = 'active'
              AND (:version IS NULL OR version = :version)
            ORDER BY version DESC, id
            """
        ),
        {"version": _normalize_scope(version) or None},
    )
    rows = list(result)
    rows.sort(key=lambda row: version_sort_key(row.version), reverse=True)
    return [
        {
            "id": int(row.id),
            "title": row.title,
            "version": row.version,
            "product_series": row.product_series,
            "market": row.market,
            "preview_url": f"/api/knowledge/documents/{int(row.id)}/preview",
        }
        for row in rows
    ]
