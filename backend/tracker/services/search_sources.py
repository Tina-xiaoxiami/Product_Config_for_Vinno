"""Read-only search adapters for the workbench's structured business sources.

Each adapter keeps the source's scope and verification rules. A series-level
probe event is not a model applicability fact, and a published QA row is checked
through the existing answer router before its answer text is returned.
"""

from __future__ import annotations

from collections.abc import Iterable
import re
import sqlite3
from typing import Any

from tracker.database import Database
from tracker.services.knowledge_items import knowledge_items, probe_versions
from tracker.services.product_states import product_state_options, product_states
from tracker.services.product_strategy import ProductStrategyReader
from tracker.services.qa import find_answer
from tracker.services.registration import registration_query, registration_unit_verified


SOURCE_LABELS = {
    "registration": "注册范围",
    "product_state": "产品状态",
    "probe_version": "探头版本关系",
    "knowledge": "知识条目",
    "qa": "正式问答",
}
STRUCTURED_SOURCE_TYPES = frozenset(SOURCE_LABELS)
_PRIVATE_FIELDS = frozenset({"path_pdf", "path_docx", "database_path", "source_path"})


def safe_payload(value: Any) -> Any:
    """Reuse source payloads without returning filesystem locations to the UI."""
    if isinstance(value, dict):
        return {key: safe_payload(item) for key, item in value.items() if key not in _PRIVATE_FIELDS}
    if isinstance(value, (list, tuple)):
        return [safe_payload(item) for item in value]
    return value


def _text(*values: Any) -> str:
    return " · ".join(str(value) for value in values if value not in (None, ""))


def _matches(query: str, *values: Any) -> bool:
    return not query or query.casefold() in _text(*values).casefold()


def evidence_locator(evidence: Iterable[dict[str, Any]]) -> str:
    return "；".join(
        _text(
            row.get("document_title"), row.get("version_label"),
            f"第 {row['page']} 页" if row.get("page") is not None else "",
            row.get("sheet"), row.get("cell_range"),
        )
        for row in evidence
    )


def _result(source: str, *, title: str, scope: str, verification: str,
            matched_text: str, locator: str = "", is_current: bool = False,
            view: str, params: dict[str, str], **extra: Any) -> dict[str, Any]:
    return safe_payload({
        "source_type": source, "source_label": SOURCE_LABELS[source],
        "title": title or "未命名", "scope": scope, "verification": verification,
        "matched_text": matched_text[:500], "locator": locator,
        "is_current": is_current, "preview_id": None,
        "source_status": "source_live", "detail_action": {"view": view, "params": params},
        **extra,
    })


def _country_scope(market: str, country: str, available: Iterable[str]) -> list[str]:
    if market == "domestic" and country and country != "CN":
        raise ValueError("国内版与所选国家不一致，请核对范围。")
    if market == "overseas" and country == "CN":
        raise ValueError("海外版与中国国家范围不一致，请核对范围。")
    if country:
        return [country]
    if market == "domestic":
        return ["CN"]
    if market == "overseas":
        raise ValueError("海外资料需要先选择国家，系统不会默认查询中国范围。")
    return sorted(set(available))


def _registration_results(database: Database, *, query: str, model: str,
                          market: str, country: str) -> tuple[list[dict[str, Any]], str]:
    with database.read_session():
        return _registration_results_with_connection(database, query=query, model=model, market=market, country=country)


