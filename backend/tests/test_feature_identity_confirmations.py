from app.services.feature_identity_confirmations import (
    CONFIRMED_FEATURE_MAPPINGS,
    confirmed_ipn_by_legacy_feature_id,
)


def test_registry_contains_product_owner_confirmed_feature_merges():
    assert [
        (
            item.legacy_feature_id,
            item.legacy_name,
            item.target_ipn,
            item.confirmed_at,
        )
        for item in CONFIRMED_FEATURE_MAPPINGS
    ] == [
        (4, "穿刺引导&穿刺增强", "6000034", "2026-09-01"),
        (7, "SMF", "6000273", "2026-09-01"),
    ]


def test_registry_exposes_migration_mapping_without_duplicate_legacy_ids():
    assert confirmed_ipn_by_legacy_feature_id() == {
        4: "6000034",
        7: "6000273",
    }
