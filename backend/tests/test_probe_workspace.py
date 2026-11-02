"""Probe releases share configuration publication and preserve model differences."""
import pytest
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
