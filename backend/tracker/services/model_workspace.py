"""A read-only model workspace built from existing source services.

Selected scope is explicit. Missing state remains missing, registration units
remain separate, and records without model applicability are kept in a distinct
confirmation list rather than made into model conclusions.
"""

from __future__ import annotations

from datetime import datetime
import re
import sqlite3
from typing import Any, Callable

from tracker.database import Database
from tracker.services.document_scopes import DOCUMENT_CATEGORIES, matches_model_scope, normalize_model_scope
from tracker.services.document_scope_suggestions import suggestion_matches
from tracker.services.knowledge_documents import knowledge_documents
from tracker.services.knowledge_items import knowledge_items, probe_versions
from tracker.services.knowledge_issues import knowledge_issues
from tracker.services.product_states import product_states
from tracker.services.product_strategy import ProductStrategyReader
from tracker.services.registration import registration_query, registration_unit_verified
from tracker.services.search_sources import safe_payload, search_structured_sources


def _section(data: Any = None, *, state: str = "ready", message: str = "") -> dict[str, Any]:
    return {"state": state, "data": safe_payload(data), "message": message}


def build_model_workspace(
    database: Database, reader: ProductStrategyReader | None = None, *, model: str,
    market: str = "domestic", country: str = "", series: str = "",
    scope_suggester: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Collect independent sections without writes, inference, or source coupling."""
    model, market, country = model.strip(), market.strip().casefold(), country.strip().upper()
    if not model:
        raise ValueError("请选择机型。")
    if market not in {"domestic", "overseas"}:
        raise ValueError("请选择国内版或海外版。")
    if country and not re.fullmatch(r"[A-Z]{2}", country):
        raise ValueError("国家必须使用两位代码。")
    if market == "domestic":
        if country and country != "CN":
            raise ValueError("国内版与所选国家不一致，请核对范围。")
        country = "CN"
    elif country == "CN":
        raise ValueError("海外版与中国国家范围不一致，请核对范围。")

    sections: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    pending: dict[str, list[dict[str, Any]]] = {"documents": [], "knowledge": [], "questions": [], "product_states": []}

    def read(name: str, label: str, callback: Callable[[], dict[str, Any]]) -> None:
        try:
            sections[name] = callback()
        except (sqlite3.Error, OSError, ValueError, RuntimeError):
            message = f"{label}来源当前不可用，请检查系统状态。"
            errors[name] = message
            sections[name] = _section(state="unavailable", message=message)

    def state_section() -> dict[str, Any]:
        payload = product_states(database, market_code=country, model_name=model)
        pending["product_states"] = [row for group in payload["models"] for row in group["pending"]]
        return _section(payload, state="ready" if payload["models"] else "empty", message=payload["empty_reason"])

    def registration_section() -> dict[str, Any]:
        payload = registration_query(database, model, country)
        for unit in payload["units"]:
            unit["evidence_current"] = registration_unit_verified(database, payload, unit)
            unit["verification"] = "approved" if unit["evidence_current"] else "pending_review"
        return _section(
            payload, state="ready" if payload["units"] else "empty",
            message="注册单元分别展示；未复核或来源已变更的登记关系需要重新确认。",
        )

    if country:
        read("product_state", "产品状态", state_section)
        read("registration", "注册范围", registration_section)
    else:
        message = "请选择国家后查询产品状态和注册范围；海外版不会默认使用中国资料。"
        sections["product_state"] = _section(state="needs_clarification", message=message)
        sections["registration"] = _section(state="needs_clarification", message=message)

    def config_section() -> dict[str, Any]:
        if reader is None:
            raise RuntimeError("配置来源未配置")
        payload = reader.query(market=market, model=model)
        return _section(payload, state="ready" if payload["items"] else "empty")

    if market == "domestic":
        read("config", "正式配置", config_section)
    else:
        sections["config"] = _section(state="empty", message="当前接入的正式配置来源仅覆盖国内版，海外范围待接入。")

    def documents_section() -> dict[str, Any]:
        payload = knowledge_documents(database, scope_suggester=scope_suggester)
        selected = []
        suggested = []
        family_documents = []
        for row in payload["documents"]:
            document_market = row["scope_market"]
            if document_market and document_market != market:
                continue
            model_scope = normalize_model_scope(row["model_scope"])
            unknown_model = not model_scope or model_scope in DOCUMENT_CATEGORIES
            matches = matches_model_scope(model_scope, model, include_unknown=False)
            suggestion = row.get('scope_suggestion')
            if unknown_model and suggestion and suggestion['scope_kind'] == 'family':
                if model.upper().split(' ', 1)[0] in suggestion['families']:
                    family_documents.append(row)
            elif unknown_model and suggestion and suggestion_matches(suggestion, model):
                suggested.append(row)
            elif unknown_model and suggestion and suggestion['models'] and suggestion['status'] == 'suggested':
                continue
            elif unknown_model or not document_market and matches:
                pending["documents"].append(row)
            elif matches:
                selected.append(row)
        payload["documents"] = selected
        payload['suggested_documents'] = suggested
        payload['family_documents'] = family_documents
        payload["matched"] = len(selected)
        payload["scope"] = {"model": model, "market": market}
        return _section(payload, state="ready" if selected or suggested or family_documents else "empty", message="已登记资料、具体型号建议与系列线索分别展示；建议保留原文依据，确认后保存适用范围。")

    read("documents", "受控资料", documents_section)

    if series.strip():
        def probe_section() -> dict[str, Any]:
            payload = probe_versions(database, series=series.strip())
            return _section(
                payload, state="ready" if payload["rows"] else "empty",
                message="仅展示所选系列的版本事件；这些记录尚不构成所选机型和市场的适用结论。",
            )
        read("probe_versions", "探头版本关系", probe_section)
    else:
        sections["probe_versions"] = _section(
            state="needs_clarification", message="探头版本关系按系列登记，请明确选择系列；系统不会根据机型名称猜测系列。",
        )

    def knowledge_section() -> dict[str, Any]:
        payload = knowledge_items(database)
        pending["knowledge"] = [row for row in payload["items"] if row["scope_market"] == market]
        return _section(
            {"items": [], "matched": 0, "pending_count": len(pending["knowledge"])}, state="empty",
            message="知识条目尚未登记独立机型范围，列入待确认，不作为该机型的适用结论。",
        )

    read("knowledge", "知识条目", knowledge_section)

    def qa_section() -> dict[str, Any]:
        payload = search_structured_sources(database, reader, model=model, market=market, country=country, sources={"qa"})
        message = payload["source_errors"].get("qa", "")
        if message:
            errors["qa"] = message
        pending["questions"] = [row for row in database.list_qa_questions(status="open") if
            row["model_name"].casefold() == model.casefold() and row["market_code"] == market and row["country_code"] == country]
        return _section({"answers": payload["results"]}, state="ready" if payload["results"] else "empty", message=message)

    if country:
        read("qa", "正式问答", qa_section)
    else:
        sections["qa"] = _section(state="needs_clarification", message="请选择国家后查询正式问答。")

    def issues_section() -> dict[str, Any]:
        payload = knowledge_issues(database)
        # A reference identity is usable; arbitrary text mentioning a model is
        # not sufficient to assign a global issue to that model.
        refs = {model}
        config = sections["config"].get("data") or {}
        refs.update(row["code"] for row in config.get("items", []) if row.get("code"))
        registration = sections["registration"].get("data") or {}
        refs.update(row["probe_code"] for unit in registration.get("units", []) for row in unit["probes"])
        selected = [row for row in payload["issues"] if row["subject_ref"] in refs]
        return _section(
            {"issues": selected, "matched": len(selected), "global_open_total": payload["open_total"]},
            state="ready" if selected else "empty", message="按明确关联的机型或配置项展示；全局问题可在待处理清单查看。",
        )

    read("issues", "待处理问题", issues_section)
    return safe_payload({
        "scope": {"model": model, "market": market, "market_label": "国内版" if market == "domestic" else "海外版",
                  "country": country, "series": series.strip()},
        "sections": sections, "source_errors": errors, "pending_confirmation": pending,
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
