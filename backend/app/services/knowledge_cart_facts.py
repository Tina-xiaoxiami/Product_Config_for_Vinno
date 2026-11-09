"""Shared reviewed facts consumed by configuration and Cart."""
from __future__ import annotations

from importlib import import_module
import json
import re

from sqlalchemy import select, text
from sqlalchemy.dialects.sqlite import insert

from app.models.knowledge import KnowledgeFactImpact, KnowledgePublicFact

_MARKETS = {"domestic", "overseas"}
_KEY = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,159}")
_SHA256 = re.compile(r"[a-f0-9]{64}")
_CART_SERVICE = "app.services.cart_release"
BATTERY_IDENTITY_PREFIX = "component.battery:"


async def resolve_cart_fact(db, key: str, market: str, config_versions: dict) -> dict | None:
    row = await db.get(KnowledgePublicFact, (key, market), populate_existing=True)
    if row is None:
        return None
    return {"key": key, "market": market, "configuration_versions": config_versions, **json.loads(row.payload_json)}


def _fact_payload(fact: dict) -> tuple[str, str, str]:
    key, market = fact["key"], fact["market"]
    if not _KEY.fullmatch(key) or market not in _MARKETS:
        raise ValueError("事实键或市场无效")
    status = fact["status"]
    sources = fact.get("sources", [])
    issue = fact.get("issue")
    value = fact.get("value")
    conditions = fact.get("conditions") or {}
    display_value = fact.get("display_value", value if not conditions else None)
    if not isinstance(conditions, dict):
        raise ValueError("事实条件必须为对象")
    if status == "confirmed":
        if value is None or display_value is None or issue or not sources:
            raise ValueError("已确认事实须有值及原件来源，带条件的事实须有完整展示值")
        for source in sources:
            if not _SHA256.fullmatch(source.get("version_id", "")) or not source.get("locator"):
                raise ValueError("原件来源须提供版本哈希及原文定位")
    elif status == "missing":
        if not issue or not _KEY.fullmatch(issue.get("root_key", "")) or not issue.get("detail") or value is not None:
            raise ValueError("缺失事实须提供根因键和原因")
    else:
        raise ValueError("未知事实状态")
    payload = {"status": status, "sources": sources, "issue": issue, "value": value,
               "conditions": conditions, "display_value": display_value}
    return key, market, json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)


async def refresh_cart_impact(db, fact_keys: set[str]) -> list[dict]:
    if not fact_keys:
        return []
    try:
        module = import_module(_CART_SERVICE)
    except ModuleNotFoundError as exc:
        if exc.name != _CART_SERVICE:
            raise
        return []
    return await module.refresh_cart_for_facts(db, fact_keys)


async def apply_cart_facts(db, facts: list[dict]) -> dict:
    """Apply reviewed facts and their dependent refresh in the caller's transaction."""
    rows = [_fact_payload(fact) for fact in facts]
    if len({(key, market) for key, market, _ in rows}) != len(rows):
        raise ValueError("同一批次存在重复事实及市场")
    changed = set()
    for key, market, payload in rows:
        statement = insert(KnowledgePublicFact).values(fact_key=key, market=market, payload_json=payload)
        result = await db.execute(statement.on_conflict_do_update(
            index_elements=["fact_key", "market"], set_={"payload_json": statement.excluded.payload_json},
            where=KnowledgePublicFact.payload_json != statement.excluded.payload_json,
        ).returning(KnowledgePublicFact.fact_key))
        if result.scalar_one_or_none():
            changed.add(key)
    if any(key.startswith(BATTERY_IDENTITY_PREFIX) for key in changed):
        from app.services.knowledge_configuration_answers import refresh_configuration_answers

        await refresh_configuration_answers(db, runtime=True)
    return {"changed_fact_keys": sorted(changed), "cart_impacts": await refresh_cart_impact(db, changed)}


async def reviewed_battery_identities(db, market: str) -> list[dict]:
    installed = (await db.execute(text("""
        SELECT 1 FROM sqlite_master WHERE name='knowledge_public_facts' AND type='table'
    """))).scalar_one_or_none()
    if not installed:
        return []
    rows = (await db.scalars(select(KnowledgePublicFact).where(
        KnowledgePublicFact.market == market,
        KnowledgePublicFact.fact_key.startswith(BATTERY_IDENTITY_PREFIX),
    ).order_by(KnowledgePublicFact.fact_key))).all()
    result = []
    for row in rows:
        fact = json.loads(row.payload_json)
        if fact["status"] != "confirmed":
            continue
        result.append({
            "ipn": row.fact_key.removeprefix(BATTERY_IDENTITY_PREFIX), "name": fact["value"],
            "evidence_reference": "；".join(f"{source.get('file_name', '')} {source['locator']}" for source in fact["sources"]),
        })
    return result


async def invalidate_cart_facts(db, document_id: int, previous_hash: str) -> dict:
    """Require review when a registered original used by a fact changes."""
    installed = (await db.execute(text("""
        SELECT 1 FROM sqlite_master WHERE name='knowledge_public_facts' AND type='table'
    """))).scalar_one_or_none()
    if not installed:
        return {"changed_fact_keys": [], "cart_impacts": []}
    file_name = (await db.execute(text("SELECT file_name FROM knowledge_documents WHERE id=:id"),
                                  {"id": document_id})).scalar_one()
    stale = []
    for row in await db.scalars(select(KnowledgePublicFact)):
        fact = json.loads(row.payload_json)
        if fact["status"] != "confirmed":
            continue
        if any(source.get("version_id") == previous_hash
               and (source.get("document_id") == document_id or source.get("file_name") == file_name)
               for source in fact["sources"]):
            stale.append({"key": row.fact_key, "market": row.market, "status": "missing",
                          "sources": fact["sources"], "issue": {
                              "root_key": f"source.changed:{document_id}", "kind": "source_gap",
                              "detail": "原件已更新，须重新提取并核验事实后使用。",
                          }})
    return await apply_cart_facts(db, stale)


async def link_cart_fact_impact(db, root_key: str, impact: dict) -> None:
    """Record affected pages in the same transaction as the Cart candidate."""
    if not _KEY.fullmatch(root_key) or impact["market"] not in _MARKETS:
        raise ValueError("根因键或 Cart 市场无效")
    statement = insert(KnowledgeFactImpact).values(
        root_key=root_key, market=impact["market"], archive_key=impact["archive_key"],
        pages_json=json.dumps(sorted(set(impact["pages"]))),
    )
    await db.execute(statement.on_conflict_do_update(
        index_elements=["root_key", "market", "archive_key"], set_={"pages_json": statement.excluded.pages_json},
    ))


async def cart_fact_issues(db) -> list[dict]:
    groups: dict[str, dict] = {}
    facts = (await db.scalars(select(KnowledgePublicFact).order_by(
        KnowledgePublicFact.fact_key, KnowledgePublicFact.market
    ))).all()
    for fact in facts:
        issue = json.loads(fact.payload_json).get("issue")
        if issue:
            group = groups.setdefault(issue["root_key"], {**issue, "fact_keys": [], "impacts": []})
            if fact.fact_key not in group["fact_keys"]:
                group["fact_keys"].append(fact.fact_key)
    if groups:
        impacts = (await db.scalars(select(KnowledgeFactImpact).where(
            KnowledgeFactImpact.root_key.in_(groups)
        ).order_by(KnowledgeFactImpact.market, KnowledgeFactImpact.archive_key))).all()
        for row in impacts:
            groups[row.root_key]["impacts"].append({
                "market": row.market, "archive_key": row.archive_key, "pages": json.loads(row.pages_json),
            })
    return list(groups.values())
