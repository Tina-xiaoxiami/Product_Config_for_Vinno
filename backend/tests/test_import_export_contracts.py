"""Regression contracts for configuration workbook import/export safety."""

import io
import json

import openpyxl
import pytest
import pytest_asyncio
from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.import_export import (
    ExportRequest,
    cleanup_duplicate_models,
    export_excel,
    import_excel,
    preview_import,
)
from app.database import Base
from app.models import (
    ConfigDraft,
    ConfigItem,
    ConfigValue,
    ConfigVersion,
    DraftBatch,
    ProductModel,
    ProductSeries,
)
from app.models.product_model import ProductModelIdentity


SOURCE_UUID = "c5ec14b2-5715-40e8-ac91-31e8507abf26"
OTHER_UUID = "11382324-b343-4924-8dc2-a2d132c694a3"
CONFIG_FIELDS = ("final_config", "current_config", "selection_config", "rd_status")


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'contracts.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


def _upload(workbook: openpyxl.Workbook, filename: str = "config.xlsx") -> UploadFile:
    stream = io.BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return UploadFile(filename=filename, file=stream)


def _workbook(series_models: list[tuple[str, str]], *, labels=None, values=None):
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    column = 6
    width = len(labels) if labels else 4
    for series_name, model_header in series_models:
        worksheet.merge_cells(
            start_row=1,
            start_column=column,
            end_row=1,
            end_column=column + width - 1,
        )
        worksheet.cell(1, column, series_name)
        worksheet.merge_cells(
            start_row=2,
            start_column=column,
            end_row=2,
            end_column=column + width - 1,
        )
        worksheet.cell(2, column, model_header)
        if labels:
            for offset, label in enumerate(labels):
                worksheet.cell(3, column + offset, label)
        column += width
    worksheet["A4"] = "Optional Features"
    for index, value in enumerate(["Feature", "V1", "100", "功能", "Feature"], 1):
        worksheet.cell(5, index, value)
    for index, value in enumerate(values or ["FINAL", "CURRENT", "SELECT", "DONE"], 6):
        worksheet.cell(5, index, value)
    return workbook


async def _seed_config(db, *, with_snapshot: bool = False):
    series = ProductSeries(id=1, name="China")
    model = ProductModel(id=1, series_id=1, name="M", sort_order=0)
    item = ConfigItem(
        id=1,
        category="Optional Features",
        row_index=5,
        rd_name="Feature",
        v_code="V1",
        ipn="100",
        zh_desc="功能",
        en_desc="Feature",
    )
    db.add_all([series, model, item])
    await db.flush()
    db.add_all(
        [
            ProductModelIdentity(
                series_id=1,
                model_id=1,
                source_uuid=SOURCE_UUID,
                aliases_json='["M"]',
                historical_ids_json="[]",
            ),
            ConfigValue(
                item_id=1,
                model_id=1,
                final_config="FINAL",
                current_config="CURRENT",
                selection_config="SELECT",
                rd_status="DONE",
            ),
        ]
    )
    if with_snapshot:
        snapshot = {
            "models": [{"id": 1, "name": "M", "source_uuid": SOURCE_UUID}],
            "items": [
                {
                    "id": 1,
                    "ipn": "100",
                    "category": "Optional Features",
                    "values": {
                        "1": {
                            "final_config": "FINAL",
                            "current_config": "CURRENT",
                            "selection_config": "SELECT",
                            "rd_status": "DONE",
                        }
                    },
                }
            ],
        }
        db.add(
            ConfigVersion(
                series_id=1,
                version_number="1.0.0",
                snapshot_data=json.dumps(snapshot),
            )
        )
    await db.commit()
    return model, item


