import json
import io
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
async def test_old_excel_definition_preview_matches_template_applied_on_save(tmp_path, monkeypatch):
    client, sessions, engine, _ = await harness(tmp_path, monkeypatch)
    async with client:
        d = await create(client)
        path = f"/api/probes/workspaces/{d['id']}"
        exported = await client.get(path + '/export')
        async with sessions() as db:
            db.add(TemplateFeature(category_id=1, feature_id=1, default_support='conditional',
                default_excludes=json.dumps({'excludes':[], 'tender':['特殊应用']})))
            await db.commit()
        # Simulate a real workbook exported before tender columns existed.
        from openpyxl import load_workbook
        old_book = load_workbook(io.BytesIO(exported.content))
        for name in ['共同总集', '机型差异']:
            sheet = old_book[name]
            for index in range(sheet.max_column, 0, -1):
                if str(sheet.cell(1, index).value).endswith('_tender'):
                    sheet.delete_cols(index)
        old_bytes = io.BytesIO()
        old_book.save(old_bytes)
        preview = await client.post(path + '/import-preview', files={'file':('probes.xlsx',old_bytes.getvalue())})
        assert preview.status_code == 200, preview.text
        document = preview.json()['data']
        assert document['rows'][0]['defined_status'] == 'conditional'
        assert document['rows'][0]['defined_tender'] == ['特殊应用']
        saved = await save(client, d, document)
        assert saved['data'] == document
        workbook = await client.get(path + '/export')
        from openpyxl import load_workbook
        headers = [cell.value for cell in load_workbook(io.BytesIO(workbook.content))['机型结果'][1]]
        assert 'defined_tender' in headers
        assert 'current_tender' in headers
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


@pytest.mark.asyncio
async def test_template_supported_excludes_normalized_in_all_draft_paths(tmp_path, monkeypatch):
    client, sessions, engine, _ = await harness(tmp_path, monkeypatch)
    async with sessions() as db:
        db.add(TemplateFeature(category_id=1, feature_id=1, default_support='supported', default_excludes='["胎心","早孕","胎心"]'))
        await db.commit()
    async with client:
        d = await create(client)
        assert d['data']['rows'][0]['defined_status'] == 'conditional'
        viewed = (await client.get(f"/api/probes/workspaces/{d['id']}")).json()
        saved = await save(client, viewed, viewed['template_data'])
        assert saved['data'] == viewed['template_data']
        reloaded = (await client.get(f"/api/probes/workspaces/{d['id']}")).json()
        assert reloaded['template_changed'] is False
    await engine.dispose()


@pytest.mark.asyncio
async def test_published_total_refresh_proposes_draft_without_changing_snapshot(tmp_path, monkeypatch):
    from app.models.probe_workspace import ProbeWorkspace
    client, sessions, engine, _ = await harness(tmp_path, monkeypatch)
    async with client:
        d = await create(client)
        async with sessions() as db:
            item = await db.get(ProbeWorkspace, d['id'])
            item.published_data = json.dumps(d['data'])
            item.draft_data = None
            db.add(TemplateFeature(category_id=1, feature_id=1, default_support='supported'))
            await db.commit()
        path = f"/api/probes/workspaces/{d['id']}"
        normal = (await client.get(path)).json()
        assert 'template_data' not in normal
        proposed = (await client.get(path + '?refresh_template=true')).json()
        assert proposed['has_draft'] is False
        assert proposed['template_data']['rows'][0]['defined_status'] == 'supported'
        assert proposed['published_data'] == d['data']
        saved = await save(client, proposed, proposed['template_data'])
        assert saved['has_draft'] is True
        assert saved['published_data'] == d['data']
    await engine.dispose()
