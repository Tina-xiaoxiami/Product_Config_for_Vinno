"""Manual model edits share import identities without rewriting history."""
import asyncio
import io
import json

from fastapi import HTTPException, UploadFile
import openpyxl
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.models import create_model, update_model
from app.api.import_export import preview_import
from app.database import Base
from app.models import ConfigVersion, ProductModel, ProductSeries
from app.models.product_model import ProductModelIdentity
from app.schemas.model import ProductModelCreate, ProductModelUpdate
from app.services.model_identity import normalize_snapshot, resolve_import_model


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'models.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(ProductSeries(id=1, name="China"))
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_manual_rename_preserves_alias_import_and_history(db):
    model = await create_model(ProductModelCreate(series_id=1, name="Old"), db)
    snapshot = {"models": [{"id": model.id, "name": "Old"}], "items": []}
    version = ConfigVersion(series_id=1, version_number="1.0", snapshot_data=json.dumps(snapshot))
    db.add(version)
    await db.commit()
    original = version.snapshot_data
    await update_model(model.id, ProductModelUpdate(name=" New "), db)
    identity = await db.scalar(select(ProductModelIdentity).where(ProductModelIdentity.model_id == model.id))
    assert json.loads(identity.aliases_json) == ["Old", "New"]
    assert (await normalize_snapshot(db, 1, snapshot))["models"][0]["name"] == "New"
    assert version.snapshot_data == original
    assert (await resolve_import_model(db, 1, "Old", 1, 4, 0)).id == model.id
    assert (await resolve_import_model(db, 1, "New", 1, 4, 0)).id == model.id
    with pytest.raises(ValueError, match="源编号"):
        await resolve_import_model(db, 1, "New//11382324-b343-4924-8dc2-a2d132c694a3", 1, 4, 0)


@pytest.mark.asyncio
async def test_manual_create_and_update_reject_owned_names_before_writing(db):
    first = await create_model(ProductModelCreate(series_id=1, name="Old"), db)
    await update_model(first.id, ProductModelUpdate(name="New"), db)
    second = await create_model(ProductModelCreate(series_id=1, name="Other", description="keep"), db)
    for name in ["New", "Old"]:
        with pytest.raises(HTTPException) as conflict:
            await create_model(ProductModelCreate(series_id=1, name=name), db)
        assert conflict.value.status_code == 409
        with pytest.raises(HTTPException) as conflict:
            await update_model(second.id, ProductModelUpdate(name=name, description="changed"), db)
        assert conflict.value.status_code == 409
        assert second.name == "Other"
        assert second.description == "keep"
    assert len((await db.execute(select(ProductModel))).scalars().all()) == 2


@pytest.mark.asyncio
async def test_legacy_manual_model_gets_alias_identity_when_renamed(db):
    legacy = ProductModel(series_id=1, name="Legacy")
    db.add(legacy)
    await db.commit()
    await update_model(legacy.id, ProductModelUpdate(name="Current"), db)
    assert (await resolve_import_model(db, 1, "Legacy", 1, 4, 0)).id == legacy.id


@pytest.mark.asyncio
async def test_disabled_model_names_remain_owned_and_blank_names_fail(db):
    model = await create_model(ProductModelCreate(series_id=1, name="Taken"), db)
    model.is_enabled = False
    await db.commit()
    with pytest.raises(HTTPException) as conflict:
        await create_model(ProductModelCreate(series_id=1, name="Taken"), db)
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException) as invalid:
        await create_model(ProductModelCreate(series_id=1, name="  "), db)
    assert invalid.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("operations", [("create", "create"), ("create", "rename"), ("rename", "rename")])
