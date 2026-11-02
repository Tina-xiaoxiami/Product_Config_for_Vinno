"""Explicit, round-trippable probe totals and per-model differences."""
import io
import json

from fastapi import HTTPException
from openpyxl import Workbook
from app.services.config_workbook import load_config_workbook
from app.services.probe_workspace import encode, row_key

ROW_FIELDS = ['probe_model_id', 'variant_id', 'feature_id', 'defined_status', 'current_status',
              'defined_excludes', 'current_excludes', 'notes', 'priority', 'defined_tender', 'current_tender']
RULE_FIELDS = ROW_FIELDS[3:]


def export_workbook(payload, workspace_id, revision):
    workbook = Workbook()
    metadata = workbook.active
    metadata.title = '范围及版本'
    for row in [('format', 'probe-workspace-v1'), ('workspace_id', workspace_id), ('revision', revision),
                ('scope', encode(payload['data']['scope'])),
                ('version_numbers', encode(payload.get('version_numbers', {}))),
                ('说明', '共同总集为完整替换；机型差异中空白=继承总集，[]为清空排除；不得改编号；先预览后保存草稿')]:
        metadata.append(row)
    total = workbook.create_sheet('共同总集')
    cat = payload.get('catalog', {})
    probes = {p['id']: p for p in cat.get('probes', [])}
    variants = {v['id']: v for v in cat.get('variants', [])}
    features = {f['id']: f for f in cat.get('features', [])}
    models = {m['id']: m for snap in payload.get('source_snapshots', {}).values() for m in snap['models']}
    total.append([*ROW_FIELDS, 'row_key', '探头名称（只读）', 'IPN（只读）', '功能名称（只读）'])
    for row in payload['data']['rows']:
        total.append([*[encode(row.get(f, [])) if f.endswith(('_excludes', '_tender')) else row.get(f) for f in ROW_FIELDS],
                      row_key(row), probes.get(row['probe_model_id'], {}).get('name'),
                      variants.get(row.get('variant_id'), {}).get('ipn'), features.get(row['feature_id'], {}).get('name')])
    differences = workbook.create_sheet('机型差异')
    differences.append(['model_id', 'row_key', *RULE_FIELDS, '机型名称（只读）'])
    for mid, rules in payload['data']['overrides'].items():
        for key, rule in rules.items():
            differences.append([int(mid), key, *[
                encode(rule[f]) if f.endswith(('_excludes', '_tender')) and f in rule else
                '""' if f == 'notes' and rule.get(f) == '' else '(清空)' if f == 'priority' and f in rule and rule[f] is None else rule.get(f) for f in RULE_FIELDS], models.get(int(mid), {}).get('name')])
    results = workbook.create_sheet('机型结果')
    fields = ['model_id', 'model_name', 'key', 'probe_name', 'ipn', 'feature_name', 'defined_status',
              'current_status', 'defined_excludes', 'current_excludes', 'defined_tender', 'current_tender', 'defined_reason', 'current_reason', 'notes', 'priority', 'probe_configuration', 'feature_configuration']
    results.append(fields)
    for row in payload['results']:
        results.append([encode(row.get(f)) if isinstance(row.get(f), (list, dict)) else row.get(f) for f in fields])
    directory = workbook.create_sheet('编号与名称对照')
    directory.append(['类别', '编号', '探头编号', '名称', 'IPN / 内部型号'])
    for probe in cat.get('probes', []):
        directory.append(['探头', probe['id'], probe['id'], probe['name'], ''])
    for variant in cat.get('variants', []):
        directory.append(['探头变体', variant['id'], variant['probe_model_id'], '', f"{variant.get('ipn') or ''} / {variant.get('internal_model') or ''}"])
    for feature in cat.get('features', []):
        directory.append(['功能', feature['id'], '', feature['name'], feature.get('ipn')])
    for mid, model in models.items():
        if mid in payload['data']['scope']['model_ids']:
            directory.append(['机型', mid, '', model['name'], ''])
    for sheet in workbook:
        sheet.freeze_panes = 'C2'
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 24
            for cell in column:
                if isinstance(cell.value, str):
                    cell.data_type = 's'
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def import_workbook(content, filename, workspace_id, revision):
    try:
        workbook = load_config_workbook(content, filename or '')
        if not {'范围及版本', '共同总集', '机型差异'} <= set(workbook.sheetnames):
            raise ValueError('请使用本工作区导出的模板，必须包含范围、总集和机型差异工作表')
        if any(cell.data_type == 'f' for sheet in workbook for row in sheet for cell in row):
            raise ValueError('导入内容不能包含公式，请填写明确配置值')
        meta = dict(workbook['范围及版本'].iter_rows(min_row=1, max_col=2, values_only=True))
        if meta.get('format') != 'probe-workspace-v1' or int(meta['workspace_id']) != workspace_id:
            raise ValueError('模板不属于当前共同总集')
        if int(meta['revision']) != revision:
            raise HTTPException(409, '模板已过期，请重新导出后核对')
        document = {'scope': json.loads(meta['scope']), 'rows': [], 'overrides': {}}
        for sheet_name, fields in [('共同总集', ROW_FIELDS), ('机型差异', ['model_id', 'row_key', *RULE_FIELDS])]:
            sheet = workbook[sheet_name]
            headers = [c.value for c in sheet[1]]
            required = [f for f in fields if not f.endswith('_tender')]
            if any(headers.count(f) != 1 for f in required) or any(headers.count(f) > 1 for f in fields):
                raise ValueError(f'{sheet_name}表头不匹配')
            positions = {f: headers.index(f) for f in fields if f in headers}
            for number, cells in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
                entry = {f: cells[positions[f]] if f in positions else None for f in fields}
                if all(v is None for v in entry.values()):
                    continue
                rule = {}
                for field in RULE_FIELDS:
                    value = entry[field]
                    if value is None:
                        if sheet_name == '共同总集':
                            rule[field] = [] if field.endswith(('_excludes', '_tender')) else '' if field == 'notes' else None if field == 'priority' else 'pending'
                        continue
                    rule[field] = json.loads(value) if field.endswith(('_excludes', '_tender')) else '' if field == 'notes' and value == '""' else None if field == 'priority' and value == '(清空)' else value
                if sheet_name == '共同总集':
                    document['rows'].append({**rule, 'probe_model_id': int(entry['probe_model_id']),
                                             'variant_id': int(entry['variant_id']) if entry['variant_id'] else None,
                                             'feature_id': int(entry['feature_id'])})
                else:
                    rules = document['overrides'].setdefault(str(int(entry['model_id'])), {})
                    key = str(entry['row_key'])
                    if key in rules:
                        raise ValueError(f'机型差异第 {number} 行重复或冲突')
                    rules[key] = rule
        return document
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise HTTPException(422, f'Excel 无法导入：{error}') from error
