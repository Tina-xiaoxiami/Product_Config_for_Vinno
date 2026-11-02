"""The browser fixture must never initialize a real database or shared source."""
import os
from pathlib import Path
import subprocess
import sys
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
