from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any, Iterable


CHANGE_CATEGORIES = (
    "function",
    "image",
    "bug",
    "config",
    "config_note",
    "probe",
    "remark",
    "unclassified",
)
"""变更/候选分类词表（唯一来源）。

`probe`、`unclassified`、`config_note` 三者在抽取阶段就会产生：

- `probe`：探头更新/导入类条目；
- `unclassified`：章节无法判定，保留内容待人工确认（绝不静默丢弃）；
- `config_note`：配置/兼容性说明（适用机型、版本前提、兼容性限制），与知识中枢
  `kh_categories.config_note` 同名。

`change_events.category` 的数据库约束必须与这里保持一致；新增分类时除了改本表，
还要写一条迁移把约束放宽，否则候选能存进 `import_candidates` 却批不准入版本
（历史缺陷：`probe` 候选批准时报 CHECK constraint failed）。
"""

CHANGE_CATEGORY_LABELS = {
    "function": "功能",
    "image": "图像",
    "bug": "Bug",
    "config": "配置",
    "config_note": "配置/兼容性说明",
    "probe": "探头",
    "remark": "备注",
    "unclassified": "待确认",
}
"""分类的中文名。前端 `categoryLabels` 与本表必须一致（有测试守护）。"""


def canonical_key(category: str, text: str) -> str:
    """变更条目的稳定身份：`分类 + 规范化原文` 的短摘要。

    **这是唯一实现。** 写入 `change_events.canonical_key` 与按原文查重都走这里，
    它同时是唯一索引 `change_event_identity(release_id, category, canonical_key)`
    的组成部分。历史上 `database` 与 `import_service` 各留了一份逐字节相同的副本，
    任何一方先改规范（大小写、空白、摘要长度）都会让去重静默失效或变成约束冲突。

    `usedforsecurity=False`：这是内容指纹而不是签名，声明后 FIPS 环境也能算，
    且**摘要值不变**（该参数只影响算法可用性，不改变输出）。
    """
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    digest = hashlib.sha1(
        f"{category}:{normalized}".encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:16]
    return f"{category}-{digest}"


def _normalized_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _strip_repeated_title(raw: str, title: str) -> str:
    """去掉原文里与条目标题重复的首行，其余内容一字不改。

    只在首行与标题**完全相同**时剥离：标题行是「新增X / X优化」这类变更说法，
    卡片本身已经显示功能名；一旦首行与标题不同，就整段保留，绝不猜哪一行是标题。
    """
    lines = str(raw or "").splitlines()
    first_index = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first_index is None:
        return ""
    if _normalized_line(lines[first_index]) != _normalized_line(title):
        return str(raw or "").strip()
    return "\n".join(lines[first_index + 1 :]).strip()


def feature_description(
    title_cn: str,
    title_en: str,
    raw_cn: str,
    raw_en: str,
) -> tuple[str, str]:
    """功能描述取**已批准原文的完整段落**，而不是只取标题行。

    Release Note 的功能条目通常是这样：首行是与标题重复的变更说法，后面才是
    「适用范围 / 功能描述 / 支持探头 / WorkFlow」。此前建立功能时只把首行写进
    `features.cn_description`，于是功能库里只剩标题，用途、适用范围和依据全丢。

    两处刻意的保守取舍：
    - **逐侧独立取用**：中文有完整段落、英文只有一行时，各自保留自己最好的那份，
      不因为一侧缺失就把另一侧的原文也降级成标题。
    - **原文没有更多内容时退回标题**：宁可如实显示「只有标题」，也不凭空补一段
      业务描述；这类条目仍会被界面的「说明待完善」标出来。

    返回的两侧要么都非空、要么都为空（`features` 的双语约束）。
    """
    title_cn = str(title_cn or "").strip()
    title_en = str(title_en or "").strip()
    raw_cn = str(raw_cn or "").strip()
    raw_en = str(raw_en or "").strip()
    cn = _strip_repeated_title(raw_cn, title_cn) or raw_cn or title_cn
    en = _strip_repeated_title(raw_en, title_en) or raw_en or title_en
    if not cn or not en:
        return title_cn, title_en
    return cn, en


