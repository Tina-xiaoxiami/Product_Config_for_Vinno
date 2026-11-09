"""Evidence-bound name correction preserves draft choices and immutable history."""
import hashlib
import json
import sqlite3

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine

from app.database import Base
from app import models  # Register the complete production schema.


def repair_case(tmp_path):
    path = tmp_path / 'catalog.db'
    engine = create_engine(f'sqlite:///{path}')
    Base.metadata.create_all(engine)
    engine.dispose()
    old = {'excludes': ['早', '中', '晚孕'], 'tender': ['特殊应用']}
    document = {'scope': {'model_ids': [1]}, 'rows': [
        {'probe_model_id': 1, 'variant_id': None, 'feature_id': 11,
         'defined_excludes': ['早', '中', '晚孕'], 'current_excludes': ['早'],
         'defined_status': 'conditional', 'current_status': 'pending', 'notes': 'keep'},
        {'probe_model_id': 6, 'variant_id': None, 'feature_id': 11,
         'defined_excludes': ['早', '中晚孕'], 'current_excludes': [], 'notes': 'conflict'},
    ], 'overrides': {'1': {'1:0:11': {'current_excludes': ['中'], 'priority': '标2'}}}}
    raw = json.dumps(document, ensure_ascii=False)
    with sqlite3.connect(path) as db:
        db.executescript("""
            INSERT INTO product_series(id,name) VALUES(1,'Series');
            INSERT INTO product_models(id,series_id,name) VALUES(1,1,'Model');
            INSERT INTO feature_groups(id,name) VALUES(1,'Group');
            INSERT INTO features(id,group_id,name,probe_matrix_enabled,identity_status) VALUES(11,1,'Feature',1,'confirmed');
            INSERT INTO probe_categories(id,name) VALUES(1,'Convex'),(6,'Biplane');
            INSERT INTO probe_models(id,category_id,model_number) VALUES(1,1,'P1'),(6,6,'P6');
            INSERT INTO applications(id,name) VALUES(1,'早孕'),(2,'中孕'),(3,'晚孕'),(4,'子宫');
            INSERT INTO category_applications(category_id,application_id,probe_type) VALUES
                (1,1,'regular'),(1,2,'regular'),(1,3,'regular'),(6,4,'regular');
        """)
        db.execute('INSERT INTO template_features(id,category_id,feature_id,default_support,default_excludes) VALUES(9,1,11,?,?)', ('supported', json.dumps(old, ensure_ascii=False)))
        db.execute('INSERT INTO template_features(id,category_id,feature_id,default_support,default_excludes) VALUES(81,6,11,?,?)', ('conditional', '["早", "中晚孕"]'))
        db.execute('INSERT INTO template_versions(id,version_number,snapshot_data) VALUES(3,?,?)', ('original', '[]'))
        db.execute('INSERT INTO probe_workspaces(id,name,revision,draft_data,published_data,created_at) VALUES(1,?,4,?,?,?)', ('Workspace', raw, raw, '2026-11-04'))
        db.execute('INSERT INTO product_probe_configs(id,product_model_id,probe_model_id,feature_id,defined_status,current_status,defined_excludes,current_excludes) VALUES(1,1,1,11,?,?,?,?)', ('conditional', 'pending', json.dumps(old, ensure_ascii=False), '["早"]'))
    source = tmp_path / 'template.xlsx'
    workbook = Workbook(); sheet = workbook.active; sheet.title = '模板'
    sheet['O3'] = '√(除早\\中\\晚孕)'; sheet['C3'] = '早孕, 中孕, 晚孕'; sheet['D3'] = ''
    sheet['O8'] = '√(除早\\中晚孕)'; sheet['C8'] = '子宫'; sheet['D8'] = '同常规'
    workbook.save(source)
    evidence = {'source_filename': source.name, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'template_version_id': 3, 'records': []}
    for template_id, category_id, row in [(9, 1, 3), (81, 6, 8)]:
        evidence['records'].append({
            'template_id': template_id, 'category_id': category_id, 'feature_id': 11,
            'category': 'Convex' if category_id == 1 else 'Biplane', 'feature': 'Feature',
            'source_sheet': '模板', 'source_cell': f'O{row}', 'source_value': sheet[f'O{row}'].value,
            'apps_regular_cell': f'C{row}', 'apps_regular_value': sheet[f'C{row}'].value,
            'apps_poc_cell': f'D{row}', 'apps_poc_value': sheet[f'D{row}'].value or None,
            'original_excludes': ['早', '中', '晚孕'] if category_id == 1 else ['早', '中晚孕'],
            'decision': 'resolved' if category_id == 1 else 'source_conflict',
            'normalized_excludes': ['早孕', '中孕', '晚孕'] if category_id == 1 else None,
            'token_replacements': {'早': '早孕', '中': '中孕'} if category_id == 1 else {},
            'reason': 'source excludes pregnancy outside the category' if category_id == 6 else 'proved',
        })
    return path, source, evidence, raw


