import json
import pytest
from app.models.probe import TemplateFeature, TemplateDraft, Feature
from test_probe_workspace import harness, create, save


@pytest.mark.asyncio
async def test_probe_definition_uses_committed_template_preserves_current_and_model_differences(tmp_path, monkeypatch):
    client, sessions, engine, _ = await harness(tmp_path, monkeypatch)
    async with sessions() as db:
        db.add(TemplateFeature(category_id=1, feature_id=1, default_support='conditional',
                               default_excludes=json.dumps({'excludes': ['心脏'], 'tender': ['特殊应用']})))
        db.add(TemplateDraft(category_id=1, feature_id=1, new_support='unsupported'))
        await db.commit()
    async with client:
        d = await create(client)
        row = d['data']['rows'][0]
        assert row['defined_status'] == 'conditional'
        assert row['defined_excludes'] == ['心脏']
        assert row['defined_tender'] == ['特殊应用']
        assert row['current_status'] == 'pending'
        assert d['data']['overrides']['10']['1:1:1']['current_status'] == 'supported'
        assert d['data']['overrides']['10']['1:1:1']['priority'] == '标2'
        assert d['data']['template_revision']
    await engine.dispose()


@pytest.mark.asyncio
async def test_template_refresh_is_read_only_and_save_materializes_all_feature_columns(tmp_path, monkeypatch):
    client, sessions, engine, _ = await harness(tmp_path, monkeypatch)
    async with client:
        d = await create(client)
        original = d['data']
        async with sessions() as db:
            db.add(TemplateFeature(category_id=1, feature_id=1, default_support='supported'))
            db.add(Feature(id=2, group_id=1, name='新功能'))
            await db.commit()
        viewed = (await client.get(f"/api/probes/workspaces/{d['id']}")).json()
        assert viewed['data'] == original
        assert viewed['template_changed'] is True
        assert len(viewed['template_data']['rows']) == 2
        assert viewed['template_data']['rows'][0]['defined_status'] == 'supported'
        assert viewed['template_data']['rows'][1]['defined_status'] == 'unsupported'
        saved = await save(client, viewed, viewed['template_data'])
        assert len(saved['data']['rows']) == 2
        assert saved['data']['overrides'] == original['overrides']
        assert saved['published_data'] is None
    await engine.dispose()
