"""Create review-only knowledge questions from a controlled batch manifest."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge_content import find_candidate_evidence
from app.services.knowledge_qa import (
    SIMILARITY_THRESHOLD,
    normalize_question,
    question_similarity,
)


@dataclass(frozen=True)
class SeedQuestionSpec:
    category: str
    question: str


def _validate_specs(specs: list[SeedQuestionSpec]) -> list[tuple[SeedQuestionSpec, str]]:
    validated: list[tuple[SeedQuestionSpec, str]] = []
    seen: set[str] = set()
    for spec in specs:
        category = str(spec.category or "").strip()
        question = str(spec.question or "").strip()
        normalized = normalize_question(question)
        if not category:
            raise ValueError("问题类别不能为空")
        if len(normalized) < 2:
            raise ValueError("问题内容过短")
        if len(question) > 500:
            raise ValueError("问题内容不能超过500字")
        if normalized in seen:
            raise ValueError(f"批次内存在重复问题：{question}")
        seen.add(normalized)
        validated.append((SeedQuestionSpec(category=category, question=question), normalized))
    if not validated:
        raise ValueError("问题批次不能为空")
    return validated


async def _existing_questions(session: AsyncSession) -> dict[str, dict]:
    result = await session.execute(
        text(
            """
            SELECT id, question_text, normalized_question, status
            FROM knowledge_questions
            ORDER BY id
            """
        )
    )
    return {row.normalized_question: dict(row._mapping) for row in result}


async def _published_variants(session: AsyncSession) -> list[dict]:
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


def _best_published_match(question: str, variants: list[dict]) -> tuple[int | None, float]:
    normalized = normalize_question(question)
    best_question_id: int | None = None
    best_score = 0.0
    for candidate in variants:
        for variant_text, variant_normalized in (
            (candidate["question_text"], candidate["normalized_question"]),
            (candidate["phrasing_text"], candidate["normalized_phrasing"]),
        ):
            if not variant_text:
                continue
            score = (
                1.0
                if normalized == variant_normalized
                else question_similarity(question, variant_text)
            )
            if score > best_score:
                best_question_id = int(candidate["question_id"])
                best_score = score
    if best_score < SIMILARITY_THRESHOLD:
        return None, best_score
    return best_question_id, best_score


async def seed_pending_questions(
    session: AsyncSession,
    specs: list[SeedQuestionSpec],
    *,
    apply: bool,
) -> dict:
    """Preview or add generated questions without publishing answers or counting asks."""

    validated = _validate_specs(specs)
    existing = await _existing_questions(session)
    published_variants = await _published_variants(session)
    items: list[dict] = []

    for spec, normalized in validated:
        published_question_id, similarity = _best_published_match(
            spec.question,
            published_variants,
        )
        question_id: int | None = None
        if published_question_id is not None:
            action = "covered_by_published"
            question_id = published_question_id
            candidates: list[dict] = []
        elif normalized in existing:
            action = "existing_question"
            question_id = int(existing[normalized]["id"])
            candidates = await find_candidate_evidence(session, spec.question)
        else:
            action = "would_insert"
            if apply:
                result = await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_questions (
                            question_text, normalized_question, status, asked_count
                        ) VALUES (:question, :normalized, 'pending', 0)
                        RETURNING id
                        """
                    ),
                    {"question": spec.question, "normalized": normalized},
                )
                question_id = int(result.scalar_one())
                existing[normalized] = {
                    "id": question_id,
                    "question_text": spec.question,
                    "normalized_question": normalized,
                    "status": "pending",
                }
                action = "inserted"
            candidates = await find_candidate_evidence(session, spec.question)

        top_candidate = candidates[0] if candidates else None
        items.append(
            {
                "category": spec.category,
                "question": spec.question,
                "action": action,
                "question_id": question_id,
                "published_similarity": round(similarity, 4),
                "candidate_count": len(candidates),
                "top_candidate": top_candidate,
            }
        )

    if apply:
        await session.commit()
    else:
        await session.rollback()

    summary = {
        "total": len(items),
        "would_insert": sum(item["action"] == "would_insert" for item in items),
        "inserted": sum(item["action"] == "inserted" for item in items),
        "existing": sum(item["action"] == "existing_question" for item in items),
        "covered": sum(item["action"] == "covered_by_published" for item in items),
    }
    return {"summary": summary, "items": items}
