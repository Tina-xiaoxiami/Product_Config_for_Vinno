from app.services.feature_identity_confirmations import (
    CONFIRMED_FEATURE_MAPPINGS,
    CONFIRMED_FEATURE_RELATIONS,
    confirmed_ipn_by_legacy_feature_id,
    confirmed_relations_by_legacy_feature_id,
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
        (10, "向量血流", "6000349", "2026-09-01"),
        (11, "常规造影", "6000019", "2026-09-01"),
        (17, "EI", "6000018", "2026-09-01"),
        (18, "SWE", "6000190", "2026-09-01"),
        (25, "ECG", "6000321", "2026-09-01"),
        (27, "AMAS", "6000167", "2026-09-01"),
        (28, "Strain", "6000169", "2026-09-01"),
        (33, "Vaid Carotid", "6000356", "2026-09-01"),
    ]


def test_registry_exposes_migration_mapping_without_duplicate_legacy_ids():
    assert confirmed_ipn_by_legacy_feature_id() == {
        4: "6000034",
        7: "6000273",
        10: "6000349",
        11: "6000019",
        17: "6000018",
        18: "6000190",
        25: "6000321",
        27: "6000167",
        28: "6000169",
        33: "6000356",
    }


def test_registry_keeps_related_and_versioned_ipns_as_distinct_identities():
    assert [
        (
            item.legacy_feature_id,
            item.legacy_name,
            item.relation_type,
            item.target_ipns,
        )
        for item in CONFIRMED_FEATURE_RELATIONS
    ] == [
        (19, "点式剪切波", "related", ("6000190",)),
        (31, "Vmind OB", "version_variant", ("6000294", "6000415")),
        (32, "STIC", "version_variant", ("3200476", "6000323")),
    ]
    assert confirmed_relations_by_legacy_feature_id() == {
        19: ("related", ("6000190",)),
        31: ("version_variant", ("6000294", "6000415")),
        32: ("version_variant", ("3200476", "6000323")),
    }
