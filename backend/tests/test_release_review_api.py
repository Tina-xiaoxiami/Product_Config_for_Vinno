from copy import deepcopy
import pytest
from test_scenario_description_api import client, BASE

@pytest.fixture
def review_client(client,monkeypatch):
    raw={'baseline':{'version':'1.0.0','source_id':'release:source:1','content':'原始完整说明'},'content':'原始完整说明','timeline':[], 'applied_changes':[], 'unresolved_changes':[{'version':'1.1.0','source_id':'release:change:2','locator':'中文记录','text':'新增一条','reason':'需核对'}]}
    monkeypatch.setattr('tracker.app.release_evolution_answer',lambda *a,**k:deepcopy(raw))
    return client[0],raw

def data(response):
    assert response.status_code==200,response.text
    return response.json()['data']

def test_read_save_refresh_history_restore_and_conflict(review_client):
    client,raw=review_client
    first=data(client.get(BASE+'/scenario?project_id=1&task=feature&q=VATT'))
    review=first['review']
    body={'q':'VATT','target':'','revision':0,'source_fingerprint':review['source_fingerprint'],'content':'修改后的正文','decisions':[{'id':first['unresolved_changes'][0]['id'],'action':'include'}]}
    saved=data(client.put(BASE+'/scenario/review?project_id=1',json=body))
    assert saved['content']=='修改后的正文' and saved['unresolved_changes']==[]
    assert data(client.get(BASE+'/scenario?project_id=1&task=feature&q=VATT'))['review']['revision']==1
    assert client.put(BASE+'/scenario/review?project_id=1',json=body).status_code==409
    history=data(client.get(BASE+'/scenario/review-history?project_id=1&q=VATT'))['history']
    assert [row['revision'] for row in history]==[1,0]
    restored=data(client.post(BASE+'/scenario/review/restore?project_id=1',json={**body,'revision':1,'restore_revision':0}))
    assert restored['content']==raw['baseline']['content'] and len(restored['unresolved_changes'])==0
    assert restored['review']['revision']==2
    raw['content']='来源已更新'
    stale=data(client.get(BASE+'/scenario?project_id=1&task=feature&q=VATT'))
    assert stale['review']['stale'] and stale['content']==raw['baseline']['content']
    assert client.put(BASE+'/scenario/review?project_id=1',json={**body,'revision':2}).status_code==409

def test_json_validation_and_scope(review_client):
    client,_=review_client
    assert client.put(BASE+'/scenario/review',content='plain').status_code==415
    assert client.put(BASE+'/scenario/review?project_id=1',json={'q':{}}).status_code==400
    assert client.get(BASE+'/scenario/review-history?project_id=9999&q=VATT').status_code==404
    assert client.post(BASE+'/scenario/review/restore?project_id=1',json={'q':'VATT','target':{},'revision':0}).status_code==400

def test_adopt_only_changes_log_and_body_restore_preserves_it(review_client):
    client,raw=review_client
    first=data(client.get(BASE+'/scenario?project_id=1&task=feature&q=VATT'))
    body={'q':'VATT','target':'','revision':0,'source_fingerprint':first['review']['source_fingerprint'],
          'content':first['content'],'decisions':[{'id':first['unresolved_changes'][0]['id'],'action':'adopt'}]}
    adopted=data(client.put(BASE+'/scenario/review?project_id=1',json=body))
    assert adopted['content']==raw['baseline']['content']
    assert adopted['review']['body_revision']==0 and adopted['review']['log_revision']==1
    assert [row['revision'] for row in data(client.get(BASE+'/scenario/review-history?project_id=1&q=VATT'))['history']]==[0]
    restored=data(client.post(BASE+'/scenario/review/restore?project_id=1',json={**body,'revision':1,'restore_revision':0,'kind':'body'}))
    assert restored['review']['decisions']==adopted['review']['decisions']
    assert restored['review']['body_revision']==0