async def _seed_matrix(db):
    series = ProductSeries(id=1, name="China")
    models = [
        ProductModel(id=1, series_id=1, name="M1", sort_order=0),
        ProductModel(id=2, series_id=1, name="M2", sort_order=1),
    ]
    items = [
        ConfigItem(id=1, category="Optional Features", row_index=5, rd_name="F1", ipn="100"),
        ConfigItem(id=2, category="Optional Features", row_index=6, rd_name="F2", ipn="200"),
    ]
    db.add_all([series, *models, *items])
    await db.flush()
    values = []
    snapshot_items = []
    for item in items:
        item_values = {}
        for model in models:
            text = f"{item.ipn}-{model.name}"
            fields = {
                "final_config": f"FINAL-{text}",
                "current_config": text,
                "selection_config": f"SELECT-{text}",
                "rd_status": f"STATUS-{text}",
            }
            values.append(ConfigValue(item_id=item.id, model_id=model.id, **fields))
            item_values[str(model.id)] = fields
        snapshot_items.append(
            {
                "id": item.id,
                "ipn": item.ipn,
                "category": item.category,
                "values": item_values,
            }
        )
    db.add_all(values)
    db.add(
        ConfigVersion(
            series_id=1,
            version_number="1.0.0",
            snapshot_data=json.dumps(
                {
                    "models": [{"id": model.id, "name": model.name} for model in models],
                    "items": snapshot_items,
                }
            ),
        )
    )
    await db.commit()


async def _response_bytes(response) -> bytes:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


@pytest.mark.asyncio
async def test_preview_keeps_noncontiguous_series_ranges_separate(db):
    workbook = _workbook(
        [
            ("A", f"A1//{SOURCE_UUID}"),
            ("B", f"B1//{SOURCE_UUID}"),
            ("A", f"A2//{OTHER_UUID}"),
        ]
    )

    result = await preview_import(_upload(workbook), db)

    by_series = {entry["name"]: entry["models"] for entry in result["series"]}
    assert by_series == {"A": ["A1", "A2"], "B": ["B1"]}
    assert result["summary"]["total_models"] == 3


@pytest.mark.asyncio
async def test_preview_rejects_uuid_identity_conflict_without_writing(db):
    await _seed_config(db)
    workbook = _workbook([("China", f"M//{OTHER_UUID}")])

    with pytest.raises(HTTPException, match="源编号不同") as error:
        await preview_import(_upload(workbook), db)

    assert error.value.status_code == 400
    assert await db.scalar(select(func.count()).select_from(ProductModel)) == 1
    assert await db.scalar(select(func.count()).select_from(ProductModelIdentity)) == 1


@pytest.mark.asyncio
async def test_preview_of_new_valid_identity_has_no_database_side_effects(db):
    db.add(ProductSeries(id=1, name="China"))
    await db.commit()

    result = await preview_import(
        _upload(_workbook([("China", f"New model//{SOURCE_UUID}")])),
        db,
    )

    assert result["series"][0]["models"] == ["New model"]
    assert await db.scalar(select(func.count()).select_from(ProductModel)) == 0
    assert await db.scalar(select(func.count()).select_from(ProductModelIdentity)) == 0


@pytest.mark.asyncio
async def test_partial_one_column_export_roundtrip_preserves_hidden_fields(db):
    await _seed_config(db, with_snapshot=True)
    exported = await export_excel(
        ExportRequest(
            series_id=1,
            item_ids="1",
            model_ids="1",
            visible_fields="current_config",
        ),
        db,
    )
    payload = await _response_bytes(exported)
    worksheet = openpyxl.load_workbook(io.BytesIO(payload)).active
    assert worksheet["F3"].value == "当前配置"
    assert worksheet["F6"].value == "CURRENT"

    await import_excel(
        UploadFile(filename="roundtrip.xlsx", file=io.BytesIO(payload)),
        series_name=None,
        db=db,
    )

    value = await db.scalar(select(ConfigValue).where(ConfigValue.item_id == 1))
    assert {field: getattr(value, field) for field in CONFIG_FIELDS} == {
        "final_config": "FINAL",
        "current_config": "CURRENT",
        "selection_config": "SELECT",
        "rd_status": "DONE",
    }
    assert await db.scalar(select(func.count()).select_from(ConfigDraft)) == 0


