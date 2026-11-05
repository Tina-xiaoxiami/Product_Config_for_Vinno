"""Category application edits immediately agree across both management APIs."""
import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.api import applications, probe_models, probe_categories
from app.models.probe import (Application, ApplicationVersion, CategoryApplication,
                             ProbeCategory, ProbeModel, ProbeModelApp, ProbeModelVariant)


@asynccontextmanager
async def catalog(url='sqlite+aiosqlite:///:memory:'):
    engine = create_async_engine(url)
    tables = [model.__table__ for model in (Application, ApplicationVersion, CategoryApplication,
              ProbeCategory, ProbeModel, ProbeModelApp, ProbeModelVariant)]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add_all([ProbeCategory(id=1, name='凸阵'), ProbeCategory(id=2, name='线阵'),
                    Application(id=1, name='腹部'), Application(id=2, name='心脏'),
                    ProbeModel(id=1, category_id=1, model_number='P1'),
                    ProbeModel(id=2, category_id=1, model_number='P2'),
                    ProbeModel(id=3, category_id=2, model_number='P3'),
                    CategoryApplication(category_id=1, application_id=1, probe_type='regular'),
                    CategoryApplication(category_id=1, application_id=1, probe_type='poc'),
                    ProbeModelApp(probe_model_id=1, application_id=2)])
        await db.commit()
        try:
            yield db
        finally:
            await db.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_category_union_counts_both_tracks_once_and_ignores_legacy_assignments():
    async with catalog() as db:
        models = await probe_models.list_models(include_details=True, db=db)
        assert {m.id: m.application_count for m in models.items} == {1: 1, 2: 1, 3: 0}
        assert await probe_models.get_model_apps(1, db=db) == [
            {'id': 1, 'name': '腹部', 'probe_types': ['poc', 'regular']}]
        apps = await applications.list_applications(db=db)
        assert {a.id: a.usage_count for a in apps.items} == {1: 2, 2: 0}
        assert await applications.get_app_probes(1, db=db) == [
            {'probe_id': 1, 'model_number': 'P1', 'probe_types': ['poc', 'regular']},
            {'probe_id': 2, 'model_number': 'P2', 'probe_types': ['poc', 'regular']}]
        assert await applications.get_app_probes(2, db=db) == []


@pytest.mark.asyncio
async def test_batch_change_updates_all_read_paths_and_version_atomically():
    async with catalog() as db:
        result = await applications.apply_association_batch(applications.AssociationBatch(
            version_number='v1', changes=[{'action': 'remove', 'category_id': 1, 'application_id': 1, 'probe_type': 'regular'},
                                         {'action': 'add', 'category_id': 2, 'application_id': 2, 'probe_type': 'regular'}]), db=db)
        assert result['version_number'] == 'v1'
        assert (await probe_models.get_model_apps(1, db=db))[0]['probe_types'] == ['poc']
        assert await probe_models.get_model_apps(3, db=db) == [{'id': 2, 'name': '心脏', 'probe_types': ['regular']}]
        assert await applications.get_app_probes(2, db=db) == [{'probe_id': 3, 'model_number': 'P3', 'probe_types': ['regular']}]
        apps = await applications.list_applications(db=db)
        assert {a.id: a.usage_count for a in apps.items} == {1: 2, 2: 1}
        snapshot = json.loads((await db.scalar(select(ApplicationVersion))).snapshot_data)
        assert {(r['category_id'], r['application_id'], r['probe_type']) for r in snapshot} == {(1, 1, 'poc'), (2, 2, 'regular')}
        assert await db.scalar(select(func.count()).select_from(ProbeModelApp)) == 1


@pytest.mark.asyncio
async def test_late_validation_failure_rolls_back_earlier_changes():
    async with catalog() as db:
        with pytest.raises(HTTPException) as error:
            await applications.apply_association_batch(applications.AssociationBatch(changes=[
                {'action': 'remove', 'category_id': 1, 'application_id': 1, 'probe_type': 'regular'},
                {'action': 'add', 'category_id': 99, 'application_id': 1, 'probe_type': 'regular'}]), db=db)
        assert error.value.status_code == 404
        assert (await probe_models.get_model_apps(1, db=db))[0]['probe_types'] == ['poc', 'regular']
        assert await db.scalar(select(func.count()).select_from(ApplicationVersion)) == 0


@pytest.mark.asyncio
async def test_snapshot_failure_rolls_back_changes_and_keeps_legacy(monkeypatch):
    async with catalog() as db:
        async def failure(*args):
            raise RuntimeError('snapshot unavailable')
        monkeypatch.setattr(applications, 'add_app_version', failure)
        with pytest.raises(RuntimeError):
            await applications.apply_association_batch(applications.AssociationBatch(changes=[
                {'action': 'remove', 'category_id': 1, 'application_id': 1, 'probe_type': 'regular'}]), db=db)
        assert (await probe_models.get_model_apps(1, db=db))[0]['probe_types'] == ['poc', 'regular']
        assert await db.scalar(select(func.count()).select_from(ProbeModelApp)) == 1


@pytest.mark.asyncio
async def test_legacy_write_and_referenced_application_deletion_are_blocked():
    async with catalog() as db:
        with pytest.raises(HTTPException) as error:
            await probe_models.set_model_apps(1, {'app_ids': [2]}, db=db)
        assert error.value.status_code == 409
        for app_id in [1, 2]:
            with pytest.raises(HTTPException) as deletion:
                await applications.delete_application(app_id, db=db)
            assert deletion.value.status_code == 409
        assert await db.scalar(select(func.count()).select_from(ProbeModelApp)) == 1


@pytest.mark.asyncio
async def test_legacy_category_writes_cannot_bypass_the_version_transaction():
    async with catalog() as db:
        before = list((await db.scalars(select(CategoryApplication.id))).all())
        for operation in [probe_categories.add_category_app(2, {'application_id': 2}, db=db),
                          probe_categories.remove_category_app(1, 1, db=db)]:
            with pytest.raises(HTTPException) as error:
                await operation
            assert error.value.status_code == 409
        assert list((await db.scalars(select(CategoryApplication.id))).all()) == before
        assert await db.scalar(select(func.count()).select_from(ApplicationVersion)) == 0


@pytest.mark.asyncio
async def test_concurrent_batches_do_not_duplicate_the_same_category_application(tmp_path):
    async with catalog(f'sqlite+aiosqlite:///{tmp_path / "concurrent.db"}') as db:
        barrier = asyncio.Barrier(2)

        async def submit(number):
            async with AsyncSession(db.bind, expire_on_commit=False) as session:
                await session.execute(select(Application.id))
                await barrier.wait()
                return await applications.apply_association_batch(applications.AssociationBatch(
                    version_number=f'concurrent-{number}', changes=[{
                        'action': 'add', 'category_id': 2, 'application_id': 2, 'probe_type': 'regular'
                    }]), db=session)

        await asyncio.gather(submit(1), submit(2))
        assert await db.scalar(select(func.count()).select_from(CategoryApplication).where(
            CategoryApplication.category_id == 2, CategoryApplication.application_id == 2,
            CategoryApplication.probe_type == 'regular')) == 1
        for row in (await db.scalars(select(ApplicationVersion))).all():
            keys = [(item['category_id'], item['application_id'], item['probe_type']) for item in json.loads(row.snapshot_data)]
            assert len(keys) == len(set(keys))
