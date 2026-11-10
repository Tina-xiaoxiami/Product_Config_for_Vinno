"""Resolve explicit configuration-backed recipes and retain computed revisions."""
from __future__ import annotations

import json
import re

from sqlalchemy import text

from app.services.knowledge_parameters import ParameterError, answer_snapshot, preview
from app.services.knowledge_runtime import runtime_for_model, runtime_models, runtime_question, runtime_source, series_market

_TABLE = "knowledge_configuration_answer_revisions"


async def _installed(db) -> bool:
    return bool((await db.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"
    ), {"name": _TABLE})).first())


async def _model(db, model_id: int, market: str | None = None) -> dict | None:
    row = (await db.execute(text("""
        SELECT m.id,m.name,m.series_id,s.name AS series FROM product_models m
        JOIN product_series s ON s.id=m.series_id WHERE m.id=:id AND m.is_enabled=1 AND COALESCE(m.status, '')<>'已合并'
    """), {"id": model_id})).mappings().one_or_none()
    if row is None:
        return None
    expected = series_market(row["series"])
    if not expected or market not in (None, expected):
        return None
    return {**row, "market": expected}


async def _resolve(db, recipe: str, model: dict, **snapshot_selection) -> dict:
    metadata, snapshot = await answer_snapshot(db, model["series_id"], **snapshot_selection)
    kind, key = recipe.split(":", 1)
    if kind == "runtime":
        result = await runtime_for_model(db, key, model, metadata, snapshot)
    else:
        result = await preview(db, int(key), metadata["id"], [model["id"]])
        result["kind"] = "parameter"
        result["model"] = model
        result["issues"] = result["rows"][0]["issues"]
    return {**result, "recipe": recipe}


async def _resolve_or_review(db, recipe: str, model: dict, **snapshot_selection) -> dict:
    try:
        return await _resolve(db, recipe, model, **snapshot_selection)
    except ParameterError as error:
        return {"recipe": recipe, "kind": recipe.split(":", 1)[0], "model": model,
                "snapshot": None, "rows": [], "issues": [str(error)]}


async def _record(db, result: dict) -> int:
    recipe, model_id = result["recipe"], result["model"]["id"]
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False)
    old = (await db.execute(text(f"""
        SELECT id,payload_json FROM {_TABLE} WHERE recipe=:recipe AND model_id=:model_id ORDER BY id DESC LIMIT 1
    """), {"recipe": recipe, "model_id": model_id})).one_or_none()
    if old and old.payload_json == payload:
        return old.id
    revision = await db.execute(text(f"""
        INSERT INTO {_TABLE}(recipe,model_id,config_version_id,payload_json)
        VALUES (:recipe,:model_id,:version,:payload) RETURNING id
    """), {"recipe": recipe, "model_id": model_id, "version": (result["snapshot"] or {}).get("id"),
            "payload": payload})
    return revision.scalar_one()


async def configuration_answers(
    db, question: str, scope: dict | None, topics: list[dict], *, configuration_version_id: int | None = None,
    unified: bool = False,
) -> list[dict] | None:
    """Return None only for ordinary QA, or a deterministic configuration result."""
    scope = scope or {}
    runtime_text = re.sub(r"国内|海外|中国区|国外|\bchina\b|\boverseas?\b|\d+(?:\.\d+){2,3}(?:版本)?",
                          "", question, flags=re.I) if unified else question
    model_key = runtime_question(runtime_text)
    if unified and model_key == "a5":
        return None
    if not model_key and (not topics or not scope.get("product_model_id")):
        return None
    history = await _installed(db)
    if not history:
        return None
    if model_key and not scope.get("product_model_id") and model_key in {"v5iq", "v6iq"}:
        models = await runtime_models(db, model_key, scope)
        if not models:
            measured, issue = await runtime_source(db, model_key)
            if measured:
                return [{"kind": "runtime", "historical_model": model_key.upper(), "snapshot": None,
                         "rows": [], "historical_rows": measured, "issues": [],
                         "scope_note": "仅列原表中的 IQ 型号实测。原表未登记市场及软件版本，当前配置身份待资料核实。"}]
    software_version = str(scope.get("software_version") or "").strip()
    explicit_snapshot = bool(configuration_version_id or software_version)
    if not explicit_snapshot:
        await db.execute(text("BEGIN IMMEDIATE"))
    try:
        if model_key:
            models = await runtime_models(db, model_key, scope)
            recipes = [f"runtime:{model_key}"]
        else:
            model = await _model(db, scope["product_model_id"], scope.get("market"))
            models = [model] if model else []
            recipes = [f"parameter:{topic['id']}" for topic in topics]
        if not models:
            await db.rollback()
            return [{"kind": "runtime" if model_key else "parameter", "snapshot": None, "rows": [],
                     "issues": ["未找到与问题及所选市场一致的启用机型，请核对完整型号和市场"]}]
        results = []
        for recipe in recipes:
            for model in models:
                result = await _resolve_or_review(
                    db, recipe, model, configuration_version_id=configuration_version_id,
                    software_version=software_version,
                )
                if not explicit_snapshot:
                    result["revision_id"] = await _record(db, result)
                results.append(result)
        if not explicit_snapshot:
            await db.commit()
        return results
    except Exception:
        await db.rollback()
        raise


