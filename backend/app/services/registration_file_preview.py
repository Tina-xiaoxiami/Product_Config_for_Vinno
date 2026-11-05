"""Read-only suggestions from a registration certificate and difference workbook."""

from datetime import date
from pathlib import Path
import re
import unicodedata

from app.services.knowledge_content import _pdf_blocks
from app.services.registration_rules import parse_domestic_registration_workbook


def preview_certificate(path: str | Path) -> dict:
    blocks = _pdf_blocks(Path(path))
    candidates: dict[str, dict[str, str]] = {'registration_number': {}, 'effective_date': {}}
    for block in blocks:
        text = unicodedata.normalize('NFKC', block.text)
        for match in re.finditer(r'注册证(?:编号|号)\s*[:：]?\s*([^\s，,;；]+)', text):
            value = match.group(1).strip('。.')
            if re.fullmatch(r'[\u4e00-\u9fff]{1,10}械注(?:准|进|许)\d{7,15}', value):
                candidates['registration_number'][value] = block.source_ref
        for match in re.finditer(r'(?:注册日期|生效日期)\s*[:：]?\s*(\d{4})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*日?', text):
            try:
                value = date(*(int(part) for part in match.groups())).isoformat()
            except ValueError:
                continue
            candidates['effective_date'][value] = block.source_ref
    fields, evidence, warnings = {}, {}, []
    for key, label in [('registration_number', '注册证号'), ('effective_date', '生效日期')]:
        values = candidates[key]
        if len(values) == 1:
            value, source = next(iter(values.items()))
            fields[key], evidence[key] = value, source
        else:
            warnings.append(f'{label}未识别到唯一结果，请对照原件填写。')
    if not blocks:
        warnings.insert(0, '未能提取 PDF 文字，可能需要 OCR 或人工填写。')
    return {'fields': fields, 'evidence': evidence, 'warnings': warnings}


def preview_difference(path: str | Path) -> dict:
    parsed = parse_domestic_registration_workbook(path)
    return {'model_count': len(parsed.models), 'probe_count': len(parsed.probes)}
