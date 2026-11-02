"""Read existing feature relationships without inventing family membership."""
from __future__ import annotations

import re
from typing import Any

from tracker.database import Database
from tracker.domain import version_key
from tracker.services.search_intent import family_mentions, family_excerpt, in_version_range


def feature_family(database: Database, query: str, *, project_id: int | None,
                   scope: str, version_from: str = '', version_to: str = '',
                   market: str = '', selected_versions: tuple[str, ...] = ()) -> dict[str, Any]:
    members = []
    for project in database.list_projects():
        if scope != 'all' and project['id'] != (project_id or database.default_project_id()):
            continue
        features = database.list_features(project_id=project['id'])
        direct = {row['id'] for row in features if family_mentions(
            ' '.join(str(row.get(key) or '') for key in ('cn_name', 'en_name', 'cn_description', 'en_description')), query)}
        for row in features:
            explicit = row['id'] in direct
            if not explicit and row['parent_feature_id'] not in direct:
                continue
            detail = database.get_feature(row['id'])
            versions = sorted({r['version'] for key, track in detail['market_releases'].items()
                               if not market or key == market for r in track}, key=version_key)
            if (version_from or version_to or selected_versions) and not any(in_version_range(v, version_from, version_to, selected_versions) for v in versions):
                continue
            if market and not detail['market_releases'].get(market):
                continue
            texts = [row['cn_description'], row['en_description']]
            excerpt = next((text for text in texts if family_mentions(text, query)), texts[0] or texts[1])
            # Keep the family mention visible even deep inside a long description.
            locator = '中文记录' if excerpt == texts[0] else 'English record'
            excerpt = family_excerpt(excerpt, query)
            members.append({
                'feature_id': row['id'], 'project_id': project['id'], 'project_name': project['name'],
                'title': ' / '.join(filter(None, (row['cn_name'], row['en_name']))),
                'relation': 'explicit_mention' if explicit else 'declared_child',
                'parent_name': row.get('parent_cn_name') or row.get('parent_en_name') or '',
                'excerpt': excerpt, 'linked_versions': versions,
                'codes': sorted(set(re.findall(r'\bV\d{4,}\b', ' '.join([row['cn_name'], row['en_name'], *texts])))),
                'preview_id': f'release:feature:{row["id"]}',
                'locator': locator,
                'verification': 'approved',
            })
    return {'query': query, 'members': members,
            'notice': '依据当前功能档案中的明确提及和已登记父子关系汇总。父功能提及某功能族不代表全部子能力均属于该功能族；关联版本不代表该子能力在当时已支持。历史依据请核对下方原文。'}
