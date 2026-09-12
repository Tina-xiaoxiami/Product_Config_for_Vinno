"""海外注册名称纠正：人工确认映射（编辑一次长期沿用）+ 纯标点差异自动纠正。

纠正只影响系统内的解析结果与正式数据，**绝不改写受控原件**。

自动纠正的口径刻意保守：只有「去掉所有非字母数字后完全相同」才自动合并
（如 ``D26C`` ↔ ``D2-6C``）。差一个数字或字母的一律不自动——``D3-6C`` 与
``D2-6C``、``G2-5C`` 与 ``G2-6C`` 都是真实存在的不同探头，猜错就是静默的数据损坏。
这类只作为候选交给人工确认，确认结果写进映射表后长期沿用。
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path

from app.services.overseas_registration_history import (
    migrate_overseas_registration_history_schema,
)
from app.services.overseas_registration_preview import (
    OverseasRegistrationPreview,
    build_overseas_relations,
    evaluate_overseas_row_issues,
)
from app.services.registration_rules import normalize_business_name


ENTITY_TYPES = ("model", "probe")


@dataclass(frozen=True)
class OverseasNameMapping:
    entity_type: str
    source_name: str
    target_name: str
    confirmed_by: str
    change_note: str | None = None


@dataclass(frozen=True)
class OverseasNameCorrection:
    entity_type: str
    source_name: str
    target_name: str
    reason: str  # mapping（人工确认） | punctuation（纯标点差异）


@dataclass(frozen=True)
class OverseasCorrectionResult:
    preview: OverseasRegistrationPreview
    corrections: tuple[OverseasNameCorrection, ...]


def _mapping_key(value: object) -> str:
    return normalize_business_name(value).casefold()


def _punctuation_identity(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "", str(value or "")).upper()


def _identity_index(names) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for name in names:
        text = str(name or "").strip()
        if text:
            index.setdefault(_punctuation_identity(text), []).append(text)
    return index


def list_overseas_name_mappings(
    database_path: str | Path,
) -> tuple[OverseasNameMapping, ...]:
    database = Path(database_path).expanduser().resolve()
    migrate_overseas_registration_history_schema(database)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT entity_type, source_name, target_name, confirmed_by, change_note
            FROM overseas_name_mappings
            ORDER BY entity_type, source_name
            """
        ).fetchall()
        return tuple(OverseasNameMapping(**dict(row)) for row in rows)
    finally:
        connection.close()