def description_is_title_only(cn_description: str, en_description: str) -> bool:
    """功能描述是否**只有标题**（没有正文段落）。

    「说明待完善」的统一判据，只在后端算一次，前端直接渲染接口给的字段——
    界面上再写一套「以新增开头」之类的规则会与这里的口径漂移：补全后的正文本身
    可能以「新增…」开头（例如心肌应变成像的第一段），那样就会被误判成不完整。

    判据刻意保守：**两侧都只有一行，且都短**才算只有标题。分段、长文、任一侧有
    正文的，一律视为已具备完整描述。
    """
    cn = str(cn_description or "").strip()
    en = str(en_description or "").strip()
    if not cn or not en:
        return True
    single_line = "\n" not in cn and "\n" not in en
    return single_line and len(cn) < 24 and len(en) < 60


def version_key(version: str) -> tuple[int, ...]:
    """Return a numeric key for dotted product versions."""
    try:
        return tuple(int(segment) for segment in version.split("."))
    except ValueError as exc:
        raise ValueError(f"Invalid version: {version}") from exc


def sort_versions(versions: Iterable[str], reverse: bool = False) -> list[str]:
    return sorted(versions, key=version_key, reverse=reverse)


def compare_change_sets(
    earlier: Iterable[dict[str, Any]], later: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Compare two normalized change collections without conflating categories."""
    earlier_by_key = {
        (item["category"], item["canonical_key"]): item for item in earlier
    }
    later_by_key = {
        (item["category"], item["canonical_key"]): item for item in later
    }
    result: dict[str, Any] = {
        bucket: {category: [] for category in CHANGE_CATEGORIES}
        for bucket in ("added", "removed", "common")
    }

    for key in sorted(later_by_key.keys() - earlier_by_key.keys()):
        category, _ = key
        result["added"].setdefault(category, []).append(later_by_key[key])
    for key in sorted(earlier_by_key.keys() - later_by_key.keys()):
        category, _ = key
        result["removed"].setdefault(category, []).append(earlier_by_key[key])
    for key in sorted(earlier_by_key.keys() & later_by_key.keys()):
        category, _ = key
        result["common"].setdefault(category, []).append(later_by_key[key])

    result["feature_candidates"] = list(result["added"].get("function", []))
    return result


def group_changes(changes: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for change in changes:
        grouped[change["category"]].append(change)
    return {category: grouped.get(category, []) for category in CHANGE_CATEGORIES}


def excerpt(text: str, limit: int = 48) -> str:
    """把一条原文压成一句可直接读的摘录，用于提醒与批量动作说明。"""

    collapsed = re.sub(r"\s+", " ", str(text or "")).strip()
    return f"「{collapsed[:limit]}」" if collapsed else "「（空）」"


def pair_single_language_items(
    chinese: list[Any], english: list[Any]
) -> list[tuple[Any, Any]]:
    """中英两侧「未配对条数相等」时按文档顺序 1:1 配对；数量不等则不做任何推测。

    **这是唯一实现**：扫描时用它决定「疑似同一变更」提醒列哪几组，人工确认合并时用它
    重算还剩哪几组。两边若各写一份，合并完一组之后提醒就会与实际剩余对不上。

    数量相等是原文自己给出的强信号（两侧都多出同样条数），但它是**顺序证据而不是语义
    证据**，所以这里只负责配对，是否合并始终由人确认。
    """

    if not chinese or len(chinese) != len(english):
        return []
    return list(zip(chinese, english))


def matching_excerpt(text: str, query: str, radius: int = 70, *, match_index: int | None = None) -> str:
    normalized_text = text.strip()
    if match_index is None:
        match_index = normalized_text.casefold().find(query.casefold())
    if match_index < 0:
        return normalized_text[: radius * 2]
    start = max(0, match_index - radius)
    end = min(len(normalized_text), match_index + len(query) + radius)
    excerpt = normalized_text[start:end].replace("\n", " ").strip()
    return f"{'…' if start else ''}{excerpt}{'…' if end < len(normalized_text) else ''}"

