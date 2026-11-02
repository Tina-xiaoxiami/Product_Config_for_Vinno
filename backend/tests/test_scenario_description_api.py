"""Release evolution replaces the old model-summary query workflow."""
import sqlite3
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.integrations.release_workbench import create_integrated_workbench, mount_release_workbench, close_release_workbench

@pytest.fixture
def client(tmp_path, monkeypatch):
    canonical=tmp_path/'canonical.db'; sqlite3.connect(canonical).close()
    wb=create_integrated_workbench({'TESTING':True,'DATABASE_PATH':tmp_path/'tracker.db','PRODUCT_CONFIG_DATABASE':canonical,'RELEASE_NOTE_ROOT':None,'CONTROLLED_MATERIALS_ROOT':None,'TRAINING_ROOT':None,'SOURCE_ROOTS':[],'CONTROLLED_EXTRACTION_ROOTS':[],'WORKBENCH_HOME':False})
    host=FastAPI();mount_release_workbench(host,wb)
    def forbidden(*a,**k):raise AssertionError('model must never run')
    monkeypatch.setattr(wb.extensions['description_model'],'generate',forbidden)
    monkeypatch.setattr('tracker.app.sync_search_roots_and_metadata',lambda *a,**k:{})
    try:
        with TestClient(host) as connection:yield connection,wb
    finally:close_release_workbench(wb)

BASE='/release-workbench/api/v1/workbench'

def test_release_query_never_uses_whitepaper_or_model_and_forwards_target(client,monkeypatch):
    connection,wb=client
    def evolution(db,project,query,target):
        assert query=='VATT' and project==1 and target=='1.51.90'
        return {'content':'起始完整内容\n新增支持连续测量','baseline':{'version':'1.51.20','content':'起始完整内容'},'applied_changes':[{'version':'1.51.90'}]}
    monkeypatch.setattr('tracker.app.release_evolution_answer',evolution)
    monkeypatch.setattr('tracker.app.feature_answer',lambda *a,**k:pytest.fail('whitepaper leaked'))
    for response in [connection.get(BASE+'/scenario?project_id=1&task=feature&q=VATT&target=1.51.90'),connection.post(BASE+'/scenario?project_id=1',json={'task':'feature','q':'VATT','target':'1.51.90'})]:
        assert response.status_code==200,response.text
        assert response.json()['data']['content'].startswith('起始完整内容')
        assert 'description' not in response.json()['data']

def test_whitepaper_is_independent_no_release_fallback_or_model(client,monkeypatch):
    connection,wb=client
    monkeypatch.setattr('tracker.app.feature_answer',lambda *a,**k:{'baseline':None,'section':None})
    monkeypatch.setattr('tracker.app.release_evolution_answer',lambda *a,**k:pytest.fail('release leaked'))
    response=connection.get(BASE+'/scenario?project_id=1&task=whitepaper&q=VATT')
    assert response.status_code==200,response.text
    assert response.json()['data']['baseline'] is None
    assert response.json()['data']['description'] is None

def test_old_summary_edit_is_retired_and_settings_remain_private(client):
    connection,wb=client
    response=connection.put(BASE+'/scenario/feature-description?project_id=1',json={'q':'VATT','content':'old summary'})
    assert response.status_code==410
    assert connection.put(BASE+'/scenario/feature-description',content='text').status_code==415
    assert connection.put(BASE+'/model-settings',json={'provider':'deepseek','model':'deepseek-chat','api_key':'synthetic-private'}).status_code==200
    assert 'synthetic-private' not in connection.get(BASE+'/model-settings').text

def test_whitepaper_excludes_older_hits_when_latest_registered_version_does_not_match(client,monkeypatch):
    connection,wb=client;db=wb.extensions['tracker_database']
    monkeypatch.setattr(db,'list_documents',lambda:[{'id':9,'title':'6S白皮书'}])
    monkeypatch.setattr(db,'list_document_versions',lambda doc:[{'id':1,'version_label':'1.51.9'},{'id':2,'version_label':'1.51.10'}])
    monkeypatch.setattr('tracker.app.unified_search',lambda *a,**k:{'results':[{'document_version_id':1,'version':'1.51.9'}],'total':1})
    def check(db,project,query,model,search,*a):
        assert search(1,'')['results']==[]
        return {'baseline':None,'section':None}
    monkeypatch.setattr('tracker.app.feature_answer',check)
    response=connection.get(BASE+'/scenario?project_id=1&task=whitepaper&q=VATT')
    assert response.status_code==200,response.text


def test_whitepaper_uses_existing_title_version_when_label_is_empty(client,monkeypatch):
    connection,wb=client;db=wb.extensions['tracker_database']
    monkeypatch.setattr(db,'list_documents',lambda:[{'id':9,'title':'6S白皮书_1.51.80'}])
    monkeypatch.setattr(db,'list_document_versions',lambda doc:[{'id':1,'version_label':''}])
    monkeypatch.setattr('tracker.app.unified_search',lambda *a,**k:{'results':[{'document_version_id':1,'version':'1.51.80'}],'total':1})
    def check(db,project,query,model,search,*a):
        assert len(search(1,'')['results'])==1
        return {'baseline':None,'section':None}
    monkeypatch.setattr('tracker.app.feature_answer',check)
    assert connection.get(BASE+'/scenario?project_id=1&task=whitepaper&q=VATT').status_code==200
