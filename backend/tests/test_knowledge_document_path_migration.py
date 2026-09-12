from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

from app.services.knowledge_document_path_migration import (
    migrate_knowledge_document_paths,
    migrate_registration_artifact_paths,
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


def _create_registration_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE registration_package_versions (
                id INTEGER PRIMARY KEY,
                certificate_artifact_path TEXT,
                certificate_sha256 TEXT,
                difference_artifact_path TEXT,
                difference_sha256 TEXT
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


def _insert_package_version(
    database: Path,
    *,
    version_id: int,
    certificate_path: Path | None,
    certificate_sha: str | None,
    difference_path: Path | None,
    difference_sha: str | None,
) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            INSERT INTO registration_package_versions (
                id, certificate_artifact_path, certificate_sha256,
                difference_artifact_path, difference_sha256
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                version_id,
                str(certificate_path) if certificate_path else None,
                certificate_sha,
                str(difference_path) if difference_path else None,
                difference_sha,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _registered_artifacts(database: Path, version_id: int) -> tuple[str, str]:
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            """
            SELECT certificate_artifact_path, difference_artifact_path
            FROM registration_package_versions WHERE id = ?
            """,
            (version_id,),
        ).fetchone()
        assert row is not None
        return str(row[0]), str(row[1])
    finally:
        connection.close()


def test_registration_artifacts_migrate_by_relative_path(tmp_path: Path) -> None:
    """注册包原件按相对路径迁移；目标缺失或 sha 不符时一律不动。"""

    database = tmp_path / "product_config.db"
    source_root = tmp_path / "obsidian" / "受控材料"
    target_root = tmp_path / "obsidian-vault" / "受控材料"
    _create_registration_database(database)

    # v1：新库同相对路径下文件齐备且内容一致 → 可迁移（注册资料相对路径是嵌套的）
    v1_certificate = Path("注册资料") / "CN" / "湘械注准20222062053" / "注册变更.pdf"
    v1_difference = Path("注册资料") / "CN" / "湘械注准20222062053" / "差异表.xlsx"
    for relative, content in ((v1_certificate, b"certificate"), (v1_difference, b"difference")):
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    _insert_package_version(
        database,
        version_id=1,
        certificate_path=source_root / v1_certificate,
        certificate_sha=_sha256(b"certificate"),
        difference_path=source_root / v1_difference,
        difference_sha=_sha256(b"difference"),
    )

    # v2：新库两个目标都不存在 → target_missing
    v2_certificate = Path("注册资料") / "CN" / "苏械注准20232061322" / "注册证.pdf"
    v2_difference = Path("注册资料") / "CN" / "苏械注准20232061322" / "差异表.xlsx"
    _insert_package_version(
        database,
        version_id=2,
        certificate_path=source_root / v2_certificate,
        certificate_sha=_sha256(b"certificate-2"),
        difference_path=source_root / v2_difference,
        difference_sha=_sha256(b"difference-2"),
    )

    # v3：新库有文件但内容与登记 sha 不符 → hash_mismatch
    v3_difference = Path("注册资料") / "CN" / "湘械注准20242061214" / "差异表.xlsx"
    v3_target = target_root / v3_difference
    v3_target.parent.mkdir(parents=True, exist_ok=True)
    v3_target.write_bytes(b"tampered")
    _insert_package_version(
        database,
        version_id=3,
        certificate_path=None,
        certificate_sha=None,
        difference_path=source_root / v3_difference,
        difference_sha=_sha256(b"original"),
    )

    # v4：登记路径已在目标目录下 → already_migrated
    _insert_package_version(
        database,
        version_id=4,
        certificate_path=None,
        certificate_sha=None,
        difference_path=target_root / "注册资料" / "CN" / "已迁移" / "差异表.xlsx",
        difference_sha=_sha256(b"whatever"),
    )

    dry_run = migrate_registration_artifact_paths(
        database,
        source_root=source_root,
        target_root=target_root,
        apply=False,
    )

    assert dry_run.counts == {
        "scanned": 6,
        "ready": 2,
        "updated": 0,
        "already_migrated": 1,
        "target_missing": 2,
        "hash_mismatch": 1,
    }
    assert _registered_artifacts(database, 1)[0] == str(source_root / v1_certificate)

    applied = migrate_registration_artifact_paths(
        database,
        source_root=source_root,
        target_root=target_root,
        apply=True,
    )

    assert applied.counts["updated"] == 2
    assert _registered_artifacts(database, 1) == (
        str((target_root / v1_certificate).resolve()),
        str((target_root / v1_difference).resolve()),
    )
    # 未通过校验的目标一律不动
    assert _registered_artifacts(database, 2)[1] == str(source_root / v2_difference)
    assert _registered_artifacts(database, 3)[1] == str(source_root / v3_difference)
