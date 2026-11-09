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
import re
import sqlite3

from app.services.feature_identity import clean_feature_name


# --------------------------------------------------------------------------
# 动作定义
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class NewFeatureIdentity:
    """为一个「有配置项但还没有功能身份」的 IPN 新建身份。

    主名默认从 `config_items` 派生（zh_desc / en_desc），避免手抄出错；
    填写 `expected_cn_name` / `expected_en_name` 时只用于**核对**，
    与配置项不一致会在计划里给出 warning，仍以配置项数据为准。
    """

    ipn: str
    group_name: str
    a_record: str
    source_reference: str
    expected_cn_name: str = ""
    expected_en_name: str = ""
    aliases: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class AliasAction:
    """把 A 侧名称登记为已有身份的曾用名。"""

    target: str
    language: str
    name: str
    a_record: str
    source_reference: str


@dataclass(frozen=True)
class PrimaryNameNormalization:
    """把被污染的中文主名规范化，旧值登记为曾用名。"""

    feature_id: int
    expected_current_name: str
    normalized_name: str
    source_reference: str


@dataclass(frozen=True)
class ConfigItemTextNormalization:
    """规范化功能主数据的来源字段（配置项描述）。

    这一层独立于功能身份：H1 的中文主名就是从 `config_items.zh_desc` 派生的，
    只改功能侧而不改来源，重跑身份迁移会把污染值带回来。
    """

    config_item_id: int
    column: str
    expected_current: str
    normalized: str
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
    # ---- 2026-09-18 用户裁定（H3/H4/H5/H7 + 解除两条 supersedes 的端点缺口）----
    NewFeatureIdentity(
        ipn="6000242",
        group_name="基础功能",
        a_record="A3#22 Auto一键优化",
        source_reference="H4 裁定 2026-09-18",
        expected_cn_name="自动优化功能",
        expected_en_name="Auto optimization",
        # 代号 Auto 故意不登记：它会命中 33 条 Auto* 配置项，登记成别名只会污染检索。
        aliases=(("cn", "一键优化"),),
    ),
    NewFeatureIdentity(
        ipn="6000185",
        group_name="妇产",
        a_record="A3#31 壁龛成像",
        source_reference="H5 裁定 2026-09-18",
        expected_cn_name="壁龛成像",
        expected_en_name="Niche View",
    ),
    NewFeatureIdentity(
        ipn="6000281",
        group_name="心血管",
        a_record="A2#21 PWV+超快脉搏波定量分析技术成像",
        source_reference="H3 裁定 2026-09-13",
        expected_cn_name="PWV+超快脉搏波定量分析技术",
        expected_en_name="Ultra frame PWV+",
        aliases=(("cn", "PWV+超快脉搏波定量分析技术成像"),),
    ),
    NewFeatureIdentity(
        ipn="6000075",
        group_name="基础功能",
        a_record="A3#35 远程超声连接（杏聆荟）",
        source_reference="H7 裁定 2026-09-13",
        expected_cn_name="远程传输接口",
        expected_en_name="VCloud interface",
        aliases=(("cn", "远程超声连接（杏聆荟）"),),
    ),
    # 解除两条 supersedes 的端点缺口（2026-09-18 裁定：为基准/变体 IPN 建身份）。
    NewFeatureIdentity(
        ipn="3200476",
        group_name="妇产",
        a_record="A1#8 STIC",
        source_reference="2026-09-18 裁定（解除 STIC supersedes 端点缺口：为基准版建身份）",
    ),
    NewFeatureIdentity(
        ipn="6000318",
        group_name="造影成像",
        a_record="A1#2 CBI",
        source_reference="2026-09-18 裁定（解除 CBI supersedes 端点缺口：为变体 IPN 建身份）",
    ),
    # ---- 阶段 0 判定应新建的身份（确认/高置信度）----
    NewFeatureIdentity(
        ipn="6000171",
        group_name="基础功能",
        a_record="A1#3 HQ剪影模式",
        source_reference="阶段 0 A1#3（确认）",
    ),
    NewFeatureIdentity(
        ipn="6000032",
        group_name="基础功能",
        a_record="A1#4 Mcut超声断层成像",
        source_reference="阶段 0 A1#4（确认）",
        aliases=(("cn", "Mcut超声断层成像"),),
    ),
    NewFeatureIdentity(
        ipn="6000202",
        group_name="妇产",
        a_record="A1#7 Smart Face智能胎儿面部成像",
        source_reference="阶段 0 A1#7（确认）",
        aliases=(("cn", "Smart Face智能胎儿面部成像"),),
    ),
    NewFeatureIdentity(
        ipn="6000073",
        group_name="妇产",
        a_record="A1#14 VOCAL智能三维容积计算",
        source_reference="阶段 0 A1#14（高）",
        aliases=(("cn", "VOCAL智能三维容积计算"),),
    ),
    NewFeatureIdentity(
        ipn="6000216",
        group_name="基础功能",
        a_record="A2#36 超声3D内视渲染技术",
        source_reference="阶段 0 A2#36（中；与 3200474 的关系待确认）",
    ),
    NewFeatureIdentity(
        ipn="3200474",
        group_name="妇产",
        a_record="A3#33 羊膜腔镜成像技术",
        source_reference="阶段 0 A3#33（确认）",
    ),
    NewFeatureIdentity(
        ipn="6000241",
        group_name="基础功能",
        a_record="A3#25 vFusion复合成像技术",
        source_reference="阶段 0 A3#25（高）",
        aliases=(("cn", "vFusion复合成像技术"),),
    ),
    NewFeatureIdentity(
        ipn="6000087",
        group_name="基础功能",
        a_record="A3#26 vSpeckle斑点噪声抑制技术",
        source_reference="阶段 0 A3#26（高）",
        aliases=(("cn", "vSpeckle斑点噪声抑制技术"),),
    ),
    NewFeatureIdentity(
        ipn="3200487",
        group_name="心血管",
        a_record="A3#27 vTissue组织速度特征成像",
        source_reference="阶段 0 A3#27（确认）",
        aliases=(("cn", "vTissue组织速度特征成像"),),
    ),
    NewFeatureIdentity(
        ipn="6000198",
        group_name="基础功能",
        a_record="A3#28 vWork自定义工作流",
        source_reference="阶段 0 A3#28（中）",
        aliases=(("cn", "vWork自定义工作流"),),
    ),
    NewFeatureIdentity(
        ipn="6000023",
        group_name="妇产",
        a_record="A3#34 魔术刀",
        source_reference="阶段 0 A3#34（确认）",
    ),
    NewFeatureIdentity(
        ipn="3200478",
        group_name="基础功能",
        a_record="A3#23 DICOM基础功能",
        source_reference="阶段 0 A3#23（高）",
        aliases=(("cn", "DICOM基础功能"),),
    ),
    # H6 裁定「产科与卵泡各自按 B 的维度与代际拆分」→ 只建身份，不合并成一条。
    NewFeatureIdentity(
        ipn="6000070",
        group_name="妇产",
        a_record="A3#29 产科自动测量",
        source_reference="阶段 0 A3#29（基础代际）+ H6 裁定 2026-09-13",
    ),
    NewFeatureIdentity(
        ipn="6000193",
        group_name="妇产",
        a_record="A3#29 产科自动测量",
        source_reference="阶段 0 A3#29（VAim 代际）+ H6 裁定 2026-09-13",
    ),
    NewFeatureIdentity(
        ipn="6000411",
        group_name="妇产",
        a_record="A3#29 产科自动测量",
        source_reference="阶段 0 A3#29（VAim+ 代际）+ H6 裁定 2026-09-13",
    ),
    NewFeatureIdentity(
        ipn="6000090",
        group_name="妇产",
        a_record="A3#30 卵泡自动测量",
        source_reference="阶段 0 A3#30（二维代际）+ H6 裁定 2026-09-13",
    ),
    NewFeatureIdentity(
        ipn="6000091",
        group_name="妇产",
        a_record="A3#30 卵泡自动测量",
        source_reference="阶段 0 A3#30（三维代际）+ H6 裁定 2026-09-13",
    ),
    NewFeatureIdentity(
        ipn="6000195",
        group_name="妇产",
        a_record="A3#30 卵泡自动测量",
        source_reference="阶段 0 A3#30（VAim 代际）+ H6 裁定 2026-09-13",
    ),
    NewFeatureIdentity(
        ipn="6000413",
        group_name="妇产",
        a_record="A3#30 卵泡自动测量",
        source_reference="阶段 0 A3#30（VAim+ 代际）+ H6 裁定 2026-09-13",
    ),
)


