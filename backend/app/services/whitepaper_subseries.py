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
    if any(isinstance(entry, dict) and 'model_refs' in entry for entry in entries):
        try:
            document, _ = _source_document(path)
            view = _editor_view(document, '', models, series_names)
        except (ValueError, TypeError, KeyError):
            return memberships, ['白皮书子系列定义无效，请检查共享定义文件']
        for group in view['groups']:
            for model_id in group['model_ids']:
                memberships[model_id].append(group['name'])
            if group['missing_models']:
                problems.append(f"子系列「{group['name']}」有未匹配或不唯一机型，请核对")
        return memberships, problems
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


_OMITTED = object()


def _clean_combinations(combinations, group_names):
    """Validate direct group references before resolving or persisting them."""
    if not isinstance(combinations, list):
        raise ValueError('子系列组合必须是数组')
    cleaned = []
    names = set()
    for index, combination in enumerate(combinations):
        if not isinstance(combination, dict):
            raise ValueError(f'第 {index + 1} 个子系列组合无效')
        name = combination.get('name')
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f'第 {index + 1} 个子系列组合名称不能为空')
        name = name.strip()
        if name in names:
            raise ValueError(f'子系列组合名称重复：{name}')
        names.add(name)
        references = combination.get('sub_series')
        if not isinstance(references, list) or not references or any(
                not isinstance(reference, str) or not reference.strip() for reference in references):
            raise ValueError(f'子系列组合「{name}」至少选择一个有效子系列')
        references = list(dict.fromkeys(reference.strip() for reference in references))
        for reference in references:
            if reference not in group_names:
                raise ValueError(f'子系列组合「{name}」引用的子系列不存在：{reference}；请同步更新组合')
        cleaned.append({'name': name, 'sub_series': references})
    return cleaned


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
            if 'series_names' in entry and (not isinstance(entry['series_names'], list) or any(not isinstance(value, str) or not value.strip() for value in entry['series_names'])):
                raise ValueError('invalid series_names')
            if 'model_refs' in entry and (not isinstance(entry['model_refs'], list) or any(not isinstance(ref, dict) or not isinstance(ref.get('series'), str) or not isinstance(ref.get('name'), str) or not ref['name'].strip() for ref in entry['model_refs'])):
                raise ValueError('invalid model_refs')
            if entry['name'].strip() in seen:
                raise ValueError('duplicate group')
            seen.add(entry['name'].strip())
    except (ValueError, TypeError, UnicodeError) as error:
        raise SubseriesSourceError('子系列共享定义无效，请先在源文件中修复，当前内容未覆盖') from error
    document = {'sub_series': entries} if isinstance(raw, list) else raw
    try:
        _clean_combinations(document.get('sub_series_combinations', []), seen)
    except ValueError as error:
        raise SubseriesSourceError(f'子系列组合共享定义无效，请先在源文件中修复，当前内容未覆盖：{error}') from error
    return document, hashlib.sha256(content).hexdigest()


def _group_matches(value, parent, models, parents):
    return [model for model in models if (not parent or parents.get(model.series_id) == parent)
            and _model_key(model.name) == _model_key(value)]


def _unambiguous_per_series(matches):
    return len({model.series_id for model in matches}) == len(matches)


def _entry_series(source):
    return source.get('series_names', [source['series']] if source.get('series') else [])


def _entry_matches(source, models, parents):
    refs = source.get('model_refs')
    if refs is not None:
        return [(ref['name'], (_group_matches(ref['name'], ref['series'], models, parents) if ref['series'] else [])) for ref in refs]
    series = _entry_series(source)
    pool = [model for model in models if not series or parents.get(model.series_id) in series]
    return [(member, _group_matches(member, '', pool, parents)) for member in source['models']]


def _editor_view(document, revision, models, parents):
    groups = []
    for source in document['sub_series']:
        if 'model_refs' not in source:
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
            groups.append({'name': name, 'series': parent, 'models': members,
                           'model_ids': list(original_by_id), 'missing_models': unresolved,
                           'options': list(unique_options.values())})
            continue
        original_by_id, unresolved = {}, []
        for member, matches in _entry_matches(source, models, parents):
            if matches and _unambiguous_per_series(matches):
                for model in matches:
                    original_by_id.setdefault(model.id, member)
            else:
                unresolved.append(member)
        groups.append({'name': source['name'].strip(), 'series': source.get('series', ''),
                       'series_names': _entry_series(source),
                       'models': list(dict.fromkeys(source['models'])),
                       'model_ids': list(original_by_id), 'missing_models': unresolved,
                       'unresolved_refs': [ref for ref in source.get('model_refs', []) if not ref['series'] or not _group_matches(ref['name'], ref['series'], models, parents) or not _unambiguous_per_series(_group_matches(ref['name'], ref['series'], models, parents))],
                       'options': []})
    by_name = {group['name']: group for group in groups}
    combinations = []
    for source in _clean_combinations(document.get('sub_series_combinations', []), by_name):
        referenced = [by_name[name] for name in source['sub_series']]
        combinations.append({**source,
                             'model_ids': list(dict.fromkeys(
                                 model_id for group in referenced for model_id in group['model_ids'])),
                             'missing_models': [f"{group['name']}：{member}"
                                                for group in referenced for member in group['missing_models']]})
    return {
        'revision': revision,
        'groups': groups,
        'combinations': combinations,
        'catalog': [{'id': model.id, 'name': model.name, 'series_id': model.series_id,
                     'series': parents.get(model.series_id, '')} for model in models],
        'series': [{'id': sid, 'name': name} for sid, name in parents.items()],
    }


