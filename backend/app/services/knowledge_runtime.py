"""Deterministic battery runtime facts from current configuration and cited tests."""
from __future__ import annotations

import asyncio
from pathlib import Path
import re

from sqlalchemy import text

from app.services.config_history import build_snapshot_item_comparison_index
from app.services.knowledge_parameters import ParameterError, SELECTION_LABELS, USABLE_SELECTIONS, confirmed_component_specs
from app.services.knowledge_qa import normalize_question
from app.services.knowledge_sources import CitationSourceError, verified_original
from app.services.workbook_preview import WorkbookPreviewError, read_cited_workbook_rows

BATTERY_LABELS = {"v8bat": "V8BAT", "v9bat": "V9BAT", "v8电池": "V8BAT", "v9电池": "V9BAT"}
BATTERY_TEST = "便携式机台BAT续航时间测试"
SUPPORTED_MODEL_NAMES = {
    "v10": {"v10", "vinno10"},
    "v8": {"v8", "vinno8"},
    "v6": {"v6", "vinno6"},
    "v5": {"v5", "vinno5"},
    "a5": {"a5", "vinnoa5"},
    "v6iq": {"v6iq", "vinno6iq"},
    "v5iq": {"v5iq", "vinno5iq"},
}
RUNTIME_QUESTION = re.compile(r"(?:vinno)?(v10|v8|v6iq|v5iq|v6|v5|a5)(?:的)?(?:实测)?续航(?:时长)?(?:是多少|有多久|是多久|多久)?")


def runtime_question(question: str) -> str | None:
    match = RUNTIME_QUESTION.fullmatch(normalize_question(question))
    return match[1] if match else None


def series_market(series_name: str) -> str | None:
    return {"china": "domestic", "oversea": "overseas"}.get(series_name.rsplit("-", 1)[-1].casefold())


async def runtime_models(db, model_key: str, scope: dict | None = None) -> list[dict]:
    scope = scope or {}
    names = SUPPORTED_MODEL_NAMES[model_key]
    rows = (await db.execute(text("""
        SELECT m.id,m.name,m.series_id,s.name AS series FROM product_models m
        JOIN product_series s ON s.id=m.series_id WHERE m.is_enabled=1 AND COALESCE(m.status, '')<>'已合并'
        ORDER BY m.id
    """))).mappings()
    matches = []
    for row in rows:
        market = series_market(row["series"])
        if normalize_question(row["name"]) not in names or not market:
            continue
        if scope.get("product_model_id") not in (None, row["id"]) or scope.get("market") not in (None, market):
            continue
        matches.append({**row, "market": market})
    return matches


def battery_configuration(snapshot: dict, model_id: int, specs: list[dict] | None = None) -> list[dict]:
    result = []
    for (kind, ipn), item in build_snapshot_item_comparison_index(snapshot).items():
        if kind != "ipn":
            continue
        description = [str(item.get(field) or "").strip() for field in ("zh_desc", "en_desc", "rd_name")]
        named_batteries = {BATTERY_LABELS[normalize_question(v)] for v in description
                           if normalize_question(v) in BATTERY_LABELS}
        matching_specs = [spec for spec in (specs or []) if spec["ipn"] == ipn
                          and normalize_question(spec["name"]) in BATTERY_LABELS]
        names = named_batteries | {BATTERY_LABELS[normalize_question(spec["name"])] for spec in matching_specs}
        if not names and ipn != "1000349":
            continue
        values = item.get("values", {})
        if not isinstance(values, dict) or not isinstance(values.get(str(model_id), {}), dict):
            raise ParameterError("快照配置值格式无效")
        raw = values.get(str(model_id), {})
        selection = str(raw.get("selection_config") or "").strip()
        if selection in USABLE_SELECTIONS:
            battery = next(iter(names)) if len(names) == 1 else None
            result.append({"ipn": ipn, "battery": battery, "name": description[0] or description[1],
                           "selection": selection, "condition": SELECTION_LABELS[selection],
                           "identity_issue": "电池型号与已核对参数映射冲突" if len(names) > 1 else None,
                           "identity_sources": list(dict.fromkeys(spec["evidence_reference"] for spec in matching_specs))})
    return result


