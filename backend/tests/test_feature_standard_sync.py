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

from app.services.feature_standard_sync import plan_standard_sync

def source(fid,name,cn,en,linked=()):
    return {'id':fid,'legacy_name':name,'cn_name':cn,'en_name':en,'names_cn':[],'names_en':[],
            'primary_links':[],'identity_names':list(linked)}

def test_sync_preserves_plus_identity_and_does_not_assign_auto_to_unrelated_auto_av():
    standards=[{'cn_name':'脉搏波定量分析','en_name':'PWV'}, {'cn_name':'超快脉搏波定量分析','en_name':'PWV+'}, {'cn_name':'自动优化','en_name':'Auto'}]
    features={1:source(1,'PWV','脉搏波定量分析','PWV'),
              2:source(2,'PWV+超快脉搏波定量分析技术','PWV+超快脉搏波定量分析技术','Ultra frame PWV+',['Pulse Wave Velocity(PWV)']),
              3:source(3,'主动脉瓣自动测量','主动脉瓣自动测量','Auto AV')}
    plan=plan_standard_sync(standards,features)
    assert [(row['feature_id'],row['en']) for row in plan['checked']]==[(1,'PWV'),(2,'PWV+')]
    assert [row['feature_id'] for row in plan['skipped']]==[3]

def test_multiple_ipn_versions_share_a_name_without_merging_and_conflicting_definitions_are_skipped():
    features={1:source(1,'CBI微泡造影成像','CBI微泡造影成像','Contrast imaging'),2:source(2,'常规造影','CBI微泡造影成像','Contrast imaging')}
    plan=plan_standard_sync([{'cn_name':'造影成像','en_name':'CBI'}],features)
    assert [row['feature_id'] for row in plan['checked']]==[1,2]
    conflicting=plan_standard_sync([{'cn_name':'名称1','en_name':'Contrast imaging'},{'cn_name':'名称2','en_name':'Contrast imaging'}],features)
    assert not conflicting['checked'] and len(conflicting['skipped'])==2

def test_batch_never_collapses_dimension_or_version_parentheses():
    for wrong,right in [('Strain(3D)','Strain(2D)'),('Analysis(V2)','Analysis(V1)')]:
        plan=plan_standard_sync([{'cn_name':'标准功能','en_name':right}],{1:source(1,wrong,wrong,wrong)})
        assert not plan['checked']

def test_plus_variant_cannot_fall_back_to_a_nonplus_rd_alias():
    plan=plan_standard_sync([{'cn_name':'脉搏波定量分析','en_name':'PWV'}],{1:source(1,'PWV+超快功能','超快功能','Ultra frame PWV+',['PWV'])})
    assert not plan['checked']

import subprocess
import sys
from pathlib import Path

@pytest.mark.asyncio
@pytest.mark.parametrize('alias',['same','symlink','hardlink'])
async def test_sync_cli_refuses_report_over_source_database(tmp_path,alias):
    path,client,engine=await setup(tmp_path)
    await client.aclose();await engine.dispose()
    report=path
    if alias=='symlink':
        report=tmp_path/'report.json';report.symlink_to(path)
    elif alias=='hardlink':
        import os
        report=tmp_path/'report.json';os.link(path,report)
    before=path.read_bytes()
    script=Path(__file__).resolve().parents[1]/'scripts/sync_feature_standard_names.py'
    result=subprocess.run([sys.executable,str(script),'--database',str(path),'--report',str(report)],capture_output=True,text=True)
    assert result.returncode != 0
    assert path.read_bytes()==before