# A 侧名称 → 已有 B 身份的曾用名（阶段 1 第 2 步：只做增量，不改主名、不删名称）。
# A 名称里的「（选配）」等状态标记不登记，避免把状态写进名称。
STAGE1_ALIASES: tuple[AliasAction, ...] = (
    AliasAction("ipn:6000167", "cn", "AMAS整体动脉僵硬度自动测量系统", "A1#1", "阶段 0 A1#1（确认）"),
    AliasAction("ipn:3200470", "cn", "PView宽景成像", "A1#5", "阶段 0 A1#5（确认）"),
    AliasAction("ipn:6000273", "cn", "SMF超微细血流", "A1#6", "阶段 0 A1#6（确认）"),
    AliasAction("ipn:6000017", "cn", "TView梯形扩展成像", "A1#9", "阶段 0 A1#9（确认）"),
    AliasAction("ipn:6000333", "cn", "URM超分辨显微成像", "A1#10", "阶段 0 A1#10（确认）"),
    AliasAction("ipn:6000358", "cn", "VATT超声衰减成像", "A1#11", "阶段 0 A1#11（确认）"),
    AliasAction("ipn:6000072", "cn", "VFlash低强度超声治疗", "A1#12", "阶段 0 A1#12（中）"),
    AliasAction("ipn:6000168", "cn", "VFlow高灵敏度血流", "A1#13", "阶段 0 A1#13（确认）"),
    AliasAction("ipn:6000190", "cn", "VShear剪切波弹性成像", "A1#15", "阶段 0 A1#15（确认）"),
    AliasAction("ipn:6000355", "cn", "VVI心肌矢量成像", "A1#16", "阶段 0 A1#16（确认）"),
)


