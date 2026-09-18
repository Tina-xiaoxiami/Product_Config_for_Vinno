"""从 Release Note 正文推导「功能版本」候选。

规则要点（对齐知识与审计约定）：

- Release Note 的「配置变更 / 配置更新」表是「功能进入该版本」的证据；
  正文里的优化、修复段落只说明「该版本涉及该功能」，不足以判定首发。
- 匹配键按可信度分层：V 代码 > IPN > 中英文名称；命中方式随候选一起返回，
  便于人工复核时判断该候选是怎么来的。
- 只生成候选，不自动成为结论：候选落库时 `review_status='pending'`。
- 「资料中最早出现」不等于「首发版本」，候选里用 `is_first_release_candidate`
  标记最早的新增证据，并由调用方同时给出已纳管资料的最早版本。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.feature_release_versions import (
    version_sort_key,
)


CONFIGURATION_SECTION_PATTERN = re.compile(
    r"(配置变更|配置更新|配置变化|configuration\s+change|configuration\s+update)",
    re.IGNORECASE,
)
NUMBERED_HEADING_PATTERN = re.compile(r"^\d+(?:\.\d+)*[\.、]?\s*\S")
V_CODE_PATTERN = re.compile(r"(?<![A-Z0-9])V\d{4,6}(?![0-9])")
IPN_PATTERN = re.compile(r"(?<!\d)\d{6,7}(?!\d)")

ADDED_MARKERS = ("新增", "上架", "added", "new")
REMOVED_MARKERS = ("下架", "移除", "removed", "delete")
OPTIMIZE_MARKERS = ("优化", "optimiz", "improve")
FIX_MARKERS = ("修复", "fix", "bug")
STATUS_MARKERS = ("选配", "标配", "招标", "未注册", "optional", "standard", "tender", "unregistered")

MAX_EXCERPT_CHARACTERS = 400

NAME_TYPE_LABELS = {
    "primary": "name",
    "alias": "alias",
}


@dataclass(frozen=True)
class NamePattern:
    """一个用于正文匹配的功能名称。"""

    raw: str
    normalized: str
    is_ascii: bool
    label: str
    regex: re.Pattern[str] | None = None


@dataclass
class FeatureMatchKeys:
    feature_id: int
    feature_name: str
    primary_cn_name: str | None
    primary_en_name: str | None
    ipn: str | None
    v_codes: set[str] = field(default_factory=set)
    ipns: set[str] = field(default_factory=set)
    names: list[NamePattern] = field(default_factory=list)


def _normalize(value: str | None) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def _has_cjk(value: str) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in value)


def _build_name_pattern(raw: str, label: str) -> NamePattern | None:
    cleaned = str(raw or "").strip()
    if not cleaned:
        return None
    normalized = _normalize(cleaned)
    if not normalized:
        return None
    ascii_only = normalized.isascii()
    # 短英文名（SMF、CBI…）太容易误命中，要求至少 3 个字符并加词边界。
    if ascii_only:
        if len(normalized) < 3 or not re.search(r"[a-z]", normalized):
            return None
        regex = re.compile(
            r"(?<![a-z0-9])" + re.escape(normalized) + r"(?![a-z0-9])"
        )
    else:
        if len(normalized) < 2:
            return None
        regex = None
    return NamePattern(
        raw=cleaned,
        normalized=normalized,
        is_ascii=ascii_only,
        label=label,
        regex=regex,
    )


async def _feature_match_keys(
    session: AsyncSession,
    *,
    feature_ids: list[int] | None = None,
) -> list[FeatureMatchKeys]:
    params: dict[str, object] = {}
    feature_filter = ""
    if feature_ids:
        feature_filter = "WHERE feature.id IN :feature_ids"
        params["feature_ids"] = feature_ids

    feature_query = text(
        f"""
        SELECT feature.id, feature.name, feature.ipn,
               feature.primary_cn_name, feature.primary_en_name
        FROM features feature
        {feature_filter}
        ORDER BY feature.sort_order, feature.id
        """
    )
    if feature_ids:
        feature_query = feature_query.bindparams(bindparam("feature_ids", expanding=True))
    feature_rows = list(await session.execute(feature_query, params))

    keys_by_feature: dict[int, FeatureMatchKeys] = {}
    for row in feature_rows:
        feature_id = int(row.id)
        keys = FeatureMatchKeys(
            feature_id=feature_id,
            feature_name=row.name,
            primary_cn_name=row.primary_cn_name,
            primary_en_name=row.primary_en_name,
            ipn=row.ipn,
        )
        if row.ipn:
            keys.ipns.add(str(row.ipn).strip())
        for raw, label in (
            (row.name, "name"),
            (row.primary_cn_name, "name"),
            (row.primary_en_name, "name"),
        ):
            pattern = _build_name_pattern(raw or "", label)
            if pattern is not None:
                keys.names.append(pattern)
        keys_by_feature[feature_id] = keys

    link_query = text(
        f"""
        SELECT link.feature_id, item.v_code, item.ipn
        FROM feature_config_item_links link
        JOIN config_items item ON item.id = link.config_item_id
        WHERE link.review_status = 'approved'
        {('AND link.feature_id IN :feature_ids') if feature_ids else ''}
        """
    )
    if feature_ids:
        link_query = link_query.bindparams(bindparam("feature_ids", expanding=True))
    for row in await session.execute(link_query, params):
        keys = keys_by_feature.get(int(row.feature_id))
        if keys is None:
            continue
        if row.v_code:
            keys.v_codes.add(str(row.v_code).strip().upper())
        if row.ipn:
            keys.ipns.add(str(row.ipn).strip())

    name_query = text(
        f"""
        SELECT name.feature_id, name.name, name.name_type
        FROM feature_names name
        WHERE name.review_status = 'approved'
        {('AND name.feature_id IN :feature_ids') if feature_ids else ''}
        """
    )
    if feature_ids:
        name_query = name_query.bindparams(bindparam("feature_ids", expanding=True))
    for row in await session.execute(name_query, params):
        keys = keys_by_feature.get(int(row.feature_id))
        if keys is None:
            continue
        pattern = _build_name_pattern(row.name, NAME_TYPE_LABELS.get(row.name_type, "alias"))
        if pattern is not None:
            keys.names.append(pattern)

    return list(keys_by_feature.values())


@dataclass(frozen=True)
class ChunkRecord:
    document_id: int
    document_title: str
    version: str
    product_series: str
    market: str
    chunk_id: int
    chunk_index: int
    page_number: int | None
    source_ref: str
    content: str
    # 每个原始行的章节状态：True 表示该行位于「配置变更」表内。
    line_states: tuple[bool, ...] = ()

    def state_at(self, line_index: int) -> bool:
        if not self.line_states:
            return False
        if line_index < 0 or line_index >= len(self.line_states):
            return self.line_states[-1]
        return self.line_states[line_index]


async def _release_note_chunks(
    session: AsyncSession,
    *,
    software_versions: list[str] | None = None,
    product_series: str | None = None,
) -> list[ChunkRecord]:
    params: dict[str, object] = {
        "product_series": str(product_series or "").strip(),
        "software_versions": software_versions or None,
    }
    versions_filter = ""
    if software_versions:
        versions_filter = "AND document.version IN :software_versions"
    query = text(
        f"""
        SELECT chunk.id AS chunk_id, chunk.chunk_index, chunk.page_number,
               chunk.source_ref, chunk.content,
               document.id AS document_id, document.title AS document_title,
               document.version, document.product_series, document.market
        FROM knowledge_document_chunks chunk
        JOIN knowledge_documents document ON document.id = chunk.document_id
        JOIN knowledge_document_extractions extraction
          ON extraction.document_id = document.id
         AND extraction.status = 'completed'
        WHERE document.document_type = 'release_note'
          AND document.source_status = 'active'
          AND document.version IS NOT NULL
          AND (:product_series = '' OR document.product_series = :product_series)
          {versions_filter}
        ORDER BY document.version, document.id, chunk.chunk_index
        """
    )
    if software_versions:
        query = query.bindparams(bindparam("software_versions", expanding=True))

    records: list[ChunkRecord] = []
    section_state: dict[int, bool] = {}
    for row in await session.execute(query, params):
        document_id = int(row.document_id)
        content = row.content or ""
        line_states, final_state = _line_section_states(
            content, section_state.get(document_id, False)
        )
        section_state[document_id] = final_state
        records.append(
            ChunkRecord(
                document_id=document_id,
                document_title=row.document_title,
                version=row.version,
                product_series=row.product_series or "",
                market=row.market or "domestic",
                chunk_id=int(row.chunk_id),
                chunk_index=int(row.chunk_index),
                page_number=int(row.page_number) if row.page_number else None,
                source_ref=row.source_ref,
                content=content,
                line_states=line_states,
            )
        )
    return records


SECTION_HEADING_MAX_CHARACTERS = 40

# 目录行（点前导 + 页码）只是章节标题列表，正文里的真实变更在别处；
# 把目录行当证据会在多份 Release Note 上伪造出「新增」记录。
TABLE_OF_CONTENTS_PATTERN = re.compile(r"[.·。\u2026]{3,}\s*\d{1,3}\s*$")


def _is_table_of_contents_line(line: str) -> bool:
    """A heading followed by dot leaders and a page number is a TOC entry."""

    return bool(TABLE_OF_CONTENTS_PATTERN.search(str(line or "").strip()))


def _is_section_heading(line: str) -> bool:
    """A numbered, short line that is not a table row is treated as a heading."""

    stripped = line.strip()
    if not stripped or len(stripped) > SECTION_HEADING_MAX_CHARACTERS:
        return False
    if V_CODE_PATTERN.search(stripped.upper()):
        return False
    return bool(NUMBERED_HEADING_PATTERN.match(stripped))


def _line_section_states(content: str, carried: bool) -> tuple[tuple[bool, ...], bool]:
    """Track「配置变更」section membership per line.

    Extractors flatten whole pages into one chunk, so a single chunk often holds
    "1 / 1. 概述 / 2. 配置变更" followed by the table rows. Only looking at the
    first line would misclassify every table row, so the state is tracked line by
    line and carried into the following chunk (tables can span chunks).
    """

    states: list[bool] = []
    state = carried
    for line in str(content or "").splitlines():
        if not line.strip():
            states.append(state)
            continue
        if CONFIGURATION_SECTION_PATTERN.search(line):
            state = True
        elif _is_section_heading(line):
            state = False
        states.append(state)
    return tuple(states), state


def _match_feature(keys: FeatureMatchKeys, content: str) -> tuple[str, str, int] | None:
    """Return (matched_by, matched_line, line_index) or None."""

    upper = str(content or "").upper()
    codes = set(V_CODE_PATTERN.findall(upper))
    if codes and keys.v_codes & codes:
        code = sorted(keys.v_codes & codes)[0]
        line, index = _line_for_token(content, code)
        return "v_code", line, index

    ipns = set(IPN_PATTERN.findall(str(content or "")))
    if ipns and keys.ipns & ipns:
        ipn = sorted(keys.ipns & ipns)[0]
        line, index = _line_for_token(content, ipn)
        return "ipn", line, index

    normalized_content = _normalize(content)
    for pattern in keys.names:
        matched = False
        if pattern.is_ascii:
            matched = bool(pattern.regex and pattern.regex.search(normalized_content))
        else:
            matched = pattern.normalized in normalized_content
        if matched:
            line, index = _line_for_token(content, pattern.raw)
            return pattern.label, line, index
    return None


def _line_for_token(content: str, token: str) -> tuple[str, int]:
    """Return the line containing the token plus its index in the raw content."""

    token_folded = _normalize(token)
    lines = str(content or "").splitlines()
    for index, line in enumerate(lines):
        if token_folded and token_folded in _normalize(line):
            return line.strip()[:MAX_EXCERPT_CHARACTERS], index
    for index, line in enumerate(lines):
        if line.strip():
            return line.strip()[:MAX_EXCERPT_CHARACTERS], index
    return "", 0


def _classify_change(content: str, line: str, in_configuration_section: bool) -> tuple[str, str | None]:
    haystack = _normalize(line or content)
    if in_configuration_section:
        if any(marker in haystack for marker in ADDED_MARKERS):
            return "added", _release_status(line)
        if any(marker in haystack for marker in REMOVED_MARKERS):
            return "removed", _release_status(line)
        if any(marker in haystack for marker in STATUS_MARKERS):
            return "status_changed", _release_status(line)
        return "status_changed", _release_status(line)

    if any(marker in haystack for marker in ADDED_MARKERS):
        return "added", None
    if any(marker in haystack for marker in OPTIMIZE_MARKERS):
        return "optimized", None
    if any(marker in haystack for marker in FIX_MARKERS):
        return "fixed", None
    if any(marker in haystack for marker in REMOVED_MARKERS):
        return "removed", None
    return "unknown", None


def _release_status(line: str) -> str | None:
    """Keep the configuration-table remainder as the raw status wording."""

    cleaned = " ".join(str(line or "").split())
    if not cleaned:
        return None
    without_code = V_CODE_PATTERN.sub("", cleaned).strip(" |,，")
    without_code = re.sub(r"^[\s|,，]+", "", without_code)
    return without_code[:200] or None


def _evidence_rank(
    record: ChunkRecord, change_type: str, in_configuration_section: bool
) -> tuple[int, int, int]:
    return (
        0 if in_configuration_section else 1,
        0 if change_type == "added" else 1,
        record.page_number or 0,
    )


async def preview_feature_version_candidates(
    session: AsyncSession,
    *,
    product_series: str | None = None,
    software_versions: list[str] | None = None,
    feature_ids: list[int] | None = None,
    limit: int | None = None,
) -> dict:
    """Derive feature-version candidates from Release Note content (no writes)."""

    keys_list = await _feature_match_keys(session, feature_ids=feature_ids)
    if not keys_list:
        return {
            "candidates": [],
            "total": 0,
            "applicable": 0,
            "skipped": 0,
            "earliest_ingested_version": None,
            "coverage_note": "",
        }

    chunks = await _release_note_chunks(
        session,
        software_versions=software_versions,
        product_series=product_series,
    )

    best: dict[tuple[int, str, str, str], dict] = {}
    for record in chunks:
        for keys in keys_list:
            matched = _match_feature(keys, record.content)
            if matched is None:
                continue
            matched_by, line, line_index = matched
            if _is_table_of_contents_line(line):
                # 目录行没有独立的变更证据；同一功能若真的在本版本变更，
                # 正文里的表格或段落会在其他 chunk 命中。
                continue
            in_configuration_section = record.state_at(line_index)
            change_type, release_status = _classify_change(
                record.content, line, in_configuration_section
            )
            candidate_key = (
                keys.feature_id,
                record.version,
                record.product_series,
                record.market,
            )
            payload = {
                "feature_id": keys.feature_id,
                "feature_name": keys.feature_name,
                "feature_primary_cn_name": keys.primary_cn_name,
                "feature_primary_en_name": keys.primary_en_name,
                "feature_ipn": keys.ipn,
                "software_version": record.version,
                "product_series": record.product_series,
                "market": record.market,
                "change_type": change_type,
                "configuration_status": release_status,
                "matched_by": matched_by,
                "evidence_document_id": record.document_id,
                "evidence_document_title": record.document_title,
                "evidence_source_ref": record.source_ref,
                "evidence_excerpt": line or record.content[:MAX_EXCERPT_CHARACTERS],
                "evidence_kind": (
                    "configuration_change" if in_configuration_section else "narrative"
                ),
            }
            rank = _evidence_rank(record, change_type, in_configuration_section)
            current = best.get(candidate_key)
            if current is None or rank < current["_rank"]:
                payload["_rank"] = rank
                best[candidate_key] = payload

    candidates = sorted(
        best.values(),
        key=lambda item: (
            item["feature_id"],
            version_sort_key(item["software_version"]),
            item["product_series"],
        ),
    )

    existing_rows = await session.execute(
        text(
            """
            SELECT id, feature_id, software_version, product_series, market,
                   review_status, change_type, evidence_kind
            FROM feature_versions
            """
        )
    )
    existing: dict[tuple[int, str, str, str], dict] = {}
    for row in existing_rows:
        existing[
            (
                int(row.feature_id),
                row.software_version,
                row.product_series or "",
                row.market,
            )
        ] = {"id": int(row.id), "review_status": row.review_status}

    # 首发候选：在该功能、该系列下，最早一条「配置变更表 + 新增」证据。
    first_by_scope: dict[tuple[int, str], str] = {}
    for item in candidates:
        if item["change_type"] != "added" or item["evidence_kind"] != "configuration_change":
            continue
        scope = (item["feature_id"], item["product_series"])
        current = first_by_scope.get(scope)
        if current is None or version_sort_key(item["software_version"]) < version_sort_key(current):
            first_by_scope[scope] = item["software_version"]

    scanned_total = len(candidates)
    if limit is not None:
        candidates = candidates[:limit]

    applicable = 0
    skipped = 0
    for item in candidates:
        scope_key = (
            item["feature_id"],
            item["software_version"],
            item["product_series"],
            item["market"],
        )
        existing_row = existing.get(scope_key)
        if existing_row is not None:
            item["existing_version_id"] = existing_row["id"]
            item["skip_reason"] = (
                "已确认" if existing_row["review_status"] == "confirmed" else "已存在待复核记录"
            )
            skipped += 1
        else:
            applicable += 1
        item["is_first_release_candidate"] = (
            item["change_type"] == "added"
            and item["evidence_kind"] == "configuration_change"
            and first_by_scope.get((item["feature_id"], item["product_series"]))
            == item["software_version"]
        )
        item.pop("_rank", None)

    earliest = None
    version_pool = [record.version for record in chunks if record.version]
    if version_pool:
        earliest = min(version_pool, key=version_sort_key)
    coverage_note = ""
    if earliest:
        coverage_note = (
            f"已纳管 Release Note 最早版本为 {earliest}；"
            f"候选只能证明该版本之前的功能「未在资料中再次出现」，不能证明首发。"
        )

    return {
        "candidates": candidates,
        "total": len(candidates),
        "scanned_total": scanned_total,
        "applicable": applicable,
        "skipped": skipped,
        "earliest_ingested_version": earliest,
        "coverage_note": coverage_note,
    }


async def apply_feature_version_candidates(
    session: AsyncSession,
    candidates: list[dict],
) -> int:
    """Persist candidates as pending rows. Existing scopes are skipped."""

    created = 0
    for item in candidates:
        if item.get("existing_version_id"):
            continue
        result = await session.execute(
            text(
                """
                INSERT OR IGNORE INTO feature_versions (
                    feature_id, software_version, version_sort_key, product_series,
                    market, release_date, change_type, configuration_status,
                    lifecycle_status, evidence_document_id, evidence_source_ref,
                    evidence_excerpt, evidence_kind, matched_by, source,
                    review_status, change_note
                ) VALUES (
                    :feature_id, :software_version, :version_sort_key, :product_series,
                    :market, NULL, :change_type, :configuration_status,
                    'undefined', :evidence_document_id, :evidence_source_ref,
                    :evidence_excerpt, :evidence_kind, :matched_by,
                    'release_note', 'pending', NULL
                )
                """
            ),
            {
                "feature_id": item["feature_id"],
                "software_version": item["software_version"],
                "version_sort_key": version_sort_key(item["software_version"]),
                "product_series": item.get("product_series") or "",
                "market": item.get("market") or "domestic",
                "change_type": item.get("change_type") or "unknown",
                "configuration_status": item.get("configuration_status"),
                "evidence_document_id": item.get("evidence_document_id"),
                "evidence_source_ref": item.get("evidence_source_ref"),
                "evidence_excerpt": item.get("evidence_excerpt"),
                "evidence_kind": item.get("evidence_kind") or "manual",
                "matched_by": item.get("matched_by"),
            },
        )
        created += int(result.rowcount or 0)
    await session.commit()
    return created
