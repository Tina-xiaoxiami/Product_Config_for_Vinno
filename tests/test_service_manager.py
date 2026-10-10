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


def test_real_foreign_listener_stays_open(tmp_path):
    import socket
    module = manager()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        service = module.Service('backend', tmp_path, ['python', '-m', 'uvicorn', 'main:app', '--port', str(port)], port, '')
        assert not module.port_is_free(port)
        with pytest.raises(module.LaunchError, match=str(port)):
            module.check_service(service)
        assert listener.fileno() >= 0


@pytest.mark.parametrize('service_name', ['backend', 'frontend'])
def test_owned_process_requires_both_command_and_checkout(tmp_path, service_name):
    module = manager()
    service = module.Service(service_name, tmp_path, [], 18886, '')
    command = ['python', '-m', 'uvicorn', 'main:app', '--port', '18886'] if service_name == 'backend' else ['node', str(tmp_path / 'node_modules/vite/bin/vite.js')]
    process = SimpleNamespace(cwd=lambda: str(tmp_path), cmdline=lambda: command)
    assert module.process_matches(process, service)
    process.cwd = lambda: str(tmp_path / 'another-checkout')
    assert not module.process_matches(process, service)
    process.cwd = lambda: str(tmp_path)
    process.cmdline = lambda: ['python', 'unrelated.py']
    assert not module.process_matches(process, service)


def test_reload_parent_owns_child_listener(monkeypatch, tmp_path):
    module = manager()
    service = module.Service('backend', tmp_path, [], 18886, '')
    child = SimpleNamespace(net_connections=lambda kind: [SimpleNamespace(status=module.psutil.CONN_LISTEN, laddr=SimpleNamespace(port=18886))])
    parent = SimpleNamespace(pid=123, cwd=lambda: str(tmp_path), cmdline=lambda: ['python', '-m', 'uvicorn', 'main:app', '--port', '18886'], children=lambda recursive: [child], net_connections=lambda kind: [], create_time=lambda: 12.0)
    monkeypatch.setattr(module.psutil, 'process_iter', lambda: [parent])
    assert module.find_owned_listener(service) == {'pid': 123, 'created': 12.0}


def test_stop_verified_family_without_touching_unrelated_processes(monkeypatch, tmp_path):
    module = manager()
    calls = []
    child = SimpleNamespace(terminate=lambda: calls.append('child'), kill=lambda: calls.append('child-kill'))
    parent = SimpleNamespace(create_time=lambda: 12.0, cwd=lambda: str(tmp_path), cmdline=lambda: ['python', '-m', 'uvicorn', 'main:app', '--port', '18886'], children=lambda recursive: [child], terminate=lambda: calls.append('parent'))
    monkeypatch.setattr(module.psutil, 'Process', lambda pid: parent)
    monkeypatch.setattr(module.psutil, 'wait_procs', lambda processes, timeout: ([parent], [child]))
    service = module.Service('backend', tmp_path, [], 18886, '')
    assert module.stop_record(service, {'pid': 123, 'created': 12.0})
    assert calls == ['child', 'parent', 'child-kill']


def test_port_conflict_prevents_starting_any_service(monkeypatch, tmp_path):
    module = manager()
    calls = []
    services = [module.Service(name, tmp_path, [], port, '') for name, port in [('backend', 18886), ('frontend', 13006)]]
    def check(service):
        if service.name == 'frontend':
            raise module.LaunchError('13006 occupied')
        return None
    monkeypatch.setattr(module, 'check_service', check)
    monkeypatch.setattr(module, 'spawn_service', lambda *args: calls.append(args))
    with pytest.raises(module.LaunchError):
        module.start(services, tmp_path)
    assert calls == []


def test_start_reuses_backend_and_detaches_only_missing_frontend(monkeypatch, tmp_path):
    module = manager()
    services = [module.Service(name, tmp_path, [], port, '') for name, port in [('backend', 18886), ('frontend', 13006)]]
    calls = []
    monkeypatch.setattr(module, 'check_service', lambda service: {'pid': 1, 'created': 1.0} if service.name == 'backend' else None)
    monkeypatch.setattr(module, 'spawn_service', lambda service, runtime: calls.append(service.name) or {'pid': 2, 'created': 2.0})
    monkeypatch.setattr(module.psutil, 'Process', lambda pid: SimpleNamespace(is_running=lambda: True, status=lambda: 'running'))
    monkeypatch.setattr(module, 'healthy', lambda service: True)
    module.start(services, tmp_path)
    assert calls == ['frontend']
    assert module.read_state(tmp_path) == {'backend': {'pid': 1, 'created': 1.0}, 'frontend': {'pid': 2, 'created': 2.0}}