def _registration_results_with_connection(database: Database, *, query: str, model: str,
                                          market: str, country: str) -> tuple[list[dict[str, Any]], str]:
    countries = _country_scope(market, country, (
        row["country_code"] for row in database.list_registration_relations()
    ))
    results = []
    for code in countries:
        choices = database.list_registration_models(code)
        models = [model] if model else [*choices["base_models"], *(
            row["derived_model"] for row in choices["derived_models"]
        )]
        for name in models:
            payload = registration_query(database, name, code)
            if not payload["units"]:
                if _matches(query, name, payload["reason"]):
                    results.append(_result(
                        "registration", title=f"{name} · 注册范围待确认", scope=_text(code, name),
                        verification="pending_review", matched_text=payload["reason"],
                        view="registration", params={"model": name, "country": code},
                        registration_state="pending", registration=payload,
                    ))
                continue
            for unit in payload["units"]:
                probes = [row for row in unit["probes"] if _matches(
                    query, name, unit["certificate_no"], row["probe_code"], row["state"], row["rule"],
                    *(e.get("excerpt", "") for e in unit["evidence"]),
                )]
                if not probes:
                    continue
                current = registration_unit_verified(database, payload, unit)
                description = "；".join(_text(row["probe_code"], row["state"], row["rule"]) for row in probes)
                results.append(_result(
                    "registration", title=_text(name, unit["certificate_no"]), scope=_text(code, name),
                    verification="approved" if current else "pending_review",
                    matched_text=description if current else f"待复核登记：{description}",
                    locator=evidence_locator(unit["evidence"]), is_current=current,
                    view="registration", params={"model": name, "country": code},
                    certificate_no=unit["certificate_no"], registration_state=payload["state"],
                    registration_model=payload["registration_model"], unit=unit,
                ))
    return results, ""


def _product_state_results(database: Database, *, query: str, model: str,
                           market: str, country: str) -> tuple[list[dict[str, Any]], str]:
    countries = _country_scope(market, country, (
        row["code"] for row in product_state_options(database)["markets"]
    ))
    results = []
    for code in countries:
        payload = product_states(database, market_code=code, model_name=model)
        for group in payload["models"]:
            for row in group["history"]:
                if not _matches(query, row["model_name"], row["software_version"],
                                row["release_status_label"], row["freshness_label"], row["evidence_excerpt"]):
                    continue
                current = row["freshness"] == "current"
                verification = "approved" if current else "pending_review" if row["freshness"] == "pending_review" else row["freshness"]
                results.append(_result(
                    "product_state", title=_text(row["model_name"], row["software_version"]),
                    scope=_text(payload["scope"]["market_label"], row["model_name"]),
                    verification=verification, is_current=current,
                    matched_text=_text(row["freshness_label"], row["release_status_label"], row["evidence_excerpt"]),
                    locator=_text(f"状态记录 #{row['id']}", row.get("reviewed_at")),
                    view="product_states", params={"model": row["model_name"], "market": code},
                    state_id=row["id"], freshness=row["freshness"], product_state=row,
                ))
    return results, ""


def _knowledge_results(database: Database, *, query: str, model: str,
                       market: str, country: str) -> tuple[list[dict[str, Any]], str]:
    if model or country:
        return [], "知识条目尚无独立机型和国家范围；可清除范围筛选查看待确认条目。"
    results = []
    for row in knowledge_items(database)["items"]:
        if market and row["scope_market"] != market:
            continue
        if not _matches(query, row["code"], row["name_cn"], row["name_en"],
                        *(tag for tags in row["tags"].values() for tag in tags),
                        *(e.get("excerpt", "") for e in row["evidence"])):
            continue
        current_evidence = bool(row["evidence"]) and all(
            database.qa_evidence_is_current(e["evidence_id"]) for e in row["evidence"]
        )
        latest_review: dict[str, Any] = max(row["reviews"], key=lambda review: str(review.get("decided_at") or ""), default={})
        approved = current_evidence and latest_review.get("decision") == "approved" and not any(
            issue["status"] == "open" for issue in row["issues"]
        ) and row["status"] == "active"
        verification = "approved" if approved else "pending_review" if row["has_evidence"] else "unverified"
        results.append(_result(
            "knowledge", title=_text(row["code"], row["name_cn"] or row["name_en"]),
            scope=_text(row["scope_market"], "机型范围未登记"), verification=verification,
            matched_text=_text(row["code_type_label"], row["name_cn"], row["name_en"],
                               "；".join(e.get("excerpt", "") for e in row["evidence"])),
            locator=evidence_locator(row["evidence"]) or row["code"], is_current=approved,
            view="items", params={"q": row["code"]}, item_id=row["id"], item=row,
        ))
    return results, ""


