"""One explicit query scope shared by matching, evidence, queues and snapshots."""

from __future__ import annotations

import json
import re
import unicodedata

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


SCOPE_FIELDS = ("country", "market", "product_model_id", "software_version")
STORED_FIELDS = {*SCOPE_FIELDS, "model_name", "series_name"}


class KnowledgeScopeError(ValueError):
    pass


class KnowledgeScopeUnavailable(KnowledgeScopeError):
    pass


def missing_scope_fields(scope: dict | None) -> list[str]:
    return [name for name in SCOPE_FIELDS if not (scope or {}).get(name)]


def scope_key(scope: dict | None) -> str:
    return json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if scope else ""


def stored_scope(key: str) -> dict | None:
    if not key:
        return None
    try:
        scope = json.loads(key)
        if not isinstance(scope, dict) or set(scope) != STORED_FIELDS or missing_scope_fields(scope):
            raise ValueError("invalid stored scope")
        values = _normalized_values(scope)
        if any(scope[name] != values[name] for name in SCOPE_FIELDS):
            raise ValueError("nonnormalized scope")
        if not all(isinstance(scope[name], str) and scope[name].strip() for name in ("model_name", "series_name")):
            raise ValueError("invalid model identity")
        _check_series_market(scope["series_name"], scope["market"])
        if scope_key(scope) != key:
            raise ValueError("noncanonical stored scope")
        return scope
    except (ValueError, TypeError) as exc:
        raise KnowledgeScopeError("问题的适用范围记录无效，请先核对") from exc


async def scope_schema_ready(session: AsyncSession) -> bool:
    if "knowledge_scope_ready" not in session.info:
        questions = await session.execute(text("PRAGMA table_info(knowledge_questions)"))
        phrasings = await session.execute(text("PRAGMA table_info(knowledge_question_phrasings)"))
        session.info["knowledge_scope_ready"] = all(
            "scope_key" in {row[1] for row in rows} for rows in (questions, phrasings)
        )
    return session.info["knowledge_scope_ready"]


async def scope_expression(session: AsyncSession, alias: str = "") -> str:
    return (f"{alias}." if alias else "") + "scope_key" if await scope_schema_ready(session) else "''"


async def resolve_query_scope(session: AsyncSession, supplied: dict | None) -> dict | None:
    if missing_scope_fields(supplied):
        return None
    if not await scope_schema_ready(session):
        raise KnowledgeScopeUnavailable("查询范围尚未迁移；请先演练并执行知识库范围迁移")
    values = _normalized_values(supplied or {})
    model_id = values["product_model_id"]
    row = (await session.execute(text(
        "SELECT p.id, p.name, s.name AS series_name FROM product_models p "
        "JOIN product_series s ON s.id=p.series_id WHERE p.id=:id"
    ), {"id": model_id})).one_or_none()
    if row is None:
        raise KnowledgeScopeError("所选完整机型不存在")
    _check_series_market(row.series_name, values["market"])
    return {**values, "model_name": row.name, "series_name": row.series_name}


def _normalized_values(values: dict) -> dict:
    country = unicodedata.normalize("NFKC", str(values["country"])).strip().upper()
    market = values["market"]
    version = unicodedata.normalize("NFKC", str(values["software_version"])).strip()
    model_id = values["product_model_id"]
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise KnowledgeScopeError("国家须填写两位国家代码，如CN、DE")
    if market not in {"domestic", "overseas"} or ((country == "CN") != (market == "domestic")):
        raise KnowledgeScopeError("国家与国内/海外范围不一致")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version) or len(version) > 80:
        raise KnowledgeScopeError("请填写明确的软件版本，不支持通配符或版本范围")
    version = ".".join(str(int(part)) for part in version.split("."))
    if not isinstance(model_id, int) or isinstance(model_id, bool) or model_id <= 0:
        raise KnowledgeScopeError("请选择有效的完整机型")
    return {"country": country, "market": market, "product_model_id": model_id,
            "software_version": version}


def _check_series_market(series_name: str, market: str) -> None:
    suffix = series_name.rsplit("-", 1)[-1].casefold()
    if {"china": "domestic", "oversea": "overseas"}.get(suffix) != market:
        raise KnowledgeScopeError("所选机型的正式系列与查询市场不一致或尚未明确")


def document_matches_scope(document, scope: dict) -> bool:
    """Only explicit complete model and software metadata qualify in this first increment.

    A generic series label or a manual revision such as R10 is not a software
    applicability declaration. Those sources await explicit scope registration.
    """
    return all(document[name] == scope[field] for name, field in (
        ("country", "country"), ("market", "market"),
        ("product_series", "model_name"), ("version", "software_version"),
    ))
