"""Configuration identity coverage must not expand the probe matrix."""
import pytest
from sqlalchemy import select, text

from app.models import ConfigItem
from app.models.probe import Feature, FeatureGroup
from app.models.knowledge import FeatureConfigItemLink, FeatureName
from test_draft_safety import _draft_harness


async def catalog_case(tmp_path):
    client, sessions, engine = await _draft_harness(tmp_path)
    async with sessions() as db:
        db.add(FeatureGroup(id=1, name='Existing', sort_order=1))
        db.add_all([
            ConfigItem(id=1, category='Optional Features', row_index=1, ipn='A', zh_desc='原始中文', en_desc='Original'),
            ConfigItem(id=2, category='Optional Features', row_index=2, ipn='B', zh_desc='版本中文', en_desc='Variant'),
            ConfigItem(id=3, category=' Optional Features ', row_index=3, ipn='C', zh_desc=' ', en_desc='New English【启用】'),
            ConfigItem(id=4, category='Probes', row_index=4, ipn='D', zh_desc='探头'),
        ])
        await db.flush()
        db.add(Feature(id=1, group_id=1, name='Legacy', ipn='A', config_item_id=1,
                       primary_cn_name='人工主名', primary_en_name='Manual', identity_status='confirmed'))
        await db.flush()
        db.add_all([
            FeatureConfigItemLink(feature_id=1, config_item_id=1, relation_type='primary', source='manual'),
            FeatureConfigItemLink(feature_id=1, config_item_id=2, relation_type='version_variant', source='manual'),
            FeatureName(feature_id=1, language='cn', name='曾用名', normalized_name='曾用名', name_type='alias', source='manual', review_status='approved'),
        ])
        await db.commit()
    await client.aclose()
    return sessions, engine


@pytest.mark.asyncio
async def test_sync_keeps_old_identity_and_variant_links_and_registers_missing_language(tmp_path):
    sessions, engine = await catalog_case(tmp_path)
    try:
        from app.services.feature_catalog import sync_optional_feature_catalog, feature_catalog_coverage
        from app.services.knowledge_query import list_feature_knowledge
        async with sessions() as db:
            before = (await db.execute(text('SELECT * FROM features WHERE id=1'))).one()
            report = await sync_optional_feature_catalog(db)
            assert report['created'] == 1
            assert (await db.execute(text('SELECT * FROM features WHERE id=1'))).one() == before
            assert (await db.scalar(select(FeatureName.name).where(FeatureName.source == 'manual'))) == '曾用名'
            added = await db.scalar(select(Feature).where(Feature.ipn == 'C'))
            assert added.primary_cn_name == '' and added.primary_en_name == 'New English'
            assert added.identity_status == 'auto_matched' and added.probe_matrix_enabled is False
            coverage = await feature_catalog_coverage(db)
            assert (coverage['configured_items'], coverage['covered_items'], coverage['configured_ipns'], coverage['covered_ipns']) == (3, 3, 3, 3)
            assert coverage['unlinked_count'] == 0 and coverage['missing_cn_names'] == 1
            rows, total = await list_feature_knowledge(db, query='C', missing_name='cn')
            assert total == 1 and rows[0]['id'] == added.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sync_is_idempotent_and_follows_callers_rollback(tmp_path):
    sessions, engine = await catalog_case(tmp_path)
    try:
        from app.services.feature_catalog import sync_optional_feature_catalog
        async with sessions() as db:
            assert (await sync_optional_feature_catalog(db))['created'] == 1
            await db.rollback()
        async with sessions() as db:
            assert (await sync_optional_feature_catalog(db))['created'] == 1
            await db.commit()
        async with sessions() as db:
            before = list((await db.execute(text('SELECT * FROM features ORDER BY id'))).all())
            assert (await sync_optional_feature_catalog(db))['created'] == 0
            assert list((await db.execute(text('SELECT * FROM features ORDER BY id'))).all()) == before
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ambiguous_or_absent_ipns_are_visible_as_coverage_gaps_without_guessed_identity(tmp_path):
    sessions, engine = await catalog_case(tmp_path)
    try:
        from app.services.feature_catalog import sync_optional_feature_catalog, feature_catalog_coverage
        async with sessions() as db:
            db.add_all([ConfigItem(id=5, category='Optional Features', row_index=5, ipn='X', zh_desc='同码一'),
                        ConfigItem(id=6, category='Optional Features', row_index=6, ipn='x ', zh_desc='同码二'),
                        ConfigItem(id=7, category='Optional Features', row_index=7, ipn=' ', zh_desc='缺IPN')])
            await db.flush()
            assert (await sync_optional_feature_catalog(db))['created'] == 1
            coverage = await feature_catalog_coverage(db)
            assert coverage['unlinked_count'] == 3
            assert {item['config_item_id'] for item in coverage['unlinked_items']} == {5, 6, 7}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_full_catalog_is_searchable_but_probe_readers_keep_their_original_axis(tmp_path):
    sessions, engine = await catalog_case(tmp_path)
    try:
        from app.services.feature_catalog import sync_optional_feature_catalog
        from app.services.probe_workspace import catalog
        from app.api.features import list_features
        async with sessions() as db:
            await sync_optional_feature_catalog(db)
            assert (await list_features(db=db)).total == 2
            assert (await list_features(db=db, probe_matrix_only=True)).total == 1
            assert [item['id'] for item in (await catalog(db))['features']] == [1]
    finally:
        await engine.dispose()