def runtime_measurements(groups: list[dict], model_key: str) -> list[dict]:
    names = SUPPORTED_MODEL_NAMES[model_key]
    result = []
    for group in groups:
        cols = [normalize_question(label) for label in group["columns"]]
        if not {"机型", "模式", "探头"} <= set(cols):
            continue
        model_index = cols.index("机型")
        for row in group["rows"]:
            if row["row_number"] == group["header_row"]:
                continue
            values = dict(zip(cols, row["cells"]))
            model_name = values.get("机型") or row["merged_context"].get(model_index, "")
            if normalize_question(model_name) not in names or not values["模式"] or not values["探头"]:
                continue
            outcomes = []
            measured = values.get("放电时长实测") or values.get("放电时长")
            explicit = BATTERY_LABELS.get(normalize_question(values.get("电池")))
            if explicit and measured:
                outcomes.append((explicit, measured))
            for label, battery in BATTERY_LABELS.items():
                if label in {"v8bat", "v9bat"} and (minutes := values.get(label + "放电时长min")):
                    outcomes.append((battery, minutes + " 分钟"))
            for battery, duration in outcomes:
                duration = duration.strip()
                if not duration or duration.upper() in {"N/A", "-", "—", "未测"}:
                    continue
                conditions = " · ".join(f"{label} {values[key]}" for key, label in [
                    ("功耗", "功耗"), ("电池生产日期", "电池生产日期"), ("关机电量剩余", "关机余量（原表值）"),
                ] if values.get(key))
                result.append({"battery": battery, "probe": values["探头"], "mode": values["模式"],
                               "duration": duration, "conditions": conditions,
                               "sheet": group["sheet_name"], "row_number": row["row_number"], "hidden": row["hidden"]})
    return result


async def runtime_source(db, model_key: str) -> tuple[list[dict], str | None]:
    rows = (await db.execute(text("""
        SELECT id,title,file_name,sha256 FROM knowledge_documents
        WHERE source_status='active' AND file_name IN (:xls,:xlsx)
    """), {"xls": BATTERY_TEST + ".xls", "xlsx": BATTERY_TEST + ".xlsx"})).mappings().all()
    if len(rows) != 1:
        return [], "实测工作簿缺失或存在多个登记版本，请核对原件"
    source = rows[0]
    try:
        _, data = await verified_original(db, source["id"], source["sha256"])
        groups = await asyncio.to_thread(read_cited_workbook_rows, data, Path(source["file_name"]).suffix.casefold(), None)
    except (CitationSourceError, WorkbookPreviewError) as error:
        return [], str(error)
    return [{**row, "document_id": source["id"], "version_id": source["sha256"], "title": source["title"],
             "preview_url": f"/api/knowledge/documents/{source['id']}/preview?version_id={source['sha256']}"}
            for row in runtime_measurements(groups, model_key)], None


async def runtime_for_model(db, model_key: str, model: dict, version: dict, snapshot: dict) -> dict:
    if model["id"] not in {int(item["id"]) for item in snapshot["models"]}:
        raise ParameterError("所选配置快照不包含此完整机型")
    from app.services.knowledge_cart_facts import reviewed_battery_identities, reviewed_component_exclusions

    specs = await confirmed_component_specs(db) + await reviewed_battery_identities(db, model["market"])
    exclusions = await reviewed_component_exclusions(db, model["market"], model["id"])
    matched_batteries = battery_configuration(snapshot, model["id"], specs)
    batteries = [battery for battery in matched_batteries if battery["ipn"] not in exclusions]
    notes = [exclusions[battery["ipn"]] for battery in matched_batteries if battery["ipn"] in exclusions]
    measurements, source_issue = await runtime_source(db, model_key)
    rows, issues, review_items = [], [source_issue] if source_issue else [], []
    if not batteries and not notes:
        issues.append("当前配置未登记可用于续航匹配的电池")
    for battery in batteries:
        matches = [row for row in measurements if row["battery"] == battery["battery"]]
        if not matches:
            reason = battery["identity_issue"] or (
                "配置项未标明电池型号" if not battery["battery"] else "原表无对应机型和电池实测"
            )
            issues.append(f"IPN {battery['ipn']}：{reason}")
            rows.append({**battery, "missing": reason})
            if battery["battery"] is None:
                review_items.append({"root_key": f"component.identity:{battery['ipn']}",
                                     "kind": "owner_decision", "detail": reason})
        else:
            rows.extend({**row, **battery} for row in matches)
    return {"kind": "runtime", "model": model, "snapshot": version, "rows": rows, "issues": issues,
            "review_items": review_items,
            "historical_rows": measurements if not any(row.get("duration") for row in rows) else [],
            "scope_note": "。".join(notes + ["实测原表未登记市场和配置版本，时长仅适用于所列电池、探头和测试条件。"])}
