import sqlite3
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_feature_name_reviews import setup as name_setup
from app.database import Base
from test_feature_name_standards_api import _upload,_standard_table_bytes
from app.services.feature_standard_sync import sync_all_standard_names

async def setup(tmp_path):
    path,client,engine=await name_setup(tmp_path)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.tables['feature_display_names'].create)
    return path,client,engine

@pytest.mark.asyncio
async def test_sync_includes_unflagged_names_preserves_aliases_links_and_records_unchanged_checks(tmp_path):
    path,client,engine=await setup(tmp_path)
    async with client:
        await client.post('/api/features/standards/import',files=_upload(_standard_table_bytes([
            ('组织多普勒成像','Tissue Doppler Imaging','TDI'),('超微细血流成像','SMF','SMF')])))
        assert '7' not in (await client.get('/api/features/standards/flags')).json()['by_feature']
        with sqlite3.connect(path) as db:before=db.execute('select * from feature_config_item_links').fetchall()
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async with factory() as db:result=await sync_all_standard_names(db)
        assert {row['feature_id'] for row in result['checked']} >= {1,7}
        with sqlite3.connect(path) as db:
            assert db.execute('select primary_en_name from features where id=7').fetchone()[0]=='SMF'
            assert db.execute('select * from feature_config_item_links').fetchall()==before
            assert db.execute("select count(*) from feature_name_reviews where feature_id in(1,7)").fetchone()[0]==2
    await engine.dispose()

@pytest.mark.asyncio
async def test_display_name_can_mix_languages_without_changing_standard_primary_names(tmp_path):
    path,client,engine=await setup(tmp_path)
    async with client:
        result=await client.put('/api/features/standards/reviews/1/display-name',json={'name':'TDI'})
        assert result.status_code==200,result.text
        assert result.json()['display_name']=='TDI'
        with sqlite3.connect(path) as db:
            assert db.execute('select primary_cn_name from features where id=1').fetchone()[0]=='组织多普勒成像'
        flags=(await client.get('/api/features/standards/flags')).json()
        assert flags['checks_by_feature']['1']['feature_display_name']=='TDI'
        cleared=await client.put('/api/features/standards/reviews/1/display-name',json={'name':''})
        assert cleared.status_code==200 and cleared.json()['display_name']==''
    await engine.dispose()
