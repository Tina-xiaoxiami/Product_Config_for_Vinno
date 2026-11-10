"""Confirmed-answer Q&A workflow for product knowledge."""

from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import knowledge_answer_drafts as drafts
from app.services.knowledge_names import KnowledgeNameContext, load_name_context
from app.services.knowledge_scope_migration import has_monotonic_question_ids

from app.services.knowledge_scope import (
    KnowledgeScopeError, KnowledgeScopeUnavailable, document_matches_scope, document_model_identity_unique,
    a_only_question, compatible_scope_keys, missing_scope_fields, resolve_query_scope, scope_expression, scope_key,
    scope_schema_ready, stored_scope,
)


SIMILARITY_THRESHOLD = 0.72
_STOP_PHRASES = (
    "是不是",
    "是否",
    "这个",
    "该功能",
    "功能",
    "属于",
    "请问",
    "有没有",
    "有无",
    "的吗",
)
_NEGATED_INTENTS = ("不支持", "不能", "不可以", "未注册", "没有", "不标配", "非标配")
_MARKET_SCOPES = ("国内", "海外")


class KnowledgeQaError(ValueError):
    """Raised when a Q&A change violates controlled knowledge rules."""


def normalize_question(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _semantic_core(value: str) -> str:
    core = normalize_question(value)
    for phrase in _STOP_PHRASES:
        core = core.replace(normalize_question(phrase), "")
    return core


def _character_dice(left: str, right: str) -> float:
    left_chars = set(left)
    right_chars = set(right)
    if not left_chars or not right_chars:
        return 0.0
    return 2 * len(left_chars & right_chars) / (len(left_chars) + len(right_chars))


def _bigram_dice(left: str, right: str) -> float:
    left_pairs = {left[index : index + 2] for index in range(max(0, len(left) - 1))}
    right_pairs = {right[index : index + 2] for index in range(max(0, len(right) - 1))}
    if not left_pairs or not right_pairs:
        return 0.0
    return 2 * len(left_pairs & right_pairs) / (len(left_pairs) + len(right_pairs))


def _critical_identifiers(value: str) -> set[str]:
    normalized = normalize_question(value)
    identifiers = set(re.findall(r"(?:vinno|v)\d+[a-z0-9]*", normalized))
    identifiers.update(re.findall(r"\d{6,}", normalized))
    return {
        re.sub(r"^vinno", "v", identifier)
        for identifier in identifiers
    }


def _has_negated_intent(value: str) -> bool:
    core = _semantic_core(value)
    return any(normalize_question(marker) in core for marker in _NEGATED_INTENTS)


def _market_scopes(value: str) -> set[str]:
    normalized = normalize_question(value)
    return {scope for scope in _MARKET_SCOPES if scope in normalized}


def question_similarity(left: str, right: str) -> float:
    if _critical_identifiers(left) != _critical_identifiers(right):
        return 0.0
    if _has_negated_intent(left) != _has_negated_intent(right):
        return 0.0
    if _market_scopes(left) != _market_scopes(right):
        return 0.0
    left_core = _semantic_core(left)
    right_core = _semantic_core(right)
    if not left_core or not right_core:
        return 0.0
    if left_core == right_core:
        return 1.0
    sequence = SequenceMatcher(None, left_core, right_core).ratio()
    bag_score = 0.7 * _character_dice(left_core, right_core) + 0.3 * _bigram_dice(
        left_core, right_core
    )
    return round(max(sequence, bag_score), 4)


async def _answer_for_question(session: AsyncSession, question_id: int) -> dict | None:
    answer_result = await session.execute(
        text(
            """
            SELECT id, answer_text, review_status, version, change_note, updated_at
            FROM knowledge_answers
            WHERE question_id = :question_id
            """
        ),
        {"question_id": question_id},
    )
    answer = answer_result.one_or_none()
    if answer is None:
        return None
    citation_result = await session.execute(
        text(
            """
            SELECT citation.id, citation.document_id, document.title AS document_title,
                   citation.source_ref, citation.excerpt
            FROM knowledge_answer_citations citation
            JOIN knowledge_documents document ON document.id = citation.document_id
            WHERE citation.answer_id = :answer_id
            ORDER BY citation.sort_order, citation.id
            """
        ),
        {"answer_id": answer.id},
    )
    citations = []
    for row in citation_result:
        item = dict(row._mapping)
        item["preview_url"] = f"/api/knowledge/documents/{row.document_id}/preview"
        citations.append(item)
    return {
        "id": int(answer.id),
        "answer_text": answer.answer_text,
        "review_status": answer.review_status,
        "version": int(answer.version),
        "change_note": answer.change_note,
        "updated_at": answer.updated_at,
        "citations": citations,
    }


async def get_question(session: AsyncSession, question_id: int, *, name_context: KnowledgeNameContext | None = None) -> dict | None:
    from app.services.knowledge_answer_review import evidence_review_summary
    scope_column = await scope_expression(session)
    result = await session.execute(
        text(
            f"""
            SELECT id, question_text, status, asked_count, last_asked_at, {scope_column} AS scope_key
            FROM knowledge_questions WHERE id = :question_id
            """
        ),
        {"question_id": question_id},
    )
    question = result.one_or_none()
    if question is None:
        return None
    aliases_result = await session.execute(
        text(
            """
            SELECT phrasing_text
            FROM knowledge_question_phrasings
            WHERE question_id = :question_id AND phrasing_type = 'alias'
            ORDER BY id
            """
        ),
        {"question_id": question_id},
    )
    answer = await _answer_for_question(session, question_id)
    edit = await drafts.latest_edit(session, question_id)
    if edit and edit["published_version"] is None:
        saved_sources = edit.get("source_versions", [])
        edit["source_changed"] = saved_sources != await drafts.capture_sources(session, edit["citations"])
    if answer and answer["review_status"] == "source_changed":
        snapshot = (await drafts.publication_evidence(session, question_id)).get(answer["version"])
        if snapshot and snapshot["citations"] and all(citation.get("sha256") for citation in snapshot["citations"]):
            answer["basis_changed"] = True
            answer["citations"] = [
                {**citation, "version_id": citation["sha256"], "preview_url": f'{citation["preview_url"]}?version_id={citation["sha256"]}'}
                if citation.get("sha256") else citation for citation in snapshot["citations"]
            ]
    context = name_context if name_context is not None else await load_name_context(session)
    displayed_question, displayed_answer, bindings = context.question(question.question_text, answer['answer_text'] if answer else '')
    if answer:
        answer['display_answer_text'] = displayed_answer
    return {
        "id": int(question.id),
        "question_text": question.question_text,
        "display_question_text": displayed_question,
        "name_bindings": bindings,
        "status": question.status,
        "asked_count": int(question.asked_count),
        "last_asked_at": question.last_asked_at,
        "alias_questions": [row.phrasing_text for row in aliases_result],
        "answer": answer,
        "draft": edit if edit and edit["published_version"] is None else None,
        "scope": stored_scope(question.scope_key),
        "evidence_review": await evidence_review_summary(session, question_id),
    }


async def _published_candidates(session: AsyncSession, query_scope_key: str) -> list[dict]:
    keys = await compatible_scope_keys(session, stored_scope(query_scope_key))
    reusable_snapshot = ""
    if await drafts._has_table(session, "knowledge_answer_publication_evidence"):
        reusable_snapshot = """
          OR (answer.review_status='source_changed' AND EXISTS (
              SELECT 1 FROM knowledge_answer_revisions r
              JOIN knowledge_answer_publication_evidence e ON e.revision_id=r.id
              WHERE r.answer_id=answer.id AND r.version=answer.version
              AND json_array_length(json_extract(e.payload_json,'$.citations'))>0
              AND NOT EXISTS (
                  SELECT 1 FROM json_each(e.payload_json,'$.citations')
                  WHERE COALESCE(json_extract(value,'$.sha256'),'')=''
              )))
        """
    result = await session.execute(
        text(
            f"""
            SELECT question.id AS question_id,
                   question.scope_key,
                   question.question_text,
                   question.normalized_question,
                   answer.answer_text,
                   phrasing.phrasing_text,
                   phrasing.normalized_phrasing
            FROM knowledge_questions question
            JOIN knowledge_answers answer
              ON answer.question_id = question.id
            LEFT JOIN knowledge_question_phrasings phrasing
              ON phrasing.question_id = question.id
            WHERE ((question.status = 'answered' AND answer.review_status = 'published') {reusable_snapshot})
              AND question.scope_key IN :scope_keys
              AND NOT EXISTS (
                  SELECT 1 FROM knowledge_answer_citations citation
                  JOIN knowledge_documents document ON document.id = citation.document_id
                  WHERE citation.answer_id = answer.id AND document.source_status != 'active'
              )
            ORDER BY question.id, phrasing.id
            """
        ).bindparams(bindparam("scope_keys", expanding=True)),
        {"scope_keys": keys},
    )
    return [dict(row._mapping) for row in result]


async def ensure_question(session: AsyncSession, question_text: str, query_scope_key: str, *, count_ask: bool) -> int:
    cleaned = str(question_text or "").strip()
    normalized = normalize_question(cleaned)
    params = {"normalized": normalized, "scope": query_scope_key}
    if count_ask:
        # Acquire the writer lock before deciding whether a pending question still exists.
        existing = (await session.execute(text("""
            UPDATE knowledge_questions
            SET asked_count=asked_count+1, last_asked_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
            WHERE normalized_question=:normalized AND scope_key=:scope RETURNING id
        """), params)).one_or_none()
    else:
        existing = (await session.execute(text("""
            SELECT id FROM knowledge_questions WHERE normalized_question=:normalized AND scope_key=:scope
        """), params)).one_or_none()
    if existing:
        return int(existing.id)
    result = await session.execute(text(
        "INSERT INTO knowledge_questions (question_text,normalized_question,status,asked_count,scope_key) "
        "VALUES (:question,:normalized,'pending',:count,:scope) RETURNING id"
    ), {"question": cleaned, "normalized": normalized, "count": 1 if count_ask else 0, "scope": query_scope_key})
    return int(result.scalar_one())


async def delete_pending_question(
    session: AsyncSession, question_id: int, *, expected_question: str,
    expected_scope: dict | None, expected_answer_version: int | None, expected_draft_revision: int = 0,
) -> bool:
    """Remove one pending question and its draft data after checking the displayed version."""
    await session.execute(text("BEGIN IMMEDIATE"))
    try:
        scope_column = await scope_expression(session, "q")
        row = (await session.execute(text(f"""
            SELECT q.question_text, q.status, {scope_column} AS scope_key,
                   a.id AS answer_id, a.review_status, a.version
            FROM knowledge_questions q
            LEFT JOIN knowledge_answers a ON a.question_id=q.id
            WHERE q.id=:id
        """), {"id": question_id})).mappings().one_or_none()
        if row is None:
            await session.rollback()
            return False
        await _require_monotonic_question_ids(session)
        if row["status"] != "pending" or (row["answer_id"] is not None and row["review_status"] != "draft"):
            raise KnowledgeQaError("仅可删除待确认问题及未发布草稿")
        edit = await drafts.latest_edit(session, question_id)
        if (row["question_text"] != expected_question or row["scope_key"] != scope_key(expected_scope)
                or row["version"] != expected_answer_version or (edit["revision"] if edit else 0) != expected_draft_revision):
            raise KnowledgeQaError("问题或草稿已变化，请刷新列表后再删除")
        if row["answer_id"] is not None:
            params = {"id": row["answer_id"]}
            published_history = (await session.execute(text("""
                SELECT 1 FROM knowledge_answer_revisions
                WHERE answer_id=:id AND review_status!='draft' LIMIT 1
            """), params)).first()
            has_review_table = (await session.execute(text("""
                SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_answer_reviews'
            """))).first()
            has_reviews = has_review_table and (await session.execute(text("""
                SELECT 1 FROM knowledge_answer_reviews WHERE answer_id=:id LIMIT 1
            """), params)).first()
            if published_history or has_reviews:
                raise KnowledgeQaError("此答案已有发布或核对记录，请保留历史")
            # Existing SQLite sessions do not always enable foreign key cascades.
            await session.execute(text("DELETE FROM knowledge_answer_citations WHERE answer_id=:id"), params)
            await session.execute(text("DELETE FROM knowledge_answer_revisions WHERE answer_id=:id"), params)
            await session.execute(text("DELETE FROM knowledge_answers WHERE id=:id"), params)
        await drafts.remove_edits(session, question_id)
        await session.execute(text("DELETE FROM knowledge_question_phrasings WHERE question_id=:id"), {"id": question_id})
        await session.execute(text("DELETE FROM knowledge_questions WHERE id=:id"), {"id": question_id})
        await session.commit()
        return True
    except Exception:
        await session.rollback()
        raise


async def _require_monotonic_question_ids(session: AsyncSession) -> None:
    schema = await session.scalar(text("""
        SELECT sql FROM sqlite_master WHERE type='table' AND name='knowledge_questions'
    """))
    if not has_monotonic_question_ids(schema):
        raise KnowledgeQaError("当前问答库会复用已删除的问题编号，请完成问答库迁移后重试")


async def _checked_question_text(session: AsyncSession, question: dict, value: str) -> str:
    renamed = value.strip()
    normalized = normalize_question(renamed)
    if len(normalized) < 2:
        raise KnowledgeQaError("问题内容过短")
    if renamed == question["question_text"]:
        return renamed
    scope_column = await scope_expression(session)
    duplicate = (await session.execute(text(f"""
        SELECT 1 FROM knowledge_questions WHERE id<>:id
            AND normalized_question=:normalized AND {scope_column}=:scope
        UNION ALL
        SELECT 1 FROM knowledge_question_phrasings WHERE question_id<>:id
            AND normalized_phrasing=:normalized AND {scope_column}=:scope
        LIMIT 1
    """), {"id": question["id"], "normalized": normalized, "scope": scope_key(question["scope"])})).first()
    if duplicate:
        raise KnowledgeQaError("同一范围内已有此问题或问法")
    return renamed


async def save_answer_draft(
    session: AsyncSession, question_id: int | None, *, expected_version: int, expected_draft_revision: int,
    question_text: str | None, answer_text: str, change_note: str,
    alias_questions: list[str] | None, citations: list[dict] | None, new_scope: dict | None = None,
) -> dict | None:
    await session.execute(text("BEGIN IMMEDIATE"))
    try:
        if question_id is None:
            resolved = await resolve_query_scope(session, new_scope)
            if not resolved or len(normalize_question(question_text or "")) < 2:
                raise KnowledgeQaError("保存草稿前请补齐问题及适用范围")
            question_id = await ensure_question(session, question_text, scope_key(resolved), count_ask=False)
        question = await get_question(session, question_id)
        if question is None:
            await session.rollback()
            return None
        answer = question["answer"] or {}
        previous = question["draft"] or {}
        if (answer.get("version", 0) != expected_version or previous.get("revision", 0) != expected_draft_revision):
            raise KnowledgeQaError("草稿或正式答案已更新，请重新打开后核对修改")
        if not answer_text.strip() or not change_note.strip():
            raise KnowledgeQaError("请填写答案和变更说明")
        wording = await _checked_question_text(
            session, question, question_text if question_text is not None else previous.get("question_text", question["question_text"]),
        )
        payload = {
            "question_text": wording, "answer_text": answer_text.strip(), "change_note": change_note.strip(),
            "base_version": expected_version,
            "alias_questions": alias_questions if alias_questions is not None else previous.get("alias_questions", question["alias_questions"]),
            "citations": citations if citations is not None else previous.get("citations", answer.get("citations", [])),
        }
        payload["source_versions"] = await drafts.capture_sources(session, payload["citations"])
        await drafts.append_edit(session, question_id, payload)
        item = await get_question(session, question_id)
        await session.commit()
        return item
    except Exception:
        await session.rollback()
        raise


async def ask_question(session: AsyncSession, question_text: str, *, scope: dict | None = None,
                       record_unanswered: bool = True) -> dict:
    cleaned = str(question_text or "").strip()
    normalized = normalize_question(cleaned)
    if len(normalized) < 2:
        raise KnowledgeQaError("问题内容过短")
    resolved_scope = await resolve_query_scope(session, scope)
    if resolved_scope is None:
        return {"status": "needs_clarification", "question_id": None,
                "question": cleaned, "match_type": "none", "similarity": 0.0,
                "answer": None, "candidates": [], "scope": scope if not record_unanswered else None,
                "missing_fields": missing_scope_fields(scope)}
    query_scope_key = scope_key(resolved_scope)

    name_context = await load_name_context(session)
    explicit_query_ipns = name_context.explicit_ipns(cleaned)
    query_ipns = explicit_query_ipns or name_context.named_ipns(cleaned)
    ambiguous_name = name_context.ambiguous_query(cleaned)
    displayed_query, _ = name_context.project(cleaned)
    best_question_id: int | None = None
    best_ties: set[int] = set()
    best_score = 0.0
    best_exact = False
    candidates = [] if ambiguous_name else await _published_candidates(session, query_scope_key)
    matched_records = {int(candidate["question_id"]): candidate for candidate in candidates}
    for candidate in candidates:
        candidate_ipns = name_context.explicit_ipns(candidate['answer_text'])
        candidate_question_ipns = name_context.explicit_ipns(candidate['question_text']) or name_context.named_ipns(candidate['question_text'])
        if query_ipns and candidate_ipns and not query_ipns.intersection(candidate_ipns):
            continue
        if explicit_query_ipns and not explicit_query_ipns.issubset(candidate_ipns):
            continue
        if query_ipns and candidate_question_ipns and not query_ipns.intersection(candidate_question_ipns):
            continue
        displayed_question, _, _ = name_context.question(candidate['question_text'], candidate['answer_text'])
        displayed_phrasing, _, _ = name_context.question(candidate['phrasing_text'] or '', candidate['answer_text'])
        variants = [
            (displayed_question, normalize_question(displayed_question)),
            (displayed_phrasing, normalize_question(displayed_phrasing)),
            (candidate["question_text"], candidate["normalized_question"]),
            (candidate["phrasing_text"], candidate["normalized_phrasing"]),
        ]
        comparison_query = displayed_query
        if explicit_query_ipns:
            comparison_query = re.sub(r'[（(]\s*IPN\s*[:：]?\s*\d{7}\s*[）)]', '', comparison_query, flags=re.I)
        for variant_text, variant_normalized in variants:
            if not variant_text:
                continue
            exact = normalized == variant_normalized
            score = 1.0 if exact else max(question_similarity(cleaned, variant_text), question_similarity(comparison_query, variant_text))
            if score > best_score:
                best_question_id = int(candidate["question_id"])
                best_score = score
                best_exact = exact
                best_ties = {int(candidate['question_id'])}
            elif score == best_score and score >= SIMILARITY_THRESHOLD:
                best_ties.add(int(candidate['question_id']))

    if len(best_ties) > 1:
        identities = {(matched_records[question_id]["normalized_question"], matched_records[question_id]["answer_text"])
                      for question_id in best_ties}
        best_question_id = min(best_ties, key=lambda question_id: (
            stored_scope(matched_records[question_id]["scope_key"])["country"] is not None, question_id
        )) if len(identities) == 1 else None
    if resolved_scope["country"] is None and best_question_id is not None:
        selected = matched_records[best_question_id]
        # A unique alias or IPN match cannot hide a conflicting country sibling.
        if any(candidate["normalized_question"] == selected["normalized_question"]
               and candidate["answer_text"] != selected["answer_text"]
               for candidate in matched_records.values()):
            best_question_id = None
    if best_question_id is not None and best_score >= SIMILARITY_THRESHOLD:
        matched_key = matched_records[best_question_id]["scope_key"]
        await session.execute(
            text(
                """
                UPDATE knowledge_questions
                SET asked_count = asked_count + 1,
                    last_asked_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :question_id
                """
            ),
            {"question_id": best_question_id},
        )
        if not best_exact:
            collision = await session.execute(
                text(
                    """
                    SELECT 1 FROM knowledge_questions WHERE normalized_question = :normalized AND scope_key = :scope_key
                    UNION ALL
                    SELECT 1 FROM knowledge_question_phrasings WHERE normalized_phrasing = :normalized AND scope_key = :scope_key
                    LIMIT 1
                    """
                ),
                {"normalized": normalized, "scope_key": matched_key},
            )
            if collision.one_or_none() is None:
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_question_phrasings (
                            question_id, phrasing_text, normalized_phrasing, phrasing_type, scope_key
                        ) VALUES (:question_id, :text, :normalized, 'observed', :scope_key)
                        """
                    ),
                    {
                        "question_id": best_question_id,
                        "text": cleaned,
                        "normalized": normalized,
                        "scope_key": matched_key,
                    },
                )
        await session.commit()
        item = await get_question(session, best_question_id, name_context=name_context)
        answer = item["answer"] or {}
        if not answer.get("basis_changed") and (item["status"] != "answered" or answer.get("review_status") != "published"):
            from app.services.knowledge_content import find_candidate_evidence

            return {
                "status": "pending",
                "question_id": best_question_id,
                "question": item["question_text"],
                "match_type": "none",
                "similarity": best_score,
                "answer": None,
                "candidates": await find_candidate_evidence(session, item["question_text"], scope=resolved_scope),
                "scope": resolved_scope,
            }
        return {
            "status": "answered",
            "question_id": best_question_id,
            "question": item["question_text"],
            "display_question": (item or {}).get("display_question_text"),
            "match_type": "exact" if best_exact else "similar",
            "similarity": best_score,
            "answer": item["answer"],
            "candidates": [],
            "scope": resolved_scope,
            "matched_scope": item["scope"],
        }

    item = None
    if record_unanswered:
        question_id = await ensure_question(session, cleaned, query_scope_key, count_ask=True)
        await session.commit()
        item = await get_question(session, question_id)
    else:
        existing_id = (await session.execute(text("""
            SELECT id FROM knowledge_questions WHERE scope_key=:scope AND normalized_question=:normalized
        """), {"scope": query_scope_key, "normalized": normalized})).scalar_one_or_none()
        if existing_id is not None:
            item = await get_question(session, existing_id)
    from app.services.knowledge_content import find_candidate_evidence

    pending_text = item["question_text"] if item else cleaned
    candidates = await find_candidate_evidence(session, pending_text, scope=resolved_scope)
    from app.services.knowledge_release_history import history_for_question
    history_trace = await history_for_question(session, cleaned, resolved_scope)
    return {
        "status": "pending",
        "question_id": item["id"] if item else None,
        "question": pending_text,
        "match_type": "none",
        "similarity": best_score,
        "answer": None,
        "candidates": candidates,
        "history_trace": history_trace,
        "scope": resolved_scope,
    }


async def list_questions(
    session: AsyncSession,
    *,
    status: str | None,
    query: str | None,
    skip: int,
    limit: int,
    scope: dict | None = None,
    evidence_review: str | None = None,
    workflow: str | None = None,
    all_scopes: bool = False,
    managed: bool = False,
) -> tuple[list[dict], int]:
    cleaned_query = str(query or "").strip()
    resolved_scope = await resolve_query_scope(session, scope) if scope else None
    if scope and resolved_scope is None:
        raise KnowledgeScopeError("问题列表的查询范围不完整")
    scope_column = await scope_expression(session, "q")
    params: dict[str, object] = {
        "status": status,
        "pattern": f"%{cleaned_query}%" if cleaned_query else None,
        "skip": skip,
        "limit": limit,
        "scope_key": scope_key(resolved_scope),
    }
    if resolved_scope:
        params["scope_keys"] = await compatible_scope_keys(session, resolved_scope)
    name_context = await load_name_context(session)
    matched_ids = []
    if cleaned_query:
        search_rows = (await session.execute(text("""
            SELECT q.id,q.question_text,a.answer_text,
                   (SELECT group_concat(p.phrasing_text, CHAR(10)) FROM knowledge_question_phrasings p WHERE p.question_id=q.id) AS phrasings
            FROM knowledge_questions q LEFT JOIN knowledge_answers a ON a.question_id=q.id
        """))).mappings()
        displayed_query, _ = name_context.project(cleaned_query)
        needles = {cleaned_query.casefold(), displayed_query.casefold()}
        for row in search_rows:
            displayed_question, displayed_answer, _ = name_context.question(row['question_text'], row['answer_text'] or '')
            if any(needle in str(value or '').casefold() for needle in needles for value in
                   (row['question_text'], row['answer_text'], row['phrasings'], displayed_question, displayed_answer)):
                matched_ids.append(int(row['id']))
        params['matched_ids'] = matched_ids
    filters = f"""
        (:status IS NULL OR q.status = :status)
        AND ({"q.id IN :matched_ids" if cleaned_query else "1"})
        AND ({"1" if (all_scopes or evidence_review) and not scope else scope_column + (" IN :scope_keys" if resolved_scope else " = :scope_key")})
    """
    if evidence_review:
        from app.services.knowledge_answer_review import evidence_review_filter
        filters += " AND " + await evidence_review_filter(session, evidence_review)
    if workflow:
        working = "0"
        if await drafts._has_table(session, "knowledge_answer_draft_edits"):
            working = """COALESCE((
                SELECT edit.published_version IS NULL FROM knowledge_answer_draft_edits edit
                WHERE edit.question_id=q.id AND (edit.published_version IS NULL OR edit.published_version>0)
                ORDER BY edit.id DESC LIMIT 1
            ), 0)"""
        if workflow == "draft":
            filters += f""" AND ({working} OR EXISTS (
                SELECT 1 FROM knowledge_answers a WHERE a.question_id=q.id AND a.review_status='draft'
            ))"""
        elif workflow == "unanswered":
            filters += f" AND NOT ({working}) AND NOT EXISTS (SELECT 1 FROM knowledge_answers a WHERE a.question_id=q.id)"
    if managed:
        questions = (await session.execute(text("SELECT id,question_text FROM knowledge_questions"))).all()
        params["excluded_ids"] = [row.id for row in questions if a_only_question(row.question_text)]
        filters += " AND q.id NOT IN :excluded_ids"
    total_statement = text(f"SELECT COUNT(*) FROM knowledge_questions q WHERE {filters}")
    rows_statement = text(
            f"""
            SELECT q.id FROM knowledge_questions q
            WHERE {filters}
            ORDER BY CASE q.status WHEN 'pending' THEN 0 ELSE 1 END,
                     asked_count DESC, last_asked_at DESC, id DESC
            LIMIT :limit OFFSET :skip
            """
        )
    if cleaned_query:
        total_statement = total_statement.bindparams(bindparam('matched_ids', expanding=True))
        rows_statement = rows_statement.bindparams(bindparam('matched_ids', expanding=True))
    if resolved_scope:
        total_statement = total_statement.bindparams(bindparam('scope_keys', expanding=True))
        rows_statement = rows_statement.bindparams(bindparam('scope_keys', expanding=True))
    if managed:
        total_statement = total_statement.bindparams(bindparam('excluded_ids', expanding=True))
        rows_statement = rows_statement.bindparams(bindparam('excluded_ids', expanding=True))
    total_result = await session.execute(total_statement, params)
    rows_result = await session.execute(rows_statement, params)
    items = [await get_question(session, int(row.id), name_context=name_context) for row in rows_result]
    return items, int(total_result.scalar_one())


async def validate_publication_scope(
    session: AsyncSession, *, scope: dict, question_text: str, answer_text: str,
    alias_questions: list[str], question_id: int | None = None,
) -> None:
    """Keep canonical answers and wording owners consistent across overlapping scopes."""
    keys = await compatible_scope_keys(session, scope, overlap=True)
    normalized = normalize_question(question_text)
    wording = {normalized, *(normalize_question(alias) for alias in alias_questions
                              if len(normalize_question(alias)) >= 2)}
    if question_id is not None:
        observed = await session.execute(text(
            "SELECT normalized_phrasing FROM knowledge_question_phrasings "
            "WHERE question_id=:id AND phrasing_type='observed'"
        ), {"id": question_id})
        wording.update(row.normalized_phrasing for row in observed)
    owners = await session.execute(text("""
        SELECT q.normalized_question,a.answer_text,a.review_status,p.normalized_phrasing
        FROM knowledge_questions q
        LEFT JOIN knowledge_answers a ON a.question_id=q.id
        LEFT JOIN knowledge_question_phrasings p ON p.question_id=q.id
        WHERE q.scope_key IN :keys AND q.id != :id
    """).bindparams(bindparam("keys", expanding=True)), {"keys": keys, "id": question_id or -1})
    for owner in owners:
        same_question = owner.normalized_question == normalized
        if same_question and owner.review_status == "published" and owner.answer_text != answer_text.strip():
            raise KnowledgeQaError("适用范围内已有不同的已发布答案，请先核对或修订")
        if not same_question and (owner.normalized_question in wording or owner.normalized_phrasing in wording):
            raise KnowledgeQaError("相似问法已归属于其他问题")


async def publish_answer(
    session: AsyncSession,
    *,
    question_id: int,
    answer_text: str | None,
    alias_questions: list[str],
    citations: list[dict],
    change_note: str | None,
    commit: bool = True,
    draft_revision: int | None = None,
) -> dict | None:
    question = await get_question(session, question_id)
    if question is None:
        return None
    working = question["draft"]
    if draft_revision is not None:
        if not working:
            last = await drafts.latest_edit(session, question_id)
            if last and last["revision"] == draft_revision and last["published_version"] == (question["answer"] or {}).get("version"):
                if commit:
                    await session.rollback()
                return question
        if not working or working["revision"] != draft_revision:
            raise KnowledgeQaError("草稿已变化，请刷新后发布")
        if working["base_version"] != (question["answer"] or {}).get("version", 0):
            raise KnowledgeQaError("正式答案已变化，请重新核对草稿")
        if working["source_changed"]:
            raise KnowledgeQaError("草稿引用的原件已变化，请核对最新原文并重新保存草稿")
        answer_text = working["answer_text"]
        alias_questions = working["alias_questions"]
        citations = working["citations"]
        change_note = working["change_note"]
        wording = await _checked_question_text(session, question, working["question_text"])
    elif working:
        raise KnowledgeQaError("已有持久草稿，请从保存的草稿发布")
    else:
        wording = question["question_text"]
    if not question["scope"]:
        raise KnowledgeQaError("此问题的历史范围尚未核实；请先在明确范围内建立问答")
    query_scope_key = scope_key(question["scope"])
    cleaned_answer = str(answer_text or "").strip()
    if not cleaned_answer:
        raise KnowledgeQaError("答案不能为空")

    unique_aliases: list[tuple[str, str]] = []
    seen = {normalize_question(wording)}
    for alias in alias_questions:
        cleaned_alias = str(alias or "").strip()
        normalized_alias = normalize_question(cleaned_alias)
        if len(normalized_alias) < 2 or normalized_alias in seen:
            continue
        seen.add(normalized_alias)
        unique_aliases.append((cleaned_alias, normalized_alias))

    await validate_publication_scope(session, scope=question["scope"], question_id=question_id,
        question_text=wording, answer_text=cleaned_answer,
        alias_questions=[alias for alias, _ in unique_aliases])

    resolved_citations: list[dict] = []
    if citations and not await document_model_identity_unique(session, question["scope"]):
        raise KnowledgeQaError("同市场存在同名完整机型，资料尚无唯一机型对应，不能作为此答案依据")
    for index, citation in enumerate(citations):
        document_result = await session.execute(
            text(
                """
                SELECT id, country, market, product_series, version FROM knowledge_documents
                WHERE id = :document_id AND source_status = 'active'
                """
            ),
            {"document_id": citation["document_id"]},
        )
        document = document_result.one_or_none()
        if document is None:
            raise KnowledgeQaError(f"引用资料不存在：{citation['document_id']}")
        if not document_matches_scope(document._mapping, question["scope"]):
            raise KnowledgeQaError("引用资料尚未明确关联此市场、机型及软件版本，请先核实适用范围")
        resolved_citations.append({key: citation.get(key) for key in ("document_id", "source_ref", "excerpt")} | {"sort_order": index})

    await drafts.freeze_evidence(session, question)
    answer_result = await session.execute(
        text(
            """
            SELECT id, version FROM knowledge_answers
            WHERE question_id = :question_id
            """
        ),
        {"question_id": question_id},
    )
    existing_answer = answer_result.one_or_none()
    if existing_answer is None:
        version = 1
        inserted = await session.execute(
            text(
                """
                INSERT INTO knowledge_answers (
                    question_id, answer_text, review_status, version, change_note
                ) VALUES (
                    :question_id, :answer_text, 'published', :version, :change_note
                ) RETURNING id
                """
            ),
            {
                "question_id": question_id,
                "answer_text": cleaned_answer,
                "version": version,
                "change_note": change_note,
            },
        )
        answer_id = int(inserted.scalar_one())
    else:
        answer_id = int(existing_answer.id)
        previous_version = int(existing_answer.version)
        if draft_revision is not None and question["answer"]["review_status"] == "draft":
            previous_version = await drafts.archive_legacy_draft_versions(session, question)
        version = previous_version + 1
        await session.execute(
            text(
                """
                UPDATE knowledge_answers
                SET answer_text = :answer_text,
                    review_status = 'published',
                    version = :version,
                    change_note = :change_note,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :answer_id
                """
            ),
            {
                "answer_id": answer_id,
                "answer_text": cleaned_answer,
                "version": version,
                "change_note": change_note,
            },
        )

    await session.execute(
        text(
            """
            DELETE FROM knowledge_question_phrasings
            WHERE question_id = :question_id AND phrasing_type = 'alias'
            """
        ),
        {"question_id": question_id},
    )
    for alias_text, normalized_alias in unique_aliases:
        await session.execute(
            text(
                """
                DELETE FROM knowledge_question_phrasings
                WHERE question_id = :question_id
                  AND normalized_phrasing = :normalized
                """
            ),
            {"question_id": question_id, "normalized": normalized_alias},
        )
        await session.execute(
            text(
                """
                INSERT INTO knowledge_question_phrasings (
                    question_id, phrasing_text, normalized_phrasing, phrasing_type, scope_key
                ) VALUES (:question_id, :text, :normalized, 'alias', :scope_key)
                """
            ),
            {
                "question_id": question_id,
                "text": alias_text,
                "normalized": normalized_alias,
                "scope_key": query_scope_key,
            },
        )

    await session.execute(
        text("DELETE FROM knowledge_answer_citations WHERE answer_id = :answer_id"),
        {"answer_id": answer_id},
    )
    for citation in resolved_citations:
        await session.execute(
            text(
                """
                INSERT INTO knowledge_answer_citations (
                    answer_id, document_id, source_ref, excerpt, sort_order
                ) VALUES (
                    :answer_id, :document_id, :source_ref, :excerpt, :sort_order
                )
                """
            ),
            {"answer_id": answer_id, **citation},
        )
    await session.execute(
        text(
            """
            INSERT INTO knowledge_answer_revisions (
                answer_id, version, answer_text, review_status, change_note
            ) VALUES (
                :answer_id, :version, :answer_text, 'published', :change_note
            )
            """
        ),
        {
            "answer_id": answer_id,
            "version": version,
            "answer_text": cleaned_answer,
            "change_note": change_note,
        },
    )
    await session.execute(
        text(
            """
            UPDATE knowledge_questions
            SET status = 'answered', question_text=:wording, normalized_question=:normalized, updated_at = CURRENT_TIMESTAMP
            WHERE id = :question_id
            """
        ),
        {"question_id": question_id, "wording": wording, "normalized": normalize_question(wording)},
    )
    if draft_revision is not None:
        await drafts.mark_published(session, draft_revision, version)
    item = await get_question(session, question_id)
    await drafts.freeze_evidence(session, item)
    if commit:
        await session.commit()
    return item


async def merge_question(
    session: AsyncSession,
    *,
    source_question_id: int,
    target_question_id: int,
) -> dict | None:
    """Merge a pending duplicate into a published canonical question."""
    if source_question_id == target_question_id:
        raise KnowledgeQaError("不能将问题合并到自身")
    if not await scope_schema_ready(session):
        raise KnowledgeScopeUnavailable("请先完成知识库范围迁移再合并问题")

    result = await session.execute(
        text(
            """
            SELECT id, question_text, normalized_question, status,
                   asked_count, last_asked_at, scope_key
            FROM knowledge_questions
            WHERE id IN (:source_question_id, :target_question_id)
            """
        ),
        {
            "source_question_id": source_question_id,
            "target_question_id": target_question_id,
        },
    )
    questions = {int(row.id): row for row in result}
    if source_question_id not in questions or target_question_id not in questions:
        return None

    await _require_monotonic_question_ids(session)
    source = questions[source_question_id]
    target = questions[target_question_id]
    if source.scope_key != target.scope_key:
        raise KnowledgeQaError("不同国家、市场、机型或软件版本的问题不能合并")
    if source.status != "pending":
        raise KnowledgeQaError("只能合并尚未发布答案的待确认问题")
    source_answer = await session.execute(
        text("SELECT 1 FROM knowledge_answers WHERE question_id = :question_id"),
        {"question_id": source_question_id},
    )
    if source_answer.one_or_none() is not None or await drafts.latest_edit(session, source_question_id):
        raise KnowledgeQaError("已有答案的问题不能合并，请先复核原答案")
    if target.status != "answered":
        raise KnowledgeQaError("目标问题必须已有正式发布答案")

    published_result = await session.execute(
        text(
            """
            SELECT 1 FROM knowledge_answers
            WHERE question_id = :question_id AND review_status = 'published'
            """
        ),
        {"question_id": target_question_id},
    )
    if published_result.one_or_none() is None:
        raise KnowledgeQaError("目标问题必须已有正式发布答案")

    aliases_result = await session.execute(
        text(
            """
            SELECT phrasing_text, normalized_phrasing
            FROM knowledge_question_phrasings
            WHERE question_id = :question_id
            ORDER BY id
            """
        ),
        {"question_id": source_question_id},
    )
    variants = [(source.question_text, source.normalized_question)] + [
        (row.phrasing_text, row.normalized_phrasing) for row in aliases_result
    ]
    target_scope = stored_scope(target.scope_key)
    overlap_keys = (await compatible_scope_keys(session, target_scope, overlap=True)
                    if target_scope else [target.scope_key])
    unique_variants: list[tuple[str, str]] = []
    seen = {target.normalized_question}
    for text_value, normalized_value in variants:
        if normalized_value in seen:
            continue
        seen.add(normalized_value)
        collision_result = await session.execute(
            text(
                """
                SELECT id FROM knowledge_questions
                WHERE normalized_question = :normalized
                  AND scope_key IN :scope_keys
                  AND id NOT IN (:source_question_id, :target_question_id)
                UNION ALL
                SELECT question_id AS id FROM knowledge_question_phrasings
                WHERE normalized_phrasing = :normalized
                  AND scope_key IN :scope_keys
                  AND question_id NOT IN (:source_question_id, :target_question_id)
                LIMIT 1
                """
            ).bindparams(bindparam("scope_keys", expanding=True)),
            {
                "normalized": normalized_value,
                "source_question_id": source_question_id,
                "target_question_id": target_question_id,
                "scope_keys": overlap_keys,
            },
        )
        if collision_result.one_or_none() is not None:
            raise KnowledgeQaError("待合并问法已归属于其他问题")
        unique_variants.append((text_value, normalized_value))

    await session.execute(
        text(
            """
            UPDATE knowledge_questions
            SET asked_count = asked_count + :source_asked_count,
                last_asked_at = CASE
                    WHEN last_asked_at >= :source_last_asked_at THEN last_asked_at
                    ELSE :source_last_asked_at
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :target_question_id
            """
        ),
        {
            "source_asked_count": int(source.asked_count),
            "source_last_asked_at": source.last_asked_at,
            "target_question_id": target_question_id,
        },
    )
    await session.execute(
        text("DELETE FROM knowledge_questions WHERE id = :source_question_id"),
        {"source_question_id": source_question_id},
    )
    for phrasing_text, normalized_phrasing in unique_variants:
        existing_result = await session.execute(
            text(
                """
                SELECT 1 FROM knowledge_question_phrasings
                WHERE question_id = :question_id
                  AND normalized_phrasing = :normalized
                """
            ),
            {
                "question_id": target_question_id,
                "normalized": normalized_phrasing,
            },
        )
        if existing_result.one_or_none() is not None:
            continue
        await session.execute(
            text(
                """
                INSERT INTO knowledge_question_phrasings (
                    question_id, phrasing_text, normalized_phrasing, phrasing_type, scope_key
                ) VALUES (:question_id, :text, :normalized, 'alias', :scope_key)
                """
            ),
            {
                "question_id": target_question_id,
                "text": phrasing_text,
                "normalized": normalized_phrasing,
                "scope_key": target.scope_key,
            },
        )

    await session.commit()
    return await get_question(session, target_question_id)


async def get_answer_history(session: AsyncSession, question_id: int) -> list[dict] | None:
    question_result = await session.execute(
        text("SELECT id FROM knowledge_questions WHERE id = :question_id"),
        {"question_id": question_id},
    )
    if question_result.one_or_none() is None:
        return None
    result = await session.execute(
        text(
            """
            SELECT revision.version, revision.answer_text, revision.review_status,
                   revision.change_note, revision.created_at
            FROM knowledge_answer_revisions revision
            JOIN knowledge_answers answer ON answer.id = revision.answer_id
            WHERE answer.question_id = :question_id
            ORDER BY revision.version DESC
            """
        ),
        {"question_id": question_id},
    )
    evidence = await drafts.publication_evidence(session, question_id)
    revisions = [{**row._mapping, **evidence.get(row.version, {})} for row in result]
    return await drafts.edit_history(session, question_id) + revisions
