"""Start detached local services and stop only verified processes from this checkout."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser

import psutil

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'


class LaunchError(RuntimeError):
    """A service cannot be started or safely identified."""


@dataclass(frozen=True)
class Service:
    name: str
    cwd: Path
    command: list[str]
    port: int
    url: str


def services() -> list[Service]:
    python = ROOT / 'backend' / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
    executable = str(python) if python.exists() else sys.executable
    node = shutil.which('node')
    vite = ROOT / 'frontend/node_modules/vite/bin/vite.js'
    return [
        Service('backend', ROOT / 'backend', [executable, '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8086'], 8086, 'http://127.0.0.1:8086/'),
        Service('frontend', ROOT / 'frontend', [node or 'node', str(vite), '--host', '127.0.0.1', '--port', '3006', '--strictPort'], 3006, 'http://127.0.0.1:3006/'),
    ]


def port_is_free(port: int) -> bool:
    # Check active listeners, not bind availability: closed TCP connections may
    # remain in TIME_WAIT even though the application's server can restart.
    unavailable = {errno.ECONNREFUSED, errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL,
                   errno.ENETUNREACH, errno.EHOSTUNREACH}
    for family, host in [(socket.AF_INET, '127.0.0.1'), (socket.AF_INET6, '::1')]:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as connection:
                connection.settimeout(1)
                connection.connect((host, port))
                return False
        except OSError as exc:
            if exc.errno not in unavailable:
                return False
    return True


def process_matches(process: psutil.Process, service: Service) -> bool:
    try:
        if Path(process.cwd()).resolve() != service.cwd.resolve():
            return False
        command = process.cmdline()
        if service.name == 'backend':
            return 'uvicorn' in command and 'main:app' in command and '--port' in command and command[command.index('--port') + 1] == str(service.port)
        return any(Path(arg).resolve() == (service.cwd / 'node_modules/vite/bin/vite.js').resolve() for arg in command[1:])
    except (psutil.Error, OSError, IndexError):
        return False


def find_owned_listener(service: Service) -> dict | None:
    for process in psutil.process_iter():
        if not process_matches(process, service):
            continue
        try:
            # Reload workers may inherit their parent's listening socket.
            family = [process, *process.children(recursive=True)]
            if any(connection.status == psutil.CONN_LISTEN and connection.laddr.port == service.port
                   for member in family for connection in member.net_connections(kind='tcp')):
                return {'pid': process.pid, 'created': process.create_time()}
        except psutil.Error:
            continue
    return None


def healthy(service: Service) -> bool:
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(service.url, timeout=2) as response:
            content = response.read(1024 * 1024).decode('utf-8')
        if service.name == 'backend':
            return json.loads(content).get('message') == '产品配置管理系统 API'
        return '/@vite/client' in content and '产品配置管理系统' in content
    except (URLError, OSError, ValueError, UnicodeError):
        return False


def check_service(service: Service) -> dict | None:
    if port_is_free(service.port):
        return None
    record = find_owned_listener(service)
    if record and healthy(service):
        return record
    raise LaunchError(f'端口 {service.port} 已被占用或服务不健康，未停止任何进程。请检查后重试。')


def spawn_service(service: Service, runtime: Path) -> dict:
    if service.name == 'frontend' and (not shutil.which(service.command[0]) or not Path(service.command[1]).is_file()):
        raise LaunchError('前端依赖未准备好，请先安装 Node 并在 frontend 目录运行 npm ci。')
    runtime.mkdir(parents=True, exist_ok=True)
    options = {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    with (runtime / f'{service.name}.log').open('ab') as log:
        process = subprocess.Popen(service.command, cwd=service.cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **options)
    try:
        return {'pid': process.pid, 'created': psutil.Process(process.pid).create_time()}
    except psutil.Error as exc:
        raise LaunchError(f'{service.name} 启动失败，请查看 {runtime / (service.name + ".log")}') from exc


def stop_record(service: Service, record: dict) -> bool:
    try:
        process = psutil.Process(record['pid'])
        if process.create_time() != record['created'] or not process_matches(process, service):
            return False
        descendants = process.children(recursive=True)
        # psutil's Process object guards against PID reuse before terminate/kill.
        for member in reversed(descendants):
            try:
                member.terminate()
            except psutil.NoSuchProcess:
                continue
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
        _, alive = psutil.wait_procs([*descendants, process], timeout=5)
        for member in alive:
            try:
                member.kill()
            except psutil.NoSuchProcess:
                continue
        return True
    except (psutil.Error, KeyError, TypeError):
        return False


@contextmanager
def launcher_lock(runtime: Path):
    runtime.mkdir(parents=True, exist_ok=True)
    # OS file locks are released on process exit, including interrupted launches.
    with (runtime / 'launcher.lock').open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            try:
                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b'0')
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise LaunchError('启动或停止正在进行，请稍后重试。') from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LaunchError('启动或停止正在进行，请稍后重试。') from exc
        yield


def read_state(runtime: Path) -> dict:
    try:
        state = json.loads((runtime / 'services.json').read_text())
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(runtime: Path, records: dict):
    temporary = runtime / 'services.json.tmp'
    temporary.write_text(json.dumps(records), encoding='utf-8')
    temporary.replace(runtime / 'services.json')


def start(all_services: list[Service], runtime: Path):
    # Preflight every port before starting anything.
    records = {service.name: check_service(service) for service in all_services}
    launched = []
    try:
        for service in all_services:
            if records[service.name]:
                print(f'{service.name} 已运行，复用现有服务。')
                continue
            records[service.name] = spawn_service(service, runtime)
            launched.append(service)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                process = psutil.Process(records[service.name]['pid'])
                if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                    break
                if healthy(service):
                    break
                time.sleep(0.25)
            else:
                raise LaunchError(f'{service.name} 启动超时，请查看 {runtime / (service.name + ".log")}')
            if not healthy(service):
                raise LaunchError(f'{service.name} 启动失败，请查看 {runtime / (service.name + ".log")}')
            write_state(runtime, records)
        write_state(runtime, records)
    except (LaunchError, psutil.Error, OSError):
        for service in reversed(launched):
            stop_record(service, records[service.name])
            records[service.name] = None
        write_state(runtime, records)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description='产品配置管理系统本地服务')
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    parser.add_argument('--no-browser', action='store_true')
    arguments = parser.parse_args()
    try:
        all_services = services()
        with launcher_lock(RUNTIME):
            if arguments.action == 'start':
                start(all_services, RUNTIME)
                if not arguments.no_browser:
                    webbrowser.open(all_services[1].url)
                print('启动完成： http://127.0.0.1:3006\n服务在后台运行，关闭终端不影响使用。停止服务请运行 stop.command（Windows: stop.bat）。')
            elif arguments.action == 'stop':
                state = read_state(RUNTIME)
                remaining = {}
                for service in reversed(all_services):
                    record = state.get(service.name) or find_owned_listener(service)
                    stopped = bool(record and stop_record(service, record))
                    if not stopped:
                        current = find_owned_listener(service)
                        if current and current != record:
                            stopped = stop_record(service, current)
                        if current and not stopped:
                            remaining[service.name] = current
                    message = '已停止' if stopped else ('停止失败，请重试' if service.name in remaining else '未找到可确认属于本项目的进程')
                    print(f'{service.name}: {message}')
                write_state(RUNTIME, remaining)
                if remaining:
                    return 1
            else:
                for service in all_services:
                    print(f'{service.name}: ' + ('运行正常' if find_owned_listener(service) and healthy(service) else '未运行或未通过检查'))
        return 0
    except (LaunchError, OSError, psutil.Error) as exc:
        print(f'启动管理失败：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
