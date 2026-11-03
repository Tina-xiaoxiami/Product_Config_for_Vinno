"""Candidate tool must preview safely and bind writes to the intended source."""
import importlib.util
import io
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('measurement_suggestions_import', ROOT / 'tools/import_measurement_suggestions.py')
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


@pytest.fixture
def proposal(tmp_path):
    bundle = {'source_workbook': {'version': '1.51.90', 'sha256': 'a' * 64}, 'schema_version': 1,
              'coverage': {'total': 1}, 'candidates': [{'item_id': "E/Avg E'", 'payload': {'research_status': 'unresolved'}}]}
    library = {'batches': [{'id': 7, 'version': '1.51.90', 'sha256': 'a' * 64}]}
    file = tmp_path / 'proposal.json'
    file.write_text(json.dumps(bundle))
    return bundle, library, file


def test_source_binding_requires_one_exact_hash_version_and_optional_batch(proposal):
    bundle, library, _ = proposal
    manifest = TOOL.build_manifest(bundle, library, 7)
    assert manifest['batch_id'] == 7
    assert manifest['candidates'][0]['item_id'] == "E/Avg E'"
    for batches, batch_id in [([], None), (library['batches'] * 2, None), (library['batches'], 8),
                              ([{**library['batches'][0], 'sha256': 'b' * 64}], None),
                              ([{**library['batches'][0], 'version': '1.51.91'}], None)]:
        with pytest.raises(ValueError): TOOL.build_manifest(bundle, {'batches': batches}, batch_id)


@pytest.mark.parametrize('apply', [False, True])
def test_default_preview_never_posts_and_apply_uses_only_candidate_endpoint(proposal, monkeypatch, capsys, apply):
    _, library, file = proposal
    calls = []
    def request(url, payload=None):
        calls.append((url, payload))
        return library if payload is None else {'created': 1, 'reused': 0}
    monkeypatch.setattr(TOOL, 'request_json', request)
    monkeypatch.setattr(sys, 'argv', ['suggestions', '--file', str(file), '--batch-id', '7'] + (['--apply'] if apply else []))
    assert TOOL.main() == 0
    assert len(calls) == (2 if apply else 1)
    assert calls[0] == ('http://127.0.0.1:8086/api/measurements', None)
    if apply:
        assert calls[1][0].endswith('/api/measurements/enrichment/import')
        assert calls[1][1]['batch_id'] == 7
        assert calls[1][1]['candidates'][0]['payload']['research_status'] == 'unresolved'
    assert '1.51.90' in capsys.readouterr().out


def test_mismatch_and_missing_file_stop_before_any_write(proposal, monkeypatch):
    _, _, file = proposal
    calls = []
    def request(url, payload=None):
        calls.append(payload)
        return {'batches': []}
    monkeypatch.setattr(TOOL, 'request_json', request)
    monkeypatch.setattr(sys, 'argv', ['suggestions', '--file', str(file), '--apply'])
    assert TOOL.main() == 1
    assert calls == [None]
    monkeypatch.setattr(sys, 'argv', ['suggestions', '--file', str(file.with_name('missing.json')), '--apply'])
    assert TOOL.main() == 1
    assert calls == [None]


@pytest.mark.parametrize('error', [HTTPError('http://localhost', 409, 'changed', {}, io.BytesIO(b'stale source')), URLError('offline')])
def test_transport_errors_are_failures_not_success(proposal, monkeypatch, error):
    _, _, file = proposal
    def request(*_): raise error
    monkeypatch.setattr(TOOL, 'request_json', request)
    monkeypatch.setattr(sys, 'argv', ['suggestions', '--file', str(file), '--apply'])
    assert TOOL.main() == 1


def test_json_transport_uses_read_or_json_post_without_executing_formula(monkeypatch):
    seen = []
    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *_): self.close()
    def open_request(request, timeout):
        seen.append((request.get_method(), request.data, timeout))
        return Response(b'{"ok":true}')
    monkeypatch.setattr(TOOL, 'urlopen', open_request)
    assert TOOL.request_json('http://localhost/api/measurements') == {'ok': True}
    assert TOOL.request_json('http://localhost/api/measurements/enrichment/import', {'formula_reference': 'reference text'}) == {'ok': True}
    assert seen[0] == ('GET', None, 60)
    assert seen[1][0] == 'POST' and json.loads(seen[1][1]) == {'formula_reference': 'reference text'}
