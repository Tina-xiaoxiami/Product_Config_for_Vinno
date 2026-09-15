"""旧版 .xls 读取链路：xlrd 优先，LibreOffice 兜底。

背景：海外注册跟踪表是 .xls（BIFF8）。原来只能靠 LibreOffice 转换，
机器上装过又不在 PATH 上时整条导入链会直接断掉，且报错只说「需要
LibreOffice/soffice」。现在优先用几十 KB 的纯 Python 包 xlrd 读取。
"""

from __future__ import annotations

import struct
from pathlib import Path
import types

import pytest
import xlrd
from openpyxl import load_workbook

from app.services import overseas_registration_preview as preview


def _record(opcode: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HH", opcode, len(payload)) + payload


def _bof(stream_type: int) -> bytes:
    return _record(
        0x0809, struct.pack("<HHHHII", 0x0600, stream_type, 0x0DBB, 0x07CC, 0, 6)
    )


def _unicode(text: str, length_size: int) -> bytes:
    size = (
        struct.pack("<H", len(text))
        if length_size == 2
        else struct.pack("<B", len(text))
    )
    return size + b"\x01" + text.encode("utf-16-le")


def _label(row: int, column: int, text: str) -> bytes:
    return _record(
        0x0204, struct.pack("<HHH", row, column, 0) + _unicode(text, 2)
    )


def _number(row: int, column: int, value: float) -> bytes:
    return _record(0x0203, struct.pack("<HHHd", row, column, 0, float(value)))


def _write_biff8(path: Path, sheets) -> Path:
    """手写一个最小的 BIFF8 工作簿：真实 Excel 的 .xls 也是这个记录结构。

    只造测试需要的记录（BOF/CODEPAGE/BOUNDSHEET/EOF + 单元格），不引入
    只用于造测试数据的第三方写库。
    """

    globals_head = _bof(0x0005) + _record(0x0042, struct.pack("<H", 1200))
    boundsheets = [
        _record(0x0085, struct.pack("<iBB", 0, 0, 0) + _unicode(name, 1))
        for name, _ in sheets
    ]
    offset = (
        len(globals_head)
        + sum(len(item) for item in boundsheets)
        + len(_record(0x000A))
    )
    located: list[bytes] = []
    body = bytearray()
    for name, cells in sheets:
        located.append(
            _record(0x0085, struct.pack("<iBB", offset, 0, 0) + _unicode(name, 1))
        )
        payload = b"".join(cells)
        body += _bof(0x0010) + payload + _record(0x000A)
        offset += len(_bof(0x0010)) + len(payload) + len(_record(0x000A))
    path.write_bytes(
        globals_head + b"".join(located) + _record(0x000A) + bytes(body)
    )
    return path


def test_xlsx_source_is_used_without_conversion(tmp_path):
    source = tmp_path / "海外注册跟踪表-20260819.xlsx"
    source.write_bytes(b"placeholder")

    assert preview._resolve_parseable_workbook(source, tmp_path) == source


def test_legacy_xls_is_read_by_xlrd_without_libreoffice(tmp_path, monkeypatch):
    source = _write_biff8(
        tmp_path / "海外注册跟踪表-20260819.xls",
        [
            ("已完成注册", [_label(0, 0, "国家/地区"), _label(1, 0, "美国 FDA")]),
            ("新地址注册", [_label(0, 0, "A3 A5 A6"), _number(1, 1, 3.5)]),
        ],
    )

    def unavailable(*args, **kwargs):  # pragma: no cover - 走到这里就是失败
        raise AssertionError("有 xlrd 时不应该再调用 LibreOffice")

    monkeypatch.setattr(preview, "_convert_legacy_xls", unavailable)
    output = tmp_path / "out"
    output.mkdir()
    converted = preview._resolve_parseable_workbook(source, output)

    assert converted.suffix == ".xlsx"
    workbook = load_workbook(converted)
    assert workbook.sheetnames == ["已完成注册", "新地址注册"]
    assert [
        cell.value for cell in workbook["已完成注册"][1]
    ] == ["国家/地区"]
    assert workbook["已完成注册"]["A2"].value == "美国 FDA"
    assert workbook["新地址注册"]["A1"].value == "A3 A5 A6"
    assert workbook["新地址注册"]["B2"].value == 3.5


def test_legacy_xls_falls_back_to_libreoffice_when_xlrd_missing(tmp_path, monkeypatch):
    source = tmp_path / "tracking.xls"
    source.write_bytes(b"not biff")
    converted = tmp_path / "out" / "tracking.xlsx"
    calls: list[Path] = []

    def fake_convert(path: Path, directory: Path) -> Path:
        calls.append(path)
        converted.parent.mkdir(parents=True, exist_ok=True)
        converted.write_bytes(b"converted")
        return converted

    monkeypatch.setattr(preview, "_convert_legacy_xls", fake_convert)

    result = preview._resolve_parseable_workbook(source, converted.parent)

    assert calls == [source]
    assert result == converted


def test_legacy_xls_error_reports_both_options(tmp_path, monkeypatch):
    source = tmp_path / "tracking.xls"
    source.write_bytes(b"not biff")

    def fake_xlrd(path: Path, directory: Path) -> Path:
        raise ImportError("No module named 'xlrd'")

    def fake_soffice(path: Path, directory: Path) -> Path:
        raise ValueError("读取 .xls 需要 LibreOffice/soffice 转换组件")

    monkeypatch.setattr(preview, "_convert_legacy_xls_with_xlrd", fake_xlrd)
    monkeypatch.setattr(preview, "_convert_legacy_xls", fake_soffice)

    with pytest.raises(ValueError) as error:
        preview._resolve_parseable_workbook(source, tmp_path)

    message = str(error.value)
    assert "xlrd" in message
    assert "LibreOffice" in message
    assert "pip install xlrd" in message


def test_legacy_xls_reports_xlrd_failure_reason(tmp_path, monkeypatch):
    """xlrd 能导入、但文件读不了时，原因要带到最终报错里。"""

    source = tmp_path / "tracking.xls"
    source.write_bytes(b"definitely not a workbook")

    def fake_soffice(path: Path, directory: Path) -> Path:
        raise ValueError("读取 .xls 需要 LibreOffice/soffice 转换组件")

    monkeypatch.setattr(preview, "_convert_legacy_xls", fake_soffice)

    with pytest.raises(ValueError) as error:
        preview._resolve_parseable_workbook(source, tmp_path)

    assert "xlrd 读取失败" in str(error.value)


def test_cell_values_keep_their_type():
    book = types.SimpleNamespace(datemode=0)

    def cell(value, ctype):
        return types.SimpleNamespace(value=value, ctype=ctype)

    assert preview._xlrd_cell_value(cell("", xlrd.XL_CELL_EMPTY), book) is None
    assert preview._xlrd_cell_value(cell("A3", xlrd.XL_CELL_TEXT), book) == "A3"
    assert preview._xlrd_cell_value(cell(2024.0, xlrd.XL_CELL_NUMBER), book) == 2024
    assert preview._xlrd_cell_value(cell(3.5, xlrd.XL_CELL_NUMBER), book) == 3.5
    assert preview._xlrd_cell_value(cell(45000.0, xlrd.XL_CELL_DATE), book).year == 2023


def test_sheet_titles_are_made_xlsx_safe():
    assert preview._safe_sheet_title("新地址注册[旧]", 0) == "新地址注册_旧_"
    assert preview._safe_sheet_title("  ", 3) == "Sheet4"
    assert preview._safe_sheet_title("x" * 40, 0) == "x" * 31
