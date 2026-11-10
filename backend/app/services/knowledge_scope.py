"""One explicit query scope shared by matching, evidence, queues and snapshots."""

from __future__ import annotations

import json
import re
import unicodedata

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


SCOPE_FIELDS = ("country", "market", "product_model_id", "software_version")
REQUIRED_SCOPE_FIELDS = ("market", "product_model_id", "software_version")
STORED_FIELDS = {*SCOPE_FIELDS, "model_name", "series_name"}
_A_SERIES = re.compile(r"(?<![a-z0-9])(?:vinno\s*)?a(?:\s*系列|[0-9]+[a-z]*)(?![a-z0-9])", re.I)
_V_SERIES = re.compile(r"(?<![a-z0-9])(?:vinno\s+\d|v(?:\s*系列|\d))", re.I)


def a_only_question(question: str) -> bool:
    return bool(_A_SERIES.search(question) and not _V_SERIES.search(question))


class KnowledgeScopeError(ValueError):
    pass


class KnowledgeScopeUnavailable(KnowledgeScopeError):
    pass


def missing_scope_fields(scope: dict | None) -> list[str]:
    return [name for name in REQUIRED_SCOPE_FIELDS if not (scope or {}).get(name)]


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


async def compatible_scope_keys(session: AsyncSession, scope: dict, *, overlap: bool = False) -> list[str]:
    """Read neutral queries across valid historical countries without changing raw keys.

    Explicit-country reads remain exact. Mutation checks also include neutral
    owners because their applicability overlaps every country in that market.
    """
    key = scope_key(scope)
    if scope["country"] is not None and not overlap:
        return [key]
    keys = {key}
    rows = await session.execute(text("SELECT DISTINCT scope_key FROM knowledge_questions WHERE scope_key != ''"))
    for row in rows:
        try:
            candidate = stored_scope(row.scope_key)
        except KnowledgeScopeError:
            continue
        if not candidate or any(candidate[name] != scope[name] for name in STORED_FIELDS - {"country"}):
            continue
        if scope["country"] is None or candidate["country"] in {None, scope["country"]}:
            keys.add(row.scope_key)
    return sorted(keys)


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


async def infer_question_scope(session: AsyncSession, question: str, supplied: dict | None) -> dict:
    scope = {key: value for key, value in (supplied or {}).items() if value}
    query = unicodedata.normalize("NFKC", question).casefold()
    markets = {market for market, pattern in (
        ("domestic", r"国内|中国区|\bchina\b"), ("overseas", r"海外|国外|\boverseas?\b"),
    ) if re.search(pattern, query)}
    versions = set(re.findall(r"(?<![\d.])\d+(?:\.\d+){2,3}(?![\d.])", query))
    if len(markets) == 1:
        if scope.get("market") and scope["market"] not in markets:
            raise KnowledgeScopeError("问题中的市场与所选市场不同，请核对查询范围")
        scope.setdefault("market", next(iter(markets)))
    if len(versions) == 1:
        if scope.get("software_version") and scope["software_version"] not in versions:
            raise KnowledgeScopeError("问题中的软件版本与所选版本不同，请核对查询范围")
        scope.setdefault("software_version", next(iter(versions)))
    records = (await session.execute(text("""
        SELECT p.id,p.name,s.name AS series_name FROM product_models p
        JOIN product_series s ON s.id=p.series_id
    """))).mappings().all()
    matched = []
    for model in records:
        market = {"china": "domestic", "oversea": "overseas"}.get(model["series_name"].rsplit("-", 1)[-1].casefold())
        if not market or scope.get("market", market) != market:
            continue
        if scope.get("product_model_id") == model["id"]:
            scope.setdefault("market", market)
        name = unicodedata.normalize("NFKC", model["name"]).strip().casefold()
        parts = re.split(r"\s+", name)
        pattern = r"\s*".join(map(re.escape, parts))
        short = re.fullmatch(r"vinno\s+(\d[\w-]*)", name)
        if short:
            pattern = rf"(?:{pattern}|v{re.escape(short[1])})"
        if re.search(rf"(?<![a-z0-9_]){pattern}(?![a-z0-9_])", query):
            matched.append((len(name), model["id"], market))
    if matched:
        maximum = max(match[0] for match in matched)
        best = [match for match in matched if match[0] == maximum]
        selected = scope.get("product_model_id")
        if selected and selected not in {match[1] for match in best}:
            raise KnowledgeScopeError("问题中的机型与所选机型不同，请核对查询范围")
        if not selected and len(best) == 1:
            _, scope["product_model_id"], market = best[0]
            scope.setdefault("market", market)
    return scope


def _normalized_values(values: dict) -> dict:
    country = (unicodedata.normalize("NFKC", str(values["country"])).strip().upper()
               if values.get("country") is not None else None)
    market = values["market"]
    version = unicodedata.normalize("NFKC", str(values["software_version"])).strip()
    model_id = values["product_model_id"]
    if country is not None and not re.fullmatch(r"[A-Z]{2}", country):
        raise KnowledgeScopeError("国家须填写两位国家代码，如CN、DE")
    if market not in {"domestic", "overseas"}:
        raise KnowledgeScopeError("请选择国内或海外市场")
    if country is not None and ((country == "CN") != (market == "domestic")):
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
    return (scope["country"] is None or document["country"] == scope["country"]) and all(document[name] == scope[field] for name, field in (
        ("market", "market"),
        ("product_series", "model_name"), ("version", "software_version"),
    ))


async def document_model_identity_unique(session: AsyncSession, scope: dict) -> bool:
    """Legacy document model labels cannot distinguish same-name series identities."""
    rows = await session.execute(text(
        "SELECT p.id, s.name AS series_name FROM product_models p "
        "JOIN product_series s ON s.id=p.series_id WHERE p.name=:name"
    ), {"name": scope["model_name"]})
    matches = [row.id for row in rows if {
        "china": "domestic", "oversea": "overseas"
    }.get(row.series_name.rsplit("-", 1)[-1].casefold()) == scope["market"]]
    return matches == [scope["product_model_id"]]
