"""Contract tests for the stage-1 feature identity alignment.

阶段 1 写的是正式功能主数据，所以这里钉住三件事：
1. 默认只预演，且预演不改变任何一行；
2. 每个裁定项的动作与方向（H1 改主名+留曾用名、H4/H5/H3/H7 新建身份、
   D3 补 IPN、supersedes/child 关系方向）；
3. 裁定「先忽略」的 H2 与「不建独立身份」的 H5 第二条确实什么都没做。
"""

import sqlite3
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.services.feature_identity_stage1 import (  # noqa: E402
    STAGE1_ALIASES,
    STAGE1_BLOCKED_RELATIONS,
    STAGE1_CONFIG_ITEM_NORMALIZATIONS,
    STAGE1_IGNORED,
    STAGE1_IPN_BACKFILLS,
    STAGE1_NEW_IDENTITIES,
    STAGE1_RELATIONS,
    apply_stage1,
    build_stage1_plan,
)
from align_feature_identity_stage1 import main as stage1_main  # noqa: E402


# 下面三段由正式库结构生成（只读），保证夹具与真实数据一致。
CONFIG_ITEMS = (
    (4, 81, '6000088', 'Pulse Wave Velocity(PWV)【启用】', 'V30210', '脉搏波定量分析', 'PWV'),
    (19, 45, '6000241', 'VFusion【启用】', 'V30583', '复合超声成像', 'VFusion'),
    (20, 46, '6000087', 'Vspeckle1New【启用】', 'V30209', '组织斑点噪声抑制', 'VSpeckle'),
    (22, 47, '3200487', 'VTissue【启用】', 'V30041', '组织速度特征成像', 'VTissue'),
    (23, 48, '6000242', 'Auto optimization【启用】', 'V30584', '自动优化功能', 'Auto optimization'),
    (39, 60, '6000017', 'TView【启用】', 'V30052', '梯形成像', 'TView'),
    (40, 61, '3200470', 'PView【启用】', 'V30031', '宽景成像', 'Pview'),
    (51, 71, '6000070', 'Auto OB【启用】', 'V30171', '产科自动测量', 'Auto OB'),
    (55, 73, '6000018', 'Elastic imaging【启用】', 'V30053', 'Elastic imaging压力式弹性成像', 'Elastic imaging'),
    (65, 131, '3200476', 'Spatio Temporal Image Correlation (STIC)【停用】', 'V30037', '时间空间相关成像', 'Spatio Temporal Image Correlation (STIC)'),
    (67, 84, '6000090', 'Auto Follicle【启用】', 'V30212', '二维卵泡自动测量', '2D auto follicle'),
    (71, 88, '6000168', 'HQFlow【启用】', 'V30355', '高灵敏度血流', 'VFlow'),
    (75, 101, '6000190', 'SWEI【启用】', 'V30494', '剪切波弹性成像', 'shear wave imaging'),
    (78, 104, '6000193', 'OB AIMeasure【启用】', 'V30497', 'VAim:产科自动测量', 'VAim for OB'),
    (80, 106, '6000195', 'Follicle AIMeasure【启用】', 'V30499', 'VAim:卵泡自动测量', 'VAim for Follicle'),
    (81, 109, '6000198', 'Auto Works【启用】', 'V30502', '自定义工作流', 'Customized auto workflow'),
    (84, 154, '6000273', 'SupportHSF【启用】', 'V30615', '超微细血流成像', 'SMF(Super Micro Flow)'),
    (88, 139, '6000281', 'Pulse Wave Velocity(PWV)', 'V30623', 'PWV+超快脉搏波定量分析技术', 'Ultra frame PWV+'),
    (96, 144, '6000294', 'SupportVFetus', 'V30715', 'OB测量包', 'VMind  OB(standard)'),
    (102, 115, '3200478', 'DICOM export and storage, printer, worklist【启用】', 'V30038', 'DICOM', 'DICOM export and storage, printer, worklist'),
    (106, 118, '6000075', 'vCloud【启用】', 'V30173', '远程传输接口', 'VCloud interface'),
    (117, 156, '6000355', 'ShowVVIFuntionEnable', 'V30886', '心肌矢量成像', 'VVI'),
    (124, 121, '6000358', 'Attenuation Image【启用】', 'V30889', '超声衰减成像', 'VATT'),
    (141, 129, '6000032', 'Tomographic display (Mcut)【启用】', 'V30067', '超声断层成像', 'Tomographic display (Mcut)'),
    (145, 132, '6000323', 'Spatio Temporal Image Correlation (STIC)【启用】', 'V30787', '时间空间相关成像', 'Spatio Temporal Image Correlation (STIC)'),
    (154, 136, '6000023', 'Magic cut【启用】', 'V30058', '魔术刀', 'Magic cut'),
    (167, 141, '6000091', 'Follicle 3D【启用】', 'V30213', '三维卵泡自动测量', '3D auto follicle'),
    (175, 145, '6000202', '3D Smart Face【启用】', 'V30506', '智能胎儿面部成像', '3D Smart Face'),
    (177, 146, '6000216', 'Endoscope3D【启用】', 'V30552', '超声3D内视渲染技术', 'VNavIn 3D'),
    (183, 149, '6000185', 'Niche 3D【启用】', 'V30439', '壁龛成像', 'Niche View'),
    (206, 200, '6000318', 'Contrast imaging', 'V30054', 'CBI微泡造影成像', 'Contrast imaging'),
    (207, 201, '6000333', 'SuperResolution', 'V30842', '超分辨显微成像', 'URM'),
    (209, 74, '6000019', 'Contrast imaging【启用】', 'V30054', 'CBI微泡造影成像', 'Contrast imaging'),
    (211, 204, '6000072', 'VFlash', 'V30176', '声动力成像', 'vFlash'),
    (213, 172, '6000411', 'OB AIMeasure【启用】', 'V31090', 'VAim+：产科自动测量', 'VAim+：OB'),
    (214, 167, '6000413', 'Follicle AIMeasure【启用】', 'V31092', 'VAim+：卵泡自动测量', 'VAim+：Follical'),
    (339, 82, '6000167', 'Advanced PWV【启用】', 'V30354', '整体动脉僵硬度自动测量系统', 'AMAS( Automatic measurement of Arterial stiffness )'),
    (341, 130, '3200474', 'HQ3D&HQ4D【启用】', 'V30035', '羊膜腔镜成像技术', 'HQ (High Quality) 3D/4D'),
    (343, 139, '6000073', 'Smart 3D Volume Calculation【启用】', 'V30177', '智能三维容积计算', 'Smart 3D Volume Calculation'),
    (344, 142, '6000171', 'HQSilhouette【启用】', 'V30358', 'HQ剪影模式', '4D HQ Silhouette mode'),
)

