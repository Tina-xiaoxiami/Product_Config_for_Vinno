"""Use the shared whitepaper workspace contract without copying its definitions.

The document application's wp package depends on its own runtime. This small
adapter consumes its public sub_series file contract without importing that app.
"""
import hashlib
import json
import stat
import tempfile
import threading
from contextlib import contextmanager
import os
import re
import unicodedata
from pathlib import Path


def _model_key(name):
    # Same strict spelling rules as wp.configdb.strict_model_name: keep edition
    # qualifiers and underscores; remove only brand, language tag and spacing.
    name = unicodedata.normalize('NFKC', name).strip().casefold()
    name = re.sub(r'^\[en\]\s*', '', name)
    name = re.sub(r'^(?:vinno|ultimus)(?:\s+|(?=\d))', '', name)
    name = re.sub(r'\s+', '', name)
    return re.sub(r'^v(?=\d+(?:exp|pro|s)?$)', '', name)


def read_subseries(models, series_names):
    path = subseries_path()
    memberships = {model.id: [] for model in models}
    problems = []
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return memberships, ['未找到白皮书子系列定义，请检查共享工作区路径']
    except (OSError, ValueError):
        return memberships, ['白皮书子系列读取失败，请检查共享定义文件']
    entries = raw if isinstance(raw, list) else raw.get('sub_series') if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return memberships, ['白皮书子系列定义必须包含 sub_series 数组']
    seen = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or not entry['name'].strip() or not isinstance(entry.get('models'), list) or not entry['models'] or not all(isinstance(m, str) and m.strip() for m in entry['models']) or not isinstance(entry.get('series', ''), str):
            problems.append(f'白皮书子系列第 {index + 1} 条无效，已忽略')
            continue
        name = entry['name'].strip()
        if name in seen:
            problems.append(f'白皮书子系列「{name}」重名，已忽略')
            continue
        seen.add(name)
        parent = entry.get('series', '').strip()
        pool = [model for model in models if not parent or series_names.get(model.series_id) == parent]
        for product in entry['models']:
            matches = [model for model in pool if _model_key(model.name) == _model_key(product)]
            # One product may belong to several markets, but never guess between
            # two active identities within the same parent series.
            for sid in dict.fromkeys(model.series_id for model in matches):
                candidates = [model for model in matches if model.series_id == sid]
                if len(candidates) != 1:
                    problems.append(f'子系列「{name}」的机型「{product}」对应不唯一，未自动归类')
                elif name not in memberships[candidates[0].id]:
                    memberships[candidates[0].id].append(name)
    return memberships, problems


class SubseriesSourceError(ValueError):
    """The shared source could not safely be read or written."""


class SubseriesConflictError(ValueError):
    """Another editor saved after this revision was read."""


def subseries_path():
    vault = Path(os.environ.get('WP_VAULT', '~/Documents/Obsidian Vault/产品配置管理系统')).expanduser()
    return Path(os.environ.get('WHITEPAPER_SUBSERIES_FILE', str(vault / '白皮书工作区/子系列.json'))).expanduser().resolve()


_lock_guard = threading.Lock()
_local_locks = {}


@contextmanager
def _source_lock(path):
    # Same resource key and lock-file protocol as wp.resources.resource_lock.
    key = 'subseries:' + os.path.realpath(path)
    folder = os.environ.get('WP_RESOURCE_LOCK_DIR') or os.path.join(
        tempfile.gettempdir(), 'wp-resource-locks-' + hashlib.sha256(
            os.path.expanduser('~').encode()).hexdigest()[:16])
    identity = (os.path.realpath(folder), key)
    with _lock_guard:
        lock = _local_locks.setdefault(identity, threading.RLock())
    with lock:
        os.makedirs(folder, mode=0o700, exist_ok=True)
        lock_path = os.path.join(folder, hashlib.sha256(key.encode()).hexdigest() + '.lock')
        with open(lock_path, 'a+b') as stream:
            if os.name == 'nt':
                import msvcrt
                import errno
                import time
                if not os.path.getsize(lock_path):
                    stream.write(b'0')
                    stream.flush()
                while True:
                    try:
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError as error:
                        if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) and getattr(error, 'winerror', None) != 33:
                            raise
                        time.sleep(.05)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == 'nt':
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _source_document(path):
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return {'sub_series': []}, hashlib.sha256(b'').hexdigest()
    except OSError as error:
        raise SubseriesSourceError('子系列共享文件读取失败，请检查工作区权限') from error
    try:
        raw = json.loads(content)
        entries = raw if isinstance(raw, list) else raw.get('sub_series') if isinstance(raw, dict) else None
        if not isinstance(entries, list):
            raise ValueError('sub_series must be an array')
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or not entry['name'].strip() or not isinstance(entry.get('series', ''), str) or not isinstance(entry.get('models'), list) or not entry['models'] or any(not isinstance(name, str) or not name.strip() for name in entry['models']):
                raise ValueError('invalid group')
            if entry['name'].strip() in seen:
                raise ValueError('duplicate group')
            seen.add(entry['name'].strip())
    except (ValueError, TypeError, UnicodeError) as error:
        raise SubseriesSourceError('子系列共享定义无效，请先在源文件中修复，当前内容未覆盖') from error
    document = {'sub_series': entries} if isinstance(raw, list) else raw
    return document, hashlib.sha256(content).hexdigest()


