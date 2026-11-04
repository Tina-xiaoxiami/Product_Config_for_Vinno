"""Extract controlled source text and retrieve unconfirmed candidate evidence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
from io import BytesIO
from zipfile import ZipFile, BadZipFile
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unicodedata

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge_evidence_review import mark_changed_async
from app.services.knowledge_qa import normalize_question


EXTRACTOR_VERSION = "2"
OFFICE_EXTRACTOR_VERSION = "office-locator-v1"
MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_OFFICE_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_OFFICE_MEMBER_BYTES = 16 * 1024 * 1024
MAX_OFFICE_ENTRIES = 10000
MAX_OFFICE_CELLS = 100000
MAX_CHUNK_CHARACTERS = 1200
CHUNK_OVERLAP_CHARACTERS = 120
MAX_CANDIDATE_EXCERPT = 800
_QUESTION_FILLERS = (
    "是不是",
    "是否",
    "这个",
    "该功能",
    "请问",
    "的吗",
    "吗",
    "呢",
    "有无",
    "有没有",
)
_CONFIRMED_QUERY_EQUIVALENCES = (
    ("针增益调节", "穿刺针增益调节", "针增益", "needle gain"),
    (
        "环境光自动调节亮度",
        "环境光线自动调节亮度",
        "实时显示屏亮度调节",
        "显示屏亮度调节",
    ),
)


class KnowledgeContentError(ValueError):
    """Raised when a controlled document cannot be extracted."""


class KnowledgeDocumentMissingError(KnowledgeContentError):
    """Raised when the registered original file is unavailable."""


@dataclass(frozen=True)
class ExtractedBlock:
    text: str
    source_ref: str
    page_number: int | None = None
    section_name: str | None = None
    locator: dict | None = None


def _clean_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.splitlines()]
    return "\n".join(line for line in lines if line)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pdf_blocks(path: Path) -> list[ExtractedBlock]:
    from pypdf import PdfReader

    reader = PdfReader(path)
    blocks: list[ExtractedBlock] = []
    for page_index, page in enumerate(reader.pages, start=1):
        page_text = _clean_text(page.extract_text() or "")
        if page_text:
            blocks.append(
                ExtractedBlock(
                    text=page_text,
                    source_ref=f"第{page_index}页",
                    page_number=page_index,
                )
            )
    return blocks or _ocr_pdf_blocks(path)


def _ocr_pdf_blocks(path: Path) -> list[ExtractedBlock]:
    pdftoppm = shutil.which("pdftoppm")
    tesseract = shutil.which("tesseract")
    if not pdftoppm or not tesseract:
        return []

    with tempfile.TemporaryDirectory(prefix="vinno-pdf-ocr-") as directory:
        page_prefix = Path(directory) / "page"
        try:
            subprocess.run(
                [pdftoppm, "-png", "-r", "250", str(path), str(page_prefix)],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise KnowledgeContentError("图片型 PDF 页面渲染失败") from exc

        page_paths = sorted(
            Path(directory).glob("page-*.png"),
            key=lambda item: int(item.stem.rsplit("-", 1)[-1]),
        )
        blocks: list[ExtractedBlock] = []
        for page_number, page_path in enumerate(page_paths, start=1):
            try:
                result = subprocess.run(
                    [
                        tesseract,
                        str(page_path),
                        "stdout",
                        "-l",
                        "chi_sim+eng",
                        "--psm",
                        "3",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                raise KnowledgeContentError(
                    f"图片型 PDF 第{page_number}页 OCR 失败"
                ) from exc
            page_text = _clean_text(result.stdout)
            if page_text:
                blocks.append(
                    ExtractedBlock(
                        text=page_text,
                        source_ref=f"第{page_number}页（OCR）",
                        page_number=page_number,
                    )
                )
        return blocks


def _docx_blocks(path: Path | BytesIO) -> list[ExtractedBlock]:
    from docx import Document
    from docx.text.paragraph import Paragraph
    from docx.table import _Cell

    document = Document(str(path) if isinstance(path, Path) else path)
    blocks: list[ExtractedBlock] = []
    section_name: str | None = None
    paragraph_number, table_number = 0, 0
    body_indices = {element: index for index, element in enumerate(document.element.body, start=1)}
    for item in document.iter_inner_content():
        body_index = body_indices[item._element]
        if isinstance(item, Paragraph):
            paragraph_number += 1
            content = _clean_text(item.text)
            if not content:
                continue
            style_name = str(item.style.name or "") if item.style else ""
            if style_name.casefold().startswith("heading") or style_name.startswith("标题"):
                section_name = content
            locator = {"schema_version": 1, "format": "docx", "kind": "paragraph",
                       "part": "word/document.xml", "body_index": body_index,
                       "paragraph_index": paragraph_number}
            blocks.append(ExtractedBlock(text=content, source_ref=f"段落{paragraph_number}" + (f" · {section_name}" if section_name else ""),
                                         section_name=section_name, locator=locator))
        else:
            table_number += 1
            for row_index, row in enumerate(item.rows, start=1):
                # Physical XML cells avoid projecting merged anchors into phantom cells.
                cells = [{"cell_index": cell_index, "text": _clean_text(_Cell(tc, item).text),
                          "grid_span": tc.grid_span,
                          "vertical_merge": tc.vMerge,
                          "contains_nested_tables": bool(tc.findall("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl"))}
                         for cell_index, tc in enumerate(row._tr.tc_lst, start=1)]
                content = " | ".join(cell["text"] for cell in cells if cell["text"])
                if content:
                    locator = {"schema_version": 1, "format": "docx", "kind": "table_row",
                               "part": "word/document.xml", "body_index": body_index,
                               "table_index": table_number, "row_index": row_index, "cells": cells}
                    blocks.append(ExtractedBlock(text=content, source_ref=f"表格{table_number} 第{row_index}行",
                                                 section_name=f"表格{table_number}", locator=locator))
    return blocks


def _xlsx_blocks(path: Path | BytesIO) -> list[ExtractedBlock]:
    from openpyxl import load_workbook

    # Source formulas are retained literally; no calculation/cache result is inferred.
    workbook = load_workbook(path, read_only=False, data_only=False, keep_links=False)
    blocks: list[ExtractedBlock] = []
    try:
        total_cells = sum(ws.max_row * ws.max_column for ws in workbook.worksheets)
        if total_cells > MAX_OFFICE_CELLS:
            raise KnowledgeContentError("Office单元格数量超过本次解析上限")
        for sheet_index, worksheet in enumerate(workbook.worksheets, start=1):
            merged = {str(r.start_cell.coordinate): str(r) for r in worksheet.merged_cells.ranges}
            for row_index, row in enumerate(worksheet.iter_rows(), start=1):
                cells = []
                for cell in row:
                    if cell.value is None:
                        continue
                    value = _clean_text(str(cell.value))
                    if not value:
                        continue
                    item = {"cell": cell.coordinate, "column_index": cell.column, "text": value,
                            "value_type": "formula" if cell.data_type == "f" else "literal",
                            "number_format": cell.number_format}
                    if cell.data_type == "f":
                        item["formula_state"] = "not_evaluated"
                    if cell.coordinate in merged:
                        item["merged_range"] = merged[cell.coordinate]
                    cells.append(item)
                if cells:
                    cell_range = cells[0]["cell"] + ":" + cells[-1]["cell"]
                    locator = {"schema_version": 1, "format": "xlsx", "kind": "worksheet_row",
                               "sheet_name": worksheet.title, "sheet_index": sheet_index,
                               "row_index": row_index, "range": cell_range, "cells": cells,
                               "formula_state": "not_evaluated"}
                    blocks.append(ExtractedBlock(text=" | ".join(c["text"] for c in cells),
                        source_ref=f"{worksheet.title}!{cell_range}", section_name=worksheet.title, locator=locator))
    finally:
        workbook.close()
    return blocks


def document_extractor_version(path: Path, mime_type: str | None = None) -> str:
    return OFFICE_EXTRACTOR_VERSION if path.suffix.casefold() in {".docx", ".xlsx"} else EXTRACTOR_VERSION


def extract_office_blocks(data: bytes, suffix: str, mime_type: str | None = None) -> list[ExtractedBlock]:
    """Replay bounded Office structure from one immutable, version-identifiable snapshot.

    Coverage is main DOCX body/top-level tables or XLSX worksheet values/formulas;
    headers, footers, nested table contents and rendered appearance are not inferred.
    """
    suffix = suffix.casefold()
    expected_mime = {".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                     ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    if suffix == ".xls":
        raise KnowledgeContentError("旧XLS尚未支持结构定位，请提供原始XLSX；未按XLSX处理")
    if suffix not in expected_mime:
        raise KnowledgeContentError("暂不支持此Office格式")
    if mime_type and mime_type.casefold() != expected_mime[suffix]:
        raise KnowledgeContentError("Office文件类型与登记格式不一致")
    if len(data) > MAX_SOURCE_BYTES:
        raise KnowledgeContentError("Office原件超过本次大小上限")
    try:
        with ZipFile(BytesIO(data)) as package:
            entries = package.infolist()
            if (len(entries) > MAX_OFFICE_ENTRIES
                    or sum(e.file_size for e in entries) > MAX_OFFICE_EXPANDED_BYTES
                    or any(e.file_size > MAX_OFFICE_MEMBER_BYTES for e in entries)):
                raise KnowledgeContentError("Office解压内容超过本次解析上限")
            names = [e.filename for e in entries]
            required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml" if suffix == ".docx" else "xl/workbook.xml"}
            if len(names) != len(set(names)) or not required.issubset(names) or any(e.flag_bits & 1 for e in entries):
                raise KnowledgeContentError("Office包结构无效、重复或已加密")
            cell_count = 0
            for entry in entries:
                if entry.filename.endswith((".xml", ".rels")):
                    # Reject DTD/entity declarations in UTF-8/16/32 before library parsers.
                    xml_data = package.read(entry)
                    xml = xml_data.replace(b"\x00", b"").upper()
                    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                        raise KnowledgeContentError("Office包包含不支持的XML声明")
                    if suffix == ".xlsx":
                        from xml.etree.ElementTree import iterparse
                        from openpyxl.utils.cell import range_boundaries
                        for _, element in iterparse(BytesIO(xml_data), events=("end",)):
                            if element.tag == "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c":
                                cell_count += 1
                                if cell_count > MAX_OFFICE_CELLS:
                                    raise KnowledgeContentError("Office单元格数量超过本次解析上限")
                            if element.tag == "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}dimension":
                                left, top, right, bottom = range_boundaries(element.attrib.get("ref", "A1"))
                                if None in (left, top, right, bottom) or (right-left+1)*(bottom-top+1) > MAX_OFFICE_CELLS:
                                    raise KnowledgeContentError("Office工作表范围超过本次解析上限")
                            element.clear()
        blocks = _docx_blocks(BytesIO(data)) if suffix == ".docx" else _xlsx_blocks(BytesIO(data))
    except KnowledgeContentError:
        raise
    except Exception as error:
        raise KnowledgeContentError("Office原件结构无法读取，未采用提取结果") from error
    sha = hashlib.sha256(data).hexdigest()
    return [ExtractedBlock(text=b.text, source_ref=b.source_ref, page_number=None,
                           section_name=b.section_name, locator={**(b.locator or {}), "source_sha256": sha}) for b in blocks]


def extract_document_blocks(path: Path, mime_type: str | None) -> list[ExtractedBlock]:
    suffix = path.suffix.casefold()
    mime = str(mime_type or "").casefold()
    if suffix in {".docx", ".xlsx", ".xls"} or "wordprocessingml.document" in mime or "spreadsheetml.sheet" in mime:
        with path.open("rb") as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
        return extract_office_blocks(data, suffix, mime_type)
    if mime == "application/pdf" or suffix == ".pdf":
        return _pdf_blocks(path)
    if mime.startswith("text/") or suffix in {".txt", ".md", ".csv"}:
        content = _clean_text(path.read_text(encoding="utf-8", errors="replace"))
        return [ExtractedBlock(text=content, source_ref="全文")] if content else []
    raise KnowledgeContentError(f"暂不支持提取此文件类型：{mime_type or suffix or '未知'}")


def _split_long_text(content: str) -> list[str]:
    if len(content) <= MAX_CHUNK_CHARACTERS:
        return [content]
    paragraphs = [part.strip() for part in content.split("\n") if part.strip()]
    if not paragraphs:
        paragraphs = [content]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > MAX_CHUNK_CHARACTERS:
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(paragraph):
                end = min(len(paragraph), start + MAX_CHUNK_CHARACTERS)
                chunks.append(paragraph[start:end])
                if end == len(paragraph):
                    break
                start = max(start + 1, end - CHUNK_OVERLAP_CHARACTERS)
            continue
        combined = f"{current}\n{paragraph}".strip() if current else paragraph
        if len(combined) <= MAX_CHUNK_CHARACTERS:
            current = combined
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def build_document_chunks(blocks: list[ExtractedBlock]) -> list[dict]:
    chunks: list[dict] = []
    for block in blocks:
        cleaned = _clean_text(block.text)
        if not cleaned:
            continue
        for content in _split_long_text(cleaned):
            chunks.append(
                {
                    "chunk_index": len(chunks),
                    "page_number": block.page_number,
                    "section_name": block.section_name,
                    "source_ref": block.source_ref,
                    "content": content,
                    "normalized_content": normalize_question(content),
                    "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    **({"locator": block.locator} if block.locator is not None else {}),
                }
            )
    return chunks


async def _record_source_observation(session: AsyncSession, document_id: int, old_hash: str | None, source_sha256: str) -> None:
    if old_hash and old_hash != source_sha256:
        await mark_changed_async(session, document_id, "source_changed")
    await session.execute(
        text("UPDATE knowledge_documents SET sha256 = :sha256 WHERE id = :document_id"),
        {"sha256": source_sha256, "document_id": document_id},
    )


async def extract_registered_document(
    session: AsyncSession,
    document_id: int,
    *,
    force: bool = False,
) -> dict | None:
    document_result = await session.execute(
        text(
            """
            SELECT id, file_path, mime_type, sha256
            FROM knowledge_documents
            WHERE id = :document_id AND source_status = 'active'
            """
        ),
        {"document_id": document_id},
    )
    document = document_result.one_or_none()
    if document is None:
        return None
    path = Path(document.file_path)
    if not path.is_absolute() or not path.is_file():
        raise KnowledgeDocumentMissingError("原文件不存在或尚未同步")

    extractor_version = document_extractor_version(path, document.mime_type)
    source_sha256 = await asyncio.to_thread(_file_sha256, path)
    current_result = await session.execute(
        text(
            """
            SELECT extractor_version, source_sha256, status, chunk_count, extracted_at
            FROM knowledge_document_extractions
            WHERE document_id = :document_id
            """
        ),
        {"document_id": document_id},
    )
    current = current_result.one_or_none()
    if (
        not force
        and current is not None
        and current.status == "completed"
        and current.extractor_version == extractor_version
        and current.source_sha256 == source_sha256
        and document.sha256 == source_sha256
    ):
        return {
            "document_id": document_id,
            "status": current.status,
            "chunk_count": int(current.chunk_count),
            "extracted_at": current.extracted_at,
            "extractor_version": current.extractor_version,
            "reused": True,
        }

    old_hash = document.sha256 or (current.source_sha256 if current else None)
    try:
        blocks = await asyncio.to_thread(extract_document_blocks, path, document.mime_type)
        if any(block.locator and block.locator.get("source_sha256") != source_sha256 for block in blocks):
            raise KnowledgeContentError("Office原件在提取期间变化，请重新提取")
        if extractor_version == OFFICE_EXTRACTOR_VERSION and await asyncio.to_thread(_file_sha256, path) != source_sha256:
            raise KnowledgeContentError("Office原件在提取期间变化，请重新提取")
        chunks = build_document_chunks(blocks)
        if not chunks:
            raise KnowledgeContentError("未从原文件中提取到可检索正文")
    except Exception as exc:
        # Parsing failure does not make the old evidence current. Commit the
        # observed change and failed index together before reporting the error.
        if (old_hash and old_hash != source_sha256) or current is None or current.status != "completed" or (current.source_sha256 and current.source_sha256 != source_sha256):
            await _record_source_observation(session, document_id, old_hash, source_sha256)
            message = str(exc) if isinstance(exc, KnowledgeContentError) else "正文提取失败"
            await session.execute(
                text("""
                    INSERT INTO knowledge_document_extractions (
                        document_id, extractor_version, source_sha256, status,
                        chunk_count, error_message, updated_at
                    ) VALUES (:document_id, :extractor_version, NULL, 'failed', 0, :message, CURRENT_TIMESTAMP)
                    ON CONFLICT(document_id) DO UPDATE SET status = 'failed',
                        error_message = :message, updated_at = CURRENT_TIMESTAMP
                """),
                {"document_id": document_id, "extractor_version": extractor_version, "message": message[:1000]},
            )
            await session.commit()
        if isinstance(exc, KnowledgeContentError):
            raise
        raise KnowledgeContentError("正文提取失败") from exc

    await _record_source_observation(session, document_id, old_hash, source_sha256)
    await session.execute(
        text("DELETE FROM knowledge_document_chunks WHERE document_id = :document_id"),
        {"document_id": document_id},
    )
    for chunk in chunks:
        await session.execute(
            text(
                """
                INSERT INTO knowledge_document_chunks (
                    document_id, chunk_index, page_number, section_name,
                    source_ref, content, normalized_content, content_hash
                ) VALUES (
                    :document_id, :chunk_index, :page_number, :section_name,
                    :source_ref, :content, :normalized_content, :content_hash
                )
                """
            ),
            {"document_id": document_id, **chunk},
        )
    await session.execute(
        text(
            """
            INSERT INTO knowledge_document_extractions (
                document_id, extractor_version, source_sha256, status,
                chunk_count, error_message, extracted_at, updated_at
            ) VALUES (
                :document_id, :extractor_version, :source_sha256, 'completed',
                :chunk_count, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT(document_id) DO UPDATE SET
                extractor_version = excluded.extractor_version,
                source_sha256 = excluded.source_sha256,
                status = 'completed',
                chunk_count = excluded.chunk_count,
                error_message = NULL,
                extracted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {
            "document_id": document_id,
            "extractor_version": extractor_version,
            "source_sha256": source_sha256,
            "chunk_count": len(chunks),
        },
    )
    await session.commit()
    result = await session.execute(
        text(
            """
            SELECT status, chunk_count, extracted_at, extractor_version
            FROM knowledge_document_extractions WHERE document_id = :document_id
            """
        ),
        {"document_id": document_id},
    )
    extraction = result.one()
    return {
        "document_id": document_id,
        "status": extraction.status,
        "chunk_count": int(extraction.chunk_count),
        "extracted_at": extraction.extracted_at,
        "extractor_version": extraction.extractor_version,
        "reused": False,
    }


