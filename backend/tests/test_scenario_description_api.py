"""Release evolution replaces the old model-summary query workflow."""
import sqlite3
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.integrations.release_workbench import create_integrated_workbench, mount_release_workbench, close_release_workbench

@pytest.fixture
def client(tmp_path, monkeypatch):
    canonical=tmp_path/'canonical.db'
    with sqlite3.connect(canonical) as connection:
        connection.execute('''CREATE TABLE knowledge_documents (
            id INTEGER PRIMARY KEY, title TEXT, document_type TEXT, file_path TEXT,
            version TEXT, market TEXT, product_series TEXT, sha256 TEXT, source_status TEXT)''')
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


@pytest.mark.parametrize('latest_matches, index_matches', [(True, True), (False, True), (True, False)])
def test_whitepaper_uses_latest_publication_in_same_model_and_market(
    client, monkeypatch, tmp_path, latest_matches, index_matches,
):
    import json

    connection, wb = client
    canonical = tmp_path / 'canonical.db'
    versioned_titles = [
        (66, '6S_白皮书 _1.51.80', '1.51.80', 'domestic', 'CN'),
        (107, '6S白皮书_1.51.90', '1.51.90', 'domestic', 'CN'),
        (108, '6S白皮书_1.51.100', '1.51.100', 'overseas', 'DE'),
        (109, '6S白皮书_1.51.110', '1.51.110', 'overseas', 'GB'),
    ]
    locations = {doc_id: tmp_path / f'{doc_id}.docx' for doc_id, *_ in versioned_titles}
    with sqlite3.connect(canonical) as registry:
        registry.execute("ALTER TABLE knowledge_documents ADD country TEXT")
        registry.execute("""CREATE TABLE knowledge_whitepaper_publication_sources (
            document_id INTEGER PRIMARY KEY, sha256 TEXT, provenance TEXT)""")
        for doc_id, title, version, market, country in versioned_titles:
            registry.execute("""INSERT INTO knowledge_documents
                (id, title, document_type, file_path, version, market, product_series, sha256, source_status, country)
                VALUES (?, ?, 'whitepaper', ?, ?, ?, 'ULTIMUS 6S', 'registered-bytes', 'active', ?)""",
                (doc_id, title, str(locations[doc_id]), version, market, country))
            if doc_id in (107, 109):
                registry.execute('INSERT INTO knowledge_whitepaper_publication_sources VALUES (?, ?, ?)',
                    (doc_id, 'registered-bytes', json.dumps({
                        'publication': 'controlled-release',
                        'scope': {'model_name': 'ULTIMUS 6S', 'market': market, 'country': country,
                                  'software_version': version},
                    })))

    hits = []
    for doc_id, title, version, market, country in versioned_titles[:2]:
        if doc_id == 107 and not latest_matches:
            continue
        source_id = f'canonical:{doc_id}:file'
        hits.append({'canonical_document_id': doc_id, 'version': version, 'title': title,
                     'preview_id': source_id, 'scope': '国内 · ULTIMUS 6S',
                     'detail_evidence': {'source_id': source_id, 'locator': '段落 235'}})
    pages = []
    def search(*args, **kwargs):
        pages.append(kwargs['page'])
        return {'results': hits, 'total': len(hits)}
    monkeypatch.setattr('tracker.app.unified_search', search)
    index = wb.extensions['tracker_search_index']
    monkeypatch.setattr(index, 'source_metadata', lambda _: {
        'file_sha256': 'registered-bytes' if index_matches else 'changed-bytes'})
    monkeypatch.setattr(index, 'source_path', lambda source_id: locations[int(source_id.split(':')[1])])
    monkeypatch.setattr('tracker.app.resolve_source_candidate',
                        lambda _, source_id, **kwargs: {'path': locations[int(source_id.split(':')[1])]})
    monkeypatch.setattr(index, 'preview', lambda source_id, **kwargs: {'locator_status': 'exact',
        'section': {'content': source_id, 'complete': True, 'locator': '段落 235'}})

    data = connection.get(BASE + '/scenario?project_id=1&task=whitepaper&q=VATT').json()['data']
    assert pages == [1]
    if latest_matches and index_matches:
        assert data['selected_document'] == 'canonical:107'
        assert data['section']['content'] == 'canonical:107:file'
    else:
        assert data['section'] is None
        assert data['documents'] == []
