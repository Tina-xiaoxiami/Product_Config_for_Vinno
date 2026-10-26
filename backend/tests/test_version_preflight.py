import pytest
from sqlalchemy import select, func
from app.models import ConfigVersion
from test_draft_safety import _draft_harness, _seed_catalog


@pytest.mark.asyncio
async def test_preflight_uses_series_duplicate_rules_without_writing(tmp_path):
    client, sessions, engine = await _draft_harness(tmp_path)
    await _seed_catalog(sessions)
    async with sessions() as session:
        session.add(ConfigVersion(series_id=1, version_number='1.51.90', snapshot_data='{}'))
        await session.commit()
    async with client:
        response = await client.get('/api/drafts/version-check', params=[('series_ids', 1), ('series_ids', 2), ('version_number', '1.51.90')])
        assert response.status_code == 200
        assert [r['valid'] for r in response.json()['results']] == [False, True]
        assert 'V Series' in response.json()['results'][0]['message']
        for version in ('1.51.91', '', 'release-A'):
            result = await client.get('/api/drafts/version-check', params={'series_ids': 1, 'version_number': version})
            assert result.json()['results'][0]['valid'] is True
        missing = await client.get('/api/drafts/version-check', params={'series_ids': 999})
        assert missing.status_code == 404
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ConfigVersion)) == 1
    await engine.dispose()