STAGE1_PRIMARY_NAME_NORMALIZATIONS: tuple[PrimaryNameNormalization, ...] = (
    PrimaryNameNormalization(
        feature_id=17,
        expected_current_name="Elastic imaging压力式弹性成像",
        normalized_name="压力式弹性成像",
        source_reference="H1 裁定 2026-09-18",
    ),
)


STAGE1_CONFIG_ITEM_NORMALIZATIONS: tuple[ConfigItemTextNormalization, ...] = (
    ConfigItemTextNormalization(
        config_item_id=55,
        column="zh_desc",
        expected_current="Elastic imaging压力式弹性成像",
        normalized="压力式弹性成像",
        source_reference="H1 裁定 2026-09-18（2026-09-18 追加确认：一并规范来源字段）",
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
        source="new_ipn:6000323",
        target="new_ipn:3200476",
        relation_type="supersedes",
        review_status="approved",
        rationale="6000323 带【启用】（V30787），3200476 标【停用】（V30037）。",
        source_reference="D3 裁定 2026-09-13",
    ),
    RelationAction(
        source="new_ipn:6000318",
        target="ipn:6000019",
        relation_type="supersedes",
        review_status="pending",
        rationale=(
            "两个 IPN 的 v_code（V30054）与中文描述完全相同，无法从版本证据判断方向；"
            "暂按「已挂功能身份的 6000019 为基准、6000318 为较新变体」记录，待人工确认。"
        ),
        source_reference="Q1a 裁定 2026-09-13（方向待确认）",
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


# 裁定已明确、但**两端缺少功能身份**时无法落地：`feature_relations` 两端都必须
# 是身份。STIC 的 3200476 与 CBI 的 6000318 已于 2026-09-18 裁定建身份，
# 因此本批次为空；保留这个机制供后续出现同类缺口时使用。
STAGE1_BLOCKED_RELATIONS: tuple[tuple[RelationAction, str], ...] = ()


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
        planned_ipns = {identity.ipn.upper() for identity in STAGE1_NEW_IDENTITIES} | {
            backfill.ipn.upper() for backfill in STAGE1_IPN_BACKFILLS
        }
        if allow_planned and ipn.upper() in planned_ipns:
            # 预演阶段该身份尚未写入（新建身份或本次补 IPN），按计划引用即可。
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


PLACEHOLDER_STATUS_PATTERN = re.compile(r"【[^】]*】")


def _names_from_config_item(row: sqlite3.Row) -> tuple[str, str]:
    """Derive the primary names from the configuration item.

    主名以 `zh_desc` / `en_desc` 为准；两者为空时回退到研发名，并去掉
    「【启用】/【未发布】」这类状态标记，避免把状态写进名称。
    """

    def clean(value) -> str:
        text = PLACEHOLDER_STATUS_PATTERN.sub("", str(value or ""))
        return " ".join(text.split())

    cn_name = clean(row["zh_desc"]) or clean(row["rd_name"])
    en_name = clean(row["en_desc"]) or clean(row["rd_name"])
    if not cn_name:
        raise FeatureIdentityStage1Error("配置项缺少可用的中文名称")
    return cn_name, en_name


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
        "aliases": [],
        "config_item_normalizations": [],
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
            "primary_cn_name": identity.expected_cn_name,
            "group_name": identity.group_name,
            "a_record": identity.a_record,
            "source_reference": identity.source_reference,
            "aliases": [alias for _, alias in identity.aliases],
        }
        if existing is not None:
            item.update({"action": "skip", "reason": "该 IPN 已有功能身份",
                         "feature_id": int(existing["id"])})
        else:
            config_item = _config_item_for_ipn(connection, identity.ipn)
            _feature_group_id(connection, identity.group_name)
            derived_cn, derived_en = _names_from_config_item(config_item)
            item["primary_cn_name"] = derived_cn
            item["primary_en_name"] = derived_en
            # 期望值只用于核对：与配置项不一致时提示，不静默采用。
            for field, expected, derived in (
                ("primary_cn_name", identity.expected_cn_name, derived_cn),
                ("primary_en_name", identity.expected_en_name, derived_en),
            ):
                if expected and expected != derived:
                    item.setdefault("warnings", []).append(
                        f"{field} 与配置项不一致：期望 {expected!r}，配置项为 {derived!r}"
                    )
            item.update({"action": "create", "feature_id": None})
        plan["new_identities"].append(item)

    for alias in STAGE1_ALIASES:
        feature_id = _resolve_feature(connection, alias.target, allow_planned=True)
        item = {
            "target": alias.target,
            "feature_id": feature_id,
            "language": alias.language,
            "name": alias.name,
            "a_record": alias.a_record,
            "source_reference": alias.source_reference,
        }
        existing = None
        if feature_id is not None:
            existing = connection.execute(
                """
                SELECT id FROM feature_names
                WHERE feature_id = ? AND language = ? AND normalized_name = ?
                """,
                (feature_id, alias.language, _normalize_name(alias.name)),
            ).fetchone()
        if existing is not None:
            item.update({"action": "skip", "reason": "该名称已存在（主名或曾用名）"})
        else:
            item["action"] = "create"
        plan["aliases"].append(item)

    for normalization in STAGE1_CONFIG_ITEM_NORMALIZATIONS:
        row = connection.execute(
            f"SELECT id, {normalization.column} AS value FROM config_items WHERE id = ?",
            (normalization.config_item_id,),
        ).fetchone()
        if row is None:
            raise FeatureIdentityStage1Error(
                f"找不到配置项 #{normalization.config_item_id}"
            )
        current = row["value"] or ""
        item = {
            "config_item_id": normalization.config_item_id,
            "column": normalization.column,
            "current": current,
            "normalized": normalization.normalized,
            "source_reference": normalization.source_reference,
        }
        if current == normalization.normalized:
            item.update({"action": "skip", "reason": "已是规范值"})
        elif current != normalization.expected_current:
            item.update({"action": "skip", "reason": f"当前值与预期不符（{current!r}）"})
        else:
            item["action"] = "normalize"
        plan["config_item_normalizations"].append(item)

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
        # 预演时两侧可能都还是「计划中的身份」（例如 STIC 的较新版与基准版
        # 都在本批新建）；执行阶段会严格解析并再校验一次。
        if source_id is not None and source_id == target_id:
            raise FeatureIdentityStage1Error("功能关系的两端不能是同一身份")
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
        "aliases": sum(1 for item in plan["aliases"] if item["action"] == "create"),
        "config_item_normalizations": sum(
            1
            for item in plan["config_item_normalizations"]
            if item["action"] == "normalize"
        ),
        "ipn_backfills": sum(
            1 for item in plan["ipn_backfills"] if item["action"] == "backfill"
        ),
        "relations": sum(1 for item in plan["relations"] if item["action"] == "create"),
        "warnings": sum(len(item.get("warnings", [])) for item in plan["new_identities"]),
        "skipped": sum(
            1
            for key in (
                "new_identities",
                "renames",
                "aliases",
                "config_item_normalizations",
                "ipn_backfills",
                "relations",
            )
            for item in plan[key]
            if item["action"] == "skip"
        ),
    }
    plan["residuals"] = [
        (
            "A 记录 29 / 30（产科与卵泡自动测量）：H6 裁定「按代际拆分」，本次只建身份；"
            "A 的笼统名称「产科自动测量 / 卵泡自动测量」登记到哪一代（H6a 曾用名登记范围）仍待定。"
        ),
        (
            "A 记录 20（VMind+产筛精灵「常规版」）与 A 记录 24（Zoom图像放大）："
            "措辞或落点需确认，本次未登记曾用名、未建身份。"
        ),
        (
            "A 记录 23（DICOM）：本次按 3200478 建身份；"
            "3201201（DicomStoragePackage）/ 3201203（DicomNetworkPackage）是否属于同一打包项待确认。"
        ),
        (
            "A 记录 36（超声3D内视渲染技术 → 6000216）与 3200474（羊膜腔镜成像技术）："
            "两者是否构成 3D 渲染族的版本关系待确认，本次只建身份、不建关系。"
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

        created = {
            "features": 0,
            "names": 0,
            "links": 0,
            "relations": 0,
            "config_items": 0,
        }
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
                cn_name, en_name = _names_from_config_item(item)
                cursor = connection.execute(
                    """
                    INSERT INTO features (
                        group_id, name, ipn, sort_order, config_item_id,
                        primary_cn_name, primary_en_name, identity_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'confirmed')
                    """,
                    (
                        group_id,
                        cn_name,
                        identity.ipn,
                        sort_order,
                        int(item["id"]),
                        cn_name,
                        en_name,
                    ),
                )
                feature_id = int(cursor.lastrowid)
                created["features"] += 1
                for language, name in (("cn", cn_name), ("en", en_name)):
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

            for alias, planned in zip(STAGE1_ALIASES, plan["aliases"]):
                if planned["action"] != "create":
                    continue
                feature_id = _resolve_feature(connection, alias.target)
                inserted = connection.execute(
                    """
                    INSERT INTO feature_names (
                        feature_id, language, name, normalized_name,
                        name_type, source, review_status
                    ) VALUES (?, ?, ?, ?, 'alias', ?, 'approved')
                    ON CONFLICT(feature_id, language, normalized_name) DO NOTHING
                    """,
                    (
                        feature_id,
                        alias.language,
                        alias.name,
                        _normalize_name(alias.name),
                        f"stage1:A侧曾用名（{alias.a_record}；{alias.source_reference}）",
                    ),
                )
                created["names"] += int(inserted.rowcount or 0)

            for normalization, planned in zip(
                STAGE1_CONFIG_ITEM_NORMALIZATIONS, plan["config_item_normalizations"]
            ):
                if planned["action"] != "normalize":
                    continue
                updated = connection.execute(
                    f"""
                    UPDATE config_items SET {normalization.column} = ?
                    WHERE id = ? AND {normalization.column} = ?
                    """,
                    (
                        normalization.normalized,
                        normalization.config_item_id,
                        normalization.expected_current,
                    ),
                )
                created["config_items"] = created.get("config_items", 0) + int(
                    updated.rowcount or 0
                )

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
            for normalization in STAGE1_CONFIG_ITEM_NORMALIZATIONS:
                row = connection.execute(
                    f"SELECT {normalization.column} AS value FROM config_items WHERE id = ?",
                    (normalization.config_item_id,),
                ).fetchone()
                if row is None or (row["value"] or "") != normalization.normalized:
                    raise FeatureIdentityStage1Error(
                        f"配置项 #{normalization.config_item_id} 的 "
                        f"{normalization.column} 未按计划规范化"
                    )
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
    "AliasAction",
    "ConfigItemTextNormalization",
    "STAGE1_ALIASES",
    "STAGE1_BLOCKED_RELATIONS",
    "STAGE1_CONFIG_ITEM_NORMALIZATIONS",
    "STAGE1_IGNORED",
    "STAGE1_IPN_BACKFILLS",
    "STAGE1_NEW_IDENTITIES",
    "STAGE1_PRIMARY_NAME_NORMALIZATIONS",
    "STAGE1_RELATIONS",
    "apply_stage1",
    "build_stage1_plan",
]
