"""Import source rows without conflating IDs, imaging modes or calculated values."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import io
from pathlib import PurePosixPath
import zipfile

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.measurement import MeasurementBatch, MeasurementEntry

MAX_UPLOAD_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_ROWS = 20000
ITEM_HEADERS = {"Id", "Categories", "Mode", "Description", "ChineseName"}
CALC_HEADERS = {"Id", "Group", "Unit", "IsEnabled", "Description", "ChineseName"}


class MeasurementImportError(ValueError):
    """An invalid source workbook; no data has been persisted."""


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _validate_archive(content: bytes) -> None:
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise MeasurementImportError("请上传非空 .xlsx 文件，大小不能超过 16 MB")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if len(archive.infolist()) > 1000 or sum(item.file_size for item in archive.infolist()) > MAX_EXPANDED_BYTES:
                raise MeasurementImportError("Excel 解压后过大，无法导入")
    except zipfile.BadZipFile as exc:
        raise MeasurementImportError("无法读取 Excel 文件，请使用人用中文 .xlsx 表") from exc


def _sheet_entries(sheet, kind: str) -> list[dict]:
    if (sheet.max_row or 0) > MAX_ROWS or (sheet.max_column or 0) > 64:
        raise MeasurementImportError(f"{sheet.title} 超出允许的行列数")
    rows = sheet.iter_rows(values_only=True)
    headers = [_text(cell) for cell in next(rows, ())]
    if len(headers) > 64:
        raise MeasurementImportError(f"{sheet.title} 列数过多")
    required = ITEM_HEADERS if kind == "measurement" else CALC_HEADERS
    missing = required - set(headers)
    if missing:
        raise MeasurementImportError(f"{sheet.title} 缺少列：{', '.join(sorted(missing))}")
    if len([header for header in headers if header]) != len(set(header for header in headers if header)):
        raise MeasurementImportError(f"{sheet.title} 存在重复表头")
    entries = []
    for row_number, values in enumerate(rows, start=2):
        if row_number > MAX_ROWS or len(values) > 64:
            raise MeasurementImportError(f"{sheet.title} 超出允许的行列数")
        if not any(value is not None for value in values):
            continue
        row = dict(zip(headers, values))
        if not _text(row.get("Id")):
            raise MeasurementImportError(f"{sheet.title} 第 {row_number} 行缺少 Id")
        description = _text(row.get("Description"))
        enabled_raw = _text(row.get("IsEnabled"))
        enabled = {"true": "enabled", "false": "disabled"}.get(enabled_raw.casefold(), "unknown")
        entries.append({
            "kind": kind, "item_id": _text(row["Id"]),
            "description": description, "en_name": description or _text(row["Id"]),
            "cn_name": _text(row.get("ChineseName")), "mode": _text(row.get("Mode")),
            "categories": sorted(set(part.strip() for part in _text(row.get("Categories")).split(";") if part.strip())),
            "group": _text(row.get("Group")), "unit": _text(row.get("Unit")),
            "enabled": enabled, "enabled_raw": enabled_raw,
            "source_sheet": sheet.title, "source_row": row_number,
        })
    return entries


def _summary(entries: list[dict]) -> dict:
    items = [row for row in entries if row["kind"] == "measurement"]
    calculations = [row for row in entries if row["kind"] == "calculation"]
    fingerprints = Counter(tuple(str(row[key]) for key in row if key not in {"source_row", "en_name"}) for row in entries)
    return {
        "measurement_rows": len(items), "measurement_ids": len({row["item_id"] for row in items}),
        "calculation_rows": len(calculations), "calculation_ids": len({row["item_id"] for row in calculations}),
        "duplicate_rows": sum(count - 1 for count in fingerprints.values()),
        "common_rows": sum("Common" in row["categories"] for row in items),
        "application_rows": sum(any(value != "Common" for value in row["categories"]) for row in items),
        "unclassified_rows": sum(not row["categories"] for row in items),
        "missing_chinese": sum(not row["cn_name"] for row in entries),
        "english_id_fallback": sum(not row["description"] for row in entries),
        "enabled": dict(Counter(row["enabled"] for row in calculations)),
        "modes": dict(Counter(row["mode"] for row in items)),
        "categories": dict(Counter(category for row in items for category in row["categories"])),
        "groups": dict(Counter(row["group"] for row in calculations)),
    }


def _source_warnings(workbook, entries: list[dict], summary: dict) -> list[str]:
    warnings = []
    for sheet_name, count_key in (("ItemSummary", "measurement_rows"), ("CalcSummary", "calculation_rows")):
        if sheet_name not in workbook.sheetnames:
            continue
        sheet = workbook[sheet_name]
        if (sheet.max_row or 0) > MAX_ROWS or (sheet.max_column or 0) > 64:
            raise MeasurementImportError(f"{sheet_name} 超出允许的行列数")
        for number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            if number > MAX_ROWS or len(row) > 64:
                raise MeasurementImportError(f"{sheet_name} 超出允许的行列数")
            if len(row) > 1 and _text(row[0]) == "Total" and _text(row[1]) != str(summary[count_key]):
                warnings.append(f"{sheet_name} 的 Total 为 {_text(row[1])}，明细实际为 {summary[count_key]}；统计使用明细。")
    if summary["duplicate_rows"]:
        warnings.append(f"发现 {summary['duplicate_rows']} 行完全重复记录，保留原始行及出处；明细数量包含重复行。")
    malformed = Counter(row["enabled_raw"] for row in entries if row["kind"] == "calculation" and row["enabled_raw"] and row["enabled"] == "unknown")
    for value, count in malformed.items():
        warnings.append(f"计算项 IsEnabled={value} 共 {count} 行，标记为待核对。")
    names = defaultdict(set)
    for row in entries:
        names[(row["kind"], row["item_id"])].add((row["description"], row["cn_name"]))
    conflicts = sum(len(values) > 1 for values in names.values())
    if conflicts:
        warnings.append(f"{conflicts} 个 Id 在不同记录中的名称不一致，已分别保留，请结合模式核对。")
    return warnings


def parse_measurement_workbook(content: bytes) -> dict:
    _validate_archive(content)
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise MeasurementImportError("无法读取 Excel 文件，请检查文件是否损坏") from exc
    try:
        if len(workbook.worksheets) < 3 or workbook.worksheets[0].title != "ItemCategories" or workbook.worksheets[2].title != "Calculations":
            raise MeasurementImportError("第一个 sheet 必须是 ItemCategories，第三个 sheet 必须是 Calculations")
        entries = _sheet_entries(workbook.worksheets[0], "measurement") + _sheet_entries(workbook.worksheets[2], "calculation")
        if not entries:
            raise MeasurementImportError("工作簿中没有测量或计算明细")
        summary = _summary(entries)
        return {"entries": entries, "summary": summary, "warnings": _source_warnings(workbook, entries, summary)}
    except MeasurementImportError:
        raise
    except Exception as exc:
        raise MeasurementImportError("无法解析 Excel 工作表，请检查文件是否损坏") from exc
    finally:
        workbook.close()


async def import_measurements(db: AsyncSession, content: bytes, source_file: str, version: str) -> dict:
    version = version.strip()
    if not version or len(version) > 80:
        raise MeasurementImportError("请填写不超过 80 字的来源版本")
    parsed = await run_in_threadpool(parse_measurement_workbook, content)
    digest = hashlib.sha256(content).hexdigest()
    lookup = select(MeasurementBatch).where(MeasurementBatch.sha256 == digest, MeasurementBatch.version == version)
    existing = (await db.execute(lookup)).scalar_one_or_none()
    if existing:
        return {"batch_id": existing.id, "reused": True}
    batch = MeasurementBatch(version=version, source_file=PurePosixPath(source_file.replace("\\", "/")).name[:255], sha256=digest, summary=parsed["summary"], warnings=parsed["warnings"])
    try:
        db.add(batch)
        await db.flush()
        db.add_all([MeasurementEntry(batch_id=batch.id, **{key: value for key, value in entry.items() if key != "en_name"}) for entry in parsed["entries"]])
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = (await db.execute(lookup)).scalar_one_or_none()
        if existing:
            return {"batch_id": existing.id, "reused": True}
        raise
    return {"batch_id": batch.id, "reused": False}


def _batch_data(batch: MeasurementBatch) -> dict:
    return {"id": batch.id, "version": batch.version, "source_file": batch.source_file, "sha256": batch.sha256,
            "imported_at": batch.imported_at.isoformat(), "summary": batch.summary, "warnings": batch.warnings}


async def measurement_library(db: AsyncSession, batch_id: int | None = None) -> dict:
    batches = (await db.execute(select(MeasurementBatch).order_by(MeasurementBatch.id.desc()))).scalars().all()
    selected = next((batch for batch in batches if batch_id is None or batch.id == batch_id), None)
    if batch_id is not None and selected is None:
        raise KeyError(batch_id)
    entries = []
    if selected:
        rows = (await db.execute(select(MeasurementEntry).where(MeasurementEntry.batch_id == selected.id).order_by(MeasurementEntry.id))).scalars().all()
        for row in rows:
            data = {column.name: getattr(row, column.name) for column in MeasurementEntry.__table__.columns}
            data["en_name"] = row.description or row.item_id
            entries.append(data)
    return {"batches": [_batch_data(batch) for batch in batches], "batch": _batch_data(selected) if selected else None, "entries": entries}
