"""Answer explicit questions from scoped facts already reviewed in the knowledge base."""
import re

from pathlib import Path

from sqlalchemy import text

from app.services.config_history import build_snapshot_item_comparison_index
from app.services.knowledge_cart_facts import COMPONENT_EXCLUSION_PREFIX, resolve_cart_fact
from app.services.knowledge_parameters import ParameterError, SELECTION_LABELS, answer_snapshot
from app.services.knowledge_qa import normalize_question
from app.services.knowledge_runtime import V8BAT_IPN, runtime_models

_CART_RUNTIME = re.compile(r"cartf(?:的)?(?:整车)?(?:电池)?(?:实测)?续航(?:时长|时间)?(?:是多少|有多久|是多久|多久)?")
_V8BAT_SELECTION = re.compile(
    r"(?:(?:vinno)?v?\d+[a-z]*的?)?(?:是否|能否|能|可以)?"
    r"(?:支持选配|支持|选配|搭配|用)(?:v8bat|v30148|(?:ipn)?1000349)(?:吗|么)?"
)
_V8BAT_RUNTIME = re.compile(
    r"(?:(?:vinno|v)(?P<model>10|8|6iq|5iq|6|5))?(?:使用|搭配|用)"
    r"(?:v8bat|v30148|(?:ipn)?1000349)的?(?:实测)?续航(?:时长|时间)?(?:是多少|有多久|是多久|多久)?"
)


def _source_links(sources, market, key):
    result = []
    for index, source in enumerate(sources):
        link = dict(source)
        document_id, version = source.get("document_id"), source.get("version_id")
        if type(document_id) is int and document_id > 0 and re.fullmatch(r"[a-f0-9]{64}", version or ""):
            if Path(source.get("file_name", "")).suffix.casefold() == ".xlsx":
                link["evidence_url"] = f"/api/knowledge/reviewed-facts/{market}/{key}/sources/{index}?version_id={version}"
            else:
                link["preview_url"] = f"/api/knowledge/documents/{document_id}/preview?version_id={version}"
        result.append(link)
    return result


async def reviewed_answer(db, question, scope, *, configuration_version_id=None):
    query = normalize_question(re.sub(
        r"国内|海外|中国区|国外|\bchina\b|\boverseas?\b|(?:在|软件版本)?\s*\d+(?:\.\d+){2,3}(?:版本|下)?",
        "", question, flags=re.I,
    ))
    cart_runtime = bool(_CART_RUNTIME.fullmatch(query))
    battery_runtime = _V8BAT_RUNTIME.fullmatch(query)
    if not cart_runtime and not battery_runtime and not _V8BAT_SELECTION.fullmatch(query):
        return None
    if not (await db.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_public_facts'"
    ))).scalar_one_or_none():
        return None
    market = scope.get("market")
    model_id = scope.get("product_model_id")
    if battery_runtime and battery_runtime["model"] and not model_id and configuration_version_id is None:
        # Evaluate each exact model separately. An excluded battery in one market
        # cannot answer for another market with no reviewed fact.
        models = await runtime_models(db, f"v{battery_runtime['model']}", scope)
        results = []
        for model in models:
            result = await _battery_answer(db, model, scope, configuration_version_id)
            if result is None or result["fact_status"] != "confirmed":
                break
            results.append(result)
        else:
            if results:
                return {"status": "configuration", "configuration_answers": results}
    missing = ([] if market else ["market"]) + ([] if cart_runtime or model_id else ["product_model_id"])
    if missing:
        return {"status": "needs_clarification", "missing_fields": missing}

    if cart_runtime:
        key = "cart_f.battery_pack.runtime"
        fact = await resolve_cart_fact(db, key, market, {})
        if fact is None:
            return None
        result = _fact_answer(fact, market, key)
    else:
        from app.services.knowledge_configuration_answers import _model

        model = await _model(db, model_id, market)
        if model is None:
            return None
        result = await _battery_answer(db, model, scope, configuration_version_id)
        if result is None:
            return None
    return {"status": "configuration", "configuration_answers": [result]}


