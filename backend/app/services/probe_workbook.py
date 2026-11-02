"""Explicit, round-trippable probe totals and per-model differences."""
import io
import json

from fastapi import HTTPException
from openpyxl import Workbook
from app.services.config_workbook import load_config_workbook
from app.services.probe_workspace import encode, row_key

ROW_FIELDS = ['probe_model_id', 'variant_id', 'feature_id', 'defined_status', 'current_status',
              'defined_excludes', 'current_excludes', 'notes']
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
    total.append(ROW_FIELDS)
    for row in payload['data']['rows']:
        total.append([encode(row.get(f, [])) if f.endswith('_excludes') else row.get(f) for f in ROW_FIELDS])
    differences = workbook.create_sheet('机型差异')
    differences.append(['model_id', 'row_key', *RULE_FIELDS])
    for mid, rules in payload['data']['overrides'].items():
        for key, rule in rules.items():
            differences.append([int(mid), key, *[
                encode(rule[f]) if f.endswith('_excludes') and f in rule else
                '""' if f == 'notes' and rule.get(f) == '' else rule.get(f) for f in RULE_FIELDS]])
    results = workbook.create_sheet('机型结果')
    fields = ['model_id', 'model_name', 'key', 'probe_name', 'ipn', 'feature_name', 'defined_status',
              'current_status', 'defined_excludes', 'current_excludes', 'defined_reason', 'current_reason', 'notes']
    results.append(fields)
    for row in payload['results']:
        results.append([encode(row.get(f)) if isinstance(row.get(f), (list, dict)) else row.get(f) for f in fields])
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
            if [c.value for c in sheet[1]][:len(fields)] != fields:
                raise ValueError(f'{sheet_name}表头不匹配')
            for number, cells in enumerate(sheet.iter_rows(min_row=2, max_col=len(fields), values_only=True), 2):
                if all(v is None for v in cells):
                    continue
                entry = dict(zip(fields, cells))
                rule = {}
                for field in RULE_FIELDS:
                    value = entry[field]
                    if value is None:
                        if sheet_name == '共同总集':
                            rule[field] = [] if field.endswith('_excludes') else '' if field == 'notes' else 'pending'
                        continue
                    rule[field] = json.loads(value) if field.endswith('_excludes') else '' if field == 'notes' and value == '""' else value
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