def get_subseries_editor(models, parents):
    path = subseries_path()
    document, revision = _source_document(path)
    return _editor_view(document, revision, models, parents)


def save_subseries_editor(groups, revision, models, parents, combinations=_OMITTED):
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
                previous = next((entry for entry in document['sub_series'] if entry['name'] == name), {})
                if 'model_refs' in previous and ('series_names' not in group or 'model_ids' not in group):
                    raise ValueError('此分组使用精确机型，请重新加载后在产品型号页维护')
                parent = group.get('series', '')
                members = group.get('models', [])
                if 'series_names' in group and not isinstance(group.get('model_ids'), list):
                    raise ValueError('成员机型必须按精确身份选择，请重新加载')
                selected_ids = group.get('model_ids') if 'series_names' in group else None
                selected_series = group.get('series_names', [parent] if parent else [])
                if not isinstance(selected_series, list) or any(not isinstance(value, str) or value not in parents.values() for value in selected_series):
                    raise ValueError('所属系列无效')
                refs = None
                if selected_ids is not None:
                    if not isinstance(selected_ids, list) or any(type(value) is not int for value in selected_ids):
                        raise ValueError('成员机型无效')
                    by_id = {model.id: model for model in models}
                    refs = []
                    for model_id in dict.fromkeys(selected_ids):
                        model = by_id.get(model_id)
                        if not model or (selected_series and parents.get(model.series_id) not in selected_series):
                            raise ValueError('成员机型不属于所选系列，请核对')
                        if not _unambiguous_per_series(_group_matches(model.name, parents[model.series_id], models, parents)):
                            raise ValueError('成员机型在所属系列中不唯一，请核对配置库')
                        refs.append({'series': parents[model.series_id], 'name': model.name})
                    if not refs and not members:
                        raise ValueError('子系列至少选择一个机型')
                if not isinstance(name, str) or not name.strip():
                    raise ValueError(f'第 {index + 1} 个子系列名称不能为空')
                name = name.strip()
                if name in names:
                    raise ValueError(f'子系列名称重复：{name}')
                names.add(name)
                if not isinstance(parent, str):
                    raise ValueError('所属系列无效')
                parent = parent.strip()
                if not parent and len(selected_series) == 1:
                    parent = selected_series[0]
                if parent and parent not in parents.values():
                    raise ValueError(f'所属系列不存在：{parent}')
                if not isinstance(members, list) or (not members and not refs) or any(not isinstance(member, str) or not member.strip() for member in members):
                    raise ValueError(f'子系列「{name}」至少选择一个机型')
                members = list(dict.fromkeys(member.strip() for member in members))
                if refs is not None:
                    members = [member for member in members if not any(_model_key(member) == _model_key(ref['name']) for ref in refs)]
                for member in members:
                    matches = _group_matches(member, parent, models, parents)
                    if not _unambiguous_per_series(matches):
                        raise ValueError(f'机型「{member}」对应不唯一，请明确所属系列或核对配置机型')
                    if not matches and (parent, member) not in preserved and (previous.get('series', ''), member) not in preserved:
                        raise ValueError(f'机型「{member}」不在所选系列的配置机型中')
                unresolved_refs = group.get('unresolved_refs', [])
                preserved_refs = [ref for entry in document['sub_series'] for ref in entry.get('model_refs', [])]
                if not isinstance(unresolved_refs, list) or any(ref not in preserved_refs for ref in unresolved_refs):
                    raise ValueError('未匹配机型引用无效，请重新加载')
                entry = {'name': name, 'series': parent, 'models': members}
                if refs is not None:
                    entry.update(series_names=list(dict.fromkeys(selected_series)),
                                 model_refs=refs + unresolved_refs + [next((ref for ref in previous.get('model_refs', []) if ref['name'] == member), {'series': parent or previous.get('series', ''), 'name': member}) for member in members if not any(ref['name'] == member for ref in unresolved_refs)],
                                 models=list(dict.fromkeys([ref['name'] for ref in refs + unresolved_refs] + members)))
                cleaned.append(entry)
            updated = {**document, 'sub_series': cleaned}
            # Old clients retain references, but cannot delete/rename a referenced
            # group without explicitly updating its combinations in the same save.
            cleaned_combinations = _clean_combinations(
                document.get('sub_series_combinations', []) if combinations is _OMITTED else combinations,
                names)
            if combinations is not _OMITTED or 'sub_series_combinations' in document:
                updated['sub_series_combinations'] = cleaned_combinations
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