@pytest.mark.asyncio
async def test_patch_roundtrip_does_not_turn_empty_placeholder_into_a_change(db):
    await _seed_config(db, with_snapshot=True)
    value = await db.scalar(select(ConfigValue).where(ConfigValue.item_id == 1))
    value.current_config = None
    version = await db.scalar(select(ConfigVersion))
    snapshot = json.loads(version.snapshot_data)
    snapshot["items"][0]["values"]["1"]["current_config"] = None
    version.snapshot_data = json.dumps(snapshot)
    await db.commit()

    exported = await export_excel(
        ExportRequest(
            series_id=1,
            item_ids="1",
            model_ids="1",
            visible_fields="current_config",
        ),
        db,
    )
    payload = await _response_bytes(exported)
    assert openpyxl.load_workbook(io.BytesIO(payload)).active["F6"].value == "-"

    await import_excel(
        UploadFile(filename="empty-roundtrip.xlsx", file=io.BytesIO(payload)),
        series_name=None,
        db=db,
    )

    await db.refresh(value)
    assert value.current_config is None
    assert await db.scalar(select(func.count()).select_from(ConfigDraft)) == 0


@pytest.mark.asyncio
async def test_filtered_export_roundtrip_does_not_delete_omitted_items_or_models(db):
    await _seed_matrix(db)

    exported = await export_excel(
        ExportRequest(
            series_id=1,
            item_ids="1",
            model_ids="1",
        ),
        db,
    )
    payload = await _response_bytes(exported)
    exported_workbook = openpyxl.load_workbook(io.BytesIO(payload))
    assert exported_workbook["__VINNO_CONFIG_META__"].sheet_state == "veryHidden"
    await import_excel(
        UploadFile(filename="renamed-by-user.xlsx", file=io.BytesIO(payload)),
        series_name=None,
        db=db,
    )

    assert await db.scalar(select(func.count()).select_from(ConfigDraft)) == 0
    stored = (
        await db.execute(select(ConfigValue).order_by(ConfigValue.item_id, ConfigValue.model_id))
    ).scalars().all()
    assert [(value.item_id, value.model_id, value.current_config) for value in stored] == [
        (1, 1, "100-M1"),
        (1, 2, "100-M2"),
        (2, 1, "200-M1"),
        (2, 2, "200-M2"),
    ]


@pytest.mark.asyncio
async def test_external_workbook_without_metadata_keeps_full_sync_semantics(db):
    await _seed_matrix(db)
    exported = await export_excel(
        ExportRequest(series_id=1, item_ids="1", model_ids="1"),
        db,
    )
    workbook = openpyxl.load_workbook(io.BytesIO(await _response_bytes(exported)))
    del workbook["__VINNO_CONFIG_META__"]

    await import_excel(_upload(workbook, "external.xlsx"), series_name=None, db=db)

    drafts = (await db.execute(select(ConfigDraft))).scalars().all()
    assert [(draft.change_type, draft.item_id, draft.model_id) for draft in drafts] == [
        ("delete", 2, 1)
    ]


@pytest.mark.asyncio
async def test_unsupported_application_metadata_is_rejected_instead_of_full_sync(db):
    await _seed_matrix(db)
    exported = await export_excel(
        ExportRequest(series_id=1, item_ids="1", model_ids="1"),
        db,
    )
    workbook = openpyxl.load_workbook(io.BytesIO(await _response_bytes(exported)))
    metadata = workbook["__VINNO_CONFIG_META__"]
    version_row = next(
        row
        for row in range(1, metadata.max_row + 1)
        if metadata.cell(row, 1).value == "version"
    )
    metadata.cell(version_row, 2, "999")

    with pytest.raises(HTTPException, match="元数据") as error:
        await import_excel(_upload(workbook, "unsupported.xlsx"), series_name=None, db=db)

    assert error.value.status_code == 400
    assert await db.scalar(select(func.count()).select_from(ConfigDraft)) == 0


