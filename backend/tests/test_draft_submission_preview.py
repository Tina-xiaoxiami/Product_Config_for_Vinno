import pytest
from sqlalchemy import func, select

from app.models import ConfigDraft, ConfigValue, ConfigVersion, DraftBatch
from test_draft_safety import _draft_harness, _seed_catalog


async def seed_submission(session_factory):
    await _seed_catalog(session_factory)
    async with session_factory() as session:
        session.add(DraftBatch(id='review-batch', series_id=1, status='draft'))
        for item_id in (100, 101):
            for model_id in (10, 11):
                session.add(ConfigValue(item_id=item_id, model_id=model_id, final_config='working', current_config='working'))
        for item_id, model_id, field_name, change_type in (
            (100, 10, 'final_config', 'update'),
            (100, 11, 'current_config', 'create'),
            (101, 10, 'current_config', 'update'),
            (101, 11, None, 'delete'),
        ):
            session.add(ConfigDraft(series_id=1, batch_id='review-batch', item_id=item_id,
                                    model_id=model_id, field_name=field_name, change_type=change_type,
                                    old_value='baseline', new_value='working'))
        await session.commit()


@pytest.mark.asyncio
async def test_submit_preview_reports_actual_full_scope_without_writing(tmp_path):
    client, sessions, engine = await _draft_harness(tmp_path)
    await seed_submission(sessions)
    async with client:
        response = await client.post('/api/drafts/batch/review-batch/submit-preview', json={})
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview['series_name'] == 'V Series'
    assert preview['total_items'] == 2
    assert preview['total_models'] == 2
    assert preview['total_changes'] == 4
    assert preview['remaining_changes'] == 0
    assert preview['change_counts'] == {'create': 1, 'update': 2, 'delete': 1}
    assert set(preview['fields']) == {'final_config', 'current_config', 'selection_config', 'rd_status'}
    assert len(preview['drafts']) == 4
    assert preview['signature']
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ConfigVersion)) == 0
        assert await session.scalar(select(func.count()).select_from(ConfigDraft)) == 4
        assert (await session.get(DraftBatch, 'review-batch')).status == 'draft'
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('scope,expected', [({'item_ids': [100]}, 2), ({'model_ids': [11]}, 2), ({'item_ids': [100], 'model_ids': [11]}, 1)])
async def test_preview_scope_matches_actual_submission(tmp_path, scope, expected):
    client, sessions, engine = await _draft_harness(tmp_path)
    await seed_submission(sessions)
    async with client:
        response = await client.post('/api/drafts/batch/review-batch/submit-preview', json=scope)
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview['total_changes'] == expected
        assert preview['remaining_changes'] == 4 - expected
        response = await client.post('/api/drafts/batch/review-batch/submit', json={**scope, 'expected_signature': preview['signature']})
        assert response.status_code == 200, response.text
        assert response.json()['changes'] == expected
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ConfigDraft)) == 4 - expected
    await engine.dispose()


@pytest.mark.asyncio
async def test_changed_draft_invalidates_preview_before_submission(tmp_path):
    client, sessions, engine = await _draft_harness(tmp_path)
    await seed_submission(sessions)
    async with client:
        response = await client.post('/api/drafts/batch/review-batch/submit-preview', json={})
        assert response.status_code == 200, response.text
        signature = response.json()['signature']
        async with sessions() as session:
            draft = await session.scalar(select(ConfigDraft).where(ConfigDraft.item_id == 101, ConfigDraft.model_id == 10))
            draft.new_value = 'changed-after-review'
            await session.commit()
        response = await client.post('/api/drafts/batch/review-batch/submit', json={'expected_signature': signature})
        assert response.status_code == 409, response.text
        assert '重新' in response.json()['detail']
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ConfigVersion)) == 0
        assert await session.scalar(select(func.count()).select_from(ConfigDraft)) == 4
        assert (await session.get(DraftBatch, 'review-batch')).status == 'draft'
    await engine.dispose()


