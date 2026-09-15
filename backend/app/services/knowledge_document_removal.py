"""Remove retired knowledge documents together with their derived rows.

``knowledge_document_chunks`` and ``knowledge_document_extractions`` declare
``ON DELETE CASCADE`` against ``knowledge_documents``, but this project keeps
``PRAGMA foreign_keys`` off on its normal connections. The cascade therefore
never fires, and deleting a document without clearing its children would leave
orphan chunks behind *without raising*. This module deletes the derived rows
explicitly, in the same transaction as the document row, and turns the foreign
key pragma on as a second line of defence so a missed reference fails loudly
instead of silently orphaning.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import sqlite3


DERIVED_TABLES = ("knowledge_document_chunks", "knowledge_document_extractions")

REMOVABLE_STATUS = "archived"


class KnowledgeDocumentRemovalError(ValueError):
    """At least one requested document cannot be removed safely."""

    def __init__(self, blockers: list[str]) -> None:
        super().__init__(
            "以下资料不能删除，本次未做任何改动：" + "；".join(blockers)
        )
        self.blockers = tuple(blockers)


@dataclass(frozen=True)
class KnowledgeDocumentRemovalItem:
    document_id: int
    title: str | None
    source_status: str | None
    status: str
    chunk_count: int = 0
    extraction_count: int = 0
    citation_count: int = 0


@dataclass(frozen=True)
class KnowledgeDocumentRemovalResult:
    apply: bool
    items: tuple[KnowledgeDocumentRemovalItem, ...]
    counts: dict[str, int]


def _count(connection: sqlite3.Connection, table: str, document_id: int) -> int:
    return int(
        connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE document_id = ?",  # noqa: S608
            (document_id,),
        ).fetchone()[0]
    )


def _classify(
    connection: sqlite3.Connection, document_ids: tuple[int, ...]
) -> list[KnowledgeDocumentRemovalItem]:
    items: list[KnowledgeDocumentRemovalItem] = []
    for document_id in document_ids:
        row = connection.execute(
            "SELECT title, source_status FROM knowledge_documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if row is None:
            items.append(
                KnowledgeDocumentRemovalItem(
                    document_id=document_id,
                    title=None,
                    source_status=None,
                    status="missing",
                )
            )
            continue

        chunks = _count(connection, "knowledge_document_chunks", document_id)
        extractions = _count(
            connection, "knowledge_document_extractions", document_id
        )
        citations = _count(connection, "knowledge_answer_citations", document_id)
        source_status = str(row[1]) if row[1] is not None else None

        if citations:
            status = "cited"
        elif source_status != REMOVABLE_STATUS:
            status = "not_archived"
        else:
            status = "removable"

        items.append(
            KnowledgeDocumentRemovalItem(
                document_id=document_id,
                title=str(row[0]) if row[0] is not None else None,
                source_status=source_status,
                status=status,
                chunk_count=chunks,
                extraction_count=extractions,
                citation_count=citations,
            )
        )
    return items


def _describe(item: KnowledgeDocumentRemovalItem) -> str:
    if item.status == "missing":
        return f"id={item.document_id} 不存在"
    if item.status == "cited":
        return (
            f"id={item.document_id}（{item.title}）仍被 "
            f"{item.citation_count} 条正式答案引文引用"
        )
    return (
        f"id={item.document_id}（{item.title}）source_status="
        f"{item.source_status}，只允许删除已退役（archived）资料"
    )


def remove_knowledge_documents(
    database_path: str | Path,
    *,
    document_ids: tuple[int, ...] | list[int],
    apply: bool = False,
) -> KnowledgeDocumentRemovalResult:
    """Delete the given documents and their derived rows.

    Runs as a dry-run unless ``apply`` is set. Every requested document is
    validated before anything is written; if any of them is missing, still
    referenced by a formal answer, or not yet retired, the whole call is
    rejected and the database is left untouched.
    """

    ids = tuple(dict.fromkeys(int(item) for item in document_ids))
    if not ids:
        raise ValueError("至少需要一个 document id")

    database = Path(database_path).expanduser()
    counts: Counter[str] = Counter(scanned=len(ids))

    connection = sqlite3.connect(database, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        items = _classify(connection, ids)
        for item in items:
            counts[item.status] += 1

        if not apply:
            return KnowledgeDocumentRemovalResult(
                apply=False, items=tuple(items), counts=dict(sorted(counts.items()))
            )

        blockers = [_describe(item) for item in items if item.status != "removable"]
        if blockers:
            raise KnowledgeDocumentRemovalError(blockers)

        connection.execute("BEGIN IMMEDIATE")
        try:
            for item in items:
                for table in DERIVED_TABLES:
                    connection.execute(
                        f"DELETE FROM {table} WHERE document_id = ?",  # noqa: S608
                        (item.document_id,),
                    )
                connection.execute(
                    "DELETE FROM knowledge_documents WHERE id = ?",
                    (item.document_id,),
                )
        except Exception:
            connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")

        counts["removed"] = len(items)
        counts["removed_chunks"] = sum(item.chunk_count for item in items)
        counts["removed_extractions"] = sum(item.extraction_count for item in items)
        return KnowledgeDocumentRemovalResult(
            apply=True, items=tuple(items), counts=dict(sorted(counts.items()))
        )
    finally:
        connection.close()
