"""Probe releases share configuration publication and preserve model differences."""
import pytest
import json
import io
from sqlalchemy import select, func
from openpyxl import load_workbook
from app.models import ConfigItem, ConfigValue, ConfigVersion
from app.models.probe import ProbeCategory, ProbeModel, ProbeModelVariant, FeatureGroup, Feature, ProductProbeConfig
from app.api import probe_config
from test_draft_safety import _draft_harness, _seed_catalog


@pytest.mark.asyncio
async def test_legacy_probe_write_cannot_bypass_release_workspace(tmp_path):
    client, sessions, engine = await _draft_harness(tmp_path)
    await _seed_catalog(sessions)
    client._transport.app.include_router(probe_config.router, prefix='/api/probes/config')
    async with client:
        response = await client.put('/api/probes/config/series-feature', json={
            'target_model_ids': [10], 'probe_model_id': 1, 'feature_id': 1,
            'defined_status': 'supported', 'current_status': 'supported',
        })
    assert response.status_code == 409, response.text
    assert '草稿' in response.json()['detail']
    await engine.dispose()


async def harness(tmp_path, monkeypatch):
    from app.api import probe_workspace
    client, sessions, engine = await _draft_harness(tmp_path)
    await _seed_catalog(sessions)
    source = tmp_path / 'subseries.json'
    source.write_text(json.dumps({'sub_series': [
        {'name': 'V10', 'series': 'V Series', 'models': ['V10', 'V11']},
        {'name': 'Other', 'series': 'Other Series', 'models': ['X1']},
    ], 'sub_series_combinations': [
        {'name': 'Together', 'sub_series': ['V10', 'Other']},
    ]}))
    monkeypatch.setenv('WHITEPAPER_SUBSERIES_FILE', str(source))
    client._transport.app.include_router(probe_workspace.router, prefix='/api/probes/workspaces')
    async with sessions() as db:
        db.add_all([
            ProbeCategory(id=1, name='凸阵'), ProbeModel(id=1, category_id=1, model_number='P1'),
            ProbeModelVariant(id=1, probe_model_id=1, internal_model='P1a', ipn='P-1'),
            FeatureGroup(id=1, name='成像'), Feature(id=1, group_id=1, name='造影', config_item_id=201),
            ConfigItem(id=200, category='Probes', row_index=3, rd_name='P1', ipn='P-1'),
            ConfigItem(id=201, category='Optional Features', row_index=4, rd_name='造影', ipn='F-1'),
        ])
        for mid in (10, 11, 20):
            db.add(ConfigValue(item_id=200, model_id=mid, final_config='X' if mid != 11 else 'N/A', current_config='X', selection_config='O'))
            db.add(ConfigValue(item_id=201, model_id=mid, final_config='X', current_config='X', selection_config='O'))
        db.add(ProductProbeConfig(product_model_id=10, probe_model_id=1, feature_id=1,
                                  defined_status='conditional', current_status='supported', defined_excludes='["心脏"]'))
        await db.commit()
    return client, sessions, engine, source


async def create(client):
    r = await client.post('/api/probes/workspaces', json={'name': '共同总集', 'groups': ['V10'], 'combinations': ['Together']})
    assert r.status_code == 200, r.text
    return r.json()


def edited(data):
    draft = data['data']
    draft['rows'] = [{'probe_model_id': 1, 'variant_id': 1, 'feature_id': 1,
                      'defined_status': 'supported', 'current_status': 'supported',
                      'defined_excludes': [], 'current_excludes': [], 'notes': ''}]
    draft['overrides'] = {'20': {'1:1:1': {'current_status': 'conditional', 'current_excludes': ['心脏']}}}
    return draft


async def save(client, data, document=None):
    r = await client.put(f"/api/probes/workspaces/{data['id']}/draft", json={
        'revision': data['revision'], 'data': document or edited(data),
    })
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_combination_deduplicates_models_and_retains_legacy_as_unpublished(tmp_path, monkeypatch):
    client, sessions, engine, _ = await harness(tmp_path, monkeypatch)
    async with client:
        d = await create(client)
        assert d['data']['scope']['model_ids'] == [10, 11, 20]
        assert d['published_data'] is None
        assert d['data']['overrides']['10']['1:1:1']['defined_status'] == 'conditional'
        duplicate = await client.post('/api/probes/workspaces', json={'name': '副本', 'groups': ['V10']})
        assert duplicate.status_code == 409
        assert str(d['id']) in duplicate.json()['detail']
    await engine.dispose()


