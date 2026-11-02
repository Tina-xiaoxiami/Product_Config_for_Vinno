"""Combine the existing registration and formal-strategy readers for explicit entities.

No entity is guessed from question text. A missing registration combination is pending,
and certificate units remain separate instead of being unioned.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import sqlite3
from typing import Any

from tracker.database import Database
from tracker.services.product_strategy import ProductStrategyReader, ProductStrategySourceUnavailable
from tracker.services.registration import registration_query, registration_unit_verified


def _strategy_payload(reader: ProductStrategyReader, model: str, query: str = "") -> dict[str, Any] | None:
    try:
        return reader.query(market="domestic", model=model, query=query)
    except (ProductStrategySourceUnavailable, ValueError, sqlite3.Error):
        return None


def structured_signature(database: Database, reader: ProductStrategyReader, *, country: str, model: str) -> str:
    """Fingerprint the existing readers' model-scoped conclusions, excluding read times."""
    strategy = _strategy_payload(reader, model)
    registration = registration_query(database, model, country)
    registration.pop("checked_at", None)
    if strategy is not None:
        strategy["source"].pop("checked_at", None)
    payload = json.dumps({"registration": registration, "strategy": strategy or {"state": "unavailable"}}, sort_keys=True, ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def _exact_item(payload: dict[str, Any], term: str) -> dict[str, Any] | None:
    needle = term.strip().casefold()
    candidates = [
        item for item in payload["items"]
        if needle in {str(item[key] or "").strip().casefold() for key in ("code", "name", "zh_description")}
    ]
    return candidates[0] if len(candidates) == 1 else None


def joint_answer(
    database: Database,
    reader: ProductStrategyReader,
    *,
    market: str,
    country: str,
    model: str,
    probe: str = "",
    item: str = "",
) -> dict[str, Any]:
    """Return a read-only combined result for an explicit probe and/or strategy item."""
    missing = [key for key, value in (("market", market), ("country", country), ("model", model)) if not value.strip()]
    if missing:
        return {"state": "needs_clarification", "missing": missing}
    if not probe.strip() and not item.strip():
        return {"state": "needs_clarification", "missing": ["probe_or_item"]}
    if market == "domestic" and country != "CN":
        return {"state": "needs_clarification", "missing": ["market_country_match"]}
    if market != "domestic" or country != "CN":
        return {"state": "unanswered", "reason": "该国家/市场的注册与策略资料尚未接入，请登记为后续问题。", "reason_code": "material_gap"}

    strategy_payload = _strategy_payload(reader, model, item or probe)
    registration_payload = registration_query(database, model, country) if probe else None
    units = []
    if registration_payload:
        for unit in registration_payload["units"]:
            matches = [row for row in unit["probes"] if row["probe_code"].casefold() == probe.strip().casefold()]
            if matches:
                evidence_current = registration_unit_verified(database, registration_payload, unit)
                units.append({
                    "certificate_no": unit["certificate_no"],
                    "state": matches[0]["state"],
                    "rule": matches[0]["rule"],
                    "exclusion_consistent": unit["exclusion_consistent"],
                    "evidence_current": evidence_current,
                    "evidence": unit["evidence"],
                })
    strategy_item = _exact_item(strategy_payload, item or probe) if strategy_payload else None
    checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
    registration_state = "not_applicable" if not probe else "pending"
    if units:
        states = {unit["state"] for unit in units}
        registration_state = (
            "conflict" if len(states) != 1 or any(not unit["exclusion_consistent"] for unit in units)
            else "pending" if any(not unit["evidence_current"] for unit in units)
            else "registered" if states == {"已注册"}
            else "unregistered" if states == {"未注册"}
            else "pending"
        )
    strategy_state = strategy_item["knowledge_status"] if strategy_item else "pending_confirmation"
    strategy_label = strategy_item["strategy_label"] if strategy_item else "未找到唯一对应配置项，待确认"

    if registration_state == "unregistered":
        conclusion = "注册资料明确未注册，当前不可提供；产品策略不能覆盖注册红线。"
        state = "blocked"
    elif registration_state in {"pending", "conflict"}:
        conclusion = "注册范围尚无法确认，不能给出可提供的肯定结论。"
        state = "needs_review"
    elif strategy_state != "published":
        conclusion = "产品策略尚无可发布的唯一结论，不能确认提供方式。"
        state = "needs_review"
    elif registration_state == "registered":
        conclusion = f"已注册；当前产品策略为{strategy_label}。"
        state = "resolved"
    else:
        conclusion = f"当前产品策略为{strategy_label}；功能策略不构成该国注册结论。"
        state = "resolved"

    return {
        "state": state,
        "conclusion": conclusion,
        "scope": {"market": market, "country": country, "model": model, "registration_model": registration_payload["registration_model"] if registration_payload else None},
        "registration": {"probe": probe.strip() or None, "state": registration_state, "units": units},
        "strategy": {"query": (item or probe).strip(), "state": strategy_state, "label": strategy_label, "item": strategy_item},
        "source": {"registration": "国家—机型—探头注册关系及受控证据" if probe else "不涉及探头注册", "strategy": "产品配置管理系统 · 正式选型类别" if strategy_payload else "配置源不可用"},
        "knowledge_status": "结构化实时核对，待业务签收",
        "checked_at": checked_at,
        "limitations": "只核对明确填写的探头/配置项；未覆盖的软件版本与其他国家不作推断。",
    }
