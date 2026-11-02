"""Inventory existing knowledge sources without migrations, models or business writes."""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo


KNOWLEDGE_TABLES = (
    "knowledge_documents", "knowledge_document_extractions", "knowledge_document_chunks",
    "knowledge_questions", "knowledge_answers", "knowledge_answer_citations",
)
RELEASE_TABLES = ("projects", "releases", "source_documents")
NATIVE_RELEASE_TABLES = ("feature_versions", "release_introductions")
SCOPE_COLUMNS = ("country", "market", "product_model_id", "software_version")


class KnowledgeBaselineError(ValueError):
    """A baseline cannot be collected reliably from the selected primary source."""


@contextmanager
def _read_database(database, required_tables):
    path = Path(database).expanduser().resolve()
    if not path.is_file():
        raise KnowledgeBaselineError("数据库不存在；请提供明确的现用数据库")
    # as_uri escapes SQLite URI metacharacters in legitimate filenames.
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = set(required_tables) - tables
        if missing:
            raise KnowledgeBaselineError("数据库缺少表：" + ", ".join(sorted(missing)))
        yield connection, tables
    finally:
        connection.close()


def _count(connection, table):
    # All table arguments come from the fixed module constants, never CLI text.
    return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _finding(code, *, entity_id=None):
    return {"code": code, "entity_id": entity_id, "decision": "needs_owner_review"}


def _file_status(document, verify_hashes):
    path = Path(document["file_path"])
    try:
        if not path.is_absolute() or not path.is_file():
            return False, "not_checked"
        if not verify_hashes:
            return True, "not_checked"
        if not document["sha256"]:
            return True, "not_registered"
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        return True, "matches" if digest == document["sha256"] else "mismatch"
    except OSError:
        return False, "unreadable"


def _documents(connection, verify_hashes):
    rows = connection.execute(
        """SELECT d.id, d.document_type, d.version, d.source_status, d.file_path, d.sha256,
                  e.document_id AS extraction_id, e.status AS extraction_status,
                  e.source_sha256
           FROM knowledge_documents d
           LEFT JOIN knowledge_document_extractions e ON e.document_id = d.id
           ORDER BY d.id"""
    )
    documents, findings = [], []
    versions = Counter()
    for row in rows:
        active = row["source_status"] == "active"
        available, hash_status = _file_status(row, verify_hashes) if active else (None, "not_checked")
        extraction = row["extraction_status"] or "missing"
        if active and extraction == "completed":
            if not row["sha256"] or not row["source_sha256"]:
                extraction = "unverified"
            elif row["sha256"] != row["source_sha256"]:
                extraction = "stale"
        if active:
            if not available:
                findings.append(_finding("file_unavailable", entity_id=row["id"]))
            if extraction != "completed":
                findings.append(_finding("extraction_" + extraction, entity_id=row["id"]))
            if hash_status in {"mismatch", "not_registered"}:
                findings.append(_finding("original_hash_" + hash_status, entity_id=row["id"]))
            if row["document_type"] == "whitepaper":
                versions[row["version"] or "not_recorded"] += 1
        documents.append({
            "document_id": row["id"], "document_type": row["document_type"],
            "version": row["version"], "source_status": row["source_status"],
            "available": available, "extraction_status": extraction,
            "original_hash_status": hash_status,
        })
    return documents, findings, dict(sorted(versions.items()))


def _answer_review_queue(connection, documents):
    document_by_id = {row["document_id"]: row for row in documents}
    queue = []
    answers = connection.execute(
        """SELECT a.id, a.question_id, q.question_text, a.version
           FROM knowledge_answers a JOIN knowledge_questions q ON q.id = a.question_id
           WHERE a.review_status = 'published' ORDER BY a.id"""
    )
    for answer in answers:
        citations = connection.execute(
            "SELECT document_id, source_ref FROM knowledge_answer_citations WHERE answer_id=?",
            (answer["id"],),
        ).fetchall()
        reasons = set()
        if not citations:
            reasons.add("no_document_citation")
        for citation in citations:
            document = document_by_id.get(citation["document_id"])
            if document is None or document["source_status"] != "active":
                reasons.add("citation_document_inactive")
            elif not document["available"]:
                reasons.add("citation_file_unavailable")
            elif document["original_hash_status"] == "mismatch":
                reasons.add("citation_original_changed")
            elif document["extraction_status"] != "completed":
                reasons.add("citation_extraction_needs_review")
            if not (citation["source_ref"] or "").strip():
                reasons.add("citation_location_missing")
        if reasons:
            queue.append({
                "answer_id": answer["id"], "question_id": answer["question_id"],
                "question_text": answer["question_text"], "answer_version": answer["version"],
                "reasons": sorted(reasons), "decision": "needs_owner_review",
            })
    return queue