async def test_concurrent_manual_writers_cannot_claim_the_same_name(tmp_path, operations):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'race.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add_all([
            ProductSeries(id=1, name="China"),
            ProductModel(id=1, series_id=1, name="First"),
            ProductModel(id=2, series_id=1, name="Second"),
        ])
        await session.commit()
    ready = asyncio.Barrier(2)

    async def writer(index, operation):
        async with factory() as session:
            # Dependencies may already have begun a transaction and cached a model.
            cached_model = await session.get(ProductModel, index + 1)
            assert cached_model is not None
            await ready.wait()
            try:
                if operation == "create":
                    await create_model(ProductModelCreate(series_id=1, name="Shared"), session)
                else:
                    await update_model(index + 1, ProductModelUpdate(name="Shared"), session)
                return 200
            except HTTPException as error:
                return error.status_code

    try:
        results = await asyncio.gather(*(writer(i, operation) for i, operation in enumerate(operations)))
        assert sorted(results) == [200, 409]
        async with factory() as session:
            owners = (await session.scalars(select(ProductModel).where(ProductModel.name == "Shared"))).all()
            assert len(owners) == 1
            # A losing writer must not leave behind an alias claiming the winner.
            identities = (await session.scalars(select(ProductModelIdentity))).all()
            assert all("Shared" not in json.loads(row.aliases_json) or row.model_id == owners[0].id for row in identities)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_rename_keeps_old_name_reserved_as_an_alias(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'alias-race.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add_all([
            ProductSeries(id=1, name="China"), ProductModel(id=1, series_id=1, name="Old"),
            ProductModel(id=2, series_id=1, name="Other"),
        ])
        await session.commit()
    ready = asyncio.Barrier(2)

    async def rename(model_id, name):
        async with factory() as session:
            cached_model = await session.get(ProductModel, model_id)
            assert cached_model is not None
            await ready.wait()
            try:
                await update_model(model_id, ProductModelUpdate(name=name), session)
                return 200
            except HTTPException as error:
                return error.status_code

    try:
        assert await asyncio.gather(rename(1, "New"), rename(2, "Old")) == [200, 409]
        async with factory() as session:
            assert (await resolve_import_model(session, 1, "Old", 1, 4, 0)).id == 1
            assert (await session.get(ProductModel, 2)).name == "Other"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_import_and_manual_create_share_name_ownership(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'import-race.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(ProductSeries(id=1, name="China"))
        await session.commit()
    ready = asyncio.Barrier(2)

    async def writer(importing):
        async with factory() as session:
            await session.get(ProductSeries, 1)
            await ready.wait()
            try:
                if importing:
                    model = await resolve_import_model(session, 1, "Shared//c5ec14b2-5715-40e8-ac91-31e8507abf26", 1, 4, 0)
                    await session.commit()
                else:
                    model = await create_model(ProductModelCreate(series_id=1, name="Shared"), session)
                return model.id
            except HTTPException as error:
                assert error.status_code == 409
                return None

    try:
        results = await asyncio.gather(writer(True), writer(False))
        async with factory() as session:
            owners = (await session.scalars(select(ProductModel).where(ProductModel.name == "Shared"))).all()
            assert len(owners) == 1
            assert {value for value in results if value is not None} == {owners[0].id}
    finally:
        await engine.dispose()


def preview_workbook():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.merge_cells("F1:I1")
    sheet["F1"] = "China"
    sheet.merge_cells("F2:I2")
    sheet["F2"] = "Preview//c5ec14b2-5715-40e8-ac91-31e8507abf26"
    sheet["A4"] = "Optional Features"
    for column, value in enumerate(["Feature", "V1", "100", "功能", "Feature", "X", "X", "X", "Done"], 1):
        sheet.cell(5, column, value)
    stream = io.BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return UploadFile(filename="preview.xlsx", file=stream)


@pytest.mark.asyncio
async def test_preview_response_releases_catalog_write_lock(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'preview.db'}", connect_args={"timeout": 0.2})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(ProductSeries(id=1, name="China"))
        await session.commit()
    try:
        async with factory() as preview_session:
            await preview_import(preview_workbook(), preview_session)
            async with factory() as writer:
                model = await create_model(ProductModelCreate(series_id=1, name="After preview"), writer)
                assert model.name == "After preview"
            assert (await preview_session.scalars(select(ProductModel))).all()[0].name == "After preview"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_serialized_renames_refresh_cached_aliases_instead_of_losing_them(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cached-aliases.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(ProductSeries(id=1, name="China"))
        await session.flush()
        model = await resolve_import_model(session, 1, "Old//c5ec14b2-5715-40e8-ac91-31e8507abf26", 1, 4, 0)
        model_id = model.id
        await session.commit()
    ready = asyncio.Barrier(2)

    async def rename(name):
        async with factory() as session:
            identity = await session.scalar(select(ProductModelIdentity))
            assert json.loads(identity.aliases_json) == ["Old"]
            await ready.wait()
            await update_model(model_id, ProductModelUpdate(name=name), session)

    try:
        await asyncio.gather(rename("First"), rename("Second"))
        async with factory() as session:
            identity = await session.scalar(select(ProductModelIdentity))
            assert set(json.loads(identity.aliases_json)) == {"Old", "First", "Second"}
    finally:
        await engine.dispose()
