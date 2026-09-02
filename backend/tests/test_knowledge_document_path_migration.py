from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

from app.services.knowledge_document_path_migration import (
    migrate_knowledge_document_paths,
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _create_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE knowledge_documents (
                id INTEGER PRIMARY KEY,
                document_type TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL UNIQUE,
                sha256 TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


def _insert_document(
    database: Path,
    *,
    document_id: int,
    document_type: str,
    file_name: str,
    file_path: Path,
    sha256: str | None,
) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            INSERT INTO knowledge_documents (
                id, document_type, file_name, file_path, sha256
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (document_id, document_type, file_name, str(file_path), sha256),
        )
        connection.commit()
    finally:
        connection.close()


def _registered_path(database: Path, document_id: int) -> str:
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT file_path FROM knowledge_documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        assert row is not None
        return str(row[0])
    finally:
        connection.close()


def test_dry_run_classifies_documents_without_updating_database(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.db"
    source_root = tmp_path / "icloud"
    target_root = tmp_path / "obsidian" / "受控材料"
    _create_database(database)

    verified_content = b"verified whitepaper"
    verified_source = source_root / "materials" / "verified.pdf"
    verified_target = target_root / "白皮书" / verified_source.name
    verified_target.parent.mkdir(parents=True)
    verified_target.write_bytes(verified_content)
    _insert_document(
        database,
        document_id=1,
        document_type="whitepaper",
        file_name=verified_source.name,
        file_path=verified_source,
        sha256=_sha256(verified_content),
    )

    missing_source = source_root / "manuals" / "missing.pdf"
    _insert_document(
        database,
        document_id=2,
        document_type="manual",
        file_name=missing_source.name,
        file_path=missing_source,
        sha256=_sha256(b"missing"),
    )

    mismatch_source = source_root / "release" / "mismatch.pdf"
    mismatch_target = target_root / "发布记录" / mismatch_source.name
    mismatch_target.parent.mkdir(parents=True)
    mismatch_target.write_bytes(b"different")
    _insert_document(
        database,
        document_id=3,
        document_type="release_note",
        file_name=mismatch_source.name,
        file_path=mismatch_source,
        sha256=_sha256(b"registered"),
    )

    outside_source = tmp_path / "other" / "outside.pdf"
    _insert_document(
        database,
        document_id=4,
        document_type="whitepaper",
        file_name=outside_source.name,
        file_path=outside_source,
        sha256=_sha256(b"outside"),
    )

    already_target = target_root / "说明书" / "already.pdf"
    _insert_document(
        database,
        document_id=5,
        document_type="manual",
        file_name=already_target.name,
        file_path=already_target,
        sha256=_sha256(b"already"),
    )

    registration_source = source_root / "registration" / "certificate.pdf"
    registration_target = target_root / "注册证" / registration_source.name
    registration_target.parent.mkdir(parents=True)
    registration_target.write_bytes(b"certificate")
    _insert_document(
        database,
        document_id=6,
        document_type="registration_certificate",
        file_name=registration_source.name,
        file_path=registration_source,
        sha256=_sha256(b"certificate"),
    )

    missing_digest_source = source_root / "materials" / "no-digest.pdf"
    _insert_document(
        database,
        document_id=7,
        document_type="whitepaper",
        file_name=missing_digest_source.name,
        file_path=missing_digest_source,
        sha256=None,
    )

    difference_source = source_root / "registration" / "difference.xlsx"
    difference_target = target_root / "注册差异表" / difference_source.name
    difference_target.parent.mkdir(parents=True)
    difference_target.write_bytes(b"difference")
    _insert_document(
        database,
        document_id=8,
        document_type="registration_difference",
        file_name=difference_source.name,
        file_path=difference_source,
        sha256=_sha256(b"difference"),
    )

    unsupported_source = source_root / "other" / "unsupported.bin"
    _insert_document(
        database,
        document_id=9,
        document_type="other",
        file_name=unsupported_source.name,
        file_path=unsupported_source,
        sha256=_sha256(b"unsupported"),
    )

    result = migrate_knowledge_document_paths(
        database,
        source_root=source_root,
        target_root=target_root,
        apply=False,
    )

    assert result.counts == {
        "scanned": 9,
        "ready": 3,
        "updated": 0,
        "already_migrated": 1,
        "outside_source_root": 1,
        "unsupported_type": 1,
        "missing_sha256": 1,
        "target_missing": 1,
        "hash_mismatch": 1,
    }
    assert result.items[0].status == "ready"
    assert result.items[0].target_path == verified_target
    assert result.items[5].status == "ready"
    assert result.items[5].target_path == registration_target
    assert result.items[7].status == "ready"
    assert result.items[7].target_path == difference_target
    assert _registered_path(database, 1) == str(verified_source)


def test_apply_updates_only_verified_targets_and_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.db"
    source_root = tmp_path / "icloud"
    target_root = tmp_path / "obsidian" / "受控材料"
    _create_database(database)

    content = b"manual"
    source = source_root / "manuals" / "manual.pdf"
    target = target_root / "说明书" / source.name
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    _insert_document(
        database,
        document_id=1,
        document_type="manual",
        file_name=source.name,
        file_path=source,
        sha256=_sha256(content),
    )

    applied = migrate_knowledge_document_paths(
        database,
        source_root=source_root,
        target_root=target_root,
        apply=True,
    )

    assert applied.counts["ready"] == 1
    assert applied.counts["updated"] == 1
    assert applied.items[0].status == "updated"
    assert _registered_path(database, 1) == str(target.resolve())

    repeated = migrate_knowledge_document_paths(
        database,
        source_root=source_root,
        target_root=target_root,
        apply=True,
    )

    assert repeated.counts["updated"] == 0
    assert repeated.counts["already_migrated"] == 1
    assert repeated.items[0].status == "already_migrated"