@pytest.mark.asyncio
async def test_import_maps_recognized_row_three_labels_and_preserves_omitted_fields(db):
    await _seed_config(db, with_snapshot=True)
    workbook = _workbook(
        [("China", f"M//{SOURCE_UUID}")],
        labels=["研发状态", "当前配置"],
        values=["READY", "UPDATED"],
    )

    await import_excel(_upload(workbook), series_name=None, db=db)

    value = await db.scalar(select(ConfigValue).where(ConfigValue.item_id == 1))
    assert {field: getattr(value, field) for field in CONFIG_FIELDS} == {
        "final_config": "FINAL",
        "current_config": "UPDATED",
        "selection_config": "SELECT",
        "rd_status": "READY",
    }
    drafts = (await db.execute(select(ConfigDraft))).scalars().all()
    assert [(draft.change_type, draft.field_name, draft.new_value) for draft in drafts] == [
        ("update", "rd_status", "READY"),
        ("update", "current_config", "UPDATED"),
    ]


@pytest.mark.asyncio
async def test_import_keeps_legacy_four_column_layout_without_valid_labels(db):
    await _seed_config(db)
    workbook = _workbook(
        [("China", f"M//{SOURCE_UUID}")],
        labels=None,
        values=["NEW FINAL", "NEW CURRENT", "NEW SELECT", "NEW DONE"],
    )

    await import_excel(_upload(workbook), series_name=None, db=db)

    value = await db.scalar(select(ConfigValue).where(ConfigValue.item_id == 1))
    assert {field: getattr(value, field) for field in CONFIG_FIELDS} == {
        "final_config": "NEW FINAL",
        "current_config": "NEW CURRENT",
        "selection_config": "NEW SELECT",
        "rd_status": "NEW DONE",
    }


@pytest.mark.asyncio
async def test_duplicate_cleanup_is_read_only_and_reports_candidates(db):
    db.add_all(
        [
            ProductSeries(id=1, name="Domestic"),
            ProductSeries(id=2, name="Overseas"),
            ProductModel(id=10, series_id=1, name="Shared"),
            ProductModel(id=11, series_id=1, name="Domestic only"),
            ProductModel(id=20, series_id=2, name="Shared"),
            ConfigItem(id=1, category="Optional Features", row_index=5, ipn="100"),
        ]
    )
    await db.flush()
    db.add_all(
        [
            ConfigValue(item_id=1, model_id=10, current_config="DOMESTIC"),
            ConfigValue(item_id=1, model_id=20, current_config="OVERSEAS"),
        ]
    )
    await db.commit()

    result = await cleanup_duplicate_models(db)

    assert result["deleted"] == []
    assert result["candidates"] == [
        {
            "model_name": "Shared",
            "instances": [
                {"model_id": 10, "series_id": 1, "series_name": "Domestic"},
                {"model_id": 20, "series_id": 2, "series_name": "Overseas"},
            ],
        }
    ]
    assert [
        (model.id, model.series_id, model.name)
        for model in (
            await db.execute(select(ProductModel).order_by(ProductModel.id))
        ).scalars()
    ] == [
        (10, 1, "Shared"),
        (11, 1, "Domestic only"),
        (20, 2, "Shared"),
    ]
    assert [
        (value.model_id, value.current_config)
        for value in (
            await db.execute(select(ConfigValue).order_by(ConfigValue.model_id))
        ).scalars()
    ] == [(10, "DOMESTIC"), (20, "OVERSEAS")]


@pytest.mark.asyncio
async def test_export_accepts_chinese_series_names_in_download_headers(db):
    from urllib.parse import unquote
    await _seed_config(db)
    series = await db.get(ProductSeries, 1)
    series.name = '回归测试-国内'
    await db.commit()
    response = await export_excel(ExportRequest(series_id=1), db)
    header = response.headers['content-disposition']
    header.encode('ascii')
    assert '回归测试-国内' in unquote(header)


@pytest.mark.asyncio
async def test_patch_roundtrip_reuses_exported_item_without_ipn(db):
    await _seed_config(db)
    item = await db.get(ConfigItem, 1)
    item.ipn = None
    await db.commit()

    exported = await export_excel(
        ExportRequest(series_id=1, item_ids="1", model_ids="1"),
        db,
    )
    payload = await _response_bytes(exported)
    await import_excel(
        UploadFile(filename="no-ipn.xlsx", file=io.BytesIO(payload)),
        series_name=None,
        db=db,
    )

    items = (await db.execute(select(ConfigItem).order_by(ConfigItem.id))).scalars().all()
    assert [(entry.id, entry.rd_name, entry.ipn) for entry in items] == [
        (1, "Feature", None)
    ]
    assert await db.scalar(select(func.count()).select_from(ConfigValue)) == 1