def test_failed_start_cleans_only_new_process(monkeypatch, tmp_path):
    module = manager()
    services = [module.Service(name, tmp_path, [], port, '') for name, port in [('backend', 18886), ('frontend', 13006)]]
    stopped = []
    monkeypatch.setattr(module, 'check_service', lambda service: {'pid': 1, 'created': 1.0} if service.name == 'backend' else None)
    monkeypatch.setattr(module, 'spawn_service', lambda service, runtime: {'pid': 2, 'created': 2.0})
    monkeypatch.setattr(module.psutil, 'Process', lambda pid: SimpleNamespace(is_running=lambda: False))
    monkeypatch.setattr(module, 'healthy', lambda service: False)
    monkeypatch.setattr(module, 'stop_record', lambda service, record: stopped.append(record['pid']))
    with pytest.raises(module.LaunchError, match='frontend'):
        module.start(services, tmp_path)
    assert stopped == [2]
    assert module.read_state(tmp_path)['backend']['pid'] == 1


def test_state_and_launcher_lock_are_released(tmp_path):
    module = manager()
    assert module.read_state(tmp_path) == {}
    with module.launcher_lock(tmp_path):
        with pytest.raises(module.LaunchError):
            with module.launcher_lock(tmp_path):
                pass
    with module.launcher_lock(tmp_path):
        module.write_state(tmp_path, {'backend': {'pid': 123, 'created': 12.0}})
    (tmp_path / 'services.json').write_text('broken json')
    assert module.read_state(tmp_path) == {}


@pytest.mark.parametrize('name,content,expected', [('backend', '{"message":"产品配置管理系统 API"}', True), ('backend', '{"message":"other API"}', False), ('frontend', '产品配置管理系统 /@vite/client', True), ('frontend', '<title>another product</title>', False), ('backend', 'invalid json', False)])
def test_health_requires_product_response(monkeypatch, tmp_path, name, content, expected):
    module = manager()
    response = SimpleNamespace(read=lambda limit: content.encode(), __enter__=lambda self: self, __exit__=lambda *args: None)
    class Response:
        def __enter__(self): return response
        def __exit__(self, *args): return None
    monkeypatch.setattr(module, 'build_opener', lambda *args: SimpleNamespace(open=lambda *args, **kwargs: Response()))
    assert module.healthy(module.Service(name, tmp_path, [], 0, 'http://127.0.0.1/')) is expected


@pytest.mark.parametrize('action', ['start', 'stop', 'status'])
def test_cli_uses_only_shared_service_state(monkeypatch, tmp_path, action):
    module = manager()
    service = module.Service('backend', tmp_path, [], 0, 'http://127.0.0.1/')
    monkeypatch.setattr(module, 'RUNTIME', tmp_path)
    monkeypatch.setattr(module, 'services', lambda **kwargs: [service, service])
    monkeypatch.setattr(module.sys, 'argv', ['service_manager.py', action, '--no-browser'])
    calls = []
    monkeypatch.setattr(module, 'start', lambda *args: calls.append('start'))
    monkeypatch.setattr(module, 'find_owned_listener', lambda service: {'pid': 123, 'created': 12.0})
    monkeypatch.setattr(module, 'stop_record', lambda service, record: calls.append('stop') or True)
    monkeypatch.setattr(module, 'healthy', lambda service: True)
    assert module.main() == 0
    assert calls == (['start'] if action == 'start' else ['stop', 'stop'] if action == 'stop' else [])


def test_stop_and_status_can_identify_services_when_node_is_missing(monkeypatch):
    module = manager()
    monkeypatch.setattr(module.shutil, 'which', lambda name: None)
    # Missing dependencies should block a new start, never service identification.
    assert [service.name for service in module.services()] == ['backend', 'frontend']


def test_start_requires_frontend_dependencies(monkeypatch):
    module = manager()
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    with pytest.raises(module.LaunchError, match="依赖"): module.services(require_dependencies=True)
