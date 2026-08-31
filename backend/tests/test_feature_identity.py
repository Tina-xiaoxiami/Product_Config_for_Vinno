import pytest

from app.services.feature_identity import (
    ConfigItemIdentity,
    IdentityValidationError,
    LegacyFeature,
    build_feature_identity_preview,
)


def test_ipn_is_the_business_identity_and_config_descriptions_are_primary_names():
    preview = build_feature_identity_preview(
        config_items=[
            ConfigItemIdentity(
                id=59,
                ipn="6000034",
                rd_name="Needle enhancement【启用】",
                zh_desc="穿刺增强",
                en_desc="Needle enhancement",
            )
        ],
        legacy_features=[LegacyFeature(id=4, name="穿刺增强", ipn="")],
    )

    identity = preview.identities[0]
    assert identity.ipn == "6000034"
    assert identity.primary_cn_name == "穿刺增强"
    assert identity.primary_en_name == "Needle enhancement"
    assert identity.status == "auto_matched"
    assert [(name.language, name.name, name.name_type) for name in identity.names] == [
        ("cn", "穿刺增强", "primary"),
        ("en", "Needle enhancement", "primary"),
        ("en", "Needle enhancement【启用】", "alias"),
    ]


def test_same_ipn_with_a_different_legacy_name_keeps_the_name_as_an_alias():
    preview = build_feature_identity_preview(
        config_items=[
            ConfigItemIdentity(
                id=1,
                ipn="6000017",
                rd_name="TView",
                zh_desc="组织多普勒成像",
                en_desc="Tissue Doppler Imaging",
            )
        ],
        legacy_features=[LegacyFeature(id=1, name="组织多普勒", ipn="6000017")],
    )

    identity = preview.identities[0]
    assert identity.status == "auto_matched"
    assert ("cn", "组织多普勒", "alias") in [
        (name.language, name.name, name.name_type) for name in identity.names
    ]


def test_same_name_with_two_ipns_is_ambiguous_and_is_not_merged():
    preview = build_feature_identity_preview(
        config_items=[
            ConfigItemIdentity(1, "6000001", "SWE", "剪切波成像", "SWE"),
            ConfigItemIdentity(2, "6000002", "SWE", "剪切波弹性成像", "SWE"),
        ],
        legacy_features=[LegacyFeature(id=18, name="SWE", ipn="")],
    )

    assert preview.identities == []
    pending = preview.pending[0]
    assert pending.legacy_feature_id == 18
    assert pending.reason == "ambiguous_name"
    assert pending.candidate_ipns == ("6000001", "6000002")


def test_composite_feature_without_one_exact_ipn_stays_pending():
    preview = build_feature_identity_preview(
        config_items=[
            ConfigItemIdentity(3, "6000301", "Auto Needle enhancement", "自动穿刺增强", "Auto Needle enhancement"),
            ConfigItemIdentity(59, "6000034", "Needle enhancement", "穿刺增强", "Needle enhancement"),
        ],
        legacy_features=[LegacyFeature(id=4, name="穿刺引导&穿刺增强", ipn="")],
    )

    assert preview.identities == []
    assert preview.pending[0].reason == "no_exact_ipn_match"


def test_user_confirmed_mapping_merges_legacy_name_into_target_ipn_as_alias():
    preview = build_feature_identity_preview(
        config_items=[
            ConfigItemIdentity(
                59,
                "6000034",
                "Needle enhancement【启用】",
                "穿刺增强",
                "Needle enhancement",
            ),
        ],
        legacy_features=[LegacyFeature(4, "穿刺引导&穿刺增强", "")],
        confirmed_ipn_by_legacy_feature_id={4: "6000034"},
    )

    assert preview.pending == []
    identity = preview.identities[0]
    assert identity.ipn == "6000034"
    assert identity.status == "confirmed"
    assert ("cn", "穿刺引导&穿刺增强", "alias") in [
        (name.language, name.name, name.name_type) for name in identity.names
    ]


def test_user_confirmed_mapping_rejects_an_unknown_target_ipn():
    with pytest.raises(IdentityValidationError, match="确认映射指向未知IPN"):
        build_feature_identity_preview(
            config_items=[
                ConfigItemIdentity(59, "6000034", "Needle", "穿刺增强", "Needle")
            ],
            legacy_features=[LegacyFeature(4, "穿刺引导&穿刺增强", "")],
            confirmed_ipn_by_legacy_feature_id={4: "9999999"},
        )


def test_missing_or_duplicate_config_item_ipns_stop_the_preview():
    with pytest.raises(IdentityValidationError, match="缺少IPN"):
        build_feature_identity_preview(
            config_items=[ConfigItemIdentity(1, "", "TView", "组织多普勒", "TView")],
            legacy_features=[],
        )

    with pytest.raises(IdentityValidationError, match="重复IPN"):
        build_feature_identity_preview(
            config_items=[
                ConfigItemIdentity(1, "6000017", "TView", "组织多普勒", "TView"),
                ConfigItemIdentity(2, " 6000017 ", "TView 2", "组织多普勒2", "TView 2"),
            ],
            legacy_features=[],
        )
