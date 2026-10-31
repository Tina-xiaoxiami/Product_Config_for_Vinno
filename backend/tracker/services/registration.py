"""注册查询服务：把「全集 − 型号排除项」的派生结果连同证据一起交给页面。

红线（每条都有测试守护，改动前先看 `tests/test_knowledge_hub.py` 与 `tests/test_registration.py`）：

- 衍生型号先按**已确认映射**解析成基础型号（A33），无映射 → 待确认（A34）；
- 解析后查不到注册记录 → 待确认，**绝不判「未注册」**（A06）；
- 按**注册单元（证书号）分别呈现，不做并集**——并集会把不同证书的适用范围混成一个数字；
- 「探头全适用」表示排除集合为空，**不等于差异表缺失**；
- 每条结论都要能回溯到证书、差异表与原文位置。

本模块只读知识中枢的注册表，不写任何数据；资料本身仍只读。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from tracker.database import Database

COUNTRY_LABELS = {"CN": "中国"}

RED_LINES = (
    "查不到记录或缺映射一律返回待确认，系统不会推断「未注册」。",
    "派生关系沿用已导入的「全集 − 型号排除项」结果，不重新推断、不做无条件全组合。",
    "同一机型出现在多张注册证下时按注册单元分别呈现，不合并计算。",
    "排除项目前没有证书维度：若它落在某证书全集里却没反映到该证书的派生结果，标注为不一致，需人工核对。",
)


def _checked_at() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _collect_evidence(
    database: Database,
    evidence_ids: list[int | None],
    cache: dict[int, dict[str, Any] | None],
) -> list[dict[str, Any]]:
    described: list[dict[str, Any]] = []
    for evidence_id in evidence_ids:
        if not evidence_id:
            continue
        if evidence_id not in cache:
            cache[evidence_id] = database.describe_evidence(evidence_id)
        item = cache[evidence_id]
        if item and item not in described:
            described.append(item)
    return described


def registration_unit_verified(
    database: Database,
    payload: dict[str, Any],
    unit: dict[str, Any],
) -> bool:
    """Require complete current proof for one country/model/certificate unit.

    The display evidence list omits missing IDs, so it cannot establish
    completeness. Check the original facts instead; a proof for one probe must
    never make another probe, an exclusion, or a derived mapping verified.
    """
    country = payload.get("country", {}).get("code", "")
    model = payload.get("registration_model", "")
    certificate = unit.get("certificate_no", "")
    if payload.get("state") != "resolved" or not country or not model or not certificate:
        return False
    if not unit.get("exclusion_consistent"):
        return False

    scopes = [row for row in database.list_registration_scopes(certificate) if row["country_code"] == country]
    relations = database.list_registration_relations(country, model, certificate)
    scope_probes = {row["probe_code"] for row in scopes}
    relation_probes = {row["probe_code"] for row in relations}
    if not scopes or not relations or scope_probes != relation_probes:
        return False

    states: dict[str, set[str]] = {}
    for row in relations:
        states.setdefault(row["probe_code"], set()).add(row["state"])
    if any(len(values) != 1 or not values <= {"已注册", "未注册"} for values in states.values()):
        return False
    exclusions = [row for row in database.list_registration_exclusions(country, model) if row["probe_code"] in scope_probes]
    if any(states[row["probe_code"]] != {"未注册"} for row in exclusions):
        return False

    evidence_ids = [row["evidence_id"] for row in (*scopes, *relations, *exclusions)]
    if payload.get("derived"):
        mapping = next((row for row in database.list_model_mappings() if
                        row["derived_model"] == payload["queried_model"] and row["base_model"] == model), None)
        if not mapping or not str(mapping.get("verified_at") or "").strip() or not str(mapping.get("mapping_source") or "").strip():
            return False
        evidence_ids.append(mapping["evidence_id"])
    return all(evidence_id and database.qa_evidence_is_current(evidence_id) for evidence_id in evidence_ids)


def registration_query(
    database: Database,
    model: str,
    country_code: str = "CN",
) -> dict[str, Any]:
    """按机型查询注册探头。机型必填；国家默认中国。"""
    queried_model = model.strip()
    if not queried_model:
        raise ValueError("model is required")

    result = database.query_registration(queried_model, country_code)
    base_model = result["registration_model"]
    exclusions = (
        database.list_registration_exclusions(country_code, base_model)
        if result["state"] == "resolved"
        else []
    )
    cache: dict[int, dict[str, Any] | None] = {}

    units: list[dict[str, Any]] = []
    for unit in result.get("units", []):
        certificate_no = unit["certificate_no"]
        scope_rows = database.list_registration_scopes(certificate_no)
        scope_probes = {row["probe_code"] for row in scope_rows}
        relations = database.list_registration_relations(
            country_code, base_model, certificate_no
        )
        unregistered_probes = {
            probe["probe_code"] for probe in unit["probes"] if probe["state"] != "已注册"
        }
        unit_exclusions = [
            {
                "probe_code": row["probe_code"],
                "reason": row["reason"] or "型号排除项",
                "reflected": row["probe_code"] in unregistered_probes,
                "evidence": database.describe_evidence(row["evidence_id"]),
            }
            for row in exclusions
            if row["probe_code"] in scope_probes
        ]
        reflected = sum(1 for item in unit_exclusions if item["reflected"])
        units.append(
            {
                "certificate_no": certificate_no,
                "scope_size": unit["scope_size"],
                "excluded_total": len(unit_exclusions),
                "excluded_reflected": reflected,
                # 排除项没有证书维度：落在全集里但没反映到派生结果时，两者不一致，需人工核对
                "exclusion_consistent": reflected == len(unit_exclusions),
                "derived_total": unit["probe_total"],
                "registered": unit["registered"],
                "unregistered": unit["unregistered"],
                "all_applicable": unit["all_applicable"],
                "probes": unit["probes"],
                "excluded_probes": unit_exclusions,
                "evidence": _collect_evidence(
                    database,
                    [row["evidence_id"] for row in scope_rows]
                    + [row["evidence_id"] for row in relations]
                    + [row["evidence_id"] for row in exclusions if row["probe_code"] in scope_probes],
                    cache,
                ),
            }
        )

    payload: dict[str, Any] = {
        "checked_at": _checked_at(),
        "country": {"code": country_code, "label": COUNTRY_LABELS.get(country_code, country_code)},
        "queried_model": queried_model,
        "registration_model": base_model,
        "derived": result["derived"],
        "mapping_source": result.get("mapping_source", ""),
        "state": result["state"],
        "reason": result.get("reason", ""),
        "unit_count": len(units),
        "units": units,
        "red_lines": list(RED_LINES),
    }
    return payload