def _probe_results(database: Database, *, query: str, model: str,
                   market: str, country: str) -> tuple[list[dict[str, Any]], str]:
    if model or market or country:
        return [], "探头版本仅登记系列与软件版本，未登记机型、市场和国家适用范围；可清除范围筛选查看。"
    results = []
    for row in probe_versions(database)["rows"]:
        if not _matches(query, *row.values()):
            continue
        results.append(_result(
            "probe_version", title=_text(row["probe_code"], row["probe_model"]),
            scope=_text(row["series_code"], row["software_version"], "机型与市场范围未登记"),
            verification="unverified", matched_text=_text(row["state"], row["probe_model"], row["replaces_probe_code"]),
            locator=_text(row["series_code"], row["software_version"]), view="probe_versions",
            params={"probe": row["probe_code"], "series": row["series_code"], "version": row["software_version"]},
            probe_code=row["probe_code"], probe_version=row,
        ))
    return results, ""


def _qa_results(database: Database, reader: ProductStrategyReader | None, *, query: str,
                model: str, market: str, country: str) -> tuple[list[dict[str, Any]], str]:
    results = []
    messages = []
    for row in database.list_qa_answers(status="published"):
        if model and row["model_name"].casefold() != model.casefold():
            continue
        if market and row["market_code"] != market or country and row["country_code"] != country:
            continue
        if not _matches(query, row["standard_question"], row["answer_text"], *row["similar_questions"]):
            continue
        if row["structured_signature"] is not None and reader is None:
            messages.append("正式问答的结构化来源未配置，等待核对，未显示答案正文。")
            continue
        payload = find_answer(
            database, row["standard_question"], market=row["market_code"],
            country=row["country_code"], model=row["model_name"], reader=reader,
        )
        if payload["state"] != "answered" or payload["answer"]["id"] != row["id"]:
            messages.append(payload.get("reason", "正式答案范围尚不能唯一确认，等待复核。"))
            continue
        answer = payload["answer"]
        results.append(_result(
            "qa", title=row["standard_question"],
            scope=_text(row["market_code"], row["country_code"], row["model_name"]),
            verification="approved", matched_text=answer["answer_text"],
            locator=evidence_locator([answer["evidence"]]), is_current=True,
            view="qa", params={"q": row["standard_question"], "market": row["market_code"],
                               "country": row["country_code"], "model": row["model_name"]},
            answer_id=row["id"], answer=answer,
        ))
    return results, "；".join(dict.fromkeys(messages))


def search_structured_sources(
    database: Database, reader: ProductStrategyReader | None = None, *, query: str = "",
    model: str = "", market: str = "", country: str = "", verification: str = "",
    current_only: bool = False, sources: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Search independent sources, returning sanitized failures beside usable rows."""
    market, country = market.strip().casefold(), country.strip().upper()
    if market not in {"", "domestic", "overseas"}:
        raise ValueError("请选择国内版或海外版。")
    if country and not re.fullmatch(r"[A-Z]{2}", country):
        raise ValueError("国家必须使用两位代码。")
    selected = STRUCTURED_SOURCE_TYPES if sources is None else set(sources) & STRUCTURED_SOURCE_TYPES
    adapters = {
        "registration": lambda **args: _registration_results(database, **args),
        "product_state": lambda **args: _product_state_results(database, **args),
        "knowledge": lambda **args: _knowledge_results(database, **args),
        "probe_version": lambda **args: _probe_results(database, **args),
        "qa": lambda **args: _qa_results(database, reader, **args),
    }
    results, errors = [], {}
    for source, adapter in adapters.items():
        if source not in selected:
            continue
        try:
            rows, message = adapter(query=query.strip(), model=model.strip(), market=market, country=country)
        except ValueError as error:
            rows = []
            # Scope messages are written here, not supplied by source exceptions.
            message = str(error) if str(error) in {
                "国内版与所选国家不一致，请核对范围。",
                "海外版与中国国家范围不一致，请核对范围。",
                "海外资料需要先选择国家，系统不会默认查询中国范围。",
            } else f"{SOURCE_LABELS[source]}来源当前不可用，请检查系统状态。"
        except (sqlite3.Error, OSError, RuntimeError):
            rows, message = [], f"{SOURCE_LABELS[source]}来源当前不可用，请检查系统状态。"
        if message:
            errors[source] = message
        for row in rows:
            if current_only and not row["is_current"]:
                continue
            if verification and row["verification"] != verification:
                continue
            results.append(row)
    return {"results": results, "source_errors": errors}
