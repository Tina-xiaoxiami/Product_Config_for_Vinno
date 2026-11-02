"""Explicit owner evidence decisions, reusing existing Q&A publication rules."""

from __future__ import annotations

import hashlib
import json
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge_scope import resolve_query_scope, scope_expression, scope_key


class KnowledgeAnswerReviewError(ValueError):
    pass


class KnowledgeAnswerReviewConflict(KnowledgeAnswerReviewError):
    pass


class KnowledgeAnswerReviewUnavailable(KnowledgeAnswerReviewError):
    pass


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _prepare(session: AsyncSession) -> bool:
    connection = await session.connection()
    await connection.run_sync(lambda sync: sync.connection.create_function("kh_answer_fingerprint", 1, _hash, deterministic=True))
    return (await session.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_answer_reviews'"
    ))).first() is not None


def _fingerprint_expression(scope_column: str) -> str:
    return f"""kh_answer_fingerprint(json_object(
        'answer_id',a.id,'version',a.version,'body',a.answer_text,
        'status',a.review_status,'change_note',a.change_note,
        'question',q.question_text,'scope',{scope_column},
        'citations',COALESCE((SELECT json_group_array(json_object(
            'id',ordered.id,'document_id',ordered.document_id,'source_ref',ordered.source_ref,
            'excerpt',ordered.excerpt,'sort_order',ordered.sort_order,
            'document_sha256',ordered.sha256,'document_status',ordered.source_status
        )) FROM (SELECT c.id,c.document_id,c.source_ref,c.excerpt,c.sort_order,d.sha256,d.source_status
          FROM knowledge_answer_citations c LEFT JOIN knowledge_documents d ON d.id=c.document_id
          WHERE c.answer_id=a.id ORDER BY c.sort_order,c.id) ordered),'[]')
    ))"""


async def _source(session: AsyncSession, question_id: int):
    expression = _fingerprint_expression(await scope_expression(session, "q"))
    return (await session.execute(text(f"""
        SELECT a.id AS answer_id,a.version,a.review_status,{expression} AS fingerprint,
               (SELECT COUNT(*) FROM knowledge_answer_citations c WHERE c.answer_id=a.id) AS citation_count
        FROM knowledge_questions q JOIN knowledge_answers a ON a.question_id=q.id WHERE q.id=:id
    """), {"id": question_id})).mappings().one_or_none()


async def evidence_review_summary(session: AsyncSession, question_id: int) -> dict:
    available = await _prepare(session)
    source = await _source(session, question_id)
    latest = None
    if source and available:
        row = (await session.execute(text(
            "SELECT * FROM knowledge_answer_reviews WHERE answer_id=:id ORDER BY review_revision DESC LIMIT 1"
        ), {"id": source["answer_id"]})).mappings().one_or_none()
        if row:
            latest = dict(row)
            latest["product_model_ids"] = json.loads(latest.pop("model_ids_json"))
            latest["target_question_ids"] = json.loads(latest.pop("target_question_ids_json"))
    current = bool(source and latest and latest["source_fingerprint"] == source["fingerprint"])
    reviewed = bool(current and latest and latest["action"] in {"record_reference", "confirm_scope"})
    needs_review = bool(source and source["review_status"] == "published" and not reviewed and
                        (source["citation_count"] == 0 or (current and latest and latest["action"] == "defer")))
    return {
        "status": "reviewed" if reviewed else "needs_review" if needs_review else "not_required",
        "fingerprint": source["fingerprint"] if source else None,
        "review_revision": latest["review_revision"] if latest else 0,
        "latest": latest, "available": available,
    }


async def evidence_review_filter(session: AsyncSession, mode: str) -> str:
    """Return a server-side predicate for the outer knowledge_questions alias q."""
    available = await _prepare(session)
    fingerprint = _fingerprint_expression(await scope_expression(session, "q"))
    if available:
        latest = "r.id=(SELECT r2.id FROM knowledge_answer_reviews r2 WHERE r2.answer_id=a.id ORDER BY r2.review_revision DESC LIMIT 1)"
        confirmed = f"EXISTS(SELECT 1 FROM knowledge_answer_reviews r WHERE r.answer_id=a.id AND {latest} AND r.source_fingerprint={fingerprint} AND r.action IN ('record_reference','confirm_scope'))"
        deferred = f"EXISTS(SELECT 1 FROM knowledge_answer_reviews r WHERE r.answer_id=a.id AND {latest} AND r.source_fingerprint={fingerprint} AND r.action='defer')"
    else:
        confirmed, deferred = "0", "0"
    decision = confirmed if mode == "reviewed" else f"NOT ({confirmed}) AND (NOT EXISTS(SELECT 1 FROM knowledge_answer_citations c WHERE c.answer_id=a.id) OR ({deferred}))"
    return f"EXISTS(SELECT 1 FROM knowledge_answers a WHERE a.question_id=q.id AND a.review_status='published' AND ({decision}))"


