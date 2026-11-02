import asyncio

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from app.database import Base
from app.models.probe import ProbeCategory, ProbeModel, ProbeModelVariant, Application, ProbeModelApp
from app.api.probe_models import list_models, get_model_apps


def test_probe_list_batches_details_and_keeps_pagination():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        tables = [ProbeCategory.__table__, ProbeModel.__table__, ProbeModelVariant.__table__, Application.__table__, ProbeModelApp.__table__]
        try:
            async with engine.begin() as conn:
                await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
            async with AsyncSession(engine, expire_on_commit=False) as db:
                db.add_all([ProbeCategory(id=1, name='A'), ProbeCategory(id=2, name='B'), Application(id=1, name='App')])
                db.add_all([ProbeModel(id=i, category_id=1 if i < 4 else 2, model_number=f'P{i}', sort_order=i) for i in range(1, 5)])
                db.add_all([ProbeModelVariant(probe_model_id=1, internal_model='second', sort_order=2), ProbeModelVariant(probe_model_id=1, internal_model='first', sort_order=1), ProbeModelApp(probe_model_id=1, application_id=1)])
                await db.commit()
                queries = []
                event.listen(engine.sync_engine, 'before_cursor_execute', lambda *args: queries.append(args[2]))
                result = await list_models(category_id=1, skip=0, limit=2, include_details=True, db=db)
                assert result.total == 3
                assert [row.id for row in result.items] == [1, 2]
                assert result.items[0].application_count == 1
                assert [v.internal_model for v in result.items[0].variant_items] == ['first', 'second']
                assert result.items[1].application_count == 0
                assert result.items[1].variant_items == []
                assert len(queries) == 4
                queries.clear()
                complete = await list_models(category_id=1, skip=0, limit=200, include_details=True, db=db)
                assert len(complete.items) == 3 and len(queries) == 4
                assert await get_model_apps(1, db=db) == [{"id": 1, "name": "App"}]
                queries.clear()
                plain = await list_models(category_id=2, skip=0, limit=200, db=db)
                assert [row.id for row in plain.items] == [4]
                assert len(queries) == 2
                queries.clear()
                empty = await list_models(category_id=99, skip=0, limit=200, include_details=True, db=db)
                assert empty.total == 0 and empty.items == []
                assert len(queries) == 2
        finally:
            await engine.dispose()
    asyncio.run(run())