async def refresh_configuration_answers(
    db, series_ids: set[int] | None = None, *, recipes: set[str] | None = None, runtime: bool = False,
) -> None:
    """Refresh previously resolved recipes within the configuration publication transaction."""
    if (not series_ids and not recipes and not runtime) or not await _installed(db):
        return
    from sqlalchemy import bindparam

    statement = text(f"""
        SELECT DISTINCT r.recipe,r.model_id FROM {_TABLE} r JOIN product_models m ON m.id=r.model_id
        WHERE m.series_id IN :series OR r.recipe IN :recipes OR (:runtime AND r.recipe LIKE 'runtime:%')
        ORDER BY r.recipe,r.model_id
    """).bindparams(bindparam("series", expanding=True), bindparam("recipes", expanding=True))
    bindings = (await db.execute(statement, {"series": sorted(series_ids or ()),
                                            "recipes": sorted(recipes or ()), "runtime": runtime})).all()
    for recipe, model_id in bindings:
        model = await _model(db, model_id)
        if model:
            await _record(db, await _resolve_or_review(db, recipe, model))
        else:
            # Keep the old record while recording that it no longer applies.
            old = (await db.execute(text(f"""
                SELECT payload_json FROM {_TABLE} WHERE recipe=:recipe AND model_id=:model ORDER BY id DESC LIMIT 1
            """), {"recipe": recipe, "model": model_id})).scalar_one()
            await _record(db, {"recipe": recipe, "kind": recipe.split(":", 1)[0], "model": json.loads(old)["model"],
                               "snapshot": None, "rows": [], "issues": ["机型已停用或范围已改变"]})


async def configuration_answer_history(db, recipe: str, model_id: int) -> list[dict]:
    if not await _installed(db):
        return []
    rows = (await db.execute(text(f"""
        SELECT id,payload_json,created_at FROM {_TABLE} WHERE recipe=:recipe AND model_id=:model ORDER BY id DESC LIMIT 20
    """), {"recipe": recipe, "model": model_id})).all()
    return [{**json.loads(row.payload_json), "revision_id": row.id, "created_at": row.created_at} for row in rows]


async def configuration_answer_issues(db) -> list[dict]:
    if not await _installed(db):
        return []
    rows = (await db.execute(text(f"""
        SELECT payload_json FROM {_TABLE} WHERE id IN (
            SELECT MAX(id) FROM {_TABLE} GROUP BY recipe,model_id
        ) ORDER BY recipe,model_id
    """))).scalars()
    groups = {}
    for value in rows:
        result = json.loads(value)
        model = result["model"]
        if result["recipe"] == "runtime:a5":
            continue
        for issue in result.get("review_items", []):
            group = groups.setdefault(issue["root_key"], {**issue, "impacts": []})
            group["impacts"].append({"model_id": model["id"], "model": model["name"],
                                     "market": model["market"], "configuration_version": result["snapshot"]})
    return list(groups.values())
