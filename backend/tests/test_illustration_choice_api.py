from copy import deepcopy
from test_scenario_description_api import client, BASE


def test_role_choice_api_is_source_scoped_and_does_not_edit_description(client, monkeypatch):
    connection,wb=client
    raw={'baseline':{'version':'1.0.0','content':'正文原文'},'content':'正文原文','timeline':[],'unresolved_changes':[],'applied_changes':[],
         'illustrations':[{'source_id':'release:source:40','locator':'原文行 72','version':'1.51.90','section':{'blocks':[
             {'type':'image','image_hash':'a'*64,'comparison_role':'unknown','data_url':'data:image/png;base64,AA=='},
             {'type':'image','image_hash':'b'*64,'comparison_role':'unknown','data_url':'data:image/png;base64,AQ=='}]}}]}
    monkeypatch.setattr('tracker.app.release_evolution_answer',lambda *a,**k:deepcopy(raw))
    url=BASE+'/scenario?project_id=1&task=feature&q=VATT'
    initial=connection.get(url).json()['data'];selection=initial['illustrations'][0]['selection']
    payload={'q':'VATT','target':'','source_id':'release:source:40','locator':'原文行 72','image_hash':'b'*64,'selection_revision':0,'selection_fingerprint':selection['source_fingerprint']}
    endpoint=BASE+'/scenario/illustrations/select?project_id=1'
    result=connection.put(endpoint,json=payload)
    assert result.status_code==200,result.text
    answer=result.json()['data']
    assert answer['content']=='正文原文' and answer['review']['revision']==0
    assert answer['illustrations'][0]['section']['blocks'][1]['display_role']=='after'
    assert connection.get(url).json()['data']['illustrations'][0]['selection']['revision']==1
    assert connection.put(endpoint,json=payload).status_code==409
    assert connection.put(endpoint,json={**payload,'source_id':'release:source:99'}).status_code==400
    assert connection.put(endpoint,content='plain').status_code==415
    raw['illustrations'][0]['section']['blocks'][0]['image_hash']='c'*64
    assert connection.put(endpoint,json={**payload,'selection_revision':1}).status_code==409
