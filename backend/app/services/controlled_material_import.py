"""Discover and register product materials stored in the controlled Obsidian tree."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import mimetypes
from pathlib import Path
import re
import sqlite3


CONTROLLED_PRODUCT_DIRECTORIES = {
    "说明书": ("manual", {".pdf", ".docx"}),
    "白皮书": ("whitepaper", {".pdf"}),
    "发布记录": ("release_note", {".pdf", ".docx"}),
}
SEMANTIC_VERSION_RE = re.compile(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)")
MANUAL_REVISION_RE = re.compile(r"(?<![A-Za-z0-9])(R\d+)(?!\d)", re.IGNORECASE)


@dataclass(frozen=True)
class ControlledMaterial:
    document_type: str
    title: str
    path: Path
    version: str | None
    market: str
    country: str | None
    product_series: str | None
    mime_type: str
    sha256: str


@dataclass(frozen=True)
class ControlledMaterialImportItem:
    path: Path
    document_type: str
    status: str
    document_id: int | None = None


@dataclass(frozen=True)
class ControlledMaterialImportResult:
    apply: bool
    items: tuple[ControlledMaterialImportItem, ...]
    counts: dict[str, int]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_model_label(value: str) -> str:
    cleaned = re.sub(r"[_\s]+", " ", value).strip(" _-")
    cleaned = re.sub(r"(?<=[A-Za-z])(?=[\u4e00-\u9fff])", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _product_series(document_type: str, file_name: str) -> str | None:
    stem = Path(file_name).stem
    if document_type == "whitepaper":
        label = _clean_model_label(stem.split("白皮书", 1)[0])
        if not label:
            return None
        if label.casefold().startswith("vinno"):
            return label
        match = re.match(r"^(\d+[A-Za-z]*)(.*)$", label)
        if match:
            suffix = _clean_model_label(match.group(2))
            return f"ULTIMUS {match.group(1)}" + (f" {suffix}" if suffix else "")
        return f"ULTIMUS {label}"

    if document_type == "release_note":
        folded = stem.casefold()
        if "ultimus" in folded:
            return "ULTIMUS 9E" if re.search(r"ultimus\s*9e", folded) else "ULTIMUS Series"
        if "v10" in folded:
            return "V10"
        if "v series" in folded or "v系列" in folded:
            return "V series"
        return None

    if document_type == "manual":
        if "ULTIMUS" in stem.upper():
            return "ULTIMUS Series"
        ezono = re.search(r"eZono\s*\d+", stem, re.IGNORECASE)
        if ezono:
            return ezono.group(0).replace(" ", "")
        vinno = re.search(
            r"VINNO\s+(.+?)(?:\s+Basic|\s+Advanced)",
            stem,
            re.IGNORECASE,
        )
        if vinno:
            models = re.sub(r"\s+Series$", "", vinno.group(1), flags=re.IGNORECASE)
            return f"VINNO {models.replace('_', '/')}"
    return None


def _version(document_type: str, file_name: str, product_series: str | None) -> str | None:
    semantic = SEMANTIC_VERSION_RE.search(file_name)
    if semantic:
        version = semantic.group(1)
        if product_series in {"V10", "V series"} and version.startswith("1.4."):
            version = f"1.14.{version.rsplit('.', 1)[1]}"
        return version
    if document_type == "manual":
        revision = MANUAL_REVISION_RE.search(file_name)
        if revision:
            return revision.group(1).upper()
    return None


def discover_controlled_product_materials(
    controlled_root: str | Path,
) -> list[ControlledMaterial]:
    """Discover supported product materials without changing files or the database."""

    root = Path(controlled_root).expanduser().resolve()
    materials: list[ControlledMaterial] = []
    for directory_name, (document_type, suffixes) in CONTROLLED_PRODUCT_DIRECTORIES.items():
        directory = root / directory_name
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if (
                not path.is_file()
                or path.name.startswith(".")
                or path.suffix.casefold() not in suffixes
            ):
                continue
            resolved = path.resolve()
            product_series = _product_series(document_type, resolved.name)
            materials.append(
                ControlledMaterial(
                    document_type=document_type,
                    title=resolved.stem,
                    path=resolved,
                    version=_version(document_type, resolved.name, product_series),
                    market="domestic",
                    country="CN",
                    product_series=product_series,
                    mime_type=mimetypes.guess_type(resolved.name)[0]
                    or "application/octet-stream",
                    sha256=_sha256(resolved),
                )
            )
    return sorted(materials, key=lambda material: str(material.path))


def import_controlled_product_materials(
    database_path: str | Path,
    controlled_root: str | Path,
    *,
    apply: bool = False,
) -> ControlledMaterialImportResult:
    """Plan or apply an idempotent import of controlled product materials."""

    materials = discover_controlled_product_materials(controlled_root)
    counts: Counter[str] = Counter(scanned=len(materials), ready=0, inserted=0)
    items: list[ControlledMaterialImportItem] = []
    connection = sqlite3.connect(Path(database_path).expanduser().resolve())
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
        by_path = {str(Path(row["file_path"]).expanduser().resolve()): row for row in rows}
        by_hash: dict[str, sqlite3.Row] = {
            str(row["sha256"]): row for row in rows if row["sha256"]
        }
        by_name = {
            (str(row["document_type"]), str(row["file_name"])): row for row in rows
        }

        for material in materials:
            path_text = str(material.path)
            existing = by_path.get(path_text)
            if existing is not None:
                status = (
                    "unchanged"
                    if str(existing["sha256"] or "") == material.sha256
                    else "name_conflict"
                )
                document_id = int(existing["id"])
            elif material.sha256 in by_hash:
                status = "duplicate_content"
                document_id = int(by_hash[material.sha256]["id"])
            elif (material.document_type, material.path.name) in by_name:
                status = "name_conflict"
                document_id = int(
                    by_name[(material.document_type, material.path.name)]["id"]
                )
            else:
                status = "ready"
                document_id = None
                counts["ready"] += 1

            if status != "ready":
                counts[status] += 1

            if apply and status == "ready":
                cursor = connection.execute(
                    """
                    INSERT INTO knowledge_documents (
                        document_type, title, file_name, file_path, version,
                        market, country, product_series, mime_type, sha256,
                        source_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                    """,
                    (
                        material.document_type,
                        material.title,
                        material.path.name,
                        path_text,
                        material.version,
                        material.market,
                        material.country,
                        material.product_series,
                        material.mime_type,
                        material.sha256,
                    ),
                )
                document_id = int(cursor.lastrowid)
                status = "inserted"
                counts["inserted"] += 1
                by_path[path_text] = connection.execute(
                    """
                    SELECT id, document_type, file_name, file_path, sha256
                    FROM knowledge_documents WHERE id = ?
                    """,
                    (document_id,),
                ).fetchone()
                by_hash[material.sha256] = by_path[path_text]
                by_name[(material.document_type, material.path.name)] = by_path[path_text]

            items.append(
                ControlledMaterialImportItem(
                    path=material.path,
                    document_type=material.document_type,
                    status=status,
                    document_id=document_id,
                )
            )

        if apply:
            connection.commit()
    except Exception:
        if apply:
            connection.rollback()
        raise
    finally:
        connection.close()

    return ControlledMaterialImportResult(
        apply=apply,
        items=tuple(items),
        counts=dict(counts),
    )
