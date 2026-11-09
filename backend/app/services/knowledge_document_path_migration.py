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
    "registration_certificate": "注册证",
    "registration_difference": "注册差异表",
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


_ARTIFACT_COLUMNS = {
    "certificate": ("certificate_artifact_path", "certificate_sha256"),
    "difference": ("difference_artifact_path", "difference_sha256"),
}


@dataclass(frozen=True)
class RegistrationArtifactPathMigrationItem:
    version_id: int
    artifact_type: str
    file_name: str
    source_path: Path
    target_path: Path | None
    status: str
    expected_sha256: str | None
    actual_sha256: str | None = None


@dataclass(frozen=True)
class RegistrationArtifactPathMigrationResult:
    apply: bool
    items: tuple[RegistrationArtifactPathMigrationItem, ...]
    counts: dict[str, int]


def _relative_below(path: Path, root: Path) -> Path | None:
    try:
        return path.relative_to(root)
    except ValueError:
        return None


def migrate_registration_artifact_paths(
    database_path: str | Path,
    *,
    source_root: str | Path,
    target_root: str | Path,
    apply: bool = False,
) -> RegistrationArtifactPathMigrationResult:
    """Repoint registration package artifacts from a legacy root to the vault root.

    Unlike knowledge documents these paths are nested (``注册资料/CN/<证号>/…``), so the
    relative path is preserved instead of being rebuilt from a type directory. The same
    safety rule applies: the destination must already exist and match the registered
    SHA-256, and no file is ever copied.
    """

    database = Path(database_path).expanduser().resolve()
    source = Path(source_root).expanduser().resolve()
    target = Path(target_root).expanduser().resolve()
    counts: Counter[str] = Counter(scanned=0, ready=0, updated=0)
    items: list[RegistrationArtifactPathMigrationItem] = []

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        if apply:
            connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """
            SELECT id, certificate_artifact_path, certificate_sha256,
                   difference_artifact_path, difference_sha256
            FROM registration_package_versions
            ORDER BY id
            """
        ).fetchall()

        for row in rows:
            for artifact_type, (path_column, sha_column) in _ARTIFACT_COLUMNS.items():
                registered_raw = str(row[path_column] or "").strip()
                if not registered_raw:
                    continue
                counts["scanned"] += 1
                registered_path = Path(registered_raw).expanduser().resolve()
                expected_digest = str(row[sha_column] or "").strip().casefold() or None
                target_path: Path | None = None
                actual_digest: str | None = None
                relative = _relative_below(registered_path, source)
                if _is_below(registered_path, target):
                    status = "already_migrated"
                elif relative is None:
                    status = "outside_source_root"
                elif not expected_digest:
                    status = "missing_sha256"
                else:
                    target_path = target / relative
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

                item = RegistrationArtifactPathMigrationItem(
                    version_id=int(row["id"]),
                    artifact_type=artifact_type,
                    file_name=registered_path.name,
                    source_path=registered_path,
                    target_path=target_path,
                    status=status,
                    expected_sha256=expected_digest,
                    actual_sha256=actual_digest,
                )

                if apply and status == "ready" and target_path is not None:
                    cursor = connection.execute(
                        f"""
                        UPDATE registration_package_versions
                        SET {path_column} = ?
                        WHERE id = ? AND {path_column} = ? AND {sha_column} = ?
                        """,
                        (
                            str(target_path),
                            int(row["id"]),
                            str(row[path_column]),
                            str(row[sha_column]),
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError(
                            "registration package version "
                            f"{int(row['id'])} changed during migration"
                        )
                    counts["updated"] += 1
                    item = RegistrationArtifactPathMigrationItem(
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

    return RegistrationArtifactPathMigrationResult(
        apply=apply,
        items=tuple(items),
        counts=dict(counts),
    )
