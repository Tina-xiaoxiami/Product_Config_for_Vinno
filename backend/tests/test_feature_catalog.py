"""Configuration identity coverage must not expand the probe matrix."""
import pytest
import sqlite3
from sqlalchemy import select, text

from app.models import ConfigItem
from app.models.probe import Feature, FeatureGroup
from app.models.knowledge import FeatureConfigItemLink, FeatureName
from test_draft_safety import _draft_harness
from test_import_export_contracts import db, _upload, _workbook


def test_existing_identity_migration_preserves_probe_scope_default(tmp_path):
    from test_knowledge_api import _create_knowledge_database
    path = tmp_path / 'old.db'
    _create_knowledge_database(path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT probe_matrix_enabled FROM features').fetchall() == [(1,), (1,), (1,)]


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
async def test_name_gaps_include_existing_related_only_identity_owners(tmp_path):
    sessions, engine = await catalog_case(tmp_path)
    try:
        from app.services.feature_catalog import sync_optional_feature_catalog, feature_catalog_coverage
        from app.services.knowledge_query import list_feature_knowledge
        async with sessions() as db:
            db.add(Feature(id=99, group_id=1, name='Relationship', identity_status='related'))
            db.add(ConfigItem(id=5, category='Optional Features', row_index=5, ipn='RELATED'))
            await db.flush()
            db.add(FeatureConfigItemLink(feature_id=99, config_item_id=5, relation_type='related', source='manual'))
            await db.flush()
            assert (await sync_optional_feature_catalog(db))['created'] == 1
            coverage = await feature_catalog_coverage(db)
            assert coverage['covered_items'] == 4
            assert coverage['catalog_identities'] == 3
            rows, total = await list_feature_knowledge(db, missing_name='cn')
            assert coverage['missing_cn_names'] == total == 2
            assert 99 in {row['id'] for row in rows}
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
            probe_catalog = await catalog(db)
            assert [item['id'] for item in probe_catalog['features']] == [1]
            assert probe_catalog['feature_groups'] == [{'id': 1, 'name': 'Existing'}]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_configuration_import_preview_rolls_back_catalog_and_apply_registers_it(db):
    from app.api.import_export import preview_import, import_excel
    from app.services.feature_catalog import feature_catalog_coverage
    from app.models.knowledge import FeatureConfigItemLink

    for _ in range(2):
        await preview_import(_upload(_workbook([('New', 'Model')])), db)
        assert list((await db.scalars(select(Feature))).all()) == []
        assert list((await db.scalars(select(FeatureGroup))).all()) == []
        assert list((await db.scalars(select(FeatureName))).all()) == []
        assert list((await db.scalars(select(FeatureConfigItemLink))).all()) == []
        assert (await feature_catalog_coverage(db))['configured_items'] == 0

    await import_excel(_upload(_workbook([('New', 'Model')])), series_name=None, db=db)
    feature = await db.scalar(select(Feature))
    assert feature.ipn == '100' and feature.primary_cn_name == '功能'
    assert feature.probe_matrix_enabled is False
    assert (await feature_catalog_coverage(db))['covered_items'] == 1


@pytest.mark.asyncio
async def test_restored_configuration_registers_identity_in_the_same_transaction(db):
    from app.models import ProductSeries, ProductModel, ConfigValue
    from app.services.config_history import restore_series_snapshot

    db.add(ProductSeries(id=1, name='History'))
    await db.flush()
    db.add(ProductModel(id=1, series_id=1, name='Model'))
    await db.commit()
    snapshot = {'models': [{'id': 1, 'name': 'Model'}], 'items': [{
        'id': 20, 'category': 'Optional Features', 'row_index': 5,
        'ipn': 'RESTORED', 'zh_desc': '历史功能', 'values': {'1': {'current_config': 'X'}}
    }]}
    assert await restore_series_snapshot(db, 1, snapshot) == 1
    feature = await db.scalar(select(Feature))
    assert feature.ipn == 'RESTORED' and feature.primary_cn_name == '历史功能'
    assert feature.probe_matrix_enabled is False
    await db.rollback()
    assert await db.scalar(select(Feature)) is None
    assert await db.scalar(select(ConfigItem)) is None
    assert await db.scalar(select(ConfigValue)) is None
