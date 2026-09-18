"""阶段 1 功能主数据对齐：按已裁定项落地新身份、曾用名与功能关系。

每条动作都带 `source_reference`，指向阶段 0 的记录号或裁定编号：

- H1 / H4 / H5：2026-09-18 用户裁定
- H3 / H7 / D3 / Q1a：2026-09-13 用户裁定
- H2（穿刺引导 + 穿刺增强）：裁定「先忽略」，本模块**显式不做任何动作**

边界（对齐 `.agents/skills/vinno-feature-identity-curation` 与交接文档）：

- 不删除任何 IPN、主名或历史名称；H1 的旧值登记为中文曾用名而不是丢弃；
- 新关系写 `review_status`，方向无法从版本证据判定的标 `pending` 等人工确认；
- 默认 dry-run，只有显式 apply 才写库；写库前对副本验证。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from app.services.feature_identity import clean_feature_name


# --------------------------------------------------------------------------
# 动作定义
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class NewFeatureIdentity:
    """为一个「有配置项但还没有功能身份」的 IPN 新建身份。"""

    ipn: str
    primary_cn_name: str
    primary_en_name: str
    group_name: str
    a_record: str
    source_reference: str
    aliases: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class PrimaryNameNormalization:
    """把被污染的中文主名规范化，旧值登记为曾用名。"""

    feature_id: int
    expected_current_name: str
    normalized_name: str
    source_reference: str


@dataclass(frozen=True)
class IpnBackfill:
    """给已有功能身份补 IPN 与配置项关联（D3 裁定）。"""

    feature_id: int
    ipn: str
    primary_cn_name: str
    primary_en_name: str
    source_reference: str


@dataclass(frozen=True)
class RelationAction:
    """功能之间的关系。

    引用形式：`ipn:xxx`（已有身份）、`feature:12`（按 id）、
    `new_ipn:xxx`（由本迁移新建的身份——预演时允许，执行时先建身份再解析）。
    """

    source: str
    target: str
    relation_type: str
    review_status: str
    rationale: str
    source_reference: str


@dataclass(frozen=True)
class IgnoredDecision:
    """明确「本轮不处理」的裁定，避免后人以为漏做。"""

    decision: str
    reason: str


STAGE1_NEW_IDENTITIES: tuple[NewFeatureIdentity, ...] = (
    NewFeatureIdentity(
        ipn="6000242",
        primary_cn_name="自动优化功能",
        primary_en_name="Auto optimization",
        # 通用图像自动优化，归入基础功能（现有成员：自由臂3D / 宽景成像 / 梯形成像）。
        group_name="基础功能",
        a_record="22 Auto一键优化",
        source_reference="H4 裁定 2026-09-18",
        # A 的中文「一键优化」登记为曾用名；代号 Auto 故意不登记——
        # 它会命中 B 里所有 Auto* 配置项（33 条），登记成别名只会污染检索。
        aliases=(("cn", "一键优化"),),
    ),
    NewFeatureIdentity(
        ipn="6000185",
        primary_cn_name="壁龛成像",
        primary_en_name="Niche View",
        # 三维渲染在妇产场景使用（关联项 ci#341 HQ3D&HQ4D 的中文描述为「羊膜腔镜成像技术」）。
        group_name="妇产",
        a_record="31 壁龛成像",
        source_reference="H5 裁定 2026-09-18",
    ),
    NewFeatureIdentity(
        ipn="6000281",
        primary_cn_name="PWV+超快脉搏波定量分析技术",
        primary_en_name="Ultra frame PWV+",
        group_name="心血管",
        a_record="21 PWV+超快脉搏波定量分析技术成像",
        source_reference="H3 裁定 2026-09-13",
        aliases=(("cn", "PWV+超快脉搏波定量分析技术成像"),),
    ),
    NewFeatureIdentity(
        ipn="6000075",
        primary_cn_name="远程传输接口",
        primary_en_name="VCloud interface",
        group_name="基础功能",
        a_record="35 远程超声连接（杏聆荟）",
        source_reference="H7 裁定 2026-09-13",
        aliases=(("cn", "远程超声连接（杏聆荟）"),),
    ),
)


STAGE1_PRIMARY_NAME_NORMALIZATIONS: tuple[PrimaryNameNormalization, ...] = (
    PrimaryNameNormalization(
        feature_id=17,
        expected_current_name="Elastic imaging压力式弹性成像",
        normalized_name="压力式弹性成像",
        source_reference="H1 裁定 2026-09-18",
    ),
)


STAGE1_IPN_BACKFILLS: tuple[IpnBackfill, ...] = (
    IpnBackfill(
        feature_id=31,
        ipn="6000294",
        primary_cn_name="OB测量包",
        primary_en_name="VMind  OB(standard)",
        source_reference="D3 裁定 2026-09-13（Vmind OB 补 6000294 标准版）",
    ),
    IpnBackfill(
        feature_id=32,
        ipn="6000323",
        primary_cn_name="时间空间相关成像",
        primary_en_name="Spatio Temporal Image Correlation (STIC)",
        source_reference="D3 裁定 2026-09-13（STIC 补带【启用】的 6000323 为主身份）",
    ),
)


STAGE1_RELATIONS: tuple[RelationAction, ...] = (
    RelationAction(
        source="new_ipn:6000281",
        target="ipn:6000088",
        relation_type="supersedes",
        review_status="approved",
        rationale="PWV+（V30623 / Ultra frame）是较新版，基础版为 V30210；两者不可同时选购。",
        source_reference="H3 裁定 2026-09-13",
    ),
    RelationAction(
        source="ipn:6000190",
        target="feature:19",
        relation_type="child",
        review_status="pending",
        rationale="点式剪切波是剪切波弹性成像下的子能力（D3 选项 a：不补 IPN）。",
        source_reference="D3 裁定 2026-09-13",
    ),
)


# 裁定已明确、但当前**无法落地**的关系：`feature_relations` 两端都必须是功能身份，
# 而这两组的另一端 IPN 在 B 里还没有身份（阶段 0 的新建身份清单也没收录它们）。
# 不擅自为基准版 IPN 造身份——先如实报告，等确认后再落地。
STAGE1_BLOCKED_RELATIONS: tuple[tuple[RelationAction, str], ...] = (
    (
        RelationAction(
            source="new_ipn:6000323",
            target="missing_ipn:3200476",
            relation_type="supersedes",
            review_status="approved",
            rationale="6000323 带【启用】（V30787），3200476 标【停用】（V30037）。",
            source_reference="D3 裁定 2026-09-13",
        ),
        "3200476（STIC 基准版）在 B 里没有功能身份，无法作为关系端点",
    ),
    (
        RelationAction(
            source="missing_ipn:6000318",
            target="ipn:6000019",
            relation_type="supersedes",
            review_status="pending",
            rationale=(
                "两个 IPN 的 v_code（V30054）与中文描述完全相同，无法从版本证据判断方向；"
                "暂按「已挂功能身份的 6000019 为基准、6000318 为较新变体」记录，待人工确认。"
            ),
            source_reference="Q1a 裁定 2026-09-13（方向待确认）",
        ),
        "6000318 在 B 里没有功能身份，无法作为关系端点",
    ),
)


STAGE1_IGNORED: tuple[IgnoredDecision, ...] = (
    IgnoredDecision(
        decision="H2 穿刺引导 / 穿刺增强（IPN 6000034）",
        reason=(
            "用户裁定「先忽略」：不建曾用名、不建关系、不改动既有 alias。"
            "A 侧拆成两条说明策划口径可能认为二者可独立配置，将来确认后再改为 bundle。"
        ),
    ),
    IgnoredDecision(
        decision="H5 第二条「在容积图像中显示壁龛成像三维坐标轴位置」",
        reason="用户裁定「不建独立身份」；它描述的是显示细节，不作为独立功能登记。",
    ),
    IgnoredDecision(
        decision="A 记录 40 / 41（M 模式、PW 模式的基本测量）",
        reason="B 全库无对应配置项，阶段 0 判定「建议先不建」，等业务确认。",
    ),
    IgnoredDecision(
        decision="A 记录 42 测试功能（FUNC-001）",
        reason="D2 裁定丢弃，不进入 B。",
    ),
)


# --------------------------------------------------------------------------
# 预演与执行
# --------------------------------------------------------------------------


class FeatureIdentityStage1Error(ValueError):
    """Raised when the stage-1 migration cannot be applied safely."""


def _normalize_name(value: str) -> str:
    return clean_feature_name(value).casefold()


def _connect(database_path: str | Path, *, read_only: bool) -> sqlite3.Connection:
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FeatureIdentityStage1Error(f"数据库不存在：{path}")
    connection = sqlite3.connect(f"file:{path}?mode=ro" if read_only else path, uri=read_only)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.row_factory = sqlite3.Row
    return connection


def _resolve_feature(
    connection: sqlite3.Connection,
    reference: str,
    *,
    allow_planned: bool = False,
) -> int | None:
    """Resolve a relation endpoint; ``new_ipn:`` may still be a planned identity."""

    if reference.startswith(("ipn:", "new_ipn:")):
        planned = reference.startswith("new_ipn:")
        ipn = reference.split(":", 1)[1].strip()
        row = connection.execute(
            "SELECT id FROM features WHERE UPPER(TRIM(COALESCE(ipn, ''))) = ?",
            (ipn.upper(),),
        ).fetchone()
        if row is not None:
            return int(row["id"])
        if planned and allow_planned and any(
            identity.ipn.upper() == ipn.upper() for identity in STAGE1_NEW_IDENTITIES
        ):
            # 预演阶段该身份尚未写入，按计划引用即可。
            return None
        raise FeatureIdentityStage1Error(f"找不到 IPN {ipn} 对应的功能身份")
    if reference.startswith("feature:"):
        feature_id = int(reference.split(":", 1)[1])
        row = connection.execute(
            "SELECT id FROM features WHERE id = ?", (feature_id,)
        ).fetchone()
        if row is None:
            raise FeatureIdentityStage1Error(f"找不到功能 #{feature_id}")
        return int(row["id"])
    raise FeatureIdentityStage1Error(f"无法解析引用：{reference}")


def _config_item_for_ipn(connection: sqlite3.Connection, ipn: str) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT id, ipn, zh_desc, en_desc, rd_name
        FROM config_items
        WHERE UPPER(TRIM(COALESCE(ipn, ''))) = ?
        ORDER BY id
        LIMIT 1
        """,
        (ipn.upper(),),
    ).fetchone()
    if row is None:
        raise FeatureIdentityStage1Error(f"找不到 IPN {ipn} 的配置项")
    return row


