"""Confirmed-answer Q&A workflow for product knowledge."""

from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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
            WHERE question_id = :question_id AND review_status = 'published'
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


async def get_question(session: AsyncSession, question_id: int) -> dict | None:
    result = await session.execute(
        text(
            """
            SELECT id, question_text, status, asked_count, last_asked_at
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
    return {
        "id": int(question.id),
        "question_text": question.question_text,
        "status": question.status,
        "asked_count": int(question.asked_count),
        "last_asked_at": question.last_asked_at,
        "alias_questions": [row.phrasing_text for row in aliases_result],
        "answer": await _answer_for_question(session, question_id),
    }


async def _published_candidates(session: AsyncSession) -> list[dict]:
    result = await session.execute(
        text(
            """
            SELECT question.id AS question_id,
                   question.question_text,
                   question.normalized_question,
                   phrasing.phrasing_text,
                   phrasing.normalized_phrasing
            FROM knowledge_questions question
            JOIN knowledge_answers answer
              ON answer.question_id = question.id
             AND answer.review_status = 'published'
            LEFT JOIN knowledge_question_phrasings phrasing
              ON phrasing.question_id = question.id
            WHERE question.status = 'answered'
            ORDER BY question.id, phrasing.id
            """
        )
    )
    return [dict(row._mapping) for row in result]


async def ask_question(session: AsyncSession, question_text: str) -> dict:
    cleaned = str(question_text or "").strip()
    normalized = normalize_question(cleaned)
    if len(normalized) < 2:
        raise KnowledgeQaError("问题内容过短")

    best_question_id: int | None = None
    best_score = 0.0
    best_exact = False
    for candidate in await _published_candidates(session):
        variants = [
            (candidate["question_text"], candidate["normalized_question"]),
            (candidate["phrasing_text"], candidate["normalized_phrasing"]),
        ]
        for variant_text, variant_normalized in variants:
            if not variant_text:
                continue
            exact = normalized == variant_normalized
            score = 1.0 if exact else question_similarity(cleaned, variant_text)
            if score > best_score:
                best_question_id = int(candidate["question_id"])
                best_score = score
                best_exact = exact

    if best_question_id is not None and best_score >= SIMILARITY_THRESHOLD:
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
                    SELECT 1 FROM knowledge_questions WHERE normalized_question = :normalized
                    UNION ALL
                    SELECT 1 FROM knowledge_question_phrasings WHERE normalized_phrasing = :normalized
                    LIMIT 1
                    """
                ),
                {"normalized": normalized},
            )
            if collision.one_or_none() is None:
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_question_phrasings (
                            question_id, phrasing_text, normalized_phrasing, phrasing_type
                        ) VALUES (:question_id, :text, :normalized, 'observed')
                        """
                    ),
                    {
                        "question_id": best_question_id,
                        "text": cleaned,
                        "normalized": normalized,
                    },
                )
        await session.commit()
        item = await get_question(session, best_question_id)
        return {
            "status": "answered",
            "question_id": best_question_id,
            "question": item["question_text"],
            "match_type": "exact" if best_exact else "similar",
            "similarity": best_score,
            "answer": item["answer"],
        }

    existing_result = await session.execute(
        text(
            """
            SELECT id FROM knowledge_questions
            WHERE normalized_question = :normalized_question
            """
        ),
        {"normalized_question": normalized},
    )
    existing = existing_result.one_or_none()
    if existing:
        question_id = int(existing.id)
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
            {"question_id": question_id},
        )
    else:
        result = await session.execute(
            text(
                """
                INSERT INTO knowledge_questions (
                    question_text, normalized_question, status, asked_count
                ) VALUES (:question_text, :normalized_question, 'pending', 1)
                RETURNING id
                """
            ),
            {"question_text": cleaned, "normalized_question": normalized},
        )
        question_id = int(result.scalar_one())
    await session.commit()
    item = await get_question(session, question_id)
    return {
        "status": item["status"],
        "question_id": question_id,
        "question": item["question_text"],
        "match_type": "none",
        "similarity": best_score,
        "answer": item["answer"],
    }


async def list_questions(
    session: AsyncSession,
    *,
    status: str | None,
    query: str | None,
    skip: int,
    limit: int,
) -> tuple[list[dict], int]:
    cleaned_query = str(query or "").strip()
    params = {
        "status": status,
        "pattern": f"%{cleaned_query}%" if cleaned_query else None,
        "skip": skip,
        "limit": limit,
    }
    filters = """
        (:status IS NULL OR status = :status)
        AND (:pattern IS NULL OR question_text LIKE :pattern)
    """
    total_result = await session.execute(
        text(f"SELECT COUNT(*) FROM knowledge_questions WHERE {filters}"), params
    )
    rows_result = await session.execute(
        text(
            f"""
            SELECT id FROM knowledge_questions
            WHERE {filters}
            ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,
                     asked_count DESC, last_asked_at DESC, id DESC
            LIMIT :limit OFFSET :skip
            """
        ),
        params,
    )
    items = [await get_question(session, int(row.id)) for row in rows_result]
    return items, int(total_result.scalar_one())


async def publish_answer(
    session: AsyncSession,
    *,
    question_id: int,
    answer_text: str,
    alias_questions: list[str],
    citations: list[dict],
    change_note: str | None,
) -> dict | None:
    question = await get_question(session, question_id)
    if question is None:
        return None
    cleaned_answer = str(answer_text or "").strip()
    if not cleaned_answer:
        raise KnowledgeQaError("答案不能为空")

    unique_aliases: list[tuple[str, str]] = []
    seen = {normalize_question(question["question_text"])}
    for alias in alias_questions:
        cleaned_alias = str(alias or "").strip()
        normalized_alias = normalize_question(cleaned_alias)
        if len(normalized_alias) < 2 or normalized_alias in seen:
            continue
        seen.add(normalized_alias)
        unique_aliases.append((cleaned_alias, normalized_alias))

    for _, normalized_alias in unique_aliases:
        collision_result = await session.execute(
            text(
                """
                SELECT id FROM knowledge_questions
                WHERE normalized_question = :normalized AND id != :question_id
                UNION ALL
                SELECT question_id AS id FROM knowledge_question_phrasings
                WHERE normalized_phrasing = :normalized AND question_id != :question_id
                LIMIT 1
                """
            ),
            {"normalized": normalized_alias, "question_id": question_id},
        )
        if collision_result.one_or_none() is not None:
            raise KnowledgeQaError("相似问法已归属于其他问题")

    resolved_citations: list[dict] = []
    for index, citation in enumerate(citations):
        document_result = await session.execute(
            text(
                """
                SELECT id FROM knowledge_documents
                WHERE id = :document_id AND source_status = 'active'
                """
            ),
            {"document_id": citation["document_id"]},
        )
        if document_result.one_or_none() is None:
            raise KnowledgeQaError(f"引用资料不存在：{citation['document_id']}")
        resolved_citations.append({**citation, "sort_order": index})

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
        version = int(existing_answer.version) + 1
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
                    question_id, phrasing_text, normalized_phrasing, phrasing_type
                ) VALUES (:question_id, :text, :normalized, 'alias')
                """
            ),
            {
                "question_id": question_id,
                "text": alias_text,
                "normalized": normalized_alias,
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
            SET status = 'answered', updated_at = CURRENT_TIMESTAMP
            WHERE id = :question_id
            """
        ),
        {"question_id": question_id},
    )
    await session.commit()
    return await get_question(session, question_id)


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
    return [dict(row._mapping) for row in result]