def _knowledge_source(database, verify_hashes):
    with _read_database(database, KNOWLEDGE_TABLES) as (connection, tables):
        documents, findings, versions = _documents(connection, verify_hashes)
        queue = _answer_review_queue(connection, documents)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(knowledge_questions)")}
        scope_columns = [name for name in SCOPE_COLUMNS if name in columns]
        if len(scope_columns) != len(SCOPE_COLUMNS):
            findings.append(_finding("structured_question_scope_missing"))
        active = [row for row in documents if row["source_status"] == "active"]
        return {
            "state": "available",
            "counts": {
                "documents": len(documents), "active_documents": len(active),
                "extracted_documents": connection.execute(
                    "SELECT COUNT(*) FROM knowledge_document_extractions WHERE status='completed'"
                ).fetchone()[0],
                "chunks": _count(connection, "knowledge_document_chunks"),
                "questions": _count(connection, "knowledge_questions"),
                "answers": _count(connection, "knowledge_answers"),
                "published_answers": connection.execute(
                    "SELECT COUNT(*) FROM knowledge_answers WHERE review_status='published'"
                ).fetchone()[0],
                "citations": _count(connection, "knowledge_answer_citations"),
                "published_answers_without_document_citation": sum(
                    "no_document_citation" in row["reasons"] for row in queue
                ),
                "active_documents_without_extraction": sum(
                    row["extraction_status"] == "missing" for row in active
                ),
                "active_documents_with_stale_extraction": sum(
                    row["extraction_status"] == "stale" for row in active
                ),
                "active_documents_unavailable": sum(not row["available"] for row in active),
            },
            "native_release_counts": {
                table: _count(connection, table) if table in tables else None
                for table in NATIVE_RELEASE_TABLES
            },
            "question_scope_columns": scope_columns, "whitepaper_versions": versions,
            "documents": documents, "answer_review_queue": queue, "findings": findings,
        }


def _release_source(database):
    if database is None:
        return {"state": "not_requested"}
    if not Path(database).expanduser().is_file():
        return {"state": "unavailable"}
    try:
        with _read_database(database, RELEASE_TABLES) as (connection, _):
            return {"state": "available", "counts": {
                table: _count(connection, table) for table in RELEASE_TABLES
            }}
    except (OSError, sqlite3.Error, KnowledgeBaselineError):
        return {"state": "invalid", "findings": [_finding("release_source_unreadable")]}


def _library_source(library):
    if library is None:
        return {"state": "not_requested"}
    path = Path(library).expanduser()
    if not path.is_file():
        return {"state": "unavailable"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        features = data["features"]
        if not isinstance(data["revision"], int) or isinstance(data["revision"], bool):
            raise ValueError("Invalid revision")
        if not isinstance(features, list):
            raise ValueError("Invalid features")
        ids = [feature["id"] for feature in features]
        if any(not isinstance(identity, str) or not identity.strip() for identity in ids) or len(set(ids)) != len(ids):
            raise ValueError("Invalid or duplicate feature identity")
        return {"state": "available", "revision": data["revision"], "counts": {"cards": len(features)}}
    except (OSError, ValueError, TypeError, KeyError):
        return {"state": "invalid", "findings": [_finding("feature_library_unreadable")]}


def _receipt_kind(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data["controlled"], bool) or not data["id"] or data["job_id"] != path.parent.name:
        raise ValueError("Invalid receipt identity")
    artifacts = data["artifacts"]
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("Invalid receipt artifacts")
    for artifact in artifacts.values():
        if (not isinstance(artifact["destinations"], dict)
                or not isinstance(artifact["hashes"], dict) or not artifact["generation_id"]):
            raise ValueError("Invalid artifact provenance")
    return "controlled_unverified" if data["controlled"] else "archived_unverified"


def _receipt_source(root):
    if root is None:
        return {"state": "not_requested"}
    path = Path(root).expanduser()
    if not path.is_dir():
        return {"state": "unavailable"}
    counts = {"receipts": 0, "controlled_unverified": 0, "archived_unverified": 0, "invalid": 0}
    try:
        for receipt in sorted(path.glob("*/*.json")):
            counts["receipts"] += 1
            try:
                counts[_receipt_kind(receipt)] += 1
            except (OSError, ValueError, KeyError, TypeError):
                counts["invalid"] += 1
    except OSError:
        return {"state": "unavailable", "findings": [_finding("receipt_directory_unreadable")]}
    return {
        "state": "degraded" if counts["invalid"] else "available", "counts": counts,
        "findings": [_finding("receipt_invalid")] if counts["invalid"] else [],
    }


def build_knowledge_baseline(database, *, release_database=None, feature_library=None,
                             publication_root=None, verify_file_hashes=False):
    """Collect independently observed sources; never infer approval from availability.

    Database reads use independent read-only transactions. Cross-source results are
    an inventory, not an atomic publication snapshot or a source synchronization.
    Paths and answer bodies are intentionally excluded from the returned report.
    """
    try:
        knowledge = _knowledge_source(database, verify_file_hashes)
    except (sqlite3.Error, OSError) as exc:
        raise KnowledgeBaselineError("无法读取知识库；请检查文件和表结构") from exc
    return {
        "schema_version": 1,
        "observed_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "checks": {
            "original_file_hashes": "requested" if verify_file_hashes else "not_requested",
            "publication_eligibility": "not_checked",
        },
        "sources": {
            "knowledge": knowledge, "release": _release_source(release_database),
            "feature_library": _library_source(feature_library),
            "publication_receipts": _receipt_source(publication_root),
        },
    }