def _feature_group_id(connection: sqlite3.Connection, name: str) -> int:
    row = connection.execute(
        "SELECT id FROM feature_groups WHERE name = ?", (name,)
    ).fetchone()
    if row is None:
        raise FeatureIdentityStage1Error(f"找不到功能组「{name}」")
    return int(row["id"])


def _next_sort_order(connection: sqlite3.Connection, group_id: int) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS value FROM features WHERE group_id = ?",
        (group_id,),
    ).fetchone()
    return int(row["value"]) + 1


def build_stage1_plan(connection: sqlite3.Connection) -> dict:
    """Compute what the migration would do, without writing anything."""

    plan: dict = {
        "new_identities": [],
        "renames": [],
        "ipn_backfills": [],
        "relations": [],
        "blocked_relations": [
            {
                "source": action.source,
                "target": action.target,
                "relation_type": action.relation_type,
                "review_status": action.review_status,
                "rationale": action.rationale,
                "source_reference": action.source_reference,
                "blocked_by": reason,
            }
            for action, reason in STAGE1_BLOCKED_RELATIONS
        ],
        "ignored": [
            {"decision": item.decision, "reason": item.reason} for item in STAGE1_IGNORED
        ],
    }

    for identity in STAGE1_NEW_IDENTITIES:
        existing = connection.execute(
            "SELECT id, primary_cn_name FROM features WHERE UPPER(TRIM(COALESCE(ipn, ''))) = ?",
            (identity.ipn.upper(),),
        ).fetchone()
        item = {
            "ipn": identity.ipn,
            "primary_cn_name": identity.primary_cn_name,
            "group_name": identity.group_name,
            "a_record": identity.a_record,
            "source_reference": identity.source_reference,
            "aliases": [alias for _, alias in identity.aliases],
        }
        if existing is not None:
            item.update({"action": "skip", "reason": "该 IPN 已有功能身份",
                         "feature_id": int(existing["id"])})
        else:
            _config_item_for_ipn(connection, identity.ipn)
            _feature_group_id(connection, identity.group_name)
            item.update({"action": "create", "feature_id": None})
        plan["new_identities"].append(item)

    for normalization in STAGE1_PRIMARY_NAME_NORMALIZATIONS:
        row = connection.execute(
            "SELECT id, name, ipn, primary_cn_name FROM features WHERE id = ?",
            (normalization.feature_id,),
        ).fetchone()
        if row is None:
            raise FeatureIdentityStage1Error(f"找不到功能 #{normalization.feature_id}")
        current = row["primary_cn_name"] or ""
        item = {
            "feature_id": normalization.feature_id,
            "legacy_name": row["name"],
            "ipn": row["ipn"],
            "current_name": current,
            "normalized_name": normalization.normalized_name,
            "source_reference": normalization.source_reference,
        }
        if current == normalization.normalized_name:
            item.update({"action": "skip", "reason": "中文主名已是规范值"})
        elif current != normalization.expected_current_name:
            # 数据被人改过：不静默覆盖，交给人工确认。
            item.update({"action": "skip", "reason": f"当前值与预期不符（{current!r}）"})
        else:
            item["action"] = "rename"
        plan["renames"].append(item)

    for backfill in STAGE1_IPN_BACKFILLS:
        row = connection.execute(
            "SELECT id, name, ipn FROM features WHERE id = ?", (backfill.feature_id,)
        ).fetchone()
        if row is None:
            raise FeatureIdentityStage1Error(f"找不到功能 #{backfill.feature_id}")
        current_ipn = (row["ipn"] or "").strip()
        item = {
            "feature_id": backfill.feature_id,
            "legacy_name": row["name"],
            "current_ipn": current_ipn,
            "ipn": backfill.ipn,
            "primary_cn_name": backfill.primary_cn_name,
            "source_reference": backfill.source_reference,
        }
        if current_ipn.upper() == backfill.ipn.upper():
            item.update({"action": "skip", "reason": "IPN 已补齐"})
        elif current_ipn:
            item.update({"action": "skip", "reason": f"已有其它 IPN（{current_ipn}），不覆盖"})
        else:
            _config_item_for_ipn(connection, backfill.ipn)
            item["action"] = "backfill"
        plan["ipn_backfills"].append(item)

    for relation in STAGE1_RELATIONS:
        source_id = _resolve_feature(connection, relation.source, allow_planned=True)
        target_id = _resolve_feature(connection, relation.target, allow_planned=True)
        if source_id is not None and source_id == target_id:
            raise FeatureIdentityStage1Error("功能关系的两端不能是同一身份")
        if source_id is None and target_id is None:
            raise FeatureIdentityStage1Error("功能关系的两端不能都是新建身份")
        existing = connection.execute(
            """
            SELECT id FROM feature_relations
            WHERE source_feature_id = ? AND target_feature_id = ? AND relation_type = ?
            """,
            (source_id, target_id, relation.relation_type),
        ).fetchone()
        item = {
            "source_feature_id": source_id,
            "target_feature_id": target_id,
            "source_reference_key": relation.source,
            "target_reference_key": relation.target,
            "relation_type": relation.relation_type,
            "review_status": relation.review_status,
            "rationale": relation.rationale,
            "source_reference": relation.source_reference,
            "planned_endpoint": source_id is None or target_id is None,
        }
        if existing is not None:
            item.update({"action": "skip", "reason": "关系已存在"})
        else:
            item["action"] = "create"
        plan["relations"].append(item)

    plan["summary"] = {
        "new_identities": sum(
            1 for item in plan["new_identities"] if item["action"] == "create"
        ),
        "renames": sum(1 for item in plan["renames"] if item["action"] == "rename"),
        "ipn_backfills": sum(
            1 for item in plan["ipn_backfills"] if item["action"] == "backfill"
        ),
        "relations": sum(1 for item in plan["relations"] if item["action"] == "create"),
        "skipped": sum(
            1
            for key in ("new_identities", "renames", "ipn_backfills", "relations")
            for item in plan[key]
            if item["action"] == "skip"
        ),
    }
    plan["residuals"] = [
        (
            "受阻关系：STIC 基准版 3200476 与 CBI 变体 6000318 在 B 里都没有功能身份，"
            "而 feature_relations 的两端必须是身份；需先裁定是否为这两个基准/变体 IPN 建身份。"
        ),
        (
            "H1：config_items.zh_desc 仍是「Elastic imaging压力式弹性成像」"
            "（配置项 ci#55）。配置主数据属另一层，未一并修改；"
            "只要它不改，将来重跑身份迁移仍会派生带英文的中文主名。"
        ),
        (
            "H5 第二条子能力按裁定不建独立身份，A 侧该记录不进入 B，"
            "如需保留描述请改挂参数或说明字段。"
        ),
    ]
    return plan


