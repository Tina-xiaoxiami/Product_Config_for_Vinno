"""Evidence-bound corrections to current exclusion names; history stays immutable."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3

from openpyxl import load_workbook

from app.utils.time import utcnow


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _names(value):
    if value is None:
        return []
    parsed = json.loads(value) if isinstance(value, str) else value
    names = parsed.get('excludes', []) if isinstance(parsed, dict) else parsed
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError('排除应用数据结构无效，未执行修复')
    return names


def _replace_list(names, replacements):
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError('排除应用必须是名称列表，未执行修复')
    updated = [replacements.get(name, name) for name in names]
    return list(dict.fromkeys(updated)) if updated != names else names


def _replace_json(value, replacements):
    if not value:
        return value
    parsed = json.loads(value)
    before = _names(parsed)
    after = _replace_list(before, replacements)
    if before == after:
        return value
    if isinstance(parsed, dict):
        parsed['excludes'] = after
    else:
        parsed = after
    return json.dumps(parsed, ensure_ascii=False)


def _verify_source(source, evidence):
    if _hash(source) != evidence['sha256']:
        raise ValueError('原始资料摘要已变化，未执行修复')
    workbook = load_workbook(source, read_only=True, data_only=False)
    try:
        for record in evidence['records']:
            sheet = workbook[record['source_sheet']]
            for cell_field, value_field in [('source_cell', 'source_value'),
                                           ('apps_regular_cell', 'apps_regular_value'),
                                           ('apps_poc_cell', 'apps_poc_value')]:
                if sheet[record[cell_field]].value != record[value_field]:
                    raise ValueError(f"证据单元格不一致：{record['source_sheet']}!{record[cell_field]}")
    finally:
        workbook.close()
    if _hash(source) != evidence['sha256']:
        raise ValueError('核对期间原始资料摘要已变化，未执行修复')


def repair_exclusions(database, source, evidence, *, apply=False):
    """Preview or atomically apply only proved token corrections in mutable rows.

    The file fingerprint and each source cell are checked again on every run.
    Existing versions, published workspace data and release snapshots are never
    rewritten. Workspace revisions advance so an older open editor cannot undo
    a correction. No application, support state or model membership is inferred.
    """
    from app.services.probe_exclusion_rules import parse_exclusions

    _verify_source(source, evidence)
    path = Path(database).resolve(strict=True)
    connection = sqlite3.connect(path.as_uri() + ('?mode=rw' if apply else '?mode=ro'), uri=True)
    connection.row_factory = sqlite3.Row
    changes, unresolved = [], []
    try:
        connection.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        categories = {row['id']: row['name'] for row in connection.execute('SELECT id,name FROM probe_categories')}
        features = {row['id']: row['name'] for row in connection.execute('SELECT id,name FROM features')}
        templates = {row['id']: dict(row) for row in connection.execute('SELECT * FROM template_features')}
        apps = {}
        for row in connection.execute('SELECT ca.category_id,a.name FROM category_applications ca JOIN applications a ON a.id=ca.application_id'):
            apps.setdefault(row['category_id'], set()).add(row['name'])
        mappings = {}
        seen = set()
        for record in evidence['records']:
            template_id = record['template_id']
            if template_id in seen:
                raise ValueError('证据包含重复模板记录，未执行修复')
            seen.add(template_id)
            row = templates.get(template_id)
            if (row is None or (row['category_id'], row['feature_id']) != (record['category_id'], record['feature_id'])
                    or categories.get(row['category_id']) != record['category'] or features.get(row['feature_id']) != record['feature']):
                raise ValueError(f'模板 {template_id} 的身份已变化，未执行修复')
            if record['decision'] == 'source_conflict':
                conflict = deepcopy(record)
                conflict['current_excludes'] = _names(row['default_excludes'])
                conflict['current_application_names'] = sorted(apps.get(row['category_id'], set()))
                unresolved.append(conflict)
                continue
            if record['decision'] != 'resolved':
                raise ValueError('证据决定无效，未执行修复')
            expected = record['normalized_excludes']
            if not set(expected).issubset(apps.get(row['category_id'], set())):
                raise ValueError(f'模板 {template_id} 的当前类别应用已变化，未执行修复')
            raw = parse_exclusions(record['source_value'], apps[row['category_id']])
            if raw != expected or _replace_list(record['original_excludes'], record['token_replacements']) != expected:
                raise ValueError(f'模板 {template_id} 的名称映射无法由原件证明，未执行修复')
            if _names(row['default_excludes']) not in [record['original_excludes'], expected]:
                raise ValueError(f'模板 {template_id} 的排除选择已变化，未执行修复')
            mappings[(row['category_id'], row['feature_id'])] = record['token_replacements']
            after = _replace_json(row['default_excludes'], record['token_replacements'])
            if after != row['default_excludes']:
                changes.append({'table': 'template_features', 'id': template_id,
                                'fields': {'default_excludes': {'before': row['default_excludes'], 'after': after}}})

        def add_text_changes(table, fields, category_for):
            if table not in tables:
                return
            for row in connection.execute(f'SELECT * FROM {table} ORDER BY id'):
                replacements = mappings.get((category_for(row), row['feature_id']))
                if not replacements:
                    continue
                values = {}
                for field in fields:
                    before = row[field]
                    after = _replace_json(before, replacements)
                    if before != after:
                        values[field] = {'before': before, 'after': after}
                if values:
                    changes.append({'table': table, 'id': row['id'], 'fields': values})

        probes = {row['id']: row['category_id'] for row in connection.execute('SELECT id,category_id FROM probe_models')}
        add_text_changes('template_drafts', ['old_excludes', 'new_excludes'], lambda row: row['category_id'])
        add_text_changes('product_probe_configs', ['defined_excludes', 'current_excludes'], lambda row: probes.get(row['probe_model_id']))
        add_text_changes('probe_config_drafts', ['old_excludes', 'new_excludes'], lambda row: probes.get(row['probe_model_id']))
        if 'probe_workspaces' in tables:
            for row in connection.execute('SELECT id,revision,draft_data FROM probe_workspaces ORDER BY id'):
                if not row['draft_data']:
                    continue
                document = json.loads(row['draft_data'])
                locations = []
                rows_by_key = {}
                for index, rule in enumerate(document.get('rows', [])):
                    key = f"{rule['probe_model_id']}:{rule.get('variant_id') or 0}:{rule['feature_id']}"
                    rows_by_key[key] = rule
                    replacements = mappings.get((probes.get(rule['probe_model_id']), rule['feature_id']), {})
                    for side in ('defined_excludes', 'current_excludes'):
                        if side in rule:
                            before = rule[side]
                            after = _replace_list(before, replacements)
                            if before != after:
                                locations.append({'location': f'rows/{index}/{side}', 'row_key': key, 'before': before, 'after': after})
                                rule[side] = after
                for model_id, rules in document.get('overrides', {}).items():
                    for key, rule in rules.items():
                        total = rows_by_key.get(key)
                        replacements = mappings.get((probes.get(total['probe_model_id']), total['feature_id']), {}) if total else {}
                        for side in ('defined_excludes', 'current_excludes'):
                            if side in rule:
                                before = rule[side]
                                after = _replace_list(before, replacements)
                                if before != after:
                                    locations.append({'location': f'overrides/{model_id}/{key}/{side}', 'row_key': key, 'before': before, 'after': after})
                                    rule[side] = after
                if locations:
                    changes.append({'table': 'probe_workspaces', 'id': row['id'], 'locations': locations,
                                    'fields': {'draft_data': {'before': row['draft_data'], 'after': json.dumps(document, ensure_ascii=False)},
                                               'revision': {'before': row['revision'], 'after': row['revision'] + 1}}})

        counts = {table: sum(item['table'] == table for item in changes) for table in
                  ['template_features', 'template_drafts', 'product_probe_configs', 'probe_config_drafts', 'probe_workspaces']}
        version_id = None
        if apply:
            for item in changes:
                names = list(item['fields'])
                connection.execute(f"UPDATE {item['table']} SET " + ','.join(f'{field}=?' for field in names) + ' WHERE id=?',
                                   [item['fields'][field]['after'] for field in names] + [item['id']])
            if counts['template_features']:
                snapshot = {'schema_version': 2,
                            'templates': [dict(item) for item in connection.execute('SELECT category_id,feature_id,default_support,default_excludes FROM template_features ORDER BY category_id,feature_id')],
                            'features': [dict(item) for item in connection.execute('SELECT id AS feature_id,group_id FROM features WHERE probe_matrix_enabled=1 ORDER BY id')]}
                from app.services.template_feature_catalog import read_template_snapshot
                encoded = json.dumps(snapshot, ensure_ascii=False)
                read_template_snapshot(encoded)
                cursor = connection.execute('INSERT INTO template_versions(version_number,description,snapshot_data,created_at) VALUES(?,?,?,?)',
                    ('exclusion-names-20261104-' + evidence['sha256'][:8],
                     f"按原件逐格规范 {counts['template_features']} 条排除名称；来源 SHA256 {evidence['sha256']}；保留 {len(unresolved)} 条原件范围冲突及全部旧版本。",
                     encoded, utcnow().isoformat()))
                version_id = cursor.lastrowid
            connection.commit()
        else:
            connection.rollback()
        return {'applied': apply, 'source_filename': evidence['source_filename'], 'source_sha256': evidence['sha256'],
                'counts': counts, 'changed_templates': counts['template_features'], 'changed_workspaces': counts['probe_workspaces'],
                'template_version_id': version_id, 'unresolved': unresolved, 'changes': changes}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