@pytest.mark.asyncio
async def test_no_ipn_patch_roundtrip_uses_published_snapshot_baseline(db):
    await _seed_config(db, with_snapshot=True)
    item = await db.get(ConfigItem, 1)
    item.ipn = None
    version = await db.scalar(select(ConfigVersion))
    snapshot = json.loads(version.snapshot_data)
    snapshot["items"][0].update(
        {
            "ipn": None,
            "row_index": 5,
            "rd_name": "Feature",
            "v_code": "V1",
            "zh_desc": "功能",
            "en_desc": "Feature",
        }
    )
    version.snapshot_data = json.dumps(snapshot)
    await db.commit()

    exported = await export_excel(
        ExportRequest(
            series_id=1,
            item_ids="1",
            model_ids="1",
            visible_fields="current_config",
        ),
        db,
    )
    payload = await _response_bytes(exported)
    await import_excel(
        UploadFile(filename="no-ipn-baseline.xlsx", file=io.BytesIO(payload)),
        series_name=None,
        db=db,
    )

    assert await db.scalar(select(func.count()).select_from(ConfigDraft)) == 0
    value = await db.scalar(select(ConfigValue).where(ConfigValue.item_id == 1))
    assert value.current_config == "CURRENT"


@pytest.mark.asyncio
async def test_full_import_creates_draft_for_new_no_ipn_pair(db):
    await _seed_config(db, with_snapshot=True)
    workbook = _workbook([("China", f"M//{SOURCE_UUID}")])
    worksheet = workbook.active
    for column, value in enumerate(
        ["New no IPN", "V2", None, "新功能", "New feature"],
        1,
    ):
        worksheet.cell(6, column, value)
    for column, value in enumerate(["NEW", "NEW", "NEW", "NEW"], 6):
        worksheet.cell(6, column, value)

    await import_excel(_upload(workbook), series_name=None, db=db)

    item = await db.scalar(select(ConfigItem).where(ConfigItem.rd_name == "New no IPN"))
    drafts = (
        await db.execute(
            select(ConfigDraft).where(
                ConfigDraft.item_id == item.id,
                ConfigDraft.model_id == 1,
            )
        )
    ).scalars().all()
    assert [(draft.change_type, draft.field_name) for draft in drafts] == [
        ("create", None)
    ]


@pytest.mark.asyncio
async def test_full_import_creates_delete_draft_for_omitted_no_ipn_pair(db):
    await _seed_config(db, with_snapshot=True)
    item = await db.get(ConfigItem, 1)
    item.ipn = None
    version = await db.scalar(select(ConfigVersion))
    snapshot = json.loads(version.snapshot_data)
    snapshot["items"][0].update(
        {
            "ipn": None,
            "row_index": 5,
            "rd_name": "Feature",
            "v_code": "V1",
            "zh_desc": "功能",
            "en_desc": "Feature",
        }
    )
    version.snapshot_data = json.dumps(snapshot)
    await db.commit()

    workbook = _workbook([("China", f"M//{SOURCE_UUID}")])
    for row in range(5, workbook.active.max_row + 1):
        for column in range(1, 10):
            workbook.active.cell(row, column).value = None
    await import_excel(_upload(workbook), series_name=None, db=db)

    drafts = (await db.execute(select(ConfigDraft))).scalars().all()
    assert [(draft.change_type, draft.item_id, draft.model_id) for draft in drafts] == [
        ("delete", 1, 1)
    ]