def apply_stage1(database_path: str | Path, *, apply: bool = False) -> dict:
    """Preview, and with ``apply=True`` write, the stage-1 alignment."""

    connection = _connect(database_path, read_only=not apply)
    try:
        plan = build_stage1_plan(connection)
        plan["database"] = str(Path(database_path).expanduser().resolve())
        plan["applied"] = False
        if not apply:
            return plan

        created = {"features": 0, "names": 0, "links": 0, "relations": 0}
        feature_count_before = connection.execute(
            "SELECT COUNT(*) FROM features"
        ).fetchone()[0]
        names_before = connection.execute(
            "SELECT COUNT(*) FROM feature_names"
        ).fetchone()[0]

        try:
            for identity, planned in zip(STAGE1_NEW_IDENTITIES, plan["new_identities"]):
                if planned["action"] != "create":
                    continue
                item = _config_item_for_ipn(connection, identity.ipn)
                group_id = _feature_group_id(connection, identity.group_name)
                sort_order = _next_sort_order(connection, group_id)
                cursor = connection.execute(
                    """
                    INSERT INTO features (
                        group_id, name, ipn, sort_order, config_item_id,
                        primary_cn_name, primary_en_name, identity_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'confirmed')
                    """,
                    (
                        group_id,
                        identity.primary_cn_name,
                        identity.ipn,
                        sort_order,
                        int(item["id"]),
                        identity.primary_cn_name,
                        identity.primary_en_name,
                    ),
                )
                feature_id = int(cursor.lastrowid)
                created["features"] += 1
                for language, name in (
                    ("cn", identity.primary_cn_name),
                    ("en", identity.primary_en_name),
                ):
                    connection.execute(
                        """
                        INSERT INTO feature_names (
                            feature_id, language, name, normalized_name,
                            name_type, source, review_status
                        ) VALUES (?, ?, ?, ?, 'primary', ?, 'approved')
                        ON CONFLICT(feature_id, language, normalized_name) DO NOTHING
                        """,
                        (
                            feature_id,
                            language,
                            name,
                            _normalize_name(name),
                            f"stage1:{identity.source_reference}",
                        ),
                    )
                    created["names"] += 1
                for language, name in identity.aliases:
                    connection.execute(
                        """
                        INSERT INTO feature_names (
                            feature_id, language, name, normalized_name,
                            name_type, source, review_status
                        ) VALUES (?, ?, ?, ?, 'alias', ?, 'approved')
                        ON CONFLICT(feature_id, language, normalized_name) DO NOTHING
                        """,
                        (
                            feature_id,
                            language,
                            name,
                            _normalize_name(name),
                            f"stage1:A侧曾用名（{identity.a_record}）",
                        ),
                    )
                    created["names"] += 1
                connection.execute(
                    """
                    INSERT INTO feature_config_item_links (
                        feature_id, config_item_id, relation_type, source, review_status
                    ) VALUES (?, ?, 'primary', ?, 'approved')
                    ON CONFLICT(feature_id, config_item_id, relation_type)
                    DO UPDATE SET source = excluded.source,
                                  review_status = excluded.review_status
                    """,
                    (
                        feature_id,
                        int(item["id"]),
                        f"stage1:{identity.source_reference}",
                    ),
                )
                created["links"] += 1

            for normalization, planned in zip(
                STAGE1_PRIMARY_NAME_NORMALIZATIONS, plan["renames"]
            ):
                if planned["action"] != "rename":
                    continue
                feature_id = normalization.feature_id
                old_name = normalization.expected_current_name
                new_name = normalization.normalized_name
                connection.execute(
                    """
                    UPDATE features SET primary_cn_name = ?
                    WHERE id = ? AND primary_cn_name = ?
                    """,
                    (new_name, feature_id, old_name),
                )
                connection.execute(
                    """
                    UPDATE feature_names
                    SET name = ?, normalized_name = ?, source = ?
                    WHERE feature_id = ? AND language = 'cn'
                      AND name_type = 'primary' AND name = ?
                    """,
                    (
                        new_name,
                        _normalize_name(new_name),
                        f"stage1:{normalization.source_reference}",
                        feature_id,
                        old_name,
                    ),
                )
                # 旧值不删除：登记为中文曾用名。
                connection.execute(
                    """
                    INSERT INTO feature_names (
                        feature_id, language, name, normalized_name,
                        name_type, source, review_status
                    ) VALUES (?, 'cn', ?, ?, 'alias', ?, 'approved')
                    ON CONFLICT(feature_id, language, normalized_name) DO UPDATE SET
                        name = excluded.name,
                        name_type = excluded.name_type,
                        source = excluded.source,
                        review_status = excluded.review_status
                    """,
                    (
                        feature_id,
                        old_name,
                        _normalize_name(old_name),
                        f"stage1:规范前中文主名（{normalization.source_reference}）",
                    ),
                )
                created["names"] += 1

            for backfill, planned in zip(STAGE1_IPN_BACKFILLS, plan["ipn_backfills"]):
                if planned["action"] != "backfill":
                    continue
                item = _config_item_for_ipn(connection, backfill.ipn)
                connection.execute(
                    """
                    UPDATE features
                    SET ipn = ?, config_item_id = ?, primary_cn_name = ?,
                        primary_en_name = ?, identity_status = 'confirmed'
                    WHERE id = ?
                    """,
                    (
                        backfill.ipn,
                        int(item["id"]),
                        backfill.primary_cn_name,
                        backfill.primary_en_name,
                        backfill.feature_id,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO feature_names (
                        feature_id, language, name, normalized_name,
                        name_type, source, review_status
                    ) VALUES (?, ?, ?, ?, 'primary', ?, 'approved')
                    ON CONFLICT(feature_id, language, normalized_name) DO UPDATE SET
                        name = excluded.name,
                        name_type = excluded.name_type,
                        source = excluded.source,
                        review_status = excluded.review_status
                    """,
                    (
                        backfill.feature_id,
                        "cn",
                        backfill.primary_cn_name,
                        _normalize_name(backfill.primary_cn_name),
                        f"stage1:{backfill.source_reference}",
                    ),
                )
                created["names"] += 1

            for relation, planned in zip(STAGE1_RELATIONS, plan["relations"]):
                if planned["action"] != "create":
                    continue
                # 身份已经建好，这里严格解析（new_ipn 也必须真实存在）。
                resolved_source = _resolve_feature(connection, relation.source)
                resolved_target = _resolve_feature(connection, relation.target)
                if resolved_source == resolved_target:
                    raise FeatureIdentityStage1Error("功能关系的两端不能是同一身份")
                planned["source_feature_id"] = resolved_source
                planned["target_feature_id"] = resolved_target
                planned["planned_endpoint"] = False
                connection.execute(
                    """
                    INSERT INTO feature_relations (
                        source_feature_id, target_feature_id, relation_type,
                        source_reference, review_status
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source_feature_id, target_feature_id, relation_type)
                    DO NOTHING
                    """,
                    (
                        resolved_source,
                        resolved_target,
                        relation.relation_type,
                        f"{relation.source_reference}；{relation.rationale}",
                        relation.review_status,
                    ),
                )
                created["relations"] += 1

            feature_count_after = connection.execute(
                "SELECT COUNT(*) FROM features"
            ).fetchone()[0]
            names_after = connection.execute(
                "SELECT COUNT(*) FROM feature_names"
            ).fetchone()[0]
            if feature_count_after != feature_count_before + created["features"]:
                raise FeatureIdentityStage1Error("功能总数变化与计划不符")
            if names_after < names_before:
                raise FeatureIdentityStage1Error("名称行数减少，违反「不删除历史名称」")
            duplicates = connection.execute(
                """
                SELECT UPPER(TRIM(ipn)) AS value, COUNT(*) AS total
                FROM features
                WHERE TRIM(COALESCE(ipn, '')) <> ''
                GROUP BY value HAVING total > 1
                """
            ).fetchall()
            if duplicates:
                raise FeatureIdentityStage1Error(f"出现重复 IPN：{duplicates}")
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise FeatureIdentityStage1Error(f"外键冲突：{violations}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        plan["created"] = created
        plan["applied"] = True
        return plan
    finally:
        connection.close()

__all__ = [
    "FeatureIdentityStage1Error",
    "IgnoredDecision",
    "IpnBackfill",
    "NewFeatureIdentity",
    "PrimaryNameNormalization",
    "RelationAction",
    "STAGE1_BLOCKED_RELATIONS",
    "STAGE1_IGNORED",
    "STAGE1_IPN_BACKFILLS",
    "STAGE1_NEW_IDENTITIES",
    "STAGE1_PRIMARY_NAME_NORMALIZATIONS",
    "STAGE1_RELATIONS",
    "apply_stage1",
    "build_stage1_plan",
]