@pytest.mark.asyncio
async def test_draft_isolated_model_results_and_atomic_shared_publication(tmp_path, monkeypatch):
    client, sessions, engine, _ = await harness(tmp_path, monkeypatch)
    async with client:
        d = await save(client, await create(client))
        result = await client.get(f"/api/probes/workspaces/{d['id']}/results")
        assert result.status_code == 200, result.text
        by_model = {r['model_id']: r for r in result.json()['results']}
        assert by_model[10]['defined_status'] == 'supported'
        assert by_model[11]['defined_status'] == 'not_applicable'
        assert by_model[20]['current_status'] == 'conditional'
        assert by_model[20]['current_excludes'] == ['心脏']
        preview = await client.post(f"/api/probes/workspaces/{d['id']}/preview", json={'version_number': '1.2.3', 'description': '发布总集'})
        assert preview.status_code == 200, preview.text
        assert len(preview.json()['source_snapshots']) == 2
        r = await client.post(f"/api/probes/workspaces/{d['id']}/publish", json={
            'version_number': '1.2.3', 'description': '发布总集', 'signature': preview.json()['signature'],
        })
        assert r.status_code == 200, r.text
        assert len(r.json()['config_version_ids']) == 2
        assert (await client.get(f"/api/probes/workspaces/{d['id']}" )).json()['has_draft'] is False
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ConfigVersion)) == 2
        legacy = await db.scalar(select(ProductProbeConfig))
        assert legacy.defined_status == 'conditional'
        versions = list((await db.scalars(select(ConfigVersion))).all())
        assert all('probe_configuration' in json.loads(v.snapshot_data) for v in versions)
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('changed', ['draft', 'source', 'membership'])
async def test_publication_rejects_stale_preview_without_partial_versions(tmp_path, monkeypatch, changed):
    client, sessions, engine, source = await harness(tmp_path, monkeypatch)
    async with client:
        d = await save(client, await create(client))
        p = (await client.post(f"/api/probes/workspaces/{d['id']}/preview", json={'version_number': '1.0.0'})).json()
        if changed == 'draft':
            d = await save(client, d)
        elif changed == 'source':
            async with sessions() as db:
                value = await db.scalar(select(ConfigValue).where(ConfigValue.model_id == 10, ConfigValue.item_id == 200))
                value.current_config = 'N/A'
                await db.commit()
        else:
            source.write_text(source.read_text() + '\n')
        r = await client.post(f"/api/probes/workspaces/{d['id']}/publish", json={'version_number': '1.0.0', 'signature': p['signature']})
        assert r.status_code == 409, r.text
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ConfigVersion)) == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_discard_restore_and_history_do_not_depend_on_current_catalog(tmp_path, monkeypatch):
    client, sessions, engine, source = await harness(tmp_path, monkeypatch)
    async with client:
        d = await save(client, await create(client))
        path = f"/api/probes/workspaces/{d['id']}"
        p = (await client.post(path + '/preview', json={'version_number': '1.0.0'})).json()
        assert (await client.post(path + '/publish', json={'version_number': '1.0.0', 'signature': p['signature']})).status_code == 200
        d = (await client.get(path)).json()
        before = d['data']
        changed = json.loads(json.dumps(before)); changed['rows'][0]['current_status'] = 'unsupported'
        d = await save(client, d, changed)
        assert (await client.post(path + '/discard', json={'revision': d['revision']})).status_code == 200
        assert (await client.get(path)).json()['data'] == before
        source.unlink()
        history = await client.get(path + '/releases')
        rid = history.json()[0]['id']
        frozen = await client.get(path + f'/releases/{rid}')
        assert len(frozen.json()['snapshot']['results']) == 3
        assert frozen.json()['snapshot']['data'] == before
    await engine.dispose()


