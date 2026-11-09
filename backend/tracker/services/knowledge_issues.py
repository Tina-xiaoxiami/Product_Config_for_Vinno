"""知识中枢待处理问题（`kh_issues`）的只读查询服务。

设计口径与交接文档的裁定一致：

- **缺资料、缺映射、查不到 → 待确认，绝不推断「未注册」或擅自择一。** 问题条目里的
  `detail` 就是判断依据本身，页面上原样展示，不做二次概括——概括会丢掉"为什么答不了"。
- **不静默**：未知的 `issue_type` 也要显示出来（回落到原始编码），不能因为词典里没有
  对应中文名就从列表里消失。新增问题类型由脚本引入时，界面必须照实呈现。
- 这是本机范围内的**全局**问题清单，没有项目维度——`kh_issues` 表本身就不带 `project_id`。
  因此页面上要写明"不随项目切换"，避免与候选/版本类的按项目统计混淆。

本模块只读，不写任何数据，也不提供任何"标记为已解决"的入口：结论归业务负责人。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from tracker.database import Database

# 严重度：high 是"会导出错误结论"的问题，必须优先看。
SEVERITY_ORDER = ("high", "medium", "low")
SEVERITY_LABELS = {"high": "高", "medium": "中", "low": "低"}

STATUS_ORDER = ("open", "resolved")
STATUS_LABELS = {"open": "待处理", "resolved": "已解决"}

# 问题类型的中文名。**新增类型时必须同步补这里**——否则界面会退回显示原始编码
# （仍可见，不会消失，但可读性下降）。`tests/test_knowledge_issues.py` 会守护
# "未知类型仍然可见"这一行为本身。
ISSUE_TYPE_LABELS = {
    "strategy_conflict": "策略冲突（配置表与策略库不一致）",
    "strategy_missing": "无正式选型值",
    "registration_marker_no_strategy": "注册核对标记不可当策略值",
    "config_duplicate_ambiguous": "配置库重复且取值不一致",
    "config_duplicate_same": "配置库重复但取值一致",
    "code_conflict": "编码冲突",
    "code_ambiguous": "编码歧义",
    "registration_multi_unit_scope": "注册单元范围重叠",
    "item_evidence_partial": "条目证据链不完整",
    "item_evidence_incomplete": "条目缺来源证据",
}

SUBJECT_TYPE_LABELS = {
    "strategy": "策略值",
    "probe": "探头",
    "item": "知识条目",
    "registration": "注册",
    "feature": "功能",
}

# 「不限」的等价写法：地址栏里空值写不进 hash（`buildHash` 会跳过空串），因此前端用
# `status=all` 表达"不限状态"；直接调接口的人也会自然地这么写，两种都要接受。
UNRESTRICTED = frozenset({"", "all"})


def _checked_at() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _label(mapping: dict[str, str], key: str, fallback_prefix: str = "") -> str:
    """词典查不到时返回带前缀的原始编码，而不是空串——空串会让条目看起来"没有类型"。"""
    if key in mapping:
        return mapping[key]
    return f"{fallback_prefix}{key}" if key else f"{fallback_prefix}未标注"


def issue_row(issue: dict[str, Any]) -> dict[str, Any]:
    """把一行 `kh_issues` 转成界面用的结构。字段一律保留原始值，便于回溯。"""
    issue_type = str(issue.get("issue_type") or "")
    severity = str(issue.get("severity") or "")
    status = str(issue.get("status") or "")
    subject_type = str(issue.get("subject_type") or "")
    return {
        "id": issue.get("id"),
        "issue_type": issue_type,
        "issue_type_label": _label(ISSUE_TYPE_LABELS, issue_type, "未登记类型："),
        "issue_type_known": issue_type in ISSUE_TYPE_LABELS,
        "severity": severity,
        "severity_label": _label(SEVERITY_LABELS, severity, "未标注严重度："),
        "status": status,
        "status_label": _label(STATUS_LABELS, status, "未知状态："),
        "subject_type": subject_type,
        "subject_type_label": _label(SUBJECT_TYPE_LABELS, subject_type, "其他："),
        "subject_ref": str(issue.get("subject_ref") or ""),
        "detail": str(issue.get("detail") or ""),
        "created_at": str(issue.get("created_at") or ""),
    }


def _counts(
    rows: list[dict[str, Any]],
    field: str,
    order: tuple[str, ...],
    labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """按给定顺序输出计数，并如实带上顺序之外的取值（不为整齐而丢弃）。

    带 `labels` 时同时给出中文名：界面直接用 `label` 显示，不再把 `high` 这类内部
    取值暴露给使用者（实测汇总行曾出现「高 12 条；high 12 · medium 122」的混排）。
    """
    seen: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "")
        seen[key] = seen.get(key, 0) + 1
    ordered = [key for key in order if key in seen]
    ordered += sorted(key for key in seen if key not in order)
    return [
        {
            "key": key,
            "label": _label(labels or {}, key, "未登记："),
            "count": seen[key],
        }
        for key in ordered
    ]


def knowledge_issues(
    database: Database,
    *,
    query: str = "",
    severity: str = "",
    status: str = "open",
    issue_type: str = "",
) -> dict[str, Any]:
    """列出待处理问题，支持按严重度、状态、类型与关键词筛选。

    默认 `status="open"`——这是"待处理清单"，已解决的默认不占版面，但汇总行会写明
    当前范围与已解决条数，不会让人误以为总数只有这么多。`status` 取 `""` 或 `all`
    表示不限状态。
    """
    everything = [issue_row(row) for row in database.list_knowledge_issues()]
    needle = query.strip().casefold()
    status = "" if status in UNRESTRICTED else status
    severity = "" if severity in UNRESTRICTED else severity
    issue_type = "" if issue_type in UNRESTRICTED else issue_type

    matched: list[dict[str, Any]] = []
    for row in everything:
        if status and row["status"] != status:
            continue
        if severity and row["severity"] != severity:
            continue
        if issue_type and row["issue_type"] != issue_type:
            continue
        if needle:
            haystack = " ".join(
                (
                    row["issue_type"],
                    row["issue_type_label"],
                    row["subject_type_label"],
                    row["subject_ref"],
                    row["detail"],
                )
            ).casefold()
            if needle not in haystack:
                continue
        matched.append(row)

    # 严重度优先：high 在前，同severity 内保持库内顺序（原为按 id，即登记顺序）。
    severity_rank = {key: index for index, key in enumerate(SEVERITY_ORDER)}
    matched.sort(key=lambda row: severity_rank.get(row["severity"], len(SEVERITY_ORDER)))

    open_rows = [row for row in everything if row["status"] == "open"]
    return {
        "checked_at": _checked_at(),
        "query": query,
        "filters": {
            "severity": severity,
            "status": status,
            "issue_type": issue_type,
        },
        "total": len(everything),
        "open_total": len(open_rows),
        "resolved_total": len(everything) - len(open_rows),
        "matched": len(matched),
        "high_open": sum(
            1 for row in open_rows if row["severity"] == "high"
        ),
        "severity_counts": _counts(open_rows, "severity", SEVERITY_ORDER, SEVERITY_LABELS),
        "status_counts": _counts(everything, "status", STATUS_ORDER, STATUS_LABELS),
        # 类型清单覆盖**所有状态**的类型，而不只是待处理的：只列 open 的话，切到
        # 「已解决」后会发现某个类型在筛选下拉里根本选不到，等于查不到它。
        # 计数给的是待处理条数（默认范围）；某个类型全是已解决时显示 0，这是实话。
        "types": [
            {
                "key": entry["key"],
                "label": _label(ISSUE_TYPE_LABELS, entry["key"], "未登记类型："),
                "count": sum(1 for row in open_rows if row["issue_type"] == entry["key"]),
            }
            for entry in _counts(everything, "issue_type", ())
        ],
        "issues": matched,
    }
