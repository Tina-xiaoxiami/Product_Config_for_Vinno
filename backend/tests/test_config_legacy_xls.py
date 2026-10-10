"""Configuration import contracts for legacy BIFF8 workbooks."""

from __future__ import annotations

import io
from pathlib import Path
import struct

import pytest
import pytest_asyncio
from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.import_export import import_excel, preview_import
from app.database import Base
from app.models import ConfigItem, ConfigValue, ProductModel, ProductSeries


def _record(opcode: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HH", opcode, len(payload)) + payload


def _bof(stream_type: int) -> bytes:
    return _record(
        0x0809,
        struct.pack("<HHHHII", 0x0600, stream_type, 0x0DBB, 0x07CC, 0, 6),
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
        0x0204,
        struct.pack("<HHH", row, column, 0) + _unicode(text, 2),
    )


def _merged_cells(*ranges: tuple[int, int, int, int]) -> bytes:
    payload = struct.pack("<H", len(ranges))
    for first_row, last_row, first_column, last_column in ranges:
        payload += struct.pack(
            "<HHHH", first_row, last_row, first_column, last_column
        )
    return _record(0x00E5, payload)


def _legacy_config_workbook(path: Path) -> Path:
    cells = [
        _label(0, 5, "Legacy Series"),
        _label(1, 5, "Legacy Model"),
        _label(2, 5, "最终配置"),
        _label(2, 6, "当前配置"),
        _label(2, 7, "选型类别"),
        _label(2, 8, "研发状态"),
        _label(3, 0, "Optional Features"),
        _label(4, 0, "Legacy Feature"),
        _label(4, 1, "V1"),
        _label(4, 2, "LEGACY-IPN"),
        _label(4, 3, "旧版功能"),
        _label(4, 4, "Legacy feature"),
        _label(4, 5, "FINAL"),
        _label(4, 6, "CURRENT"),
        _label(4, 7, "OPTIONAL"),
        _label(4, 8, "READY"),
        _merged_cells((0, 0, 5, 8), (1, 1, 5, 8)),
    ]
    globals_head = _bof(0x0005) + _record(0x0042, struct.pack("<H", 1200))
    placeholder = _record(
        0x0085,
        struct.pack("<iBB", 0, 0, 0) + _unicode("Config", 1),
    )
    sheet_stream = _bof(0x0010) + b"".join(cells) + _record(0x000A)
    offset = len(globals_head) + len(placeholder) + len(_record(0x000A))
    boundsheet = _record(
        0x0085,
        struct.pack("<iBB", offset, 0, 0) + _unicode("Config", 1),
    )
    path.write_bytes(
        globals_head + boundsheet + _record(0x000A) + sheet_stream
    )
    return path


def _upload(path: Path, filename: str | None = None) -> UploadFile:
    return UploadFile(
        filename=filename or path.name,
        file=io.BytesIO(path.read_bytes()),
    )


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'legacy-config.db'}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_preview_reads_legacy_xls_with_merged_model_columns(db, tmp_path):
    source = _legacy_config_workbook(tmp_path / "legacy-config.xls")

    result = await preview_import(_upload(source), db)

    assert result["series"] == [
        {"name": "Legacy Series", "models": ["Legacy Model"], "item_count": 1}
    ]
    assert result["summary"]["total_models"] == 1
    assert result["summary"]["total_items"] == 1


@pytest.mark.asyncio
async def test_import_reads_legacy_xls_and_persists_configuration(db, tmp_path):
    source = _legacy_config_workbook(tmp_path / "legacy-config.xls")

    await import_excel(_upload(source), series_name=None, db=db)

    assert await db.scalar(select(ProductSeries.name)) == "Legacy Series"
    assert await db.scalar(select(ProductModel.name)) == "Legacy Model"
    assert await db.scalar(select(ConfigItem.ipn)) == "LEGACY-IPN"
    value = await db.scalar(select(ConfigValue))
    assert (
        value.final_config,
        value.current_config,
        value.selection_config,
        value.rd_status,
    ) == ("FINAL", "CURRENT", "OPTIONAL", "READY")


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", [preview_import, import_excel])
async def test_malformed_xlsx_returns_clear_bad_request(endpoint, db):
    upload = UploadFile(
        filename="broken.xlsx",
        file=io.BytesIO(b"this is not an Excel workbook"),
    )

    with pytest.raises(HTTPException) as error:
        if endpoint is import_excel:
            await endpoint(upload, series_name=None, db=db)
        else:
            await endpoint(upload, db=db)

    assert error.value.status_code == 400
    assert "无法读取Excel文件" in error.value.detail
    assert await db.scalar(select(func.count()).select_from(ProductSeries)) == 0