def _search_core(value: str) -> str:
    core = normalize_question(value)
    for filler in _QUESTION_FILLERS:
        core = core.replace(normalize_question(filler), "")
    return core


def _bigrams(value: str) -> set[str]:
    return {value[index : index + 2] for index in range(max(0, len(value) - 1))}


def _query_forms(question: str) -> list[str]:
    primary = _search_core(question)
    forms = [primary]
    normalized_question = normalize_question(question)
    for group in _CONFIRMED_QUERY_EQUIVALENCES:
        normalized_group = [normalize_question(item) for item in group]
        if any(item in normalized_question for item in normalized_group):
            forms.extend(item for item in normalized_group if item not in forms)
    return forms


def _candidate_prefilter_pairs(question: str) -> tuple[str, ...]:
    pairs = {
        pair
        for form in _query_forms(question)
        for pair in _bigrams(form)
    }
    non_numeric_pairs = {pair for pair in pairs if not pair.isdigit()}
    return tuple(sorted(non_numeric_pairs or pairs))


def _canonical_identifiers(value: str) -> set[str]:
    folded = unicodedata.normalize("NFKC", str(value or "")).casefold()
    model_pattern = re.compile(
        r"(?:vinno\s*|(?<![a-z])v\s*)(\d{1,2})(?!\d)"
        r"(?:[\s_-]*(private|super|elite|expert|plus|max|pro|exp|e|p|l|g|t|s))?"
    )
    identifiers = {
        f"v{match.group(1)}{match.group(2) or ''}"
        for match in model_pattern.finditer(folded)
    }
    identifiers.update(re.findall(r"\d{6,}", normalize_question(value)))
    return identifiers


