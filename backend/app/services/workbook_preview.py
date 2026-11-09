"""只读读取工作簿内容，供应用内在线预览使用。

浏览器无法内嵌渲染 xlsx，故由后端读出单元格文本、前端自行画表；
原件本身仍按原地址下载，不做任何改写。
"""

from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

from openpyxl import load_workbook


MAX_PREVIEW_ROWS = 500
MAX_PREVIEW_COLUMNS = 40
_PREVIEWABLE_SUFFIXES = {".xlsx", ".xlsm"}


class WorkbookPreviewError(ValueError):
    """工作簿无法在线预览。"""


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.time() == time.min:
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def read_workbook_preview(
    path: str | Path,
    *,
    max_rows: int = MAX_PREVIEW_ROWS,
    max_columns: int = MAX_PREVIEW_COLUMNS,
) -> dict:
    """按工作表返回二维单元格文本；超出行列上限的部分截断并标记。"""

    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(target)
    if target.suffix.lower() not in _PREVIEWABLE_SUFFIXES:
        raise WorkbookPreviewError("该表格格式暂不支持在线预览，请下载原件查看")

    workbook = load_workbook(target, read_only=True, data_only=True)
    try:
        sheets = []
        for sheet in workbook.worksheets:
            rows: list[list[str]] = []
            truncated = False
            for index, values in enumerate(sheet.iter_rows(values_only=True)):
                if index >= max_rows:
                    truncated = True
                    break
                if len(values) > max_columns:
                    truncated = True
                rows.append([_cell_text(value) for value in values[:max_columns]])
            sheets.append({"name": sheet.title, "rows": rows, "truncated": truncated})
        return {"sheets": sheets}
    finally:
        workbook.close()


CITATION_WORKBOOK_SUFFIXES = frozenset({".xls", ".xlsx"})
HEADER_LABELS = frozenset({"型号", "机型", "模式", "探头", "电池", "功耗", "测试项目", "项目", "参数",
                           "model", "mode", "probe", "battery", "condition", "runtime", "duration"})


def read_cited_workbook_rows(data: bytes, suffix: str, sheets: dict[str, set[int]] | None) -> list[dict]:
    """Read original, 1-based rows including hidden rows, grouped by their source header."""
    from collections import defaultdict
    from io import BytesIO
    from openpyxl.utils import get_column_letter
    from app.services.knowledge_content import MAX_OFFICE_CELLS, validate_office_package

    def groups(sheet_name, grid, hidden, merged):
        results = defaultdict(list)
        header = None
        requested = sheets[sheet_name] if sheets is not None else set(range(1, len(grid) + 1))
        if not requested or max(requested) > len(grid) or min(requested) < 1:
            raise WorkbookPreviewError(f"工作表「{sheet_name}」的引用行超出原表范围")
        for number, cells in enumerate(grid, 1):
            if sum(value.strip().casefold() in HEADER_LABELS for value in cells) >= 2:
                header = number
            if number in requested and (sheets is not None or any(cells)):
                # Charging lines in a discharge sheet use a different layout.
                valid_header = None if any("充电" in value for value in cells) and not any(
                    value.strip().casefold() in {"v8bat", "v9bat"} for value in cells
                ) else header
                row = {"row_number": number, "hidden": hidden(number), "cells": cells}
                if sheets is None:
                    row["merged_context"] = {i: grid[top][i] for top, bottom, i in merged if top < number - 1 < bottom}
                results[valid_header].append(row)
        for header_row, rows in results.items():
            heading = grid[header_row - 1] if header_row else []
            used = [index for index in range(max(map(len, [heading] + [r["cells"] for r in rows])))
                    if (index < len(heading) and heading[index].strip())
                    or any(index < len(r["cells"]) and r["cells"][index].strip() for r in rows)]
            cols = [heading[i].strip() if i < len(heading) and heading[i].strip() else get_column_letter(i + 1)
                    for i in used]
            display_rows = []
            for row in rows:
                values = row["cells"]
                display = {**row, "cells": [values[i] if i < len(values) else "" for i in used]}
                if sheets is None:
                    display["merged_context"] = {index: row["merged_context"][i] for index, i in enumerate(used)
                                                 if i in row["merged_context"]}
                display_rows.append(display)
            yield {"sheet_name": sheet_name, "header_row": header_row, "columns": cols,
                   "column_letters": [get_column_letter(i + 1) for i in used], "rows": display_rows}

    try:
        if suffix == ".xls":
            import xlrd
            from app.services.overseas_registration_preview import _xlrd_cell_value

            book = xlrd.open_workbook(file_contents=data, formatting_info=True, on_demand=True)
            try:
                results = []
                for name in (sheets if sheets is not None else book.sheet_names()):
                    sheet = book.sheet_by_name(name)
                    last_row = max(sheets[name]) if sheets is not None else sheet.nrows
                    if sheet.nrows * sheet.ncols > MAX_OFFICE_CELLS:
                        raise WorkbookPreviewError("旧版工作表超过预览上限")
                    grid = [[_cell_text(_xlrd_cell_value(cell, book)) for cell in sheet.row(index)]
                            for index in range(min(sheet.nrows, last_row))]
                    merged = [(top, bottom, first) for top, bottom, first, last in sheet.merged_cells
                              if bottom - top > 1 and last - first == 1]
                    results.extend(groups(name, grid, lambda n: bool(getattr(sheet.rowinfo_map.get(n - 1), "hidden", False)), merged))
                return results
            finally:
                book.release_resources()
        if suffix != ".xlsx":
            raise WorkbookPreviewError("引用表格格式暂不支持")
        validate_office_package(data, suffix)
        workbook = load_workbook(BytesIO(data), data_only=True, keep_links=False)
        try:
            results = []
            for name in (sheets if sheets is not None else workbook.sheetnames):
                sheet = workbook[name]
                height = min(sheet.max_row, max(sheets[name])) if sheets is not None else sheet.max_row
                if height * sheet.max_column > MAX_OFFICE_CELLS:
                    raise WorkbookPreviewError("工作表超过预览上限")
                grid = [[_cell_text(value) for value in row] for row in
                        sheet.iter_rows(max_row=height, values_only=True)]
                merged = [(r.min_row - 1, r.max_row, r.min_col - 1) for r in sheet.merged_cells.ranges
                          if r.min_row < r.max_row and r.min_col == r.max_col]
                results.extend(groups(name, grid, lambda n: bool(getattr(sheet.row_dimensions.get(n), "hidden", False)), merged))
            return results
        finally:
            workbook.close()
    except WorkbookPreviewError:
        raise
    except Exception as error:
        raise WorkbookPreviewError("无法读取引用工作表或指定行，请查看原件") from error