@pytest.mark.asyncio
async def test_patch_rejects_recycled_item_id_metadata(db):
    await _seed_config(db)
    item = await db.get(ConfigItem, 1)
    item.ipn = None
    await db.commit()
    exported = await export_excel(
        ExportRequest(series_id=1, item_ids="1", model_ids="1"),
        db,
    )
    payload = await _response_bytes(exported)

    item.rd_name = "Recycled record"
    item.v_code = "OTHER"
    item.zh_desc = "另一条记录"
    item.en_desc = "Another record"
    await db.commit()

    with pytest.raises(HTTPException, match="配置项身份") as error:
        await import_excel(
            UploadFile(filename="stale-export.xlsx", file=io.BytesIO(payload)),
            series_name=None,
            db=db,
        )

    assert error.value.status_code == 400
    await db.refresh(item)
    assert item.rd_name == "Recycled record"


@pytest.mark.asyncio
async def test_patch_rejects_rows_moved_away_from_their_identity_metadata(db):
    await _seed_config(db)
    first = await db.get(ConfigItem, 1)
    first.ipn = None
    second = ConfigItem(
        id=2,
        category="Optional Features",
        row_index=6,
        rd_name="Second",
        v_code="V2",
        ipn=None,
        zh_desc="第二项",
        en_desc="Second",
    )
    db.add(second)
    await db.flush()
    db.add(ConfigValue(item_id=2, model_id=1, current_config="SECOND"))
    await db.commit()

    exported = await export_excel(
        ExportRequest(series_id=1, item_ids="1,2", model_ids="1"),
        db,
    )
    workbook = openpyxl.load_workbook(io.BytesIO(await _response_bytes(exported)))
    worksheet = workbook.active
    first_row = [worksheet.cell(6, column).value for column in range(1, 10)]
    second_row = [worksheet.cell(7, column).value for column in range(1, 10)]
    for column, value in enumerate(second_row, 1):
        worksheet.cell(6, column, value)
    for column, value in enumerate(first_row, 1):
        worksheet.cell(7, column, value)

    with pytest.raises(HTTPException, match="配置项身份") as error:
        await import_excel(_upload(workbook, "moved-rows.xlsx"), series_name=None, db=db)

    assert error.value.status_code == 400
    assert await db.scalar(select(func.count()).select_from(ConfigItem)) == 2


@pytest.mark.asyncio
async def test_patch_roundtrip_preserves_database_row_and_model_span(db):
    model, item = await _seed_config(db, with_snapshot=True)
    item.row_index = 100
    model.column_start = 20
    model.column_end = 23
    await db.commit()

    exported = await export_excel(
        ExportRequest(
            series_id=1,
            item_ids="1",
            model_ids="1",
            visible_fields="current_config",
        ),
        db,
    )
    payload = await _response_bytes(exported)
    await import_excel(
        UploadFile(filename="filtered.xlsx", file=io.BytesIO(payload)),
        series_name=None,
        db=db,
    )

    await db.refresh(item)
    await db.refresh(model)
    assert item.row_index == 100
    assert (model.column_start, model.column_end) == (20, 23)


@pytest.mark.asyncio
async def test_patch_rejects_model_outside_declared_export_scope(db):
    await _seed_config(db)
    exported = await export_excel(
        ExportRequest(series_id=1, item_ids="1", model_ids="1"),
        db,
    )
    workbook = openpyxl.load_workbook(io.BytesIO(await _response_bytes(exported)))
    workbook.active["F2"] = f"Injected//{OTHER_UUID}"

    with pytest.raises(HTTPException, match="机型范围") as error:
        await import_excel(_upload(workbook, "changed-model.xlsx"), series_name=None, db=db)

    assert error.value.status_code == 400
    assert await db.scalar(select(func.count()).select_from(ProductModel)) == 1


