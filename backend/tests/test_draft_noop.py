"""Field edits returning to their first baseline must not leave phantom drafts."""
import pytest
from sqlalchemy import func, select

from app.models import ConfigDraft, ConfigValue, ConfigVersion, DraftBatch
from test_draft_safety import _draft_harness, _draft_payload, _seed_catalog


@pytest.mark.asyncio
@pytest.mark.parametrize('field,baseline', [
    ('final_config', 'X'), ('current_config', 'X'),
    ('selection_config', 'X'), ('rd_status', '已完成'),
])
async def test_clear_then_restore_removes_field_draft_without_touching_other_changes(tmp_path, field, baseline):
    client, sessions, engine = await _draft_harness(tmp_path)
    await _seed_catalog(sessions)
    async with sessions() as db:
        db.add_all([
            DraftBatch(id='batch-1', series_id=1, status='draft'),
            ConfigValue(item_id=100, model_id=10, **{field: baseline}),
            ConfigDraft(batch_id='batch-1', series_id=1, item_id=101, model_id=10,
                        field_name='current_config', change_type='update', old_value='other-old', new_value='other-new'),
        ])
        await db.commit()
    async with client:
        cleared = await client.post('/api/drafts/draft', json=_draft_payload(field_name=field, new_value=None))
        assert cleared.status_code == 200, cleared.text
        restored = await client.post('/api/drafts/draft', json=_draft_payload(field_name=field, old_value=None, new_value=baseline))
        assert restored.status_code == 200, restored.text
        assert restored.json()['draft_id'] is None
        assert restored.json()['removed'] is True
        assert restored.json()['current_value'] == baseline
        current = await client.get('/api/drafts/batch/current/1')
        assert len(current.json()['drafts']) == 1
        assert current.json()['drafts'][0]['item_id'] == 101
        assert current.json()['batch']['total_count'] == 1
    async with sessions() as db:
        value = await db.scalar(select(ConfigValue).where(ConfigValue.item_id == 100))
        assert getattr(value, field) == baseline
        drafts = (await db.execute(select(ConfigDraft))).scalars().all()
        assert len(drafts) == 1
        assert drafts[0].new_value == 'other-new'
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('baseline,new_value,kind', [('X', 'X', 'update'), (None, 'N/A', 'create'), ('', None, 'create')])
async def test_first_semantically_unchanged_field_request_creates_no_draft_or_version(tmp_path, baseline, new_value, kind):
    client, sessions, engine = await _draft_harness(tmp_path)
    await _seed_catalog(sessions)
    async with sessions() as db:
        db.add_all([DraftBatch(id='batch-1', series_id=1, status='draft'),
                    ConfigValue(item_id=100, model_id=10, current_config=baseline)])
        await db.commit()
    async with client:
        response = await client.post('/api/drafts/draft', json=_draft_payload(old_value='untrusted', new_value=new_value, change_type=kind))
        assert response.status_code == 200, response.text
        assert response.json()['draft_id'] is None
        assert response.json()['unchanged'] is True
        assert response.json()['current_value'] == baseline
        submitted = await client.post('/api/drafts/batch/batch-1/submit', json={})
        assert submitted.status_code == 400
        assert submitted.json()['detail'] == '没有待提交的草稿'
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ConfigDraft)) == 0
        assert await db.scalar(select(func.count()).select_from(ConfigVersion)) == 0
        batch = await db.get(DraftBatch, 'batch-1')
        assert (batch.total_count, batch.create_count, batch.update_count, batch.delete_count) == (0, 0, 0, 0)
        assert await db.scalar(select(ConfigValue.current_config)) == baseline
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('baseline,restored', [(None, None), ('N/A', None), ('', 'N/A')])
async def test_field_create_restoring_semantic_empty_removes_original_draft(tmp_path, baseline, restored):
    client, sessions, engine = await _draft_harness(tmp_path)
    await _seed_catalog(sessions)
    async with sessions() as db:
        db.add_all([DraftBatch(id='batch-1', series_id=1, status='draft'),
                    ConfigValue(item_id=100, model_id=10, current_config=baseline)])
        await db.commit()
    async with client:
        first = await client.post('/api/drafts/draft', json=_draft_payload(new_value='X', change_type='create'))
        assert first.status_code == 200
        response = await client.post('/api/drafts/draft', json=_draft_payload(new_value=restored, change_type='create'))
        assert response.status_code == 200, response.text
        assert response.json()['draft_id'] is None
        assert response.json()['removed'] is True
        assert response.json()['current_value'] == baseline
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ConfigDraft)) == 0
        assert await db.scalar(select(ConfigValue.current_config)) == baseline
    await engine.dispose()