def save_overseas_name_mapping(
    database_path: str | Path,
    *,
    entity_type: str,
    source_name: object,
    target_name: object,
    confirmed_by: object,
    change_note: object = None,
) -> OverseasNameMapping:
    """登记一条人工确认的名称映射；同一源写法重复登记为覆盖。"""

    kind = str(entity_type or "").strip()
    if kind not in ENTITY_TYPES:
        raise ValueError("名称映射类型必须为 model 或 probe")
    source = normalize_business_name(source_name)
    if not source:
        raise ValueError("原表写法不能为空")
    target = normalize_business_name(target_name)
    if not target:
        raise ValueError("目标名称不能为空")
    actor = str(confirmed_by or "").strip()
    if not actor:
        raise ValueError("确认人不能为空")
    note = str(change_note or "").strip() or None

    database = Path(database_path).expanduser().resolve()
    migrate_overseas_registration_history_schema(database)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            INSERT INTO overseas_name_mappings (
                entity_type, source_name, target_name, normalized_source,
                confirmed_by, change_note
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_type, normalized_source) DO UPDATE SET
                source_name = excluded.source_name,
                target_name = excluded.target_name,
                confirmed_by = excluded.confirmed_by,
                change_note = excluded.change_note,
                updated_at = CURRENT_TIMESTAMP
            """,
            (kind, source, target, _mapping_key(source), actor, note),
        )
        connection.commit()
    finally:
        connection.close()
    return OverseasNameMapping(
        entity_type=kind,
        source_name=source,
        target_name=target,
        confirmed_by=actor,
        change_note=note,
    )


def delete_overseas_name_mapping(
    database_path: str | Path,
    *,
    entity_type: str,
    source_name: object,
) -> bool:
    database = Path(database_path).expanduser().resolve()
    migrate_overseas_registration_history_schema(database)
    connection = sqlite3.connect(database)
    try:
        cursor = connection.execute(
            """
            DELETE FROM overseas_name_mappings
            WHERE entity_type = ? AND normalized_source = ?
            """,
            (str(entity_type or "").strip(), _mapping_key(source_name)),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def apply_overseas_name_corrections(
    preview: OverseasRegistrationPreview,
    *,
    mappings: tuple[OverseasNameMapping, ...] = (),
    known_model_names=(),
    known_probe_names=(),
) -> OverseasCorrectionResult:
    """按「人工确认映射 → 纯标点差异」的顺序纠正名称，并重算疑问与关系。

    原始文本（``model_raw`` / ``probe_raw``）保持不动，作为原表证据；
    只改写解析出的名称元组，并据此重新判定该行是否还需要人工确认。
    """

    mapping_index = {
        (item.entity_type, _mapping_key(item.source_name)): item.target_name
        for item in mappings
    }
    identity_indexes = {
        "model": _identity_index(known_model_names),
        "probe": _identity_index(known_probe_names),
    }

    def _correct(names, entity_type: str):
        corrected: list[str] = []
        corrections: list[OverseasNameCorrection] = []
        for name in names:
            target = mapping_index.get((entity_type, _mapping_key(name)))
            reason = "mapping"
            if target is None:
                candidates = identity_indexes[entity_type].get(
                    _punctuation_identity(name), []
                )
                if len(candidates) == 1 and candidates[0] != name:
                    target, reason = candidates[0], "punctuation"
                else:
                    target, reason = None, None
            if target and target != name:
                corrections.append(
                    OverseasNameCorrection(entity_type, name, target, reason)
                )
                corrected.append(target)
            else:
                corrected.append(name)
        return tuple(dict.fromkeys(corrected)), corrections

    records = []
    corrections: list[OverseasNameCorrection] = []
    for record in preview.records:
        models, model_corrections = _correct(record.models, "model")
        probes, probe_corrections = _correct(record.probes, "probe")
        corrections.extend(model_corrections)
        corrections.extend(probe_corrections)
        issue_codes = evaluate_overseas_row_issues(
            jurisdiction_code=record.jurisdiction_code,
            status=record.registration_status,
            model_raw=record.model_raw,
            probe_raw=record.probe_raw,
            models=models,
            probes=probes,
        )
        records.append(
            replace(
                record,
                models=models,
                probes=probes,
                issue_codes=issue_codes,
                ready_for_import=not issue_codes,
            )
        )

    summary = {
        **(preview.summary or {}),
        "ready_rows": sum(1 for record in records if record.ready_for_import),
        "review_rows": sum(1 for record in records if not record.ready_for_import),
    }
    if records:
        relations = build_overseas_relations(records)
    else:
        # 外部构造的预览可能只带关系、没有逐行记录（解析器之外调用）：
        # 这类就地按同一套纠正重命名，不能凭空重建。
        rename = {
            (item.entity_type, _mapping_key(item.source_name)): item.target_name
            for item in corrections
        }
        relations = tuple(
            replace(
                relation,
                model_name=rename.get(
                    ("model", _mapping_key(relation.model_name)), relation.model_name
                ),
                probe_model=rename.get(
                    ("probe", _mapping_key(relation.probe_model)), relation.probe_model
                ),
            )
            for relation in preview.relations
        )
    corrected_preview = replace(
        preview,
        records=tuple(records),
        relations=relations,
        summary=summary,
    )
    return OverseasCorrectionResult(
        preview=corrected_preview,
        corrections=tuple(corrections),
    )