@pytest.mark.asyncio
async def test_reimport_reconciles_touched_draft_and_keeps_untouched_draft(db):
    await _seed_config(db, with_snapshot=True)

    async def import_current(value):
        workbook = _workbook(
            [("China", f"M//{SOURCE_UUID}")],
            labels=["当前配置"],
            values=[value],
        )
        await import_excel(_upload(workbook), series_name=None, db=db)

    await import_current("B")
    batch = await db.scalar(select(DraftBatch).where(DraftBatch.status == "draft"))
    db.add(
        ConfigDraft(
            series_id=1,
            batch_id=batch.id,
            change_type="update",
            item_id=1,
            model_id=1,
            field_name="rd_status",
            old_value="DONE",
            new_value="MANUAL",
        )
    )
    await db.commit()

    await import_current("C")
    drafts = (
        await db.execute(select(ConfigDraft).order_by(ConfigDraft.field_name))
    ).scalars().all()
    assert [
        (draft.field_name, draft.old_value, draft.new_value)
        for draft in drafts
    ] == [
        ("current_config", "CURRENT", "C"),
        ("rd_status", "DONE", "MANUAL"),
    ]

    await import_current("CURRENT")
    drafts = (await db.execute(select(ConfigDraft))).scalars().all()
    assert [
        (draft.field_name, draft.old_value, draft.new_value)
        for draft in drafts
    ] == [("rd_status", "DONE", "MANUAL")]


@pytest.mark.asyncio
async def test_reimport_converts_delete_back_to_update_without_stale_draft(db):
    await _seed_config(db, with_snapshot=True)

    await import_excel(
        _upload(
            _workbook(
                [("China", f"M//{SOURCE_UUID}")],
                labels=list(CONFIG_FIELDS),
                values=["-", "-", "-", "-"],
            )
        ),
        series_name=None,
        db=db,
    )
    drafts = (await db.execute(select(ConfigDraft))).scalars().all()
    assert [(draft.change_type, draft.field_name) for draft in drafts] == [
        ("delete", None)
    ]

    await import_excel(
        _upload(
            _workbook(
                [("China", f"M//{SOURCE_UUID}")],
                labels=list(CONFIG_FIELDS),
                values=["REVISED", "CURRENT", "SELECT", "DONE"],
            )
        ),
        series_name=None,
        db=db,
    )
    drafts = (await db.execute(select(ConfigDraft))).scalars().all()
    assert [
        (draft.change_type, draft.field_name, draft.old_value, draft.new_value)
        for draft in drafts
    ] == [("update", "final_config", "FINAL", "REVISED")]


@pytest.mark.asyncio
async def test_reimport_removes_stale_create_when_pair_returns_to_empty(db):
    await _seed_config(db, with_snapshot=True)
    item = ConfigItem(
        id=2,
        category="Optional Features",
        row_index=6,
        rd_name="New pair",
        ipn="200",
    )
    db.add(item)
    await db.flush()
    db.add(
        ConfigValue(
            item_id=2,
            model_id=1,
            final_config="NEW",
            current_config="NEW",
            selection_config="NEW",
            rd_status="NEW",
        )
    )
    await db.commit()

    exported = await export_excel(
        ExportRequest(series_id=1, item_ids="2", model_ids="1"),
        db,
    )
    payload = await _response_bytes(exported)
    await import_excel(
        UploadFile(filename="new-pair.xlsx", file=io.BytesIO(payload)),
        series_name=None,
        db=db,
    )
    drafts = (await db.execute(select(ConfigDraft))).scalars().all()
    assert [(draft.change_type, draft.item_id, draft.model_id) for draft in drafts] == [
        ("create", 2, 1)
    ]

    workbook = openpyxl.load_workbook(io.BytesIO(payload))
    for column in range(6, 10):
        workbook.active.cell(6, column, "-")
    await import_excel(_upload(workbook, "empty-pair.xlsx"), series_name=None, db=db)

    assert await db.scalar(select(func.count()).select_from(ConfigDraft)) == 0


