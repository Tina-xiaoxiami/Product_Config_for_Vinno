"""Discover and register the V10 source materials already supplied by the owner."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import mimetypes
from pathlib import Path
import re
import sqlite3


@dataclass(frozen=True)
class KnowledgeSource:
    document_type: str
    title: str
    path: Path
    version: str | None
    market: str
    country: str | None
    product_series: str | None
    mime_type: str


def _source(
    path: Path,
    *,
    document_type: str,
    title: str,
    version: str | None = None,
    product_series: str | None = "V10",
) -> KnowledgeSource:
    return KnowledgeSource(
        document_type=document_type,
        title=title,
        path=path.resolve(),
        version=version,
        market="domestic",
        country="CN",
        product_series=product_series,
        mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )


def discover_v10_knowledge_sources(document_root: str | Path) -> list[KnowledgeSource]:
    """Find supported materials below the V10 document root without changing them."""

    root = Path(document_root).resolve()
    sources: list[KnowledgeSource] = []

    registration_directory = root / "注册" / "国内" / "长沙变更"
    fixed_sources = (
        (
            registration_directory / "注册变更-20260615.pdf",
            "registration_certificate",
            "V10系列国内注册变更",
            "20260615",
        ),
        (
            registration_directory / "V10系列国内注册变更型号差异20250729.xlsx",
            "registration_difference",
            "V10系列国内注册型号差异",
            "20250729",
        ),
        (
            registration_directory
            / "IFU 8000574 VINNO 9_9E_9P_10_10E_10P Basic User Manual_ZH-CN R10（CS）.pdf",
            "manual",
            "VINNO 9/10系列基本用户手册",
            "R10",
        ),
    )
    for path, document_type, title, version in fixed_sources:
        if path.is_file():
            sources.append(
                _source(
                    path,
                    document_type=document_type,
                    title=title,
                    version=version,
                )
            )

    whitepaper_directory = (
        root / "Datasheet" / "国内" / "1.14.80" / "去封面" / "1.14.80白皮书"
    )
    for path in whitepaper_directory.glob("*.pdf"):
        product_series = path.stem.split("白皮书", 1)[0].strip()
        sources.append(
            _source(
                path,
                document_type="whitepaper",
                title=path.stem,
                version="1.14.80",
                product_series=product_series or "V10",
            )
        )

    release_directory = root / "release note" / "1.14.80"
    confirmed_release_version = release_directory.name
    for path in release_directory.iterdir() if release_directory.is_dir() else ():
        if not path.is_file() or path.suffix.lower() not in {".pdf", ".docx"}:
            continue
        if "release note" not in path.name.casefold():
            continue
        sources.append(
            _source(
                path,
                document_type="release_note",
                title=re.sub(
                    r"\d+\.\d+\.\d+",
                    confirmed_release_version,
                    path.stem,
                ),
                version=confirmed_release_version,
                product_series="V series",
            )
        )

    unique_sources = {str(item.path): item for item in sources}
    return sorted(unique_sources.values(), key=lambda item: str(item.path))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_knowledge_sources(
    database_path: str | Path,
    document_root: str | Path,
) -> dict[str, int]:
    """Idempotently register discovered source files in a migrated database."""

    sources = discover_v10_knowledge_sources(document_root)
    counters = {
        "discovered": len(sources),
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
    }
    connection = sqlite3.connect(Path(database_path))
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        for source in sources:
            file_path = str(source.path)
            digest = _sha256(source.path)
            existing = connection.execute(
                "SELECT id, sha256 FROM knowledge_documents WHERE file_path = ?",
                (file_path,),
            ).fetchone()
            values = (
                source.document_type,
                source.title,
                source.path.name,
                file_path,
                source.version,
                source.market,
                source.country,
                source.product_series,
                source.mime_type,
                digest,
            )
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO knowledge_documents (
                        document_type, title, file_name, file_path, version,
                        market, country, product_series, mime_type, sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                counters["inserted"] += 1
            elif existing[1] != digest:
                connection.execute(
                    """
                    UPDATE knowledge_documents
                    SET document_type = ?, title = ?, file_name = ?, file_path = ?,
                        version = ?, market = ?, country = ?, product_series = ?,
                        mime_type = ?, sha256 = ?, source_status = 'active',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (*values, existing[0]),
                )
                counters["updated"] += 1
            else:
                counters["unchanged"] += 1
        connection.commit()
        return counters
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