def _software_versions(value: str) -> set[str]:
    return set(re.findall(r"(?<!\d)\d+\.\d+\.\d+(?!\d)", value))


def _registration_authorities(value: str) -> set[str]:
    normalized = normalize_question(value)
    authorities: set[str] = set()
    if any(marker in normalized for marker in ("湘证", "湘械", "湖南注册")):
        authorities.add("xiang")
    if any(marker in normalized for marker in ("苏证", "苏械", "苏州注册", "江苏注册")):
        authorities.add("su")
    return authorities


def _pair_coverage(query_core: str, content_core: str) -> float:
    query_pairs = _bigrams(query_core)
    if not query_pairs:
        return 1.0 if query_core and query_core in content_core else 0.0
    if query_core in content_core:
        return 1.0
    return sum(pair in content_core for pair in query_pairs) / len(query_pairs)


def _candidate_score(question: str, content: str, document_context: str) -> float:
    query_forms = _query_forms(question)
    content_core = normalize_question(content)
    context_core = normalize_question(document_context)
    if not query_forms[0] or not content_core:
        return 0.0
    coverage = max(_pair_coverage(form, content_core) for form in query_forms)
    identifiers = _canonical_identifiers(question)
    requested_models = {item for item in identifiers if item.startswith("v")}
    content_models = {
        item for item in _canonical_identifiers(content) if item.startswith("v")
    }
    context_models = {
        item for item in _canonical_identifiers(document_context) if item.startswith("v")
    }
    source_identifiers = _canonical_identifiers(f"{content} {document_context}")
    requested_numbers = identifiers - requested_models
    if not requested_models:
        model_scope_match = True
    elif content_models:
        model_scope_match = bool(requested_models & content_models)
    elif "registrationpackagescope" in context_core:
        model_scope_match = bool(requested_models & context_models)
    else:
        model_scope_match = True
    identifier_scope_match = (
        model_scope_match and requested_numbers.issubset(source_identifiers)
    )
    intent_terms = {
        term for term in ("标配", "选配", "招标", "未注册", "注册", "支持", "参数")
        if term in question
    }
    if intent_terms:
        matched_intents = sum(term in content for term in intent_terms)
        coverage = 0.85 * coverage + 0.15 * (matched_intents / len(intent_terms))
    requested_versions = _software_versions(question)
    if requested_versions:
        source_versions = _software_versions(f"{content} {document_context}")
        coverage = (
            min(1.0, coverage + 0.25)
            if requested_versions.issubset(source_versions)
            else coverage * 0.55
        )
    registration_intent = any(term in question for term in ("注册", "湘证", "苏证"))
    registration_certificate = "registrationcertificate" in context_core
    registration_difference = "registrationdifference" in context_core
    authority_scope_match = True
    if registration_intent:
        requested_authorities = _registration_authorities(question)
        source_authorities = _registration_authorities(document_context)
        if requested_authorities:
            if requested_authorities & source_authorities:
                coverage = min(1.0, coverage + 0.3)
            elif source_authorities:
                authority_scope_match = False
            else:
                coverage *= 0.55
        probe_scope_intent = "探头" in question and any(
            term in question for term in ("支持", "适用", "注册", "不支持", "不适用")
        )
        if probe_scope_intent:
            if registration_difference:
                coverage = min(1.0, coverage + 0.35)
            elif registration_certificate:
                coverage *= 0.75
            else:
                coverage *= 0.55
        elif registration_certificate:
            coverage = min(1.0, coverage + 0.25)
        elif registration_difference:
            coverage = min(1.0, coverage + 0.15)
        else:
            coverage *= 0.65
    if not authority_scope_match:
        coverage *= 0.05
    if not identifier_scope_match:
        coverage *= 0.2
    return round(min(1.0, coverage), 4)