def test_repairs_current_layers_but_preserves_source_conflicts_and_frozen_history(tmp_path):
    from app.services.probe_exclusion_repair import repair_exclusions
    path, source, evidence, raw = repair_case(tmp_path)
    preview = repair_exclusions(path, source, evidence, apply=False)
    assert preview['changed_templates'] == 1 and len(preview['unresolved']) == 1
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT draft_data FROM probe_workspaces').fetchone()[0] == raw
    applied = repair_exclusions(path, source, evidence, apply=True)
    assert applied['changed_workspaces'] == 1
    with sqlite3.connect(path) as db:
        value = json.loads(db.execute('SELECT default_excludes FROM template_features WHERE id=9').fetchone()[0])
        assert value == {'excludes': ['早孕', '中孕', '晚孕'], 'tender': ['特殊应用']}
        assert db.execute('SELECT default_excludes FROM template_features WHERE id=81').fetchone()[0] == '["早", "中晚孕"]'
        draft, published, revision = db.execute('SELECT draft_data,published_data,revision FROM probe_workspaces').fetchone()
        draft = json.loads(draft)
        assert revision == 5 and published == raw
        assert draft['rows'][0]['defined_excludes'] == ['早孕', '中孕', '晚孕']
        assert draft['rows'][0]['current_status'] == 'pending' and draft['rows'][0]['notes'] == 'keep'
        assert draft['overrides']['1']['1:0:11'] == {'current_excludes': ['中孕'], 'priority': '标2'}
        assert draft['rows'][1]['defined_excludes'] == ['早', '中晚孕']
        assert db.execute('SELECT snapshot_data FROM template_versions WHERE id=3').fetchone()[0] == '[]'
        assert db.execute('SELECT count(*) FROM template_versions').fetchone()[0] == 2
    again = repair_exclusions(path, source, evidence, apply=True)
    assert again['changed_templates'] == again['changed_workspaces'] == 0
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM template_versions').fetchone()[0] == 2


def test_refuses_changed_source_and_live_dictionary_before_any_write(tmp_path):
    from app.services.probe_exclusion_repair import repair_exclusions
    path, source, evidence, raw = repair_case(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute('DELETE FROM category_applications WHERE application_id=1')
    with pytest.raises(ValueError, match='应用'):
        repair_exclusions(path, source, evidence, apply=True)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT draft_data FROM probe_workspaces').fetchone()[0] == raw
        assert db.execute('SELECT count(*) FROM template_versions').fetchone()[0] == 1
    source.write_bytes(source.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='摘要'):
        repair_exclusions(path, source, evidence, apply=True)


def test_snapshot_failure_rolls_back_all_mutable_layers(tmp_path):
    from app.services.probe_exclusion_repair import repair_exclusions
    path, source, evidence, raw = repair_case(tmp_path)
    with sqlite3.connect(path) as db:
        before = db.execute('SELECT default_excludes FROM template_features WHERE id=9').fetchone()[0]
        db.execute("CREATE TRIGGER fail_snapshot BEFORE INSERT ON template_versions BEGIN SELECT RAISE(ABORT,'snapshot unavailable'); END")
    with pytest.raises(sqlite3.IntegrityError, match='snapshot unavailable'):
        repair_exclusions(path, source, evidence, apply=True)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT default_excludes FROM template_features WHERE id=9').fetchone()[0] == before
        assert db.execute('SELECT draft_data FROM probe_workspaces').fetchone()[0] == raw
        assert db.execute('SELECT revision FROM probe_workspaces').fetchone()[0] == 4
        assert db.execute('SELECT count(*) FROM template_versions').fetchone()[0] == 1


def test_repair_refuses_a_concurrently_changed_template_choice(tmp_path):
    from app.services.probe_exclusion_repair import repair_exclusions
    path, source, evidence, raw = repair_case(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute('UPDATE template_features SET default_excludes=? WHERE id=9', ('["早"]',))
    with pytest.raises(ValueError, match='排除选择已变化'):
        repair_exclusions(path, source, evidence, apply=True)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT draft_data FROM probe_workspaces').fetchone()[0] == raw
        assert db.execute('SELECT default_excludes FROM template_features WHERE id=9').fetchone()[0] == '["早"]'
