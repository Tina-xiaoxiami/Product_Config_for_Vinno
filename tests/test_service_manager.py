"""Launcher regressions use temporary ports and processes, never product services."""
import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('service_manager', ROOT / 'tools' / 'service_manager.py')


def manager():
    module = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = module
    SPEC.loader.exec_module(module)
    return module


def test_occupied_foreign_port_is_rejected_without_termination(monkeypatch, tmp_path):
    module = manager()
    service = module.Service('backend', tmp_path, ['python', '-m', 'uvicorn', 'main:app', '--port', '18886'], 18886, 'http://127.0.0.1:18886/')
    monkeypatch.setattr(module, 'port_is_free', lambda port: False)
    monkeypatch.setattr(module, 'find_owned_listener', lambda service: None)
    with pytest.raises(module.LaunchError, match='18886'):
        module.check_service(service)


def test_healthy_owned_listener_is_reused(monkeypatch, tmp_path):
    module = manager()
    service = module.Service('frontend', tmp_path, ['node', 'vite.js', '--port', '13006'], 13006, 'http://127.0.0.1:13006/')
    record = {'pid': 123, 'created': 12.0}
    monkeypatch.setattr(module, 'port_is_free', lambda port: False)
    monkeypatch.setattr(module, 'find_owned_listener', lambda service: record)
    monkeypatch.setattr(module, 'healthy', lambda service: True)
    assert module.check_service(service) == record


def test_stop_rejects_recycled_pid(monkeypatch, tmp_path):
    module = manager()
    terminated = []
    process = SimpleNamespace(create_time=lambda: 99.0, terminate=lambda: terminated.append(1))
    monkeypatch.setattr(module.psutil, 'Process', lambda pid: process)
    service = module.Service('backend', tmp_path, ['python', '-m', 'uvicorn', 'main:app', '--port', '18886'], 18886, '')
    assert module.stop_record(service, {'pid': 123, 'created': 12.0}) is False
    assert terminated == []


def test_spawn_is_detached_and_uses_explicit_service_directory(tmp_path):
    module = manager()
    service = module.Service('test', tmp_path, [sys.executable, '-c', 'import time; time.sleep(10)'], 0, '')
    record = module.spawn_service(service, tmp_path)
    process = module.psutil.Process(record['pid'])
    try:
        assert Path(process.cwd()).resolve() == tmp_path.resolve()
        if sys.platform != 'win32':
            import os
            assert os.getsid(process.pid) == process.pid
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_entrypoints_never_kill_processes_by_port():
    for name in ['start.command', 'start.sh', 'start.bat', 'stop.command', 'stop.bat']:
        source = (ROOT / name).read_text()
        assert 'service_manager.py' in source
        assert 'taskkill' not in source
        assert 'pkill' not in source
        assert 'lsof' not in source
