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
    STAGE1_BLOCKED_RELATIONS,
    STAGE1_IGNORED,
    STAGE1_IPN_BACKFILLS,
    STAGE1_NEW_IDENTITIES,
    STAGE1_RELATIONS,
    apply_stage1,
    build_stage1_plan,
)
from align_feature_identity_stage1 import main as stage1_main  # noqa: E402


CONFIG_ITEMS = (
    # id, row_index, ipn, rd_name, v_code, zh_desc, en_desc
    (4, 1, "6000088", "Pulse Wave Velocity(PWV)【启用】", "V30210", "脉搏波定量分析", "PWV"),
    (23, 2, "6000242", "Auto optimization【启用】", "V30584", "自动优化功能", "Auto optimization"),
    (55, 3, "6000018", "Elastic imaging【启用】", "V30053", "Elastic imaging压力式弹性成像", "Elastic imaging"),
    (65, 4, "3200476", "Spatio Temporal Image Correlation (STIC)【停用】", "V30037", "时间空间相关成像", "Spatio Temporal Image Correlation (STIC)"),
    (88, 5, "6000281", "Pulse Wave Velocity(PWV)", "V30623", "PWV+超快脉搏波定量分析技术", "Ultra frame PWV+"),
    (96, 6, "6000294", "SupportVFetus", "V30715", "OB测量包", "VMind  OB(standard)"),
    (106, 7, "6000075", "vCloud【启用】", "V30173", "远程传输接口", "VCloud interface"),
    (145, 8, "6000323", "Spatio Temporal Image Correlation (STIC)【启用】", "V30787", "时间空间相关成像", "Spatio Temporal Image Correlation (STIC)"),
    (183, 9, "6000185", "Niche 3D【启用】", "V30439", "壁龛成像", "Niche View"),
    (206, 10, "6000318", "Contrast imaging", "V30054", "CBI微泡造影成像", "Contrast imaging"),
    (209, 11, "6000019", "Contrast imaging【启用】", "V30054", "CBI微泡造影成像", "Contrast imaging"),
    (75, 12, "6000190", "SupportShearWave【启用】", "V30566", "剪切波弹性成像", "shear wave imaging"),
)

FEATURES = (
    # id, group_id, name, ipn, sort_order, config_item_id, cn, en, status
    (11, 4, "常规造影", "6000019", 15, 209, "CBI微泡造影成像", "Contrast imaging", "confirmed"),
    (17, 5, "EI", "6000018", 21, 55, "Elastic imaging压力式弹性成像", "Elastic imaging", "confirmed"),
    (18, 5, "SWE", "6000190", 22, 75, "剪切波弹性成像", "shear wave imaging", "confirmed"),
    (19, 5, "点式剪切波", "", 23, None, None, None, "related"),
    (26, 7, "PWV", "6000088", 30, 4, "脉搏波定量分析", "PWV", "auto_matched"),
    (31, 8, "Vmind OB", "", 35, None, None, None, "related"),
    (32, 8, "STIC", "", 36, None, None, None, "related"),
)

GROUPS = ((4, "造影成像", 3), (5, "弹性成像", 4), (7, "心血管", 6), (8, "妇产", 7), (1, "基础功能", 0))


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
        # 代号 Auto 之类的短名不登记成曾用名，避免污染检索。
        assert "Auto" not in [alias for _, alias in identity.aliases]
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
        "ipn_backfills": len(STAGE1_IPN_BACKFILLS),
        "relations": len(STAGE1_RELATIONS),
        "skipped": 0,
    }
    # 受阻关系只会出现在计划里，不会被写入。
    assert len(plan["blocked_relations"]) == len(STAGE1_BLOCKED_RELATIONS) == 2
    assert all(item["blocked_by"] for item in plan["blocked_relations"])


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

    created = _rows(
        database_path,
        "SELECT f.id, f.ipn, f.primary_cn_name, f.primary_en_name, f.identity_status,"
        " f.config_item_id, g.name AS group_name"
        " FROM features f JOIN feature_groups g ON g.id = f.group_id"
        " WHERE f.ipn IN ('6000242', '6000185', '6000281', '6000075') ORDER BY f.ipn",
    )
    assert [item["ipn"] for item in created] == ["6000075", "6000185", "6000242", "6000281", "6000323"][:0] + [
        "6000075",
        "6000185",
        "6000242",
        "6000281",
    ]
    assert {item["primary_cn_name"] for item in created} == {
        "远程传输接口",
        "壁龛成像",
        "自动优化功能",
        "PWV+超快脉搏波定量分析技术",
    }
    assert all(item["identity_status"] == "confirmed" for item in created)
    assert all(item["config_item_id"] for item in created)
    groups = {item["ipn"]: item["group_name"] for item in created}
    assert groups["6000242"] == "基础功能"
    assert groups["6000185"] == "妇产"
    assert groups["6000281"] == "心血管"
    assert groups["6000075"] == "基础功能"

    # A 侧曾用名按裁定登记，且每条新身份都有配置项关联。
    aliases = _rows(
        database_path,
        "SELECT n.feature_id, n.name FROM feature_names n"
        " JOIN features f ON f.id = n.feature_id"
        " WHERE n.name_type = 'alias' AND f.ipn IN ('6000242', '6000281', '6000075')",
    )
    assert {item["name"] for item in aliases} == {
        "一键优化",
        "PWV+超快脉搏波定量分析技术成像",
        "远程超声连接（杏聆荟）",
    }
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
        ("6000190", "child", "#19", "pending"),
    ]
    assert all(item["source_reference"] for item in relations)

    # STIC / CBI 的 supersedes 因缺端点身份而受阻，不能被悄悄丢掉。
    plan = apply_stage1(database_path, apply=False)
    blocked = {(item["source"], item["target"]): item for item in plan["blocked_relations"]}
    assert set(blocked) == {("new_ipn:6000323", "missing_ipn:3200476"),
                            ("missing_ipn:6000318", "ipn:6000019")}
    assert all("没有功能身份" in item["blocked_by"] for item in blocked.values())


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
        len(STAGE1_NEW_IDENTITIES) + 1 + len(STAGE1_IPN_BACKFILLS) + len(STAGE1_RELATIONS)
    )
    assert second["summary"]["relations"] == 0

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
    assert "受阻关系" in output
    assert "3200476" in output
    assert "H2 穿刺引导 / 穿刺增强" in output
    assert "config_items.zh_desc" in output

    assert stage1_main(["--database", str(database_path), "--apply"]) == 0
    applied_output = capsys.readouterr().out
    assert "已写入：功能 4 个" in applied_output

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
        "6000242",
        "6000185",
        "6000281",
        "6000075",
    }
    assert [item["feature_id"] for item in plan["ipn_backfills"]] == [31, 32]
    assert len(plan["relations"]) == len(STAGE1_RELATIONS) == 2
    assert len(plan["blocked_relations"]) == len(STAGE1_BLOCKED_RELATIONS) == 2
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
