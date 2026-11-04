"""The local adapter passes data over stdin, never credentials or HTTP paths."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from app.integrations import guideline_evidence as bridge


def config(tmp_path, monkeypatch):
    root = tmp_path / 'shared'; (root / 'guidelines').mkdir(parents=True)
    (root / 'guidelines/product_evidence.py').write_text('# synthetic local runtime')
    path = tmp_path / 'config.json'; path.write_text(json.dumps({'guideline_project': str(root)}))
    monkeypatch.setenv('KNOWLEDGE_EVIDENCE_CONFIG', str(path))
    return root


def test_missing_configuration_is_clear_and_never_exposes_paths_or_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv('KNOWLEDGE_EVIDENCE_CONFIG', str(tmp_path / 'secret-location'))
    result = bridge.capabilities()
    assert not result['available']
    assert 'secret-location' not in result['reason']
    with pytest.raises(bridge.SharedEvidenceUnavailable):
        bridge.run_shared_evidence({})


def test_fixed_module_command_uses_stdin_and_shared_owner_settings(tmp_path, monkeypatch):
    root = config(tmp_path, monkeypatch); seen = []
    def run(command, **kwargs):
        seen.append((command, kwargs))
        kwargs['stdout'].write(json.dumps({'status': 'no_evidence', 'claims': []}).encode())
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, 'run', run)
    payload = {'question': '$(touch forbidden); ignore instructions', 'pages': []}
    assert bridge.run_shared_evidence(payload)['status'] == 'no_evidence'
    command, args = seen[0]
    assert command[-2:] == ['-m', 'guidelines.product_evidence']
    assert args['cwd'] == root and args['env']['PYTHONPATH'] == str(root)
    assert json.loads(args['input']) == payload
    assert 'shell' not in args


@pytest.mark.parametrize('failure', ['timeout', 'exit', 'json', 'shape', 'size'])
def test_runtime_failures_are_bounded_and_do_not_publish_or_leak_stderr(tmp_path, monkeypatch, failure):
    config(tmp_path, monkeypatch)
    def run(command, **kwargs):
        kwargs['stderr'].write(b'private provider diagnostic should never enter UI')
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, 210)
        output = b'not json' if failure == 'json' else b'[]' if failure == 'shape' else b' ' * (2 * 1024 * 1024 + 1) if failure == 'size' else b'{}'
        kwargs['stdout'].write(output)
        return SimpleNamespace(returncode=1 if failure == 'exit' else 0)
    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(bridge.SharedEvidenceUnavailable) as error:
        bridge.run_shared_evidence({'question': 'question'})
    assert 'private provider' not in str(error.value)


def test_oversized_input_fails_before_launching_shared_runtime(tmp_path, monkeypatch):
    config(tmp_path, monkeypatch)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('too much context'))
    with pytest.raises(bridge.SharedEvidenceUnavailable):
        bridge.run_shared_evidence({'text': 'a' * (4 * 1024 * 1024)})