@pytest.mark.asyncio
async def test_excel_preview_then_apply_preserves_model_differences_and_rejects_bad_id(tmp_path, monkeypatch):
    client, sessions, engine, _ = await harness(tmp_path, monkeypatch)
    async with client:
        d = await save(client, await create(client))
        path = f"/api/probes/workspaces/{d['id']}"
        exported = await client.get(path + '/export')
        assert exported.status_code == 200
        wb = load_workbook(io.BytesIO(exported.content))
        assert {'范围及版本', '共同总集', '机型差异', '机型结果'} <= set(wb.sheetnames)
        out = io.BytesIO(); wb.save(out)
        preview = await client.post(path + '/import-preview', files={'file': ('probes.xlsx', out.getvalue())})
        assert preview.status_code == 200, preview.text
        assert preview.json()['data']['overrides']['20']['1:1:1']['current_excludes'] == ['心脏']
        wb['共同总集'].cell(2, 1, 999)
        out = io.BytesIO(); wb.save(out)
        bad = await client.post(path + '/import-preview', files={'file': ('probes.xlsx', out.getvalue())})
        assert bad.status_code == 422, bad.text
    await engine.dispose()


@pytest.mark.asyncio
async def test_source_only_change_can_publish_while_current_release_remains_frozen(tmp_path, monkeypatch):
    from app.services.config_history import build_series_snapshot
    client, sessions, engine, _ = await harness(tmp_path, monkeypatch)
    async with client:
        d = await save(client, await create(client)); path = f"/api/probes/workspaces/{d['id']}"
        p = (await client.post(path + '/preview', json={'version_number': '1.0.0'})).json()
        assert (await client.post(path + '/publish', json={'version_number': '1.0.0', 'signature': p['signature']})).status_code == 200
        frozen = (await client.get(path + '/results')).json()['results']
        async with sessions() as db:
            v = await db.scalar(select(ConfigValue).where(ConfigValue.model_id == 10, ConfigValue.item_id == 200))
            v.current_config = 'N/A'; await db.commit()
            main_snapshot = await build_series_snapshot(db, 1)
            assert 'probe_configuration' in main_snapshot
        assert (await client.get(path + '/results')).json()['results'] == frozen
        d = (await client.get(path)).json()
        d = await save(client, d, d['data'])
        p = await client.post(path + '/preview', json={'version_number': '1.0.1'})
        assert p.status_code == 200, p.text
        assert next(r for r in p.json()['results'] if r['model_id'] == 10)['current_status'] == 'not_applicable'
    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_edit_missing_mapping_invalid_rule_and_main_drafts_are_safe(tmp_path, monkeypatch):
    from app.models import ConfigDraft, DraftBatch
    client, sessions, engine, _ = await harness(tmp_path, monkeypatch)
    async with client:
        initial = await create(client); d = await save(client, initial)
        path = f"/api/probes/workspaces/{d['id']}"
        stale = await client.put(path + '/draft', json={'revision': initial['revision'], 'data': d['data']})
        assert stale.status_code == 409
        for mutation in ['unknown_model', 'duplicate', 'bad_excludes', 'unknown_feature']:
            doc = json.loads(json.dumps(d['data']))
            if mutation == 'unknown_model': doc['overrides']['999'] = {'1:1:1': {'current_status': 'supported'}}
            elif mutation == 'duplicate': doc['rows'].append(doc['rows'][0].copy())
            elif mutation == 'bad_excludes': doc['rows'][0]['current_excludes'] = None
            else: doc['rows'][0]['feature_id'] = 999
            r = await client.put(path + '/draft', json={'revision': d['revision'], 'data': doc})
            assert r.status_code == 422, r.text
        async with sessions() as db:
            feature = await db.get(Feature, 1); feature.config_item_id = None; feature.ipn = None
            db.add(DraftBatch(id='pending-source', series_id=1))
            db.add(ConfigDraft(series_id=1, batch_id='pending-source', item_id=200, model_id=10, change_type='update', field_name='current_config', new_value='X'))
            await db.commit()
        result = (await client.get(path + '/results')).json()['results']
        assert next(r for r in result if r['model_id'] == 10)['current_status'] == 'pending'
        r = await client.post(path + '/preview', json={})
        assert r.status_code == 400
        assert '草稿' in r.json()['detail']
    await engine.dispose()
