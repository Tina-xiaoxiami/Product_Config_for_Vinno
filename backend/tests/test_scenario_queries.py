from tracker.services.scenario_queries import probe_answer, feature_answer, version_answer

class Data:
    def list_probe_versions(self):
        return [{'probe_model':'F4-9E','probe_code':'V20064','series_code':'V10','state':'discontinued','software_version':'1.14.80'},
                {'probe_model':'F4-9E','probe_code':'V20131','series_code':'V10','state':'added','software_version':'1.14.80'}]
    def search_release_history(self, query, project_id=None, **kwargs):
        if project_id == 1:
            return {'results': []}
        return {'results':[{'preview_id':'release:table:1','version':'1.14.80','matched_text':'V10系列 | F4-9E | V20064 | 下架，升级为V20131'},
                           {'preview_id':'release:table:2','version':'1.14.80','matched_text':'V10系列 | F4-9E | V20131 | 新增'}]}
    def list_releases(self, project):
        return [{'id':1,'version':'1.51.9'}, {'id':2,'version':'1.51.10'}, {'id':3,'version':'1.51.11'}]
    def list_changes(self, rid):
        return [{'id':1, 'category':'function','title_cn':'子宫畸形分类','description_cn':'修正说明','review_status':'approved'}] if rid == 3 else []

def test_probe_identity_and_explicit_added():
    db=Data()
    assert len(probe_answer(db, 2, 'F4-9E')['identities']) == 2
    assert not probe_answer(db, 1, 'V20131')['identities']
    result=probe_answer(db, 2, 'F4-9E', 'V20131', 'V10')
    assert result['evidence']['preview_id'] == 'release:table:2'
    assert probe_answer(db, 2, 'F4-9E', 'V20064', 'V10')['evidence'] is None
    assert probe_answer(db, 2, 'F4-9E', 'V20131', 'V9')['evidence'] is None

def test_feature_pagination_full_section_and_later_changes():
    def search(page, model):
        version = '1.51.9' if page == 1 else '1.51.10'
        return {'total':2, 'page_size':1, 'results':[{'_scenario_document_id':'1','version':version,'detail_evidence':{'source_id':version,'locator':'p1'},'is_stale':False}], 'whitepaper_models':{'selected':'model:6s','options':[]}, 'source_errors':{}}
    def preview(source, locator, query):
        return {'stale':False,'locator_status':'exact','section':{'complete':True,'content':source+' complete'}}
    result=feature_answer(Data(),1,'子宫畸形分类','',search,preview)
    assert result['baseline']['version'] == '1.51.10'
    assert result['section']['content'] == '1.51.10 complete'
    assert result['later_changes'][0]['version'] == '1.51.11'

def test_version_unknown_does_not_fallback():
    result=version_answer(Data(),1,'9.0.0','',lambda a,b: {})
    assert result['target'] is None
    assert '1.51.10' in result['versions']


def test_newer_unresolved_or_unversioned_candidate_cannot_be_called_latest():
    def search(page, model):
        return {'total':3, 'page_size':100, 'results':[
            {'_scenario_document_id':'1','version':'1.51.10','detail_evidence':{'source_id':'new','locator':'p'}},
            {'_scenario_document_id':'1','version':'1.51.9','detail_evidence':{'source_id':'old','locator':'p'}},
            {'_scenario_document_id':'1','version':'','detail_evidence':{'source_id':'unknown','locator':'p'}}],
            'whitepaper_models':{'selected':'model:6s','options':[]}, 'source_errors':{}}
    def preview(source, locator, query):
        return {'stale':False,'locator_status':'exact','section':{'complete':source == 'old','content':'完整'}}
    result=feature_answer(Data(),1,'子宫畸形分类','',search,preview)
    assert result['baseline']['version'] == '1.51.9'
    assert not result['latest_certified']
    assert result['unresolved_candidates'] == 2