def _clean_payload(payload: dict) -> dict:
    values = dict(payload)
    for field in ("evidence_reference", "note", "confirmed_by"):
        values[field] = str(values.get(field) or "").strip()
    if not values["confirmed_by"]:
        raise KnowledgeAnswerReviewError("请填写实际确认人")
    if values["action"] == "defer":
        if not values["note"]:
            raise KnowledgeAnswerReviewError("暂缓核对须填写原因")
    elif not values["evidence_reference"]:
        raise KnowledgeAnswerReviewError("请填写已有确认记录或资料依据")
    values["country"] = (values.get("country") or "").strip().upper() or None
    if values["country"] and not re.fullmatch(r"[A-Z]{2}", values["country"]):
        raise KnowledgeAnswerReviewError("国家须填写两位国家代码")
    if values["country"] and values.get("market") and ((values["country"] == "CN") != (values["market"] == "domestic")):
        raise KnowledgeAnswerReviewError("国家与国内/海外范围不一致")
    models = values.get("product_model_ids") or []
    if any(not isinstance(model, int) or isinstance(model, bool) or model <= 0 for model in models):
        raise KnowledgeAnswerReviewError("请选择有效的完整机型")
    values["product_model_ids"] = sorted(set(models))
    values["software_version"] = (values.get("software_version") or "").strip() or None
    return values


async def _append(session: AsyncSession, source, values: dict, request_hash: str, targets: list[int]) -> None:
    await session.execute(text("""
        INSERT INTO knowledge_answer_reviews (
            answer_id,answer_version,source_fingerprint,review_revision,action,country,market,
            model_ids_json,software_version,version_applicability,evidence_reference,note,confirmed_by,
            target_question_ids_json,request_fingerprint
        ) VALUES (:id,:version,:fingerprint,
            (SELECT COALESCE(MAX(review_revision),0)+1 FROM knowledge_answer_reviews WHERE answer_id=:id),
            :action,:country,:market,:models,:software_version,:version_applicability,:evidence_reference,
            :note,:confirmed_by,:targets,:request_hash)
    """), {**values, "id": source["answer_id"], "version": source["version"],
            "fingerprint": source["fingerprint"], "models": _json(values["product_model_ids"]),
            "targets": _json(targets), "request_hash": request_hash})


async def review_answer(session: AsyncSession, question_id: int, **payload) -> dict | None:
    from app.services.knowledge_qa import get_question, ensure_question, normalize_question, publish_answer

    if not await _prepare(session):
        raise KnowledgeAnswerReviewUnavailable("答案核对记录表尚未初始化，请更新服务后重试")
    values = _clean_payload(payload)
    request_hash = _hash(_json({key: value for key, value in values.items() if not key.startswith("expected_")}))
    # A dedicated API request owns this transaction; no nested publication commits.
    await session.execute(text("BEGIN IMMEDIATE"))
    try:
        question = await get_question(session, question_id)
        source = await _source(session, question_id)
        if question is None or source is None:
            await session.rollback()
            return None
        summary = question["evidence_review"]
        if (source["version"] != values["expected_answer_version"] or
                source["fingerprint"] != values["expected_fingerprint"]):
            raise KnowledgeAnswerReviewConflict("答案、依据或范围已变化，请重新打开核对窗口")
        latest = summary["latest"]
        if summary["review_revision"] != values["expected_review_revision"]:
            if (latest and latest["source_fingerprint"] == source["fingerprint"] and
                    latest["request_fingerprint"] == request_hash):
                await session.rollback()
                return await get_question(session, question_id)
            raise KnowledgeAnswerReviewConflict("已有新的核对结论，请重新打开窗口")
        targets: list[int] = []
        if values["action"] == "confirm_scope":
            if values["version_applicability"] != "specific" or not values["product_model_ids"]:
                raise KnowledgeAnswerReviewError("用于查询的答案必须明确具体软件版本和完整机型")
            scopes = []
            for model_id in values["product_model_ids"]:
                scope = await resolve_query_scope(session, {"country": values["country"], "market": values["market"],
                    "product_model_id": model_id, "software_version": values["software_version"]})
                if scope is None:
                    raise KnowledgeAnswerReviewError("请补齐国家、市场、完整机型和软件版本")
                scopes.append(scope)
            for scope in scopes:
                key = scope_key(scope)
                normalized = normalize_question(question["question_text"])
                collision = (await session.execute(text(
                    "SELECT 1 FROM knowledge_question_phrasings WHERE scope_key=:scope AND normalized_phrasing=:normalized "
                    "AND question_id NOT IN (SELECT id FROM knowledge_questions WHERE scope_key=:scope AND normalized_question=:normalized)"
                ), {"scope": key, "normalized": normalized})).first()
                if collision:
                    raise KnowledgeAnswerReviewConflict("该范围中的问法已属于其他问题，请先核对或修订")
                target_id = await ensure_question(session, question["question_text"], key, count_ask=False)
                target = await get_question(session, target_id)
                if target["answer"]:
                    if (target["answer"]["answer_text"] != question["answer"]["answer_text"] or
                            target["answer"]["review_status"] != "published"):
                        raise KnowledgeAnswerReviewConflict("该范围已有不同答案，请先查看并修订，不会自动覆盖")
                else:
                    await publish_answer(session, question_id=target_id, answer_text=question["answer"]["answer_text"],
                        alias_questions=question["alias_questions"], citations=[],
                        change_note=f"依据历史问题Q{question_id}/答案v{source['version']}，由{values['confirmed_by']}确认范围；{values['evidence_reference']}",
                        commit=False)
                targets.append(target_id)
                target_source = await _source(session, target_id)
                if target_source["answer_id"] != source["answer_id"]:
                    await _append(session, target_source, values, request_hash, [])
        await _append(session, source, values, request_hash, targets)
        await session.commit()
        return await get_question(session, question_id)
    except Exception:
        await session.rollback()
        raise
