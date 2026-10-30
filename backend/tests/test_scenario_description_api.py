from copy import deepcopy
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.integrations.release_workbench import create_integrated_workbench, mount_release_workbench, close_release_workbench


@pytest.fixture
def client(tmp_path, monkeypatch):
    canonical = tmp_path / 'canonical.db'
    sqlite3.connect(canonical).close()
    workbench = create_integrated_workbench({'TESTING': True, 'DATABASE_PATH': tmp_path / 'tracker.db',
        'PRODUCT_CONFIG_DATABASE': canonical, 'RELEASE_NOTE_ROOT': None, 'CONTROLLED_MATERIALS_ROOT': None,
        'TRAINING_ROOT': None, 'SOURCE_ROOTS': [], 'CONTROLLED_EXTRACTION_ROOTS': [], 'WORKBENCH_HOME': False})
    host = FastAPI()
    mount_release_workbench(host, workbench)
    evidence = {'selected_document': 'cn', 'models': {'selected':'model:6s'},
        'baseline': {'version':'1.51.80','detail_evidence': {'source_id':'controlled:1:docx','scope':'国内'}},
        'section': {'content':'VAid Liver 原始功能说明','locator':'5.23'}, 'later_changes': []}
    monkeypatch.setattr('tracker.app.feature_answer', lambda *args: deepcopy(evidence))
    monkeypatch.setattr('tracker.app.sync_search_roots_and_metadata', lambda *args, **kwargs: {})
    calls = []
    def generate(payload):
        calls.append(payload)
        return {'paragraphs':[{'text':'VAid Liver 整理后的说明','citations':[{'id':'baseline','quote':'原始功能说明'}]}], 'unresolved':[]}, {'total_tokens':55}
    monkeypatch.setattr(workbench.extensions['description_model'], 'generate', generate)
    try:
        with TestClient(host) as connection:
            yield connection, evidence, calls, workbench
    finally:
        close_release_workbench(workbench)


BASE = '/release-workbench/api/v1/workbench'


def query(client):
    response = client.post(BASE + '/scenario?project_id=1', json={'task':'feature','q':'VAid Liver'})
    assert response.status_code == 200, response.text
    return response.json()['data']['description']


def body(description, content):
    return {**description['context'], 'content':content, 'revision':description['revision'],
            'source_fingerprint':description['source_fingerprint']}


def test_mounted_model_settings_private_and_feature_edits_roundtrip_without_model_calls(client):
    connection, evidence, calls, wb = client
    original = query(connection)
    assert original['status'] == 'unconfigured' and calls == []
    configured = connection.put(BASE + '/model-settings', json={'provider':'deepseek','model':'deepseek-flash', 'api_key':'synthetic-private'})
    assert configured.status_code == 200
    assert 'synthetic-private' not in configured.text
    assert 'synthetic-private' not in connection.get(BASE + '/model-settings').text
    automatic = query(connection)
    assert automatic['content'] == 'VAid Liver 整理后的说明'
    assert len(calls) == 1
    assert query(connection)['status'] == 'ready'
    assert len(calls) == 1
    response = connection.put(BASE + '/scenario/feature-description?project_id=1', json=body(automatic,'手工说明'))
    assert response.status_code == 200, response.text
    assert response.json()['data']['revision'] == 1
    assert len(calls) == 1
    assert query(connection)['content'] == '手工说明'
    assert len(calls) == 1
    stale = connection.put(BASE + '/scenario/feature-description?project_id=1', json=body(automatic,'另一窗口旧稿'))
    assert stale.status_code == 400
    assert '修订' in stale.json()['error']['message']


def test_source_changed_save_is_rejected_and_does_not_call_model(client):
    connection, evidence, calls, wb = client
    original = query(connection)
    evidence['section']['content'] += ' 新版限制'
    response = connection.put(BASE + '/scenario/feature-description?project_id=1', json=body(original,'手工说明'))
    assert response.status_code == 400 and '资料' in response.json()['error']['message']
    assert calls == []


def test_settings_and_edits_require_json_and_invalid_fields_cannot_write(client):
    connection, evidence, calls, wb = client
    assert connection.put(BASE + '/model-settings', data={'provider':'openai'}).status_code == 415
    assert connection.put(BASE + '/scenario/feature-description', content='text').status_code == 415
    assert connection.put(BASE + '/model-settings', json={'provider':'bad'}).status_code == 400
    assert connection.put(BASE + '/model-settings', json={'model':{}}).status_code == 400
    assert connection.put(BASE + '/scenario/feature-description', json={'q':{}}).status_code == 400
    assert connection.put(BASE + '/scenario/feature-description?project_id=9999', json={'q':'VAid Liver'}).status_code == 404


def test_schema_migration_is_idempotent_and_revision_history_is_preserved(client):
    connection, evidence, calls, wb = client
    original = query(connection)
    saved = connection.put(BASE + '/scenario/feature-description?project_id=1', json=body(original,'第一次修订')).json()['data']
    connection.put(BASE + '/scenario/feature-description?project_id=1', json=body(saved,'第二次修订'))
    db = wb.extensions['tracker_database']
    db.initialize()
    assert query(connection)['content'] == '第二次修订'
    with db.connect() as sql:
        assert sql.execute('SELECT COUNT(*) FROM scenario_description_revisions').fetchone()[0] == 2
        assert sql.execute('SELECT COUNT(*) FROM schema_migrations WHERE version=15').fetchone()[0] == 1


def test_read_only_get_cannot_trigger_paid_generation(client):
    connection, evidence, calls, wb = client
    connection.put(BASE + '/model-settings', json={'provider':'deepseek','model':'deepseek-flash','api_key':'synthetic'})
    response = connection.get(BASE + '/scenario', params={'task':'feature','q':'VAid Liver'})
    assert response.status_code == 200
    assert calls == []
    assert connection.post(BASE + '/scenario', data={'task':'feature','q':'VAid Liver'}).status_code == 415
    query(connection)
    assert len(calls) == 1


def test_release_baseline_survives_query_context_and_manual_save(client, monkeypatch):
    connection, evidence, calls, workbench = client
    whitepaper = {'baseline':None,'section':None,'documents':[{'value':'35'}], 'selected_document':'35','section_options':[],'models':{'selected':'model:6s','options':[]}}
    def search_whitepaper(db,project,q,model,search,preview,target,document,section):
        return {**whitepaper,'selected_document':'' if document.startswith('release-project:') else '35'}
    release = {**deepcopy(evidence),'selected_document':'release-project:1:cn'}
    monkeypatch.setattr('tracker.app.feature_answer', search_whitepaper)
    monkeypatch.setattr('tracker.app.release_feature_answer', lambda *args: deepcopy(release))
    first = query(connection)
    assert first['context']['document'] == 'release-project:1:cn'
    again = connection.post(BASE+'/scenario?project_id=1', json={'task':'feature',**first['context']})
    assert again.json()['data']['description'] is not None
    saved = connection.put(BASE+'/scenario/feature-description?project_id=1',json=body(first,'Release Note 手工修订'))
    assert saved.status_code == 200
    assert saved.json()['data']['content']=='Release Note 手工修订'
    assert calls==[]
