"""Read the whitepaper workspace's JSON contract; never copy or change its data.

The document application's wp package depends on its own runtime. This small
adapter consumes its public sub_series file contract without importing that app.
"""
import json
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
    vault = Path(os.environ.get('WP_VAULT', '~/Documents/Obsidian Vault/产品配置管理系统')).expanduser()
    path = Path(os.environ.get('WHITEPAPER_SUBSERIES_FILE', str(vault / '白皮书工作区/子系列.json'))).expanduser()
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