FEATURES = (
    (1, 1, 'TView', '6000017', 5, 39, '梯形成像', 'TView', 'auto_matched'),
    (2, 1, 'PView', '3200470', 6, 40, '宽景成像', 'Pview', 'auto_matched'),
    (6, 3, 'VFlow', '6000168', 10, 71, '高灵敏度血流', 'VFlow', 'auto_matched'),
    (7, 3, 'SMF', '6000273', 11, 84, '超微细血流成像', 'SMF(Super Micro Flow)', 'confirmed'),
    (11, 4, '常规造影', '6000019', 15, 209, 'CBI微泡造影成像', 'Contrast imaging', 'confirmed'),
    (12, 4, 'VFlash', '6000072', 16, 211, '声动力成像', 'vFlash', 'auto_matched'),
    (14, 4, 'URM', '6000333', 18, 207, '超分辨显微成像', 'URM', 'auto_matched'),
    (17, 5, 'EI', '6000018', 21, 55, 'Elastic imaging压力式弹性成像', 'Elastic imaging', 'confirmed'),
    (18, 5, 'SWE', '6000190', 22, 75, '剪切波弹性成像', 'shear wave imaging', 'confirmed'),
    (19, 5, '点式剪切波', '', 23, None, None, None, 'related'),
    (21, 6, 'VATT', '6000358', 25, 124, '超声衰减成像', 'VATT', 'auto_matched'),
    (26, 7, 'PWV', '6000088', 30, 4, '脉搏波定量分析', 'PWV', 'auto_matched'),
    (27, 7, 'AMAS', '6000167', 31, 339, '整体动脉僵硬度自动测量系统', 'AMAS( Automatic measurement of Arterial stiffness )', 'confirmed'),
    (30, 7, 'VVI', '6000355', 34, 117, '心肌矢量成像', 'VVI', 'auto_matched'),
    (31, 8, 'Vmind OB', '', 35, None, None, None, 'related'),
    (32, 8, 'STIC', '', 36, None, None, None, 'related'),
)