@pytest.mark.asyncio
async def test_partial_patch_does_not_remove_create_draft_for_hidden_values(db):
    await _seed_config(db, with_snapshot=True)
    item = ConfigItem(
        id=2,
        category="Optional Features",
        row_index=6,
        rd_name="New pair",
        ipn="200",
    )
    db.add(item)
    await db.flush()
    db.add(
        ConfigValue(
            item_id=2,
            model_id=1,
            final_config="HIDDEN",
            current_config=None,
            selection_config=None,
            rd_status=None,
        )
    )
    await db.commit()

    full_export = await export_excel(
        ExportRequest(series_id=1, item_ids="2", model_ids="1"),
        db,
    )
    await import_excel(
        UploadFile(
            filename="create-pair.xlsx",
            file=io.BytesIO(await _response_bytes(full_export)),
        ),
        series_name=None,
        db=db,
    )
    partial_export = await export_excel(
        ExportRequest(
            series_id=1,
            item_ids="2",
            model_ids="1",
            visible_fields="current_config",
        ),
        db,
    )
    await import_excel(
        UploadFile(
            filename="partial-create-pair.xlsx",
            file=io.BytesIO(await _response_bytes(partial_export)),
        ),
        series_name=None,
        db=db,
    )

    drafts = (await db.execute(select(ConfigDraft))).scalars().all()
    assert [(draft.change_type, draft.item_id, draft.model_id) for draft in drafts] == [
        ("create", 2, 1)
    ]


@pytest.mark.asyncio
async def test_draft_export_keeps_truthful_cells_and_excludes_deleted_rows(db):
    await _seed_config(db, with_snapshot=True)
    value = await db.scalar(select(ConfigValue).where(ConfigValue.item_id == 1))
    value.current_config = "B"
    await db.commit()

    updated = await export_excel(
        ExportRequest(
            series_id=1,
            item_ids="1",
            model_ids="1",
            visible_fields="current_config",
            draft_changes=json.dumps(
                {
                    "1_1_current_config": {
                        "changeType": "update",
                        "oldValue": "CURRENT",
                        "newValue": "B",
                    }
                }
            ),
        ),
        db,
    )
    updated_workbook = openpyxl.load_workbook(io.BytesIO(await _response_bytes(updated)))
    updated_cell = updated_workbook.active["F6"]
    assert updated_cell.value == "B"
    assert updated_cell.comment is not None
    assert "CURRENT" in updated_cell.comment.text

    deleted = await export_excel(
        ExportRequest(
            series_id=1,
            item_ids="1",
            model_ids="1",
            visible_fields="current_config",
            deleted_items=json.dumps(
                {"1_1": {"current_config": "CURRENT"}}
            ),
        ),
        db,
    )
    deleted_workbook = openpyxl.load_workbook(io.BytesIO(await _response_bytes(deleted)))
    assert "Feature" not in [
        deleted_workbook.active.cell(row, 1).value
        for row in range(1, deleted_workbook.active.max_row + 1)
    ]
    metadata = deleted_workbook["__VINNO_CONFIG_META__"]
    item_ids_row = next(
        row
        for row in range(1, metadata.max_row + 1)
        if metadata.cell(row, 1).value == "item_ids"
    )
    assert metadata.cell(item_ids_row, 2).value in (None, "")


@pytest.mark.asyncio
async def test_mixed_deleted_pair_roundtrip_preserves_delete_draft_and_working_value(db):
    await _seed_matrix(db)
    batch = DraftBatch(id="mixed-delete", series_id=1, status="draft")
    db.add(batch)
    db.add(
        ConfigDraft(
            series_id=1,
            batch_id=batch.id,
            change_type="delete",
            item_id=1,
            model_id=1,
        )
    )
    await db.commit()
    before = await db.scalar(
        select(ConfigValue).where(
            ConfigValue.item_id == 1,
            ConfigValue.model_id == 1,
        )
    )
    before_fields = {field: getattr(before, field) for field in CONFIG_FIELDS}

    exported = await export_excel(
        ExportRequest(
            series_id=1,
            item_ids="1",
            model_ids="1,2",
            deleted_items=json.dumps({"1_1": before_fields}),
        ),
        db,
    )
    payload = await _response_bytes(exported)
    await import_excel(
        UploadFile(filename="mixed-delete.xlsx", file=io.BytesIO(payload)),
        series_name=None,
        db=db,
    )

    drafts = (await db.execute(select(ConfigDraft))).scalars().all()
    assert [(draft.change_type, draft.item_id, draft.model_id) for draft in drafts] == [
        ("delete", 1, 1)
    ]
    await db.refresh(before)
    assert {field: getattr(before, field) for field in CONFIG_FIELDS} == before_fields
