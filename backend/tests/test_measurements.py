"""Measurement imports must preserve UI names, scope, evidence and history."""
import io
import re
import zipfile

import httpx
import pytest
from fastapi import FastAPI
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import measurements
from app.database import Base, get_db
from app.services.measurements import MeasurementImportError, parse_measurement_workbook


def workbook_bytes(name="距离", total=9, enabled="TURE"):
    workbook = Workbook()
    items = workbook.active
    items.title = "ItemCategories"
    items.append(["Id", "Categories", "Mode", "Description", "ChineseName"])
    items.append(["Distance", "Common", "Tissue", None, name])
    items.append(["Distance", "Common", "Doppler", "Distance D", name])
    items.append(["Bladder", "ABD;GYN", "Tissue", "Bladder Vol.", "膀胱容积"])
    items.append(["Distance", "Common", "Tissue", None, name])
    items.append(["Unknown", None, "URM", None, None])
    summary = workbook.create_sheet("ItemSummary")
    summary.append(["Mode", "ItemCount"])
    summary.append(["Total", 5])
    summary.append(["ModeRenamed", "SWEI->VShear"])
    calculations = workbook.create_sheet("Calculations")
    calculations.append(["Id", "Group", "Unit", "IsEnabled", "Description", "ChineseName"])
    calculations.append(["LVEDV", "2D", "ml", "FALSE", None, "左室容积"])
    calculations.append(["SWV", None, "ms", enabled, "SWV Median", None])
    calc_summary = workbook.create_sheet("CalcSummary")
    calc_summary.append(["Group", "CalcCount"])
    calc_summary.append(["Total", total])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_parse_preserves_names_modes_categories_and_original_rows():
    parsed = parse_measurement_workbook(workbook_bytes())
    rows = parsed["entries"]
    assert len(rows) == 7
    assert rows[0]["en_name"] == "Distance"
    assert rows[0]["description"] == ""
    assert rows[0]["cn_name"] == "距离"
    assert rows[1]["en_name"] == "Distance D"
    assert rows[1]["mode"] == "Doppler"
    assert rows[2]["categories"] == ["ABD", "GYN"]
    assert rows[3]["source_row"] == 5
    assert rows[4]["categories"] == []
    assert rows[4]["cn_name"] == ""
    assert rows[5]["kind"] == "calculation"
    assert rows[5]["enabled"] == "disabled"
    assert rows[6]["enabled"] == "unknown"
    assert rows[6]["enabled_raw"] == "TURE"
    assert parsed["summary"]["measurement_rows"] == 5
    assert parsed["summary"]["measurement_ids"] == 3
    assert parsed["summary"]["calculation_rows"] == 2
    assert parsed["summary"]["duplicate_rows"] == 1
    assert any("9" in message and "2" in message for message in parsed["warnings"])


@pytest.mark.parametrize("content", [b"", b"not an xlsx", b"PKbroken"])
def test_invalid_workbook_rejected(content):
    with pytest.raises(MeasurementImportError):
        parse_measurement_workbook(content)


def test_wrong_sheets_and_missing_headers_rejected():
    workbook = Workbook()
    buffer = io.BytesIO()
    workbook.save(buffer)
    with pytest.raises(MeasurementImportError, match="ItemCategories"):
        parse_measurement_workbook(buffer.getvalue())
    workbook.active.title = "ItemCategories"
    workbook.active.append(["Id", "Categories", "Mode", "Description"])
    workbook.create_sheet("ItemSummary")
    workbook.create_sheet("Calculations")
    buffer = io.BytesIO()
    workbook.save(buffer)
    with pytest.raises(MeasurementImportError, match="ChineseName"):
        parse_measurement_workbook(buffer.getvalue())


def test_corrupt_worksheet_is_reported_as_an_invalid_upload():
    original = io.BytesIO(workbook_bytes())
    broken = io.BytesIO()
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(broken, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "xl/worksheets/sheet1.xml":
                content = content.replace(b"<row r=\"2\">", b"<row invalid=>")
            target.writestr(name, content)
    with pytest.raises(MeasurementImportError):
        parse_measurement_workbook(broken.getvalue())


def test_valid_workbook_without_optional_dimensions_can_be_imported():
    original = io.BytesIO(workbook_bytes())
    streaming = io.BytesIO()
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(streaming, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name.startswith("xl/worksheets/"):
                content = re.sub(rb'<dimension[^>]*/>', b'', content)
            target.writestr(name, content)
    assert len(parse_measurement_workbook(streaming.getvalue())["entries"]) == 7


@pytest.mark.parametrize("value,status", [(True, "enabled"), ("true", "enabled"), (False, "disabled"), (None, "unknown")])
def test_enabled_values_are_explicit(value, status):
    parsed = parse_measurement_workbook(workbook_bytes(enabled=value))
    assert parsed["entries"][-1]["enabled"] == status


@pytest.mark.asyncio
async def test_api_import_is_idempotent_versioned_and_atomic(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'measurements.db'}")
    async with engine.begin() as connection:
        for table in ("measurement_batches", "measurement_entries"):
            await connection.run_sync(Base.metadata.tables[table].create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(measurements.router, prefix="/api/measurements")

    async def db_override():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/api/measurements")).json()["entries"] == []
            content = workbook_bytes()
            upload = {"file": ("human.xlsx", content)}
            first = await client.post("/api/measurements/import", files=upload, data={"version": "1.51.90"})
            assert first.status_code == 200, first.text
            assert not first.json()["reused"]
            batch_id = first.json()["batch_id"]
            repeat = await client.post("/api/measurements/import", files=upload, data={"version": "1.51.90"})
            assert repeat.json() == {"batch_id": batch_id, "reused": True}
            second = await client.post("/api/measurements/import", files={"file": ("human2.xlsx", workbook_bytes(name="距离修订"))}, data={"version": "1.51.91"})
            assert second.status_code == 200
            current = (await client.get("/api/measurements")).json()
            assert len(current["batches"]) == 2
            assert current["entries"][0]["cn_name"] == "距离修订"
            old = (await client.get("/api/measurements", params={"batch_id": batch_id})).json()
            assert old["entries"][0]["cn_name"] == "距离"
            assert old["batch"]["version"] == "1.51.90"
            invalid = await client.post("/api/measurements/import", files={"file": ("bad.xlsx", b"invalid")}, data={"version": "bad"})
            assert invalid.status_code == 400
            assert (await client.get("/api/measurements", params={"batch_id": 99999})).status_code == 404
            assert len((await client.get("/api/measurements")).json()["batches"]) == 2
            assert (await client.post("/api/measurements/import", files=upload, data={"version": " "})).status_code == 400
    finally:
        await engine.dispose()