def _group_matches(value, parent, models, parents):
    return [model for model in models if (not parent or parents.get(model.series_id) == parent)
            and _model_key(model.name) == _model_key(value)]


def _unambiguous_per_series(matches):
    return len({model.series_id for model in matches}) == len(matches)


def _editor_view(document, revision, models, parents):
    groups = []
    for source in document['sub_series']:
        name = source['name'].strip()
        parent = source.get('series', '').strip()
        members = list(dict.fromkeys(member.strip() for member in source['models']))
        original_by_id = {}
        unresolved = []
        for member in members:
            matches = _group_matches(member, parent, models, parents)
            if matches and _unambiguous_per_series(matches):
                for model in matches:
                    original_by_id.setdefault(model.id, member)
            else:
                unresolved.append(member)
        options = [
            {'id': model.id, 'value': original_by_id.get(model.id, model.name),
             'label': model.name, 'series': parents.get(model.series_id, '')}
            for model in models if not parent or parents.get(model.series_id) == parent
        ]
        for member in unresolved:
            options = [option for option in options if option['value'] != member]
            options.append({'value': member, 'label': member + '（未匹配，保留）'})
        # Preserve every original spelling if two stored aliases share one ID.
        values = {option['value'] for option in options}
        options.extend({'value': member, 'label': member + '（原成员）'}
                       for member in members if member not in values)
        # One spelling may legitimately cover the same product in both markets.
        # Keep one select value and show all owning series in its label.
        unique_options = {}
        for option in options:
            value = option['value']
            if value not in unique_options:
                unique_options[value] = dict(option)
            else:
                previous = unique_options[value]
                if previous.get('id') != option.get('id'):
                    labels = [previous['label'], option['label']]
                    series = [previous.get('series'), option.get('series')]
                    previous['label'] = ' / '.join(dict.fromkeys(labels)) + '（' + '、'.join(dict.fromkeys(filter(None, series))) + '）'
                    previous.pop('id', None)
                    previous.pop('series', None)
        groups.append({'name': name, 'series': parent, 'models': members, 'options': list(unique_options.values())})
    return {
        'revision': revision,
        'groups': groups,
        'catalog': [{'id': model.id, 'name': model.name, 'series_id': model.series_id,
                     'series': parents.get(model.series_id, '')} for model in models],
        'series': [{'id': sid, 'name': name} for sid, name in parents.items()],
    }


def get_subseries_editor(models, parents):
    path = subseries_path()
    document, revision = _source_document(path)
    return _editor_view(document, revision, models, parents)


def save_subseries_editor(groups, revision, models, parents):
    path = subseries_path()
    try:
        with _source_lock(path):
            document, current_revision = _source_document(path)
            if revision != current_revision:
                raise SubseriesConflictError('子系列已被其他页面修改，请重新载入后再保存；当前编辑仍保留')
            if not isinstance(groups, list):
                raise ValueError('子系列必须是数组')
            preserved = {(entry.get('series', '').strip(), value.strip())
                         for entry in document['sub_series'] for value in entry['models']}
            names = set()
            cleaned = []
            for index, group in enumerate(groups):
                if not isinstance(group, dict):
                    raise ValueError(f'第 {index + 1} 个子系列无效')
                name = group.get('name')
                parent = group.get('series', '')
                members = group.get('models')
                if not isinstance(name, str) or not name.strip():
                    raise ValueError(f'第 {index + 1} 个子系列名称不能为空')
                name = name.strip()
                if name in names:
                    raise ValueError(f'子系列名称重复：{name}')
                names.add(name)
                if not isinstance(parent, str):
                    raise ValueError('所属系列无效')
                parent = parent.strip()
                if parent and parent not in parents.values():
                    raise ValueError(f'所属系列不存在：{parent}')
                if not isinstance(members, list) or not members or any(not isinstance(member, str) or not member.strip() for member in members):
                    raise ValueError(f'子系列「{name}」至少选择一个机型')
                members = list(dict.fromkeys(member.strip() for member in members))
                for member in members:
                    matches = _group_matches(member, parent, models, parents)
                    if not _unambiguous_per_series(matches):
                        raise ValueError(f'机型「{member}」对应不唯一，请明确所属系列或核对配置机型')
                    if not matches and (parent, member) not in preserved:
                        raise ValueError(f'机型「{member}」不在所选系列的配置机型中')
                cleaned.append({'name': name, 'series': parent, 'models': members})
            updated = {**document, 'sub_series': cleaned}
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
            fd, temporary = tempfile.mkstemp(prefix='.subseries-', suffix='.json', dir=path.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    os.chmod(temporary, mode)
                    json.dump(updated, stream, ensure_ascii=False, indent=2)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            saved, saved_revision = _source_document(path)
            return _editor_view(saved, saved_revision, models, parents)
    except OSError as error:
        raise SubseriesSourceError('子系列保存失败，请检查共享工作区权限；当前编辑仍保留') from error