@pytest.mark.asyncio
async def test_signature_cannot_be_reused_for_a_broader_scope(tmp_path):
    client, sessions, engine = await _draft_harness(tmp_path)
    await seed_submission(sessions)
    async with client:
        response = await client.post('/api/drafts/batch/review-batch/submit-preview', json={'item_ids': [100]})
        assert response.status_code == 200, response.text
        response = await client.post('/api/drafts/batch/review-batch/submit', json={'expected_signature': response.json()['signature']})
        assert response.status_code == 409, response.text
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('scope', [{'item_ids': []}, {'model_ids': []}])
async def test_explicit_empty_scope_never_submits_all_drafts(tmp_path, scope):
    client, sessions, engine = await _draft_harness(tmp_path)
    await seed_submission(sessions)
    async with client:
        preview = await client.post('/api/drafts/batch/review-batch/submit-preview', json=scope)
        assert preview.status_code == 200, preview.text
        assert preview.json()['total_changes'] == 0
        response = await client.post('/api/drafts/batch/review-batch/submit', json=scope)
        assert response.status_code == 400, response.text
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ConfigDraft)) == 4
    await engine.dispose()


@pytest.mark.asyncio
async def test_batch_submit_rejects_changed_review_signature(tmp_path):
    client, sessions, engine = await _draft_harness(tmp_path)
    await seed_submission(sessions)
    async with client:
        preview = await client.post('/api/drafts/batch/review-batch/submit-preview', json={})
        assert preview.status_code == 200, preview.text
        async with sessions() as session:
            draft = await session.scalar(select(ConfigDraft).where(ConfigDraft.item_id == 100, ConfigDraft.model_id == 10))
            draft.new_value = 'changed'
            await session.commit()
        response = await client.post('/api/drafts/batch/submit', json={'batch_ids': ['review-batch'], 'expected_signatures': {'review-batch': preview.json()['signature']}})
        assert response.status_code == 200, response.text
        assert response.json()['submitted_count'] == 0
        assert not response.json()['results'][0]['success']
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ConfigVersion)) == 0
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['pair_value', 'shared_description'])
@pytest.mark.parametrize('submit_mode', ['single', 'batch'])
async def test_unchanged_draft_records_cannot_hide_changed_publication_values(tmp_path, change, submit_mode):
    from app.models import ConfigItem
    client, sessions, engine = await _draft_harness(tmp_path)
    await seed_submission(sessions)
    async with sessions() as session:
        draft = await session.scalar(select(ConfigDraft).where(ConfigDraft.item_id == 100, ConfigDraft.model_id == 11))
        draft.field_name = None
        draft.old_value = None
        draft.new_value = 'CPU'
        await session.commit()
    async with client:
        preview = await client.post('/api/drafts/batch/review-batch/submit-preview', json={})
        assert preview.status_code == 200, preview.text
        async with sessions() as session:
            if change == 'pair_value':
                value = await session.scalar(select(ConfigValue).where(ConfigValue.item_id == 100, ConfigValue.model_id == 11))
                value.final_config = 'changed-after-preview'
            else:
                item = await session.get(ConfigItem, 100)
                item.zh_desc = 'changed-after-preview'
            await session.commit()
        if submit_mode == 'single':
            submitted = await client.post('/api/drafts/batch/review-batch/submit', json={'expected_signature': preview.json()['signature']})
            assert submitted.status_code == 409, submitted.text
        else:
            submitted = await client.post('/api/drafts/batch/submit', json={'batch_ids': ['review-batch'], 'expected_signatures': {'review-batch': preview.json()['signature']}})
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()['submitted_count'] == 0
            assert not submitted.json()['results'][0]['success']
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ConfigVersion)) == 0
        assert await session.scalar(select(func.count()).select_from(ConfigDraft)) == 4
    await engine.dispose()
