"""Explicit legacy retirement never removes scoped questions or their sources."""
import copy
import json
import sqlite3

import pytest

from app.services.knowledge_qa_retirement import (
    RetirementError, preview_retirement, retire_legacy_qa, restore_legacy_qa,
)


def database(tmp_path):
    path = tmp_path / 'source.db'
    db = sqlite3.connect(path)
    db.executescript('''
    PRAGMA foreign_keys=ON;
    CREATE TABLE knowledge_documents(id INTEGER PRIMARY KEY,title TEXT);
    CREATE TABLE knowledge_questions(id INTEGER PRIMARY KEY,question_text TEXT,scope_key TEXT NOT NULL,normalized_question TEXT,UNIQUE(scope_key,normalized_question));
    CREATE TABLE knowledge_question_phrasings(id INTEGER PRIMARY KEY,question_id INTEGER REFERENCES knowledge_questions(id) ON DELETE CASCADE,scope_key TEXT,phrasing_text TEXT);
    CREATE TABLE knowledge_answers(id INTEGER PRIMARY KEY,question_id INTEGER UNIQUE REFERENCES knowledge_questions(id) ON DELETE CASCADE,answer_text TEXT);
    CREATE TABLE knowledge_answer_citations(id INTEGER PRIMARY KEY,answer_id INTEGER REFERENCES knowledge_answers(id) ON DELETE CASCADE,document_id INTEGER REFERENCES knowledge_documents(id));
    CREATE TABLE knowledge_answer_revisions(id INTEGER PRIMARY KEY,answer_id INTEGER REFERENCES knowledge_answers(id) ON DELETE CASCADE,answer_text TEXT);
    CREATE TABLE knowledge_answer_reviews(id INTEGER PRIMARY KEY,answer_id INTEGER REFERENCES knowledge_answers(id) ON DELETE CASCADE,note TEXT);
    CREATE TABLE knowledge_parameter_specs(id INTEGER PRIMARY KEY,value TEXT);
    INSERT INTO knowledge_documents VALUES(5,'受控资料');
    INSERT INTO knowledge_questions VALUES(1,'旧问答','','old'),(2,'新问答','explicit-scope','new');
    INSERT INTO knowledge_question_phrasings VALUES(1,1,'','旧别名'),(2,2,'explicit-scope','新别名');
    INSERT INTO knowledge_answers VALUES(1,1,'旧答案'),(2,2,'新答案');
    INSERT INTO knowledge_answer_citations VALUES(1,1,5),(2,2,5);
    INSERT INTO knowledge_answer_revisions VALUES(1,1,'旧修订'),(2,2,'新修订');
    INSERT INTO knowledge_answer_reviews VALUES(1,1,'旧核对'),(2,2,'新核对');
    INSERT INTO knowledge_parameter_specs VALUES(1,'真实规格');
    ''')
    db.commit(); db.close()
    return path


