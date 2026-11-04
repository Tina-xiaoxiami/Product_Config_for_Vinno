"""One bounded, isolated execution of the existing four-file name coverage command."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import signal
import sqlite3
import subprocess
import sys
import time

TESTS = [
    'backend/tests/test_feature_name_reviews.py',
    'backend/tests/test_feature_name_standards_api.py',
    'backend/tests/test_standard_name_policy.py',
    'backend/tests/test_feature_standard_sync.py',
]

GUARD = '''import faulthandler, os, signal, socket, sys, time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
_stack_file = open(Path(os.environ['NAME_DIAG_STACK_DIR']) / f'pid-{os.getpid()}.log', 'a')
faulthandler.enable(file=_stack_file, all_threads=True)
faulthandler.register(signal.SIGUSR1, file=_stack_file, all_threads=True)
faulthandler.dump_traceback_later(45, repeat=True, file=_stack_file)
print(f"PHASE python.start pid={os.getpid()} time={time.monotonic():.6f}", flush=True)
allowed = Path(os.environ['NAME_DIAG_ALLOWED_ROOT']).resolve()
def audit(event, args):
    if event == 'socket.connect' and args[0].family in (socket.AF_INET, socket.AF_INET6):
        raise RuntimeError('Diagnostic refuses network connections, including model APIs')
    if event == 'sqlite3.connect':
        value = os.fspath(args[0])
        if value == ':memory:': return
        if value.startswith('file:'):
            uri = urlparse(value)
            if uri.path == ':memory:' or parse_qs(uri.query).get('mode') == ['memory']: return
            value = unquote(uri.path)
        target = Path(value).resolve()
        if not target.is_relative_to(allowed):
            raise RuntimeError('Diagnostic refused SQLite access outside its temporary root')
sys.addaudithook(audit)
'''

HOOKS = '''import time, pytest
def phase(message):
    print(f"PHASE {time.monotonic():.6f} {message}", flush=True)
def pytest_configure(config): phase('pytest.configure')
def pytest_sessionstart(session): phase('pytest.sessionstart')
def pytest_collection(session): phase('pytest.collection.begin')
def pytest_collectstart(collector): phase('collect ' + collector.nodeid)
def pytest_collection_finish(session): phase('pytest.collection.end count=' + str(len(session.items)))
def pytest_runtest_logstart(nodeid, location): phase('test.begin ' + nodeid)
def pytest_runtest_logreport(report): phase('test.' + report.when + ' ' + report.outcome + ' ' + report.nodeid)
@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    phase('fixture.begin ' + fixturedef.argname)
    yield
    phase('fixture.end ' + fixturedef.argname)
def pytest_sessionfinish(session, exitstatus): phase('pytest.session.end exit=' + str(exitstatus))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seconds', type=int, default=285)
    args = parser.parse_args()
    if not 30 <= args.seconds <= 300:
        parser.error('The hard limit must be between 30 and 300 seconds')
    root, output = args.root.resolve(), args.output.resolve()
    allowed = output.parent.resolve()
    if not root.is_relative_to(allowed) or root == allowed or output == root:
        parser.error('Source and output must be separate children of one isolated temporary root')
    output.mkdir(parents=True, exist_ok=False)
    runtime, guard = output / 'runtime', output / 'guard'
    runtime.mkdir()
    guard.mkdir()
    (output / 'stacks').mkdir()
    (guard / 'sitecustomize.py').write_text(GUARD)
    (guard / 'name_step_hooks.py').write_text(HOOKS)
    command = [sys.executable, '-u', '-m', 'pytest', *TESTS, '-q',
               '--cov-config=backend/coverage.ini', '--cov=app.services.feature_name_reviews',
               '--cov=app.services.feature_standard_sync', '--cov=app.api.feature_standards',
               '--cov-report=term-missing', '--cov-fail-under=80',
               '-vv', '-s', '--setup-show', '-p', 'name_step_hooks',
               '-o', 'faulthandler_timeout=30', '-o', f'cache_dir={output / "pytest-cache"}',
               '--basetemp', str(output / 'pytest-tmp')]
    environment = dict(os.environ)
    for name in ['PYTEST_ADDOPTS', 'PYTEST_PLUGINS', 'COVERAGE_PROCESS_START']:
        environment.pop(name, None)
    environment.update({
        'PYTHONUNBUFFERED': '1', 'PYTHONFAULTHANDLER': '1',
        'PYTHONPATH': os.pathsep.join([str(guard), str(root)]),
        'NAME_DIAG_ALLOWED_ROOT': str(allowed),
        'NAME_DIAG_STACK_DIR': str(output / 'stacks'),
        'DATABASE_URL': f'sqlite+aiosqlite:///{runtime / "config.db"}',
        'COVERAGE_FILE': str(output / '.coverage'),
        'WHITEPAPER_SUBSERIES_FILE': str(runtime / 'subseries.json'),
        'KNOWLEDGE_EVIDENCE_CONFIG': str(runtime / 'unconfigured-evidence.json'),
        'RELEASE_WORKBENCH_DATABASE': str(runtime / 'release.db'),
        'VINNO_PRODUCT_MODEL_SETTINGS': str(runtime / 'unconfigured-models.json'),
    })
    metadata = {'python': sys.version, 'executable': sys.executable,
                'platform': platform.platform(), 'machine': platform.machine(),
                'sqlite': sqlite3.sqlite_version, 'hard_limit_seconds': args.seconds,
                'command': command, 'source': str(root), 'output': str(output),
                'image_version': os.environ.get('ImageVersion'),
                'packages': {d.metadata['Name']: d.version for d in importlib.metadata.distributions()}}
    (output / 'environment.json').write_text(json.dumps(metadata, indent=2))
    print('PHASE supervisor.launch', json.dumps({'command': command, 'output': str(output)}), flush=True)
    started = time.monotonic()
    timed_out = False
    with (output / 'probe.log').open('wb', buffering=0) as log:
        process = subprocess.Popen(command, cwd=root, env=environment, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=args.seconds - 15)
        except subprocess.TimeoutExpired:
            timed_out = True
            print('PHASE supervisor.dump_then_stop', flush=True)
            try:
                os.killpg(process.pid, signal.SIGUSR1)
            except ProcessLookupError:
                pass
            time.sleep(3)
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        finally:
            # A finished leader does not prove that its subprocess group is empty.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=3)
    result = {'timed_out': timed_out, 'returncode': process.returncode,
              'elapsed_seconds': round(time.monotonic() - started, 3),
              'log': str(output / 'probe.log')}
    (output / 'result.json').write_text(json.dumps(result, indent=2))
    print('PHASE supervisor.complete', json.dumps(result), flush=True)
    return 124 if timed_out else process.returncode


if __name__ == '__main__':
    raise SystemExit(main())
