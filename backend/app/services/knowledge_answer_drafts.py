"""Persistent working drafts and the evidence frozen at publication."""
from __future__ import annotations

import json

from sqlalchemy import text


async def _has_table(db, name: str) -> bool:
    return (await db.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"
    ), {"name": name})).scalar_one_or_none() is not None


async def latest_edit(db, question_id: int) -> dict | None:
    if not await _has_table(db, "knowledge_answer_draft_edits"):
        return None
    row = (await db.execute(text("""
        SELECT id, payload_json, published_version, created_at
        FROM knowledge_answer_draft_edits
        WHERE question_id=:id AND (published_version IS NULL OR published_version>0)
        ORDER BY id DESC LIMIT 1
    """), {"id": question_id})).one_or_none()
    if row is None:
        return None
    return {**json.loads(row.payload_json), "revision": row.id, "published_version": row.published_version,
            "created_at": row.created_at}


async def append_edit(db, question_id: int, payload: dict, *, archived: bool = False, created_at: str | None = None) -> None:
    await db.execute(text("""
        INSERT INTO knowledge_answer_draft_edits(question_id,payload_json,published_version,created_at)
        VALUES (:id,:payload,:version,COALESCE(:created_at,CURRENT_TIMESTAMP))
    """), {"id": question_id, "payload": json.dumps(payload, ensure_ascii=False),
            "version": 0 if archived else None, "created_at": created_at})


async def mark_published(db, edit_id: int, version: int) -> None:
    await db.execute(text("""
        UPDATE knowledge_answer_draft_edits SET published_version=:version WHERE id=:id
    """), {"id": edit_id, "version": version})


async def edit_history(db, question_id: int) -> list[dict]:
    if not await _has_table(db, "knowledge_answer_draft_edits"):
        return []
    rows = (await db.execute(text("""
        SELECT id, payload_json, created_at FROM knowledge_answer_draft_edits
        WHERE question_id=:id ORDER BY created_at DESC, id DESC
    """), {"id": question_id})).all()
    return [{**json.loads(row.payload_json), "version": None, "draft_revision": row.id,
             "created_at": row.created_at, "review_status": "draft"} for row in rows]


async def remove_edits(db, question_id: int) -> None:
    if await _has_table(db, "knowledge_answer_draft_edits"):
        await db.execute(text("DELETE FROM knowledge_answer_draft_edits WHERE question_id=:id"), {"id": question_id})


async def archive_legacy_draft_versions(db, question: dict) -> int:
    answer = question["answer"]
    rows = (await db.execute(text("""
        SELECT version,answer_text,change_note,created_at FROM knowledge_answer_revisions
        WHERE answer_id=:id AND review_status='draft' ORDER BY version
    """), {"id": answer["id"]})).mappings().all()
    legacy = {row["version"]: dict(row) for row in rows}
    legacy[answer["version"]] = {
        **legacy.get(answer["version"], {}), "version": answer["version"], "answer_text": answer["answer_text"],
        "change_note": answer["change_note"], "created_at": answer["updated_at"],
        "citations": answer["citations"],
    }
    for revision in legacy.values():
        await append_edit(db, question["id"], {
            "legacy_version": revision["version"], "answer_text": revision["answer_text"],
            "change_note": revision["change_note"], "citations": revision.get("citations", []),
        }, archived=True, created_at=revision["created_at"])
    await db.execute(text("""
        DELETE FROM knowledge_answer_revisions WHERE answer_id=:id AND review_status='draft'
    """), {"id": answer["id"]})
    return (await db.execute(text("""
        SELECT COALESCE(MAX(version),0) FROM knowledge_answer_revisions WHERE answer_id=:id
    """), {"id": answer["id"]})).scalar_one()


async def freeze_evidence(db, question: dict) -> None:
    answer = question["answer"]
    if not answer or answer["review_status"] != "published":
        return
    if not await _has_table(db, "knowledge_answer_publication_evidence"):
        return
    citations = await capture_sources(db, answer["citations"])
    payload = {"scope": question["scope"], "question_text": question["question_text"],
               "alias_questions": question["alias_questions"], "citations": citations}
    await db.execute(text("""
        INSERT INTO knowledge_answer_publication_evidence(revision_id,payload_json)
        SELECT id,:payload FROM knowledge_answer_revisions WHERE answer_id=:id AND version=:version
        ON CONFLICT(revision_id) DO NOTHING
    """), {"id": answer["id"], "version": answer["version"], "payload": json.dumps(payload, ensure_ascii=False)})


async def capture_sources(db, references: list[dict]) -> list[dict]:
    citations = []
    for citation in references:
        document = (await db.execute(text("""
            SELECT file_name, version, sha256, source_status FROM knowledge_documents WHERE id=:id
        """), {"id": citation["document_id"]})).mappings().one_or_none()
        citations.append({**citation, **dict(document or {"source_status": "missing"})})
    return citations


async def publication_evidence(db, question_id: int) -> dict[int, dict]:
    if not await _has_table(db, "knowledge_answer_publication_evidence"):
        return {}
    rows = (await db.execute(text("""
        SELECT r.version, p.payload_json FROM knowledge_answer_publication_evidence p
        JOIN knowledge_answer_revisions r ON r.id=p.revision_id
        JOIN knowledge_answers a ON a.id=r.answer_id WHERE a.question_id=:id
    """), {"id": question_id})).all()
    return {row.version: json.loads(row.payload_json) for row in rows}
