from copy import deepcopy
import pytest
from tracker.database import Database
from tracker.services.illustration_choices import decorate_illustration_choices, save_illustration_choice
from tracker.services.release_review import ReviewConflict

@pytest.fixture
def db(tmp_path):
    database=Database(tmp_path/'roles.db');database.initialize();return database

def raw():
    return {'content':'保留正文','review':{'revision':2},'unresolved_changes':[{'id':'pending'}], 'illustrations':[{'source_id':'release:source:40','locator':'原文行 72','version':'1.51.90','section':{'blocks':[{'type':'image','image_hash':'a'*64,'comparison_role':'unknown','data_url':'data:image/png;base64,AA=='},{'type':'image','image_hash':'b'*64,'comparison_role':'unknown','data_url':'data:image/png;base64,AQ=='}]}}]}

def payload(answer):
    item=answer['illustrations'][0]
    return {'source_id':item['source_id'],'locator':item['locator'],'image_hash':'b'*64,'selection_revision':item['selection']['revision'],'selection_fingerprint':item['selection']['source_fingerprint']}

def test_choose_after_persists_without_altering_body_or_decisions(db):
    original=raw();initial=decorate_illustration_choices(db,original,1)
    chosen=save_illustration_choice(db,initial,1,payload(initial))
    assert [image['display_role'] for image in chosen['illustrations'][0]['section']['blocks']]==['comparison','after']
    assert chosen['content']==original['content'] and chosen['review']==original['review']
    assert chosen['unresolved_changes']==original['unresolved_changes']
    assert 'selection' not in original['illustrations'][0]
    assert decorate_illustration_choices(db,raw(),1)['illustrations'][0]['selection']['revision']==1
    assert decorate_illustration_choices(db,raw(),2)['illustrations'][0]['selection']['revision']==0

def test_stale_image_or_concurrent_revision_cannot_overwrite(db):
    initial=decorate_illustration_choices(db,raw(),1);body=payload(initial)
    save_illustration_choice(db,initial,1,body)
    with pytest.raises(ReviewConflict):save_illustration_choice(db,initial,1,body)
    changed=raw();changed['illustrations'][0]['section']['blocks'][0]['image_hash']='c'*64
    updated=decorate_illustration_choices(db,changed,1)
    assert updated['illustrations'][0]['selection']['stale']
    with pytest.raises(ReviewConflict):save_illustration_choice(db,updated,1,{**body,'selection_revision':1})

def test_unknown_scope_duplicate_hash_and_invalid_selection_are_rejected(db):
    initial=decorate_illustration_choices(db,raw(),1);body=payload(initial)
    for wrong in [{'source_id':'release:source:99'},{'locator':'其他章'},{'image_hash':'x'},{'selection_revision':True}]:
        with pytest.raises(ValueError):save_illustration_choice(db,initial,1,{**body,**wrong})
    duplicate=deepcopy(initial);duplicate['illustrations'][0]['section']['blocks'].append(dict(duplicate['illustrations'][0]['section']['blocks'][1]))
    with pytest.raises(ValueError):save_illustration_choice(db,duplicate,1,body)


@pytest.mark.parametrize('roles', [('before', 'after'), ('neutral', 'neutral'), ('unknown', 'before')])
def test_known_roles_cannot_be_overridden_by_manual_choice(db, roles):
    answer = raw()
    for image, role in zip(answer['illustrations'][0]['section']['blocks'], roles):
        image['comparison_role'] = role
    initial = decorate_illustration_choices(db, answer, 1)
    with pytest.raises(ValueError, match='尚未确定'):
        save_illustration_choice(db, initial, 1, payload(initial))


def test_manual_choice_preserves_other_verified_roles(db):
    answer = raw()
    answer['illustrations'][0]['section']['blocks'][0]['comparison_role'] = 'after'
    initial = decorate_illustration_choices(db, answer, 1)
    chosen = save_illustration_choice(db, initial, 1, payload(initial))
    assert [image['display_role'] for image in chosen['illustrations'][0]['section']['blocks']] == ['after', 'after']
