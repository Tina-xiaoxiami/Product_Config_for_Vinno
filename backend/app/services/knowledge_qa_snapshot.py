"""Deterministic, restorable snapshots for controlled knowledge Q&A data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from app.services.knowledge_scope import KnowledgeScopeError, scope_key, stored_scope


SCHEMA_VERSION = 1
SCOPED_SCHEMA_VERSION = 2


class KnowledgeQaSnapshotError(ValueError):
    """Raised when a Q&A snapshot cannot be safely exported or restored."""


def _connect(database_path: str | Path, *, read_only: bool) -> sqlite3.Connection:
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise KnowledgeQaSnapshotError(f"数据库不存在：{path}")
    if read_only:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
    connection.row_factory = sqlite3.Row
    return connection


def _rows(connection: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def _snapshot_hash(payload: dict[str, Any]) -> str:
    content = {key: value for key, value in payload.items() if key != "snapshot_sha256"}
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _export_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    scoped = "scope_key" in {row[1] for row in connection.execute("PRAGMA table_info(knowledge_questions)")}
    scope_column = "scope_key" if scoped else "''"
    question_rows = _rows(
        connection,
        f"""
        SELECT id, question_text, normalized_question, status, asked_count,
               last_asked_at, created_at, updated_at, {scope_column} AS scope_key
        FROM knowledge_questions
        ORDER BY normalized_question, scope_key
        """,
    )
    questions = []
    for question_row in question_rows:
        question_id = question_row.pop("id")
        question = dict(question_row)
        try:
            question["scope"] = stored_scope(question.pop("scope_key"))
        except KnowledgeScopeError as exc:
            raise KnowledgeQaSnapshotError("问答范围记录无效，不能导出") from exc
        question["phrasings"] = _rows(
            connection,
            """
            SELECT phrasing_text, normalized_phrasing, phrasing_type, created_at
            FROM knowledge_question_phrasings
            WHERE question_id = ?
            ORDER BY normalized_phrasing
            """,
            (question_id,),
        )
        answer_row = connection.execute(
            """
            SELECT id, answer_text, review_status, version, change_note,
                   created_at, updated_at
            FROM knowledge_answers
            WHERE question_id = ?
            """,
            (question_id,),
        ).fetchone()
        if answer_row is None:
            question["answer"] = None
        else:
            answer = dict(answer_row)
            answer_id = answer.pop("id")
            answer["citations"] = _rows(
                connection,
                """
                SELECT document.sha256 AS document_sha256,
                       document.title AS document_title,
                       citation.source_ref, citation.excerpt,
                       citation.sort_order
                FROM knowledge_answer_citations citation
                JOIN knowledge_documents document
                  ON document.id = citation.document_id
                WHERE citation.answer_id = ?
                ORDER BY citation.sort_order, citation.id
                """,
                (answer_id,),
            )
            answer["revisions"] = _rows(
                connection,
                """
                SELECT version, answer_text, review_status,
                       change_note, created_at
                FROM knowledge_answer_revisions
                WHERE answer_id = ?
                ORDER BY version
                """,
                (answer_id,),
            )
            question["answer"] = answer
        questions.append(question)

    schema_version = SCOPED_SCHEMA_VERSION if any(question["scope"] for question in questions) else SCHEMA_VERSION
    if schema_version == SCHEMA_VERSION:
        for question in questions:
            question.pop("scope")
    snapshot = {"schema_version": schema_version, "questions": questions}
    snapshot["snapshot_sha256"] = _snapshot_hash(snapshot)
    return snapshot


def export_knowledge_qa_snapshot(database_path: str | Path) -> dict[str, Any]:
    """Export content and verified scope identity without question IDs or paths."""
    connection = _connect(database_path, read_only=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        return _export_snapshot(connection)
    finally:
        connection.close()



def _validate_snapshot(snapshot: dict[str, Any]) -> None:
    if snapshot.get("schema_version") not in {SCHEMA_VERSION, SCOPED_SCHEMA_VERSION}:
        raise KnowledgeQaSnapshotError("不支持的问答快照版本")
    questions = snapshot.get("questions")
    if not isinstance(questions, list):
        raise KnowledgeQaSnapshotError("问答快照结构无效")
    expected_hash = snapshot.get("snapshot_sha256")
    if not expected_hash or expected_hash != _snapshot_hash(snapshot):
        raise KnowledgeQaSnapshotError("问答快照校验失败，内容可能已被修改")
    if snapshot["schema_version"] == SCHEMA_VERSION and any("scope" in question for question in questions):
        raise KnowledgeQaSnapshotError("旧版快照不能携带未经校验的范围")
    if snapshot["schema_version"] == SCOPED_SCHEMA_VERSION and not any(question.get("scope") for question in questions):
        raise KnowledgeQaSnapshotError("范围快照缺少范围信息")
    if snapshot["schema_version"] == SCOPED_SCHEMA_VERSION and not all("scope" in question for question in questions):
        raise KnowledgeQaSnapshotError("范围快照存在未记录范围状态的问题")


def _resolve_scope_keys(connection: sqlite3.Connection, snapshot: dict) -> list[str]:
    if snapshot["schema_version"] == SCHEMA_VERSION:
        return [""] * len(snapshot["questions"])
    for table in ("knowledge_questions", "knowledge_question_phrasings"):
        if "scope_key" not in {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}:
            raise KnowledgeQaSnapshotError("请先迁移目标库的问答范围结构")
    keys = []
    for question in snapshot["questions"]:
        key = scope_key(question.get("scope"))
        try:
            scope = stored_scope(key)
        except KnowledgeScopeError as exc:
            raise KnowledgeQaSnapshotError("快照中的机型范围记录无效") from exc
        if scope:
            try:
                row = connection.execute(
                    "SELECT p.name, s.name AS series_name FROM product_models p "
                    "JOIN product_series s ON s.id=p.series_id WHERE p.id=?", (scope["product_model_id"],),
                ).fetchone()
            except sqlite3.Error as exc:
                raise KnowledgeQaSnapshotError("目标库缺少可验证的机型目录") from exc
            if row is None or row["name"] != scope["model_name"] or row["series_name"] != scope["series_name"]:
                raise KnowledgeQaSnapshotError("快照机型ID与目标库完整机型/系列不一致，已拒绝恢复")
        keys.append(key)
    return keys


def _snapshot_counts(snapshot: dict[str, Any]) -> dict[str, int]:
    questions = snapshot["questions"]
    answers = [question["answer"] for question in questions if question["answer"]]
    return {
        "question_count": len(questions),
        "answer_count": len(answers),
        "citation_count": sum(len(answer["citations"]) for answer in answers),
    }


def _resolve_documents(
    connection: sqlite3.Connection,
    snapshot: dict[str, Any],
) -> dict[str, int]:
    hashes = {
        citation.get("document_sha256")
        for question in snapshot["questions"]
        if question["answer"]
        for citation in question["answer"]["citations"]
    }
    if None in hashes or "" in hashes:
        raise KnowledgeQaSnapshotError("引用的受控材料缺少SHA-256")
    documents: dict[str, int] = {}
    for document_hash in sorted(hashes):
        rows = connection.execute(
            """
            SELECT id FROM knowledge_documents
            WHERE sha256 = ? AND source_status = 'active'
            """,
            (document_hash,),
        ).fetchall()
        if len(rows) != 1:
            raise KnowledgeQaSnapshotError(
                f"无法唯一定位引用的受控材料：{document_hash}"
            )
        documents[document_hash] = int(rows[0]["id"])
    return documents


def restore_knowledge_qa_snapshot(
    database_path: str | Path,
    snapshot: dict[str, Any],
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Restore a snapshot only into an empty Q&A store; dry-run by default."""
    _validate_snapshot(snapshot)
    counts = _snapshot_counts(snapshot)
    connection = _connect(database_path, read_only=False)
    try:
        existing_count = int(
            connection.execute("SELECT COUNT(*) FROM knowledge_questions").fetchone()[0]
        )
        if existing_count:
            connection.close()
            if export_knowledge_qa_snapshot(database_path) == snapshot:
                return {"status": "already_current", **counts}
            raise KnowledgeQaSnapshotError(
                "目标数据库已有问答数据，且与快照不一致，已停止覆盖"
            )

        documents = _resolve_documents(connection, snapshot)
        scope_keys = _resolve_scope_keys(connection, snapshot)
        if not apply:
            return {"status": "ready", **counts}

        with connection:
            scoped_snapshot = snapshot["schema_version"] == SCOPED_SCHEMA_VERSION
            extra_column = ", scope_key" if scoped_snapshot else ""
            extra_placeholder = ", ?" if scoped_snapshot else ""
            for question, key in zip(snapshot["questions"], scope_keys):
                inserted_question = connection.execute(
                    f"""
                    INSERT INTO knowledge_questions (
                        question_text, normalized_question, status, asked_count,
                        last_asked_at, created_at, updated_at{extra_column}
                    ) VALUES (?, ?, ?, ?, ?, ?, ?{extra_placeholder})
                    """,
                    (
                        question["question_text"],
                        question["normalized_question"],
                        question["status"],
                        question["asked_count"],
                        question["last_asked_at"],
                        question["created_at"],
                        question["updated_at"],
                    ) + ((key,) if scoped_snapshot else ()),
                )
                question_id = int(inserted_question.lastrowid)
                for phrasing in question["phrasings"]:
                    connection.execute(
                        f"""
                        INSERT INTO knowledge_question_phrasings (
                            question_id, phrasing_text, normalized_phrasing,
                            phrasing_type, created_at{extra_column}
                        ) VALUES (?, ?, ?, ?, ?{extra_placeholder})
                        """,
                        (
                            question_id,
                            phrasing["phrasing_text"],
                            phrasing["normalized_phrasing"],
                            phrasing["phrasing_type"],
                            phrasing["created_at"],
                        ) + ((key,) if scoped_snapshot else ()),
                    )
                answer = question["answer"]
                if answer is None:
                    continue
                inserted_answer = connection.execute(
                    """
                    INSERT INTO knowledge_answers (
                        question_id, answer_text, review_status, version,
                        change_note, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        question_id,
                        answer["answer_text"],
                        answer["review_status"],
                        answer["version"],
                        answer["change_note"],
                        answer["created_at"],
                        answer["updated_at"],
                    ),
                )
                answer_id = int(inserted_answer.lastrowid)
                for citation in answer["citations"]:
                    connection.execute(
                        """
                        INSERT INTO knowledge_answer_citations (
                            answer_id, document_id, source_ref, excerpt, sort_order
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            answer_id,
                            documents[citation["document_sha256"]],
                            citation["source_ref"],
                            citation["excerpt"],
                            citation["sort_order"],
                        ),
                    )
                for revision in answer["revisions"]:
                    connection.execute(
                        """
                        INSERT INTO knowledge_answer_revisions (
                            answer_id, version, answer_text, review_status,
                            change_note, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            answer_id,
                            revision["version"],
                            revision["answer_text"],
                            revision["review_status"],
                            revision["change_note"],
                            revision["created_at"],
                        ),
                    )
            if _export_snapshot(connection) != snapshot:
                raise KnowledgeQaSnapshotError("恢复后复核失败")
        return {"status": "restored", **counts}
    finally:
        try:
            connection.close()
        except sqlite3.ProgrammingError:
            pass