async def _battery_answer(db, model, scope, configuration_version_id):
    market = model["market"]
    key = f"{COMPONENT_EXCLUSION_PREFIX}{model['id']}:{V8BAT_IPN}"
    fact = await resolve_cart_fact(db, key, market, {})
    if fact is None:
        return None
    result = _fact_answer(fact, market, key)
    result["model"] = model
    try:
        metadata, snapshot = await answer_snapshot(
            db, model["series_id"], configuration_version_id=configuration_version_id,
            software_version=scope.get("software_version"),
        )
        item = build_snapshot_item_comparison_index(snapshot).get(("ipn", V8BAT_IPN), {})
        selection = item.get("values", {}).get(str(model["id"]), {}).get("selection_config")
        result.update(snapshot=metadata, ipn=V8BAT_IPN, selection=selection,
                      selection_label=SELECTION_LABELS.get(selection, "不适用" if selection == "N/A" else "未登记"))
    except (ParameterError, ValueError) as error:
        result["issues"].append(str(error))
    return result


def _fact_answer(fact, market, key):
    return {"kind": "reviewed_fact", "market": market, "rows": [], "issues": [],
            "answer_text": fact["display_value"] if fact["status"] == "confirmed" else fact["issue"]["detail"],
            "fact_status": fact["status"], "sources": _source_links(fact.get("sources", []), market, key)}


async def reviewed_workbook_citation(db, market, key, source_index, version_id):
    """Read only the workbook rows and columns stored with the reviewed fact."""
    import asyncio
    from openpyxl.utils.cell import range_boundaries

    from app.services.knowledge_content import MAX_SOURCE_BYTES
    from app.services.knowledge_sources import CitationSourceError, _large_workbook_rows, _registered_original, read_verified_source
    from app.services.workbook_preview import WorkbookPreviewError, read_cited_workbook_rows

    fact = await resolve_cart_fact(db, key, market, {})
    sources = fact.get("sources", []) if fact else []
    if source_index >= len(sources) or sources[source_index].get("version_id") != version_id:
        raise CitationSourceError(409, "事实引用已变化，请重新查询")
    source = sources[source_index]
    document = await _registered_original(db, source["document_id"], version_id)
    suffix = Path(document["file_name"]).suffix.casefold()
    if suffix != ".xlsx":
        raise CitationSourceError(422, "引用资料不是 XLSX 原表")
    ranges, sheets = [], {}
    for ref in source["locator"].split("、"):
        match = re.fullmatch(r"([^!]+)!([A-Z]+[1-9][0-9]*:[A-Z]+[1-9][0-9]*)", ref)
        if not match:
            raise CitationSourceError(422, "引用缺少可识别的工作表或单元格范围")
        sheet, coordinates = match.groups()
        left, top, right, bottom = range_boundaries(coordinates)
        if not (1 <= top <= bottom <= 1048576 and bottom - top < 20 and 1 <= left <= right <= 16384 and right - left < 50):
            raise CitationSourceError(422, "引用的单元格范围超出核验上限")
        ranges.append((ref, sheet, left, top, right, bottom))
        sheets.setdefault(sheet, set()).update(range(top, bottom + 1))

    path = Path(document["file_path"])
    try:
        if path.stat().st_size > MAX_SOURCE_BYTES:
            groups = await asyncio.to_thread(_large_workbook_rows, document, sheets)
        else:
            data = await asyncio.to_thread(read_verified_source, path, version_id)
            groups = await asyncio.to_thread(read_cited_workbook_rows, data, suffix, sheets, read_only=True)
    except OSError as error:
        raise CitationSourceError(410, "原件不可用，请检查资料同步") from error
    except WorkbookPreviewError as error:
        raise CitationSourceError(422, str(error)) from error

    from openpyxl.utils.cell import column_index_from_string

    excerpts = []
    for ref, sheet, left, top, right, bottom in ranges:
        cells = [
            {"address": f"{letter}{row['row_number']}", "text": value}
            for group in groups if group["sheet_name"] == sheet
            for row in group["rows"] if top <= row["row_number"] <= bottom
            for letter, value in zip(group["column_letters"], row["cells"])
            if value and left <= column_index_from_string(letter) <= right
        ]
        excerpts.append({"locator": ref, "cells": cells})
    return {"excerpts": excerpts, "version_id": version_id}
