"""The browser fixture must never initialize a real database or shared source."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest


@pytest.mark.parametrize('database,source', [
    ('sqlite+aiosqlite:////tmp/probe-e2e/../../real.db', '/tmp/probe-e2e-source.json'),
    ('sqlite+aiosqlite:////tmp/probe-e2e.db', '/tmp/real-subseries.json'),
])
def test_browser_fixture_rejects_non_disposable_paths_before_import(database, source):
    fixture = Path(__file__).resolve().parents[2] / 'tests/probe_e2e_app.py'
    result = subprocess.run([sys.executable, str(fixture)], capture_output=True, text=True,
                            env={**os.environ, 'PROBE_E2E': '1', 'DATABASE_URL': database,
                                 'WHITEPAPER_SUBSERIES_FILE': source}, timeout=10)
    assert result.returncode != 0
    assert 'refuses non-disposable' in result.stderr


def test_browser_fixture_initializes_overseas_history_read_schema():
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix='probe-e2e-', dir='/tmp') as directory:
        temporary = Path(directory)
        code = """
from fastapi.testclient import TestClient
from probe_e2e_app import app
with TestClient(app) as client:
    response = client.get('/api/registrations/overseas/snapshots')
    assert response.status_code == 200, response.text
    assert response.json() == {'items': [], 'total': 0}
"""
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                                env={**os.environ, 'PROBE_E2E': '1',
                                     'PYTHONPATH': str(root / 'tests'),
                                     'DATABASE_URL': f'sqlite+aiosqlite:///{temporary / "probe-e2e.db"}',
                                     'WHITEPAPER_SUBSERIES_FILE': str(temporary / 'probe-e2e-subseries.json')},
                                timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