GROUPS = (
    (1, '基础功能', 0),
    (2, '穿刺', 1),
    (3, '血流', 2),
    (4, '造影成像', 3),
    (5, '弹性成像', 4),
    (6, 'GI其他', 5),
    (7, '心血管', 6),
    (8, '妇产', 7),
    (9, 'Vaid', 8),
)


def _create_database(path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE feature_groups (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, sort_order INTEGER
        );
        CREATE TABLE config_items (
            id INTEGER PRIMARY KEY, row_index INTEGER NOT NULL, ipn TEXT,
            rd_name TEXT, v_code TEXT, zh_desc TEXT, en_desc TEXT
        );
        CREATE TABLE features (
            id INTEGER PRIMARY KEY,
            group_id INTEGER NOT NULL REFERENCES feature_groups(id),
            name TEXT NOT NULL, ipn TEXT, sort_order INTEGER,
            config_item_id INTEGER REFERENCES config_items(id),
            primary_cn_name TEXT, primary_en_name TEXT,
            identity_status TEXT NOT NULL DEFAULT 'pending'
        );
        CREATE UNIQUE INDEX uq_features_normalized_ipn
        ON features(UPPER(TRIM(ipn))) WHERE TRIM(COALESCE(ipn, '')) <> '';
        CREATE TABLE feature_names (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE,
            language TEXT NOT NULL, name TEXT NOT NULL, normalized_name TEXT NOT NULL,
            name_type TEXT NOT NULL, source TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'approved',
            UNIQUE (feature_id, language, normalized_name)
        );
        CREATE UNIQUE INDEX uq_feature_primary_name
        ON feature_names(feature_id, language)
        WHERE name_type = 'primary' AND review_status = 'approved';
        CREATE TABLE feature_config_item_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE,
            config_item_id INTEGER NOT NULL REFERENCES config_items(id) ON DELETE CASCADE,
            relation_type TEXT NOT NULL, source TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'approved',
            UNIQUE (feature_id, config_item_id, relation_type)
        );
        CREATE TABLE feature_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE,
            target_feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE,
            relation_type TEXT NOT NULL, source_reference TEXT,
            review_status TEXT NOT NULL DEFAULT 'pending',
            UNIQUE (source_feature_id, target_feature_id, relation_type)
        );
        """
    )
    connection.executemany(
        "INSERT INTO feature_groups (id, name, sort_order) VALUES (?, ?, ?)", GROUPS
    )
    connection.executemany(
        "INSERT INTO config_items (id, row_index, ipn, rd_name, v_code, zh_desc, en_desc)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        CONFIG_ITEMS,
    )
    connection.executemany(
        "INSERT INTO features (id, group_id, name, ipn, sort_order, config_item_id,"
        " primary_cn_name, primary_en_name, identity_status)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        FEATURES,
    )
    for feature_id, language, name, name_type, source in (
        (11, "cn", "CBI微泡造影成像", "primary", "config_items.zh_desc"),
        (17, "cn", "Elastic imaging压力式弹性成像", "primary", "config_items.zh_desc"),
        (17, "en", "Elastic imaging", "primary", "config_items.en_desc"),
        (18, "cn", "剪切波弹性成像", "primary", "config_items.zh_desc"),
        (26, "cn", "脉搏波定量分析", "primary", "config_items.zh_desc"),
        (32, "en", "STIC", "alias", "legacy_features.name"),
    ):
        normalized = "".join(
            character
            for character in name.casefold()
            if character.isalnum()
        )
        connection.execute(
            "INSERT INTO feature_names (feature_id, language, name, normalized_name,"
            " name_type, source, review_status) VALUES (?, ?, ?, ?, ?, ?, 'approved')",
            (feature_id, language, name, normalized, name_type, source),
        )
    connection.executemany(
        "INSERT INTO feature_config_item_links (feature_id, config_item_id, relation_type,"
        " source, review_status) VALUES (?, ?, ?, ?, 'approved')",
        (
            (11, 209, "primary", "feature_identity_migration"),
            (18, 75, "primary", "feature_identity_migration"),
            (19, 75, "related", "product_owner_confirmation"),
            (26, 4, "primary", "feature_identity_migration"),
            (31, 96, "version_variant", "product_owner_confirmation"),
            (32, 65, "version_variant", "product_owner_confirmation"),
            (32, 145, "version_variant", "product_owner_confirmation"),
        ),
    )
    connection.commit()
    connection.close()


def _rows(path, sql, params=()):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]
    finally:
        connection.close()


def test_registries_only_reference_ruled_and_existing_ipns(tmp_path):
    database_path = tmp_path / "copy.db"
    _create_database(database_path)
    connection = sqlite3.connect(database_path)
    try:
        known_ipns = {
            row[0]
            for row in connection.execute(
                "SELECT UPPER(TRIM(ipn)) FROM config_items WHERE TRIM(COALESCE(ipn,'')) <> ''"
            )
        }
    finally:
        connection.close()

    for identity in STAGE1_NEW_IDENTITIES:
        assert identity.ipn.upper() in known_ipns, identity.ipn
        assert identity.source_reference
        assert identity.group_name
        # 代号 Auto 之类的短名不登记成曾用名，避免污染检索。
        assert "Auto" not in [alias for _, alias in identity.aliases]
        for language, alias in identity.aliases:
            assert language in ("cn", "en")
            # 状态标记不写进名称
            assert "【" not in alias and "（选配）" not in alias
    for backfill in STAGE1_IPN_BACKFILLS:
        assert backfill.ipn.upper() in known_ipns, backfill.ipn
    for relation in STAGE1_RELATIONS:
        assert relation.rationale and relation.source_reference
    assert any("H2" in item.decision for item in STAGE1_IGNORED)


def test_dry_run_changes_nothing(tmp_path):
    database_path = tmp_path / "copy.db"
    _create_database(database_path)
    before = {
        table: _rows(database_path, f"SELECT COUNT(*) AS total FROM {table}")[0]["total"]
        for table in ("features", "feature_names", "feature_config_item_links", "feature_relations")
    }
    before_name = _rows(
        database_path, "SELECT primary_cn_name FROM features WHERE id = 17"
    )[0]["primary_cn_name"]

    plan = apply_stage1(database_path, apply=False)

    after = {
        table: _rows(database_path, f"SELECT COUNT(*) AS total FROM {table}")[0]["total"]
        for table in ("features", "feature_names", "feature_config_item_links", "feature_relations")
    }
    assert before == after
    assert (
        _rows(database_path, "SELECT primary_cn_name FROM features WHERE id = 17")[0][
            "primary_cn_name"
        ]
        == before_name
    )
    assert plan["applied"] is False
    assert plan["summary"] == {
        "new_identities": len(STAGE1_NEW_IDENTITIES),
        "renames": 1,
        "aliases": len(STAGE1_ALIASES),
        "config_item_normalizations": len(STAGE1_CONFIG_ITEM_NORMALIZATIONS),
        "ipn_backfills": len(STAGE1_IPN_BACKFILLS),
        "relations": len(STAGE1_RELATIONS),
        # 期望名称与配置项不一致时只提示、不静默采用；本批全部一致。
        "warnings": 0,
        "skipped": 0,
    }
    # 受阻关系机制保留，但本批已解除（3200476 / 6000318 已建身份）。
    assert STAGE1_BLOCKED_RELATIONS == ()
    assert plan["blocked_relations"] == []


def test_apply_normalizes_h1_name_and_keeps_the_old_value_as_alias(tmp_path):
    database_path = tmp_path / "copy.db"
    _create_database(database_path)

    plan = apply_stage1(database_path, apply=True)

    assert plan["applied"] is True
    feature = _rows(
        database_path, "SELECT primary_cn_name, ipn, identity_status FROM features WHERE id = 17"
    )[0]
    assert feature["primary_cn_name"] == "压力式弹性成像"
    # 不动 IPN 与身份状态
    assert feature["ipn"] == "6000018"
    assert feature["identity_status"] == "confirmed"

    names = _rows(
        database_path,
        "SELECT language, name, name_type FROM feature_names WHERE feature_id = 17"
        " ORDER BY name_type, name",
    )
    assert {item["name"] for item in names if item["name_type"] == "alias"} == {
        "Elastic imaging压力式弹性成像"
    }
    assert {item["name"] for item in names if item["name_type"] == "primary"} == {
        "压力式弹性成像",
        "Elastic imaging",
    }


def test_apply_creates_the_ruled_identities_with_names_links_and_group(tmp_path):
    database_path = tmp_path / "copy.db"
    _create_database(database_path)

    apply_stage1(database_path, apply=True)

    expected_ipns = {identity.ipn for identity in STAGE1_NEW_IDENTITIES}
    created = _rows(
        database_path,
        "SELECT f.id, f.ipn, f.primary_cn_name, f.primary_en_name, f.identity_status,"
        " f.config_item_id, g.name AS group_name"
        " FROM features f JOIN feature_groups g ON g.id = f.group_id"
        " WHERE f.ipn IN ('6000242', '6000185', '6000281', '6000075', '6000171',"
        " '6000032', '6000202', '6000073', '3200478', '6000216', '3200474', '6000241',"
        " '6000087', '3200487', '6000198', '6000023', '3200476', '6000318',"
        " '6000070', '6000193', '6000411', '6000090', '6000091', '6000195', '6000413')"
        " ORDER BY f.ipn",
    )
    assert {item["ipn"] for item in created} == expected_ipns
    assert len(created) == len(STAGE1_NEW_IDENTITIES)
    assert all(item["identity_status"] == "confirmed" for item in created)
    assert all(item["config_item_id"] for item in created)
    assert all(item["primary_cn_name"] for item in created)
    by_ipn = {item["ipn"]: item for item in created}
    # 主名从配置项派生，不手抄
    assert by_ipn["6000242"]["primary_cn_name"] == "自动优化功能"
    assert by_ipn["6000185"]["primary_cn_name"] == "壁龛成像"
    assert by_ipn["6000281"]["primary_cn_name"] == "PWV+超快脉搏波定量分析技术"
    assert by_ipn["6000075"]["primary_cn_name"] == "远程传输接口"
    assert by_ipn["6000171"]["primary_cn_name"] == "HQ剪影模式"
    assert by_ipn["6000070"]["primary_cn_name"] == "产科自动测量"
    assert by_ipn["6000413"]["primary_cn_name"] == "VAim+：卵泡自动测量"
    assert by_ipn["3200476"]["primary_cn_name"] == "时间空间相关成像"
    assert by_ipn["6000318"]["primary_cn_name"] == "CBI微泡造影成像"
    # 研发名里的【启用】/【停用】状态标记不能进入名称
    assert not any("【" in item["primary_cn_name"] for item in created)
    groups = {item["ipn"]: item["group_name"] for item in created}
    assert groups["6000242"] == "基础功能"
    assert groups["6000185"] == "妇产"
    assert groups["6000281"] == "心血管"
    assert groups["6000075"] == "基础功能"
    assert groups["6000411"] == "妇产"
    assert groups["6000318"] == "造影成像"

    # A 侧曾用名按裁定登记，且每条新身份都有配置项关联。
    aliases = _rows(
        database_path,
        "SELECT n.name FROM feature_names n"
        " WHERE n.name_type = 'alias' AND n.source LIKE 'stage1:A侧曾用名%'",
    )
    expected_aliases = {
        name for identity in STAGE1_NEW_IDENTITIES for _, name in identity.aliases
    } | {alias.name for alias in STAGE1_ALIASES}
    assert {item["name"] for item in aliases} == expected_aliases
    assert len(expected_aliases) == 21  # 11 条新身份的 A 侧曾用名 + 10 条已有身份的
    links = _rows(
        database_path,
        "SELECT f.ipn FROM feature_config_item_links l JOIN features f ON f.id = l.feature_id"
        " WHERE l.relation_type = 'primary' AND f.ipn IN ('6000242', '6000185', '6000281', '6000075')",
    )
    assert len(links) == 4


def test_apply_backfills_d3_ipns_and_writes_relations_in_the_ruled_direction(tmp_path):
    database_path = tmp_path / "copy.db"
    _create_database(database_path)

    apply_stage1(database_path, apply=True)

    backfilled = {
        item["id"]: item
        for item in _rows(
            database_path,
            "SELECT id, ipn, primary_cn_name, identity_status FROM features WHERE id IN (19, 31, 32)",
        )
    }
    assert backfilled[31]["ipn"] == "6000294"
    assert backfilled[31]["primary_cn_name"] == "OB测量包"
    assert backfilled[31]["identity_status"] == "confirmed"
    assert backfilled[32]["ipn"] == "6000323"
    assert backfilled[32]["primary_cn_name"] == "时间空间相关成像"
    # D3 选项 a：点式剪切波保持无 IPN
    assert (backfilled[19]["ipn"] or "") == ""
    assert backfilled[19]["identity_status"] == "related"

    relations = _rows(
        database_path,
        "SELECT r.relation_type, r.review_status, s.ipn AS source_ipn, t.ipn AS target_ipn,"
        " t.id AS target_id, r.source_reference"
        " FROM feature_relations r"
        " JOIN features s ON s.id = r.source_feature_id"
        " JOIN features t ON t.id = r.target_feature_id"
        " ORDER BY r.id",
    )
    assert [
        (item["source_ipn"], item["relation_type"], item["target_ipn"] or f"#{item['target_id']}",
         item["review_status"])
        for item in relations
    ] == [
        ("6000281", "supersedes", "6000088", "approved"),
        ("6000323", "supersedes", "3200476", "approved"),
        ("6000318", "supersedes", "6000019", "pending"),
        ("6000190", "child", "#19", "pending"),
    ]
    assert all(item["source_reference"] for item in relations)
    assert apply_stage1(database_path, apply=False)["blocked_relations"] == []


def test_apply_is_idempotent_and_leaves_h2_untouched(tmp_path):
    database_path = tmp_path / "copy.db"
    _create_database(database_path)

    apply_stage1(database_path, apply=True)
    counts = {
        table: _rows(database_path, f"SELECT COUNT(*) AS total FROM {table}")[0]["total"]
        for table in ("features", "feature_names", "feature_config_item_links", "feature_relations")
    }
    second = apply_stage1(database_path, apply=True)

    after = {
        table: _rows(database_path, f"SELECT COUNT(*) AS total FROM {table}")[0]["total"]
        for table in ("features", "feature_names", "feature_config_item_links", "feature_relations")
    }
    assert counts == after
    assert second["summary"]["new_identities"] == 0
    assert second["summary"]["renames"] == 0
    assert second["summary"]["ipn_backfills"] == 0
    assert second["summary"]["relations"] == 0
    assert second["summary"]["skipped"] == (
        len(STAGE1_NEW_IDENTITIES)
        + 1
        + len(STAGE1_ALIASES)
        + len(STAGE1_CONFIG_ITEM_NORMALIZATIONS)
        + len(STAGE1_IPN_BACKFILLS)
        + len(STAGE1_RELATIONS)
    )
    assert second["summary"]["relations"] == 0
    assert second["summary"]["aliases"] == 0
    assert second["summary"]["config_item_normalizations"] == 0

    # H2 裁定「先忽略」：既没有新建「穿刺引导」身份，也没有任何 6000034 关系。
    assert _rows(database_path, "SELECT id FROM features WHERE name LIKE '%穿刺引导%'") == []
    assert (
        _rows(
            database_path,
            "SELECT id FROM feature_relations WHERE source_reference LIKE '%H2%'",
        )
        == []
    )


def test_rename_is_skipped_when_the_current_name_is_not_what_we_expect(tmp_path):
    database_path = tmp_path / "copy.db"
    _create_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE features SET primary_cn_name = '人工改过的名字' WHERE id = 17"
    )
    connection.commit()
    connection.close()

    plan = apply_stage1(database_path, apply=True)

    item = plan["renames"][0]
    assert item["action"] == "skip"
    assert "当前值与预期不符" in item["reason"]
    assert (
        _rows(database_path, "SELECT primary_cn_name FROM features WHERE id = 17")[0][
            "primary_cn_name"
        ]
        == "人工改过的名字"
    )


def test_cli_reports_the_plan_and_residuals(tmp_path, capsys):
    database_path = tmp_path / "copy.db"
    _create_database(database_path)

    assert stage1_main(["--database", str(database_path)]) == 0
    output = capsys.readouterr().out
    assert "dry-run：未写入任何数据" in output
    assert "[规范化主名] 功能 #17 EI" in output
    assert "[新建身份] 6000242 自动优化功能" in output
    assert "[新关系] " in output
    assert "[登记曾用名] " in output
    assert "[规范化配置项] " in output
    assert "3200476" in output
    assert "H2 穿刺引导 / 穿刺增强" in output
    assert "[规范化配置项] ci#55.zh_desc" in output
    assert "[登记曾用名] ipn:6000273" in output
    assert "计划：新建身份 25" in output

    assert stage1_main(["--database", str(database_path), "--apply"]) == 0
    applied_output = capsys.readouterr().out
    assert f"已写入：功能 {len(STAGE1_NEW_IDENTITIES)} 个" in applied_output

    missing = tmp_path / "nope.db"
    assert stage1_main(["--database", str(missing)]) == 2
    assert "数据库不存在" in capsys.readouterr().out


def test_build_plan_is_read_only_and_lists_every_action(tmp_path):
    database_path = tmp_path / "copy.db"
    _create_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        plan = build_stage1_plan(connection)
    finally:
        connection.close()

    assert {item["ipn"] for item in plan["new_identities"]} == {
        identity.ipn for identity in STAGE1_NEW_IDENTITIES
    }
    assert len(plan["aliases"]) == len(STAGE1_ALIASES)
    assert [item["feature_id"] for item in plan["ipn_backfills"]] == [31, 32]
    assert len(plan["relations"]) == len(STAGE1_RELATIONS) == 4
    assert plan["blocked_relations"] == []
    assert len(plan["ignored"]) >= 4
    assert any("H5" in item["decision"] for item in plan["ignored"])
    assert len(plan["residuals"]) >= 2


@pytest.mark.parametrize(
    "ipn, expected_group",
    (("6000242", "基础功能"), ("6000185", "妇产"), ("6000281", "心血管"), ("6000075", "基础功能")),
)
def test_new_identity_group_placement_is_explicit(tmp_path, ipn, expected_group):
    identity = next(item for item in STAGE1_NEW_IDENTITIES if item.ipn == ipn)
    assert identity.group_name == expected_group


def test_apply_registers_a_side_alias_names_on_existing_identities(tmp_path):
    database_path = tmp_path / "copy.db"
    _create_database(database_path)
    # 先模拟正式库里的既有主名（夹具里 17/11/18/26/32 已有名称行）。
    apply_stage1(database_path, apply=True)

    rows = _rows(
        database_path,
        "SELECT f.ipn, n.name, n.name_type, n.source FROM feature_names n"
        " JOIN features f ON f.id = n.feature_id"
        " WHERE n.name_type = 'alias' AND n.source LIKE 'stage1:A侧曾用名%'"
        " ORDER BY f.ipn",
    )
    by_ipn = {}
    for row in rows:
        by_ipn.setdefault(row["ipn"], set()).add(row["name"])
    assert by_ipn["6000017"] == {"TView梯形扩展成像"}
    assert by_ipn["3200470"] == {"PView宽景成像"}
    assert by_ipn["6000167"] == {"AMAS整体动脉僵硬度自动测量系统"}
    assert by_ipn["6000355"] == {"VVI心肌矢量成像"}
    # A 名称里的「（选配）」状态标记不登记
    assert by_ipn["6000072"] == {"VFlash低强度超声治疗"}
    # 主名未被改动
    assert (
        _rows(database_path, "SELECT primary_cn_name FROM features WHERE ipn = '6000072'")[0][
            "primary_cn_name"
        ]
        == "声动力成像"
    )


def test_apply_normalizes_the_polluted_config_item_description(tmp_path):
    database_path = tmp_path / "copy.db"
    _create_database(database_path)

    plan = apply_stage1(database_path, apply=True)

    item = plan["config_item_normalizations"][0]
    assert item["action"] == "normalize"
    assert item["current"] == "Elastic imaging压力式弹性成像"
    assert (
        _rows(database_path, "SELECT zh_desc FROM config_items WHERE id = 55")[0]["zh_desc"]
        == "压力式弹性成像"
    )
    # 研发名与英文描述不动
    row = _rows(
        database_path, "SELECT rd_name, en_desc FROM config_items WHERE id = 55"
    )[0]
    assert row["rd_name"] == "Elastic imaging【启用】"
    assert row["en_desc"] == "Elastic imaging"

    # 幂等：第二次不再改
    assert apply_stage1(database_path, apply=True)["summary"][
        "config_item_normalizations"
    ] == 0


def test_registry_entries_are_traceable_to_the_stage0_mapping_document():
    """每个动作的 IPN 与 A 侧名称都要能在阶段 0 文档里找到，防手抄出错。"""

    doc_path = Path(__file__).resolve().parents[2] / "docs" / "功能主数据映射-A到B-20260913.md"
    if not doc_path.is_file():
        pytest.skip("阶段 0 映射文档不在本工作区（未纳入版本控制）")
    document = doc_path.read_text(encoding="utf-8")

    for identity in STAGE1_NEW_IDENTITIES:
        assert identity.ipn in document, f"{identity.ipn} 不在映射文档里"
        # 「A1#3 xxx」这类引用的 xxx 必须是文档里的原文；纯描述性引用只校验 IPN。
        if identity.a_record.startswith(("A1#", "A2#", "A3#", "A4#")):
            record = identity.a_record.split(" ", 1)[-1]
            assert record in document, f"A 侧记录「{record}」不在映射文档里"
        for _, alias in identity.aliases:
            assert alias in document, f"曾用名「{alias}」不在映射文档里"
    for alias in STAGE1_ALIASES:
        assert alias.name in document, f"曾用名「{alias.name}」不在映射文档里"
