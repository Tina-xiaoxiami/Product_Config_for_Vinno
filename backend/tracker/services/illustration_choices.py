"""Source-scoped, reversible choices of the current illustration; no source edits."""
from copy import deepcopy
from hashlib import sha256
import json
import re

from tracker.services.release_review import ReviewConflict

_PREFIX = 'release-illustration-choice-v1'


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _identity(project, item):
    images = [block for block in item.get('section', {}).get('blocks', []) if block.get('type') == 'image']
    signature = {'project': project, 'source': item['source_id'], 'locator': item['locator'],
                 'images': [(image.get('image_hash'), image.get('comparison_role')) for image in images]}
    key = _PREFIX + ':' + sha256(_json([project, item['source_id'], item['locator']]).encode()).hexdigest()
    return key, sha256(_json(signature).encode()).hexdigest(), images


def decorate_illustration_choices(database, answer, project):
    output = deepcopy(answer)
    with database.connect() as connection:
        for item in output.get('illustrations', []):
            key, fingerprint, images = _identity(project, item)
            row = connection.execute('SELECT revision,content,source_fingerprint FROM scenario_description_revisions WHERE context_key=? AND project_id=? ORDER BY revision DESC LIMIT 1', (key, project)).fetchone()
            chosen = json.loads(row['content']).get('image_hash') if row else None
            valid = bool(row and row['source_fingerprint'] == fingerprint and any(image.get('image_hash') == chosen and image.get('comparison_role') == 'unknown' for image in images))
            item['selection'] = {'revision': row['revision'] if row else 0, 'source_fingerprint': fingerprint,
                                 'image_hash': chosen if valid else None, 'stale': bool(row and not valid)}
            for image in images:
                original = image.get('comparison_role') or 'neutral'
                image['display_role'] = ('after' if image.get('image_hash') == chosen else 'comparison') if valid and original == 'unknown' else original
    return output


def save_illustration_choice(database, answer, project, payload):
    item = next((item for item in answer.get('illustrations', []) if item.get('source_id') == payload.get('source_id') and item.get('locator') == payload.get('locator')), None)
    if item is None:
        raise ValueError('该图示不在当前项目与版本范围内。')
    key, fingerprint, images = _identity(project, item)
    selected = payload.get('image_hash')
    if not isinstance(selected, str) or not re.fullmatch(r'[a-f0-9]{64}', selected) or sum(image.get('image_hash') == selected and bool(image.get('data_url')) for image in images) != 1:
        raise ValueError('请选择当前可核实的原文图片。')
    if not any(image.get('image_hash') == selected and image.get('comparison_role') == 'unknown' for image in images):
        raise ValueError('仅可人工确认尚未确定前后关系的对比图。')
    revision = payload.get('selection_revision')
    if type(revision) is not int or revision < 0:
        raise ValueError('图示核对修订号无效。')
    if payload.get('selection_fingerprint') != fingerprint:
        raise ReviewConflict('图示来源已变化，请重新查询后选择。')
    with database.transaction() as connection:
        latest = connection.execute('SELECT COALESCE(MAX(revision),0) FROM scenario_description_revisions WHERE context_key=? AND project_id=?', (key, project)).fetchone()[0]
        if latest != revision:
            raise ReviewConflict('图示已有更新的选择，请重新查询。')
        connection.execute('INSERT INTO scenario_description_revisions(context_key,revision,project_id,content,source_fingerprint) VALUES (?,?,?,?,?)',
                           (key, latest + 1, project, _json({'schema': _PREFIX, 'image_hash': selected}), fingerprint))
    return decorate_illustration_choices(database, answer, project)
