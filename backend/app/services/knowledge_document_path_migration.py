"""Safely repoint controlled knowledge documents to an Obsidian vault."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3


DOCUMENT_TYPE_DIRECTORIES = {
    "manual": "说明书",
    "whitepaper": "白皮书",
    "release_note": "发布记录",
}


@dataclass(frozen=True)
class KnowledgeDocumentPathMigrationItem:
    document_id: int
    document_type: str
    file_name: str
    source_path: Path
    target_path: Path | None
    status: str
    expected_sha256: str | None
    actual_sha256: str | None = None


@dataclass(frozen=True)
class KnowledgeDocumentPathMigrationResult:
    apply: bool
    items: tuple[KnowledgeDocumentPathMigrationItem, ...]
    counts: dict[str, int]


def _is_below(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def migrate_knowledge_document_paths(
    database_path: str | Path,
    *,
    source_root: str | Path,
    target_root: str | Path,
    apply: bool = False,
) -> KnowledgeDocumentPathMigrationResult:
    """Verify staged files and optionally update their registered paths.

    The migration deliberately does not copy source files. A destination must already
    exist below ``target_root`` and match the registered SHA-256 before its database
    path can be changed.
    """

    database = Path(database_path).expanduser().resolve()
    source = Path(source_root).expanduser().resolve()
    target = Path(target_root).expanduser().resolve()
    counts: Counter[str] = Counter(scanned=0, ready=0, updated=0)
    items: list[KnowledgeDocumentPathMigrationItem] = []

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        if apply:
            connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """
            SELECT id, document_type, file_name, file_path, sha256
            FROM knowledge_documents
            ORDER BY id
            """
        ).fetchall()

        for row in rows:
            counts["scanned"] += 1
            registered_path = Path(str(row["file_path"])).expanduser().resolve()
            document_type = str(row["document_type"])
            file_name = Path(str(row["file_name"])).name
            expected_digest = (
                str(row["sha256"]).strip().casefold() if row["sha256"] else None
            )

            status: str
            target_path: Path | None = None
            actual_digest: str | None = None
            if _is_below(registered_path, target):
                status = "already_migrated"
            elif not _is_below(registered_path, source):
                status = "outside_source_root"
            elif document_type not in DOCUMENT_TYPE_DIRECTORIES:
                status = "unsupported_type"
            elif not expected_digest:
                status = "missing_sha256"
            else:
                target_path = (
                    target / DOCUMENT_TYPE_DIRECTORIES[document_type] / file_name
                )
                if not target_path.is_file() or target_path.is_symlink():
                    status = "target_missing"
                else:
                    actual_digest = _sha256(target_path)
                    if actual_digest.casefold() != expected_digest:
                        status = "hash_mismatch"
                    else:
                        status = "ready"
                        counts["ready"] += 1

            if status != "ready":
                counts[status] += 1

            item = KnowledgeDocumentPathMigrationItem(
                document_id=int(row["id"]),
                document_type=document_type,
                file_name=file_name,
                source_path=registered_path,
                target_path=target_path,
                status=status,
                expected_sha256=expected_digest,
                actual_sha256=actual_digest,
            )

            if apply and status == "ready" and target_path is not None:
                cursor = connection.execute(
                    """
                    UPDATE knowledge_documents
                    SET file_path = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND file_path = ? AND sha256 = ?
                    """,
                    (
                        str(target_path),
                        item.document_id,
                        str(row["file_path"]),
                        str(row["sha256"]),
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        f"knowledge document {item.document_id} changed during migration"
                    )
                counts["updated"] += 1
                item = KnowledgeDocumentPathMigrationItem(
                    **{**item.__dict__, "status": "updated"}
                )

            items.append(item)

        if apply:
            connection.commit()
    except Exception:
        if apply:
            connection.rollback()
        raise
    finally:
        connection.close()

    return KnowledgeDocumentPathMigrationResult(
        apply=apply,
        items=tuple(items),
        counts=dict(counts),
    )
