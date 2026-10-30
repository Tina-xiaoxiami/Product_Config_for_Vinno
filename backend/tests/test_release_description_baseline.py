from tracker.services.scenario_queries import release_feature_answer

class Data:
    def search_release_history(self, *args, **kwargs):
        return {'results':[{'preview_id':'release:source:34','version':'1.14.80'}, {'preview_id':'release:source:35','version':'1.14.80'}]}
    def list_releases(self, project): return []

def test_release_baseline_requires_full_matching_heading_and_retains_language(monkeypatch):
    sections={34:[{'complete':True,'title':'新增膈肌活动度自动测量Auto DE','content':'Auto DE完整说明及限制','locator':'原文行 126'}, {'complete':True,'title':'配置表','content':'表中提及Auto DE','locator':'原文行 5'}],35:[{'complete':True,'title':'Added Auto DE','content':'English description','locator':'原文行 30'}]}
    monkeypatch.setattr('tracker.services.scenario_queries.source_sections',lambda db,sid:sections[sid])
    monkeypatch.setattr('tracker.services.scenario_queries.release_evidence',lambda db,sid,locator,**kwargs: {'section':next(s for s in sections[int(sid.split(':')[-1])] if s['locator']==locator),'locator_status':'exact'})
    db=Data()
    monkeypatch.setattr('tracker.services.scenario_queries._release_source_language',lambda db,sid,project:'cn' if sid==34 else 'en')
    result=release_feature_answer(db,2,'Auto DE','model:vinno 10')
    assert result['baseline']['version']=='1.14.80'
    assert result['section']['content']=='Auto DE完整说明及限制'
    assert result['baseline']['detail_evidence']['source_id']=='release:source:34'
    assert '范围待核对' in result['baseline']['scope']

def test_release_mentions_without_complete_matching_section_cannot_be_baseline(monkeypatch):
    monkeypatch.setattr('tracker.services.scenario_queries.source_sections',lambda *args:[{'complete':True,'title':'配置支持列表','content':'Auto DE'}])
    db=Data();monkeypatch.setattr('tracker.services.scenario_queries._release_source_language',lambda *args:'cn')
    assert release_feature_answer(db,2,'Auto DE','model:vinno 10')['baseline'] is None

def test_future_release_baseline_not_used_for_earlier_target(monkeypatch):
    monkeypatch.setattr('tracker.services.scenario_queries.source_sections',lambda *args:[{'complete':True,'title':'Auto DE','content':'完整说明','locator':'原文行 1'}])
    monkeypatch.setattr('tracker.services.scenario_queries._release_source_language',lambda *args:'cn')
    assert release_feature_answer(Data(),2,'Auto DE','',target_version='1.14.70')['baseline'] is None

def test_release_fallback_distinguishes_missing_content_from_pending_choices():
    from tracker.services.scenario_queries import release_fallback_allowed
    selected = {'baseline':None,'documents':[{'value':'35'}],'selected_document':'35','section_options':[]}
    assert release_fallback_allowed(selected)
    assert not release_fallback_allowed({**selected,'selected_document':''})
    assert not release_fallback_allowed({**selected,'section_options':[{'value':'choice'}]})
    assert not release_fallback_allowed({**selected,'baseline':{'version':'1.51.80'}})