def snapshot(path):
    db = sqlite3.connect(path)
    result = {t: db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall()
              for t, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    db.close()
    return result


def retire(path, tmp_path, **kwargs):
    preview = preview_retirement(path)
    return retire_legacy_qa(path, expected_fingerprint=preview['fingerprint'],
                            archive_path=tmp_path/'archive.json', backup_path=tmp_path/'backup.db',
                            apply=True, **kwargs)


def test_preview_and_default_dry_run_write_nothing(tmp_path):
    path = database(tmp_path); before = snapshot(path)
    preview = preview_retirement(path)
    assert preview['question_ids'] == [1]
    assert preview['counts']['knowledge_questions'] == 1
    assert preview['counts']['knowledge_answer_reviews'] == 1
    assert retire_legacy_qa(path)['status'] == 'ready'
    assert snapshot(path) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ['source.db']


def test_apply_archives_exact_raw_rows_and_online_backup_before_removal(tmp_path):
    path = database(tmp_path); before = snapshot(path)
    result = retire(path,tmp_path)
    assert result['status'] == 'retired'
    after = snapshot(path)
    assert after['knowledge_questions'] == [before['knowledge_questions'][1]]
    assert after['knowledge_answers'] == [before['knowledge_answers'][1]]
    for t in ('knowledge_question_phrasings','knowledge_answer_citations','knowledge_answer_revisions','knowledge_answer_reviews'):
        assert after[t] == [before[t][1]]
    assert after['knowledge_documents'] == before['knowledge_documents']
    assert after['knowledge_parameter_specs'] == before['knowledge_parameter_specs']
    assert snapshot(tmp_path/'backup.db') == before
    archive = json.loads((tmp_path/'archive.json').read_text())
    assert archive['tables']['knowledge_answer_reviews'][0]['note'] == '旧核对'


def test_concurrent_target_change_rejects_without_archive_or_delete(tmp_path):
    path = database(tmp_path); fingerprint = preview_retirement(path)['fingerprint']
    db = sqlite3.connect(path); db.execute("UPDATE knowledge_answers SET answer_text='已变更' WHERE id=1"); db.commit();db.close()
    with pytest.raises(RetirementError,match='变化'):
        retire_legacy_qa(path,expected_fingerprint=fingerprint,archive_path=tmp_path/'archive.json',backup_path=tmp_path/'backup.db',apply=True)
    assert not (tmp_path/'archive.json').exists()
    assert len(snapshot(path)['knowledge_questions']) == 2


@pytest.mark.parametrize('target', ['source','existing','same','symlink'])
def test_unsafe_or_existing_destinations_are_never_overwritten(tmp_path,target):
    path=database(tmp_path); before=snapshot(path)
    archive=tmp_path/'archive.json'; backup=tmp_path/'backup.db'
    if target=='source':archive=path
    elif target=='existing':archive.write_text('keep')
    elif target=='same':backup=archive
    else:archive.symlink_to(path)
    with pytest.raises(RetirementError):
        retire_legacy_qa(path,expected_fingerprint=preview_retirement(path)['fingerprint'],archive_path=archive,backup_path=backup,apply=True)
    assert snapshot(path)==before


def test_missing_scope_schema_is_refused_instead_of_treating_all_rows_as_legacy(tmp_path):
    path=tmp_path/'old.db';db=sqlite3.connect(path);db.execute('CREATE TABLE knowledge_questions(id INTEGER PRIMARY KEY)');db.commit();db.close()
    with pytest.raises(RetirementError,match='scope_key'):
        preview_retirement(path)


def test_unknown_cascading_dependency_is_refused(tmp_path):
    path=database(tmp_path);db=sqlite3.connect(path)
    db.execute('CREATE TABLE unexpected(id INTEGER PRIMARY KEY,question_id INTEGER REFERENCES knowledge_questions(id) ON DELETE CASCADE)');db.commit();db.close()
    with pytest.raises(RetirementError,match='依赖'):
        preview_retirement(path)


def test_target_restore_preserves_new_questions_and_is_dry_by_default(tmp_path):
    path=database(tmp_path);before=snapshot(path);retire(path,tmp_path)
    db=sqlite3.connect(path);db.execute("INSERT INTO knowledge_questions VALUES(3,'后来的问答','new-scope','later')");db.commit();db.close()
    assert restore_legacy_qa(path,tmp_path/'archive.json')['status']=='ready'
    assert len(snapshot(path)['knowledge_questions'])==2
    assert restore_legacy_qa(path,tmp_path/'archive.json',apply=True)['status']=='restored'
    after=snapshot(path)
    assert after['knowledge_questions'][:2]==before['knowledge_questions']
    assert after['knowledge_questions'][-1][0]==3
    assert after['knowledge_answer_reviews']==before['knowledge_answer_reviews']
    with pytest.raises(RetirementError,match='冲突'):
        restore_legacy_qa(path,tmp_path/'archive.json',apply=True)


def test_restore_collision_or_missing_source_is_atomic(tmp_path):
    path=database(tmp_path);retire(path,tmp_path)
    db=sqlite3.connect(path);db.execute("INSERT INTO knowledge_questions VALUES(1,'新占用','new-scope','occupied')");db.commit();db.close()
    before=snapshot(path)
    with pytest.raises(RetirementError,match='冲突'):
        restore_legacy_qa(path,tmp_path/'archive.json',apply=True)
    assert snapshot(path)==before


def test_corrupted_archive_or_other_database_is_refused(tmp_path):
    path=database(tmp_path);retire(path,tmp_path)
    archive=tmp_path/'archive.json';value=json.loads(archive.read_text());value['tables']['knowledge_answers'][0]['answer_text']='changed';archive.write_text(json.dumps(value))
    with pytest.raises(RetirementError,match='校验'):
        restore_legacy_qa(path,archive,apply=True)
    assert len(snapshot(path)['knowledge_questions'])==1


def test_apply_requires_explicit_preview_fingerprint_and_paths(tmp_path):
    path=database(tmp_path)
    with pytest.raises(RetirementError):retire_legacy_qa(path,apply=True)
    assert len(snapshot(path)['knowledge_questions'])==2