def test_mounted_scenario_endpoint_uses_requested_project(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.integrations.release_workbench import create_integrated_workbench, mount_release_workbench, close_release_workbench
    import sqlite3
    canonical = tmp_path / 'canonical.db'
    sqlite3.connect(canonical).close()
    wb = create_integrated_workbench({'TESTING': True, 'DATABASE_PATH': tmp_path / 'tracker.db',
        'PRODUCT_CONFIG_DATABASE': canonical, 'RELEASE_NOTE_ROOT': None, 'CONTROLLED_MATERIALS_ROOT': None,
        'TRAINING_ROOT': None, 'SOURCE_ROOTS': [], 'CONTROLLED_EXTRACTION_ROOTS': [], 'WORKBENCH_HOME': False})
    app = FastAPI()
    mount_release_workbench(app, wb)
    try:
        db = wb.extensions['tracker_database']
        db.upsert_release('1.51.80')
        with TestClient(app) as client:
            base = '/release-workbench/api/v1/workbench/scenario'
            response = client.get(base, params={'task':'version','target':'1.51.80','project_id':1})
            assert response.status_code == 200
            assert response.json()['data']['target']['version'] == '1.51.80'
            assert client.get(base, params={'task':'version','target':'9.0.0','project_id':1}).json()['data']['target'] is None
            assert client.get(base, params={'task':'probe','q':'','project_id':1}).status_code == 400
    finally:
        close_release_workbench(wb)


def test_documents_with_unproven_shared_scope_require_selection():
    def search(page, model):
        return {'total':2,'page_size':100,'whitepaper_models':{},'source_errors':{},'results':[
            {'_scenario_document_id':'cn','title':'中文资料','version':'1.51.80','detail_evidence':{'source_id':'cn'}},
            {'_scenario_document_id':'en','title':'English','version':'1.51.90','detail_evidence':{'source_id':'en'}}]}
    def preview(source, locator, query):
        return {'stale':False,'locator_status':'exact','section':{'complete':True,'content':source}}
    answer=feature_answer(Data(),1,'子宫畸形分类','',search,preview)
    assert answer['baseline'] is None and len(answer['documents']) == 2
    answer=feature_answer(Data(),1,'子宫畸形分类','',search,preview,document='cn')
    assert answer['baseline']['version'] == '1.51.80'


def test_same_version_conflicting_sections_need_explicit_selection():
    def search(page, model):
        return {'total':2,'page_size':100,'whitepaper_models':{},'source_errors':{},'results':[
            {'_scenario_document_id':'1','version':'1.51.80','detail_evidence':{'source_id':'a','locator':'1'}},
            {'_scenario_document_id':'1','version':'1.51.80','detail_evidence':{'source_id':'b','locator':'2'}}]}
    def preview(source, locator, query):
        return {'stale':False,'locator_status':'exact','section':{'complete':True,'content':source,'locator':locator}}
    answer=feature_answer(Data(),1,'子宫畸形分类','',search,preview)
    assert answer['baseline'] is None and len(answer['section_options']) == 2
    answer=feature_answer(Data(),1,'子宫畸形分类','',search,preview,section_choice='b|2')
    assert answer['section']['content'] == 'b' and not answer['latest_certified']


def test_later_unreviewed_snapshot_is_shown_as_clue():
    class Evidence(Data):
        def search_release_history(self, query, project_id=None, **kwargs):
            return {'results':[{'version':'1.51.11','evidence_kind':'pending','preview_id':'release:candidate:3', 'matched_text':'待审核变化'},
                               {'version':'1.51.11','evidence_kind':'source_snapshot','preview_id':'release:source:4', 'locator':'原文行 3'}]}
    def search(page, model):
        return {'total':1,'page_size':100,'whitepaper_models':{},'source_errors':{},'results':[{'_scenario_document_id':'1','version':'1.51.10','detail_evidence':{'source_id':'a'}}]}
    def preview(*args):
        return {'stale':False,'locator_status':'exact','section':{'complete':True,'content':'正文'}}
    answer=feature_answer(Evidence(),1,'子宫畸形分类','',search,preview)
    assert [item['evidence_type'] for item in answer['later_changes']].count('clue') == 2


def test_same_version_word_boundaries_are_not_discarded():
    def search(page, model):
        return {'total': 2, 'whitepaper_models': {}, 'source_errors': {}, 'results': [
            {'_scenario_document_id': '1', 'version': '1.51.80',
             'detail_evidence': {'source_id': source, 'locator': '1'}}
            for source in ('a', 'b')]}

    def preview(source, locator, query):
        return {'locator_status': 'exact', 'section': {
            'complete': True, 'locator': locator,
            'content': 'supports A B' if source == 'a' else 'supports AB'}}

    answer = feature_answer(Data(), 1, 'feature', '', search, preview)
    assert answer['baseline'] is None
    assert len(answer['section_options']) == 2
    assert not answer['latest_certified']


def test_later_change_review_status_is_preserved():
    class Evidence(Data):
        def list_changes(self, rid):
            return [{'id': i, 'title_cn': 'feature', 'review_status': status}
                    for i, status in enumerate(('approved', 'pending', 'rejected', None))] if rid == 3 else []

        def search_release_history(self, query, project_id=None, **kwargs):
            return {'results': []}

    def search(page, model):
        return {'total': 1, 'whitepaper_models': {}, 'source_errors': {}, 'results': [
            {'_scenario_document_id': '1', 'version': '1.51.10',
             'detail_evidence': {'source_id': 'a'}}]}

    def preview(*args):
        return {'locator_status': 'exact', 'section': {'complete': True, 'content': 'feature'}}

    answer = feature_answer(Evidence(), 1, 'feature', '', search, preview)
    assert [(item['id'], item['evidence_type']) for item in answer['later_changes']] == [
        (0, 'record'), (1, 'clue'), (3, 'clue')]