def _candidate_excerpt(content: str, question: str) -> str:
    if len(content) <= MAX_CANDIDATE_EXCERPT:
        return content
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return content[:MAX_CANDIDATE_EXCERPT]
    forms = _query_forms(question)
    best_index = max(
        range(len(lines)),
        key=lambda index: max(
            _pair_coverage(form, normalize_question(lines[index])) for form in forms
        ),
    )
    selected = lines[best_index]
    left = best_index - 1
    right = best_index + 1
    while len(selected) < MAX_CANDIDATE_EXCERPT and (left >= 0 or right < len(lines)):
        if left >= 0:
            candidate = f"{lines[left]}\n{selected}"
            if len(candidate) <= MAX_CANDIDATE_EXCERPT:
                selected = candidate
            left -= 1
        if right < len(lines):
            candidate = f"{selected}\n{lines[right]}"
            if len(candidate) <= MAX_CANDIDATE_EXCERPT:
                selected = candidate
            right += 1
    return selected[-MAX_CANDIDATE_EXCERPT:]


async def find_candidate_evidence(
    session: AsyncSession,
    question: str,
    *,
    limit: int = 5,
    scope: dict | None = None,
) -> list[dict]:
    if scope is not None:
        from app.services.knowledge_scope import document_model_identity_unique
        if not await document_model_identity_unique(session, scope):
            return []
    prefilter_pairs = _candidate_prefilter_pairs(question)
    params = {
        f"prefilter_{index}": f"%{pair}%"
        for index, pair in enumerate(prefilter_pairs)
    }
    prefilter_sql = ""
    if params:
        prefilter_sql = "AND (" + " OR ".join(
            f"chunk.normalized_content LIKE :{name}" for name in params
        ) + ")"
    if scope is not None:
        # Unknown model/software applicability is excluded rather than guessed.
        prefilter_sql += """ AND document.market=:scope_market
            AND document.product_series=:scope_model AND document.version=:scope_version"""
        if scope["country"] is not None:
            prefilter_sql += " AND document.country=:scope_country"
            params["scope_country"] = scope["country"]
        params.update({"scope_market": scope["market"],
                       "scope_model": scope["model_name"], "scope_version": scope["software_version"]})
    result = await session.execute(
        text(
            f"""
            SELECT chunk.id AS chunk_id, chunk.document_id, document.title, CASE WHEN extraction.source_sha256 = document.sha256 THEN document.sha256 END AS version_id,
                   document.document_type, document.product_series,
                   chunk.source_ref, chunk.page_number, chunk.content,
                   COALESCE((
                       SELECT GROUP_CONCAT(
                           package.registration_number || ' ' ||
                           package.display_name || ' ' ||
                           CASE package.is_enabled WHEN 1 THEN '已启用' ELSE '未启用' END || ' ' ||
                           COALESCE((
                               SELECT GROUP_CONCAT(version_model.model_name, ' ')
                               FROM registration_package_version_models version_model
                               WHERE version_model.version_id = package_version.id
                           ), ''),
                           ' '
                       )
                       FROM registration_package_versions package_version
                       JOIN registration_packages package
                         ON package.id = package_version.package_id
                       WHERE package_version.status = 'active'
                         AND (
                             package_version.certificate_document_id = document.id
                             OR package_version.difference_document_id = document.id
                         )
                   ), '') AS registration_context
            FROM knowledge_document_chunks chunk
            JOIN knowledge_documents document ON document.id = chunk.document_id
            JOIN knowledge_document_extractions extraction
              ON extraction.document_id = document.id
             AND extraction.status = 'completed'
             AND (extraction.source_sha256 = document.sha256 OR extraction.source_sha256 IS NULL OR document.sha256 IS NULL)
            WHERE document.source_status = 'active'
              {prefilter_sql}
            ORDER BY chunk.document_id, chunk.chunk_index
            """
        ),
        params,
    )
    candidates: list[dict] = []
    for row in result:
        registration_context = row.registration_context or ""
        product_series_context = "" if registration_context else (row.product_series or "")
        score = _candidate_score(
            question,
            row.content,
            (
                f"{row.document_type} {row.title} {product_series_context} "
                f"{'registration_package_scope ' if registration_context else ''}"
                f"{registration_context}"
            ),
        )
        if score < 0.3:
            continue
        candidates.append(
            {
                "chunk_id": int(row.chunk_id),
                "document_id": int(row.document_id),
                "document_title": row.title,
                "document_type": row.document_type,
                "version_id": row.version_id,
                "source_ref": row.source_ref,
                "page_number": int(row.page_number) if row.page_number else None,
                "excerpt": _candidate_excerpt(row.content, question),
                "score": score,
                "preview_url": f"/api/knowledge/documents/{row.document_id}/preview",
            }
        )
    candidates.sort(key=lambda item: (-item["score"], item["document_id"], item["chunk_id"]))
    return candidates[:limit]


async def get_question_candidate_evidence(
    session: AsyncSession,
    question_id: int,
    *,
    limit: int = 5,
) -> list[dict] | None:
    from app.services.knowledge_scope import scope_expression, stored_scope
    scope_column = await scope_expression(session)
    result = await session.execute(
        text(f"SELECT question_text, {scope_column} AS scope_key FROM knowledge_questions WHERE id = :question_id"),
        {"question_id": question_id},
    )
    question = result.one_or_none()
    if question is None:
        return None
    scope = stored_scope(question.scope_key)
    if scope is None:
        return []
    return await find_candidate_evidence(session, question.question_text, limit=limit, scope=scope)
