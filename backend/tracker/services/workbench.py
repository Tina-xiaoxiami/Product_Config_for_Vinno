"""工作台模块能力注册表：首页「可用 / 建设中」状态的单一事实源。

首页据此渲染导航与状态，新增模块＝改这里的状态，不改首页结构。
`tests/test_workbench.py` 用同一份注册表做**漂移守卫**：声明为可用（ready/partial）
且带 `view` 的模块，必须在页面区块、导航项与前端标题表里同时存在，
否则点击会静默无反应——这正是 `switchView()` 在缺少页面或导航项时直接 return 的坑。

字段约定：

- `id`：模块稳定标识，全局唯一；
- `title`：给用户看的中文名；
- `status`：`ready`（可用）/ `partial`（可用但范围受限）/ `planned`（未开工）/ `blocked`（被依赖阻塞）；
- `view`：对应前端视图 id；没有独立页面的能力（对话框、内嵌面板）为 `None`；
- `note`：范围说明或阻塞原因。`blocked` 必须给出原因，`planned` 建议给出对应工作包编号。

状态只表达**能力是否接通**，不表达数据是否已备齐；数据统计属于首页自身职责。

`note` 只描述**当前事实**，不要指向未来工作或尚不存在的页面——它会被首页原样展示给
使用者。写成「见 WB-08」「查询页见 WB-13」这类指针时，被引用方落地后指针不会自己
更新，实测已积累两处：WB-08 早已交付而说明仍写着"见 WB-08"；WB-13 并未交付问题查询
页，说明却已指向它。**被引用方落地时，必须同时回来改这里。**
"""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from typing import Any

from tracker.database import Database

MODULE_STATUSES = ("ready", "partial", "planned", "blocked")
REACHABLE_STATUSES = ("ready", "partial")

# 顺序即首页展示顺序。
_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "id": "overview",
        "title": "总览",
        "modules": (
            {"id": "home", "title": "工作台首页", "status": "ready", "view": "home", "note": ""},
            {"id": "search", "title": "全局搜索", "status": "ready", "view": "search", "note": "汇总已接入的版本、配置、受控资料、培训资料与术语"},
        ),
    },
    {
        "id": "version",
        "title": "版本与功能",
        "modules": (
            {"id": "releases", "title": "版本中心", "status": "ready", "view": "releases", "note": ""},
            {"id": "compare", "title": "版本对比", "status": "ready", "view": "compare", "note": ""},
            {"id": "features", "title": "功能库", "status": "ready", "view": "features", "note": ""},
            {"id": "terms", "title": "术语词典", "status": "ready", "view": "terms", "note": ""},
        ),
    },
    {
        "id": "config",
        "title": "产品配置",
        "modules": (
            {
                "id": "strategy",
                "title": "正式策略查询",
                "status": "ready",
                "view": "strategy",
                "note": "",
            },
            {
                "id": "config_system",
                "title": "配置管理系统",
                "status": "ready",
                "view": None,
                "note": "外部系统入口：首页「外部系统」区探活通过后才给出可点链接",
            },
        ),
    },
    {
        "id": "knowledge",
        "title": "产品知识",
        "modules": (
            {
                "id": "materials",
                "title": "受控资料",
                "status": "ready",
                "view": "materials",
                "note": "",
            },
            {
                "id": "registration",
                "title": "注册查询",
                "status": "ready",
                "view": "registration",
                "note": "",
            },
            {
                "id": "items",
                "title": "知识条目",
                "status": "ready",
                "view": "items",
                "note": "",
            },
            {
                "id": "probe_versions",
                "title": "探头-版本",
                "status": "ready",
                "view": "probe_versions",
                "note": "",
            },
            {
                "id": "knowledge_issues",
                "title": "待处理问题",
                "status": "ready",
                "view": "issues",
                "note": "策略冲突、无正式选型值与编码歧义等待确认项；按全局统计，只呈现不判定",
            },
            {
                "id": "product_states",
                "title": "产品状态",
                "status": "ready",
                "view": "product_states",
                "note": "显式展示当前版本、发布状态、核验日期与历史；不从最大版本号推断",
            },
        ),
    },
    {
        "id": "training",
        "title": "培训中心",
        "modules": (
            {
                "id": "training",
                "title": "培训资料",
                "status": "ready",
                "view": "training",
                "note": "",
            },
        ),
    },
    {
        "id": "maintenance",
        "title": "维护中心",
        "modules": (
            {"id": "review", "title": "导入与审核", "status": "ready", "view": "review", "note": ""},
            {
                "id": "sources",
                "title": "项目管理与来源",
                "status": "ready",
                "view": None,
                "note": "在顶部「管理项目」对话框中，任意视图可用",
            },
            {
                "id": "runtime",
                "title": "运行与来源状态",
                "status": "ready",
                "view": None,
                "note": "服务健康检查、项目来源巡检与四个来源（Release Note、配置库、受控材料、培训根）的可用状态均已聚合，见首页「系统状态」区",
            },
        ),
    },
)


def module_catalog() -> dict[str, Any]:
    """返回注册表副本，避免调用方改到全局状态。"""
    return {
        "groups": [
            {
                "id": group["id"],
                "title": group["title"],
                "modules": [dict(module) for module in group["modules"]],
            }
            for group in _GROUPS
        ]
    }


def iter_modules() -> list[dict[str, Any]]:
    """展平后的模块列表，供首页与守卫测试使用。"""
    return [module for group in module_catalog()["groups"] for module in group["modules"]]


# 首页待办：`count` 由数据库提供；`view` 指向可跳转的工作区，没有页面的项只展示数字与说明。
_TODO_ITEMS: tuple[dict[str, Any], ...] = (
    {
        "id": "knowledge_issues_open",
        "title": "知识中枢待处理问题",
        "view": "issues",
        "priority": "high",
        "scope": "global",
        "impact": "可能影响正式产品结论，需要业务负责人核对",
        "action_label": "查看问题",
        "note": "策略冲突、缺失与编码问题，按全局统计，不随项目切换；只呈现不判定，结论归业务负责人",
    },
    {
        "id": "review_issues_open",
        "title": "扫描与配对问题",
        "view": "review",
        "priority": "medium",
        "scope": "project",
        "impact": "影响候选的双语配对、分类或来源定位",
        "action_label": "检查问题",
        "note": "双语配对、分类或来源问题，未处理会影响候选质量",
    },
    {
        "id": "candidates_pending",
        "title": "待审核候选",
        "view": "review",
        "priority": "normal",
        "scope": "project",
        "impact": "影响版本变更进入正式产品档案",
        "action_label": "开始审核",
        "note": "当前项目的导入候选，尚未完成人工审核",
    },
)


def overview_for_project(database: Database, project_id: int) -> dict[str, Any]:
    """首页头部数据：项目信息与待办计数。

    数字一律来自数据库，不在前端写死；三项待办的口径差异见
    `Database.todo_counts`，调用方应照实展示，不要描述成同一范围。
    """
    counts = database.todo_counts(project_id)
    project = database.get_project(project_id)
    return {
        "project": {"id": project["id"], "name": project["name"], "code": project["code"]},
        # `actionable`：0 条时界面上给完成态、不给可点入口（与「待审为零不提供继续审核」
        # 同一条规则）。由接口给出，前端不自己判断 0 与「可点」的关系。
        "todos": [
            {
                **item,
                "count": counts[item["id"]],
                "actionable": counts[item["id"]] > 0,
                "scope_label": (
                    "全局知识库"
                    if item["scope"] == "global"
                    else f"当前项目 · {project['name']}"
                ),
                "state": "attention" if counts[item["id"]] > 0 else "clear",
                "state_label": "需处理" if counts[item["id"]] > 0 else "已完成",
            }
            for item in _TODO_ITEMS
        ],
    }
# 来源状态：available 可用 / degraded 部分可用 / unavailable 不可用 / not_configured 未配置。
# 未配置与不可用必须分开报：前者是"还没告诉我在哪"，后者是"告诉我了但读不到"。
SOURCE_STATUSES = ("available", "degraded", "unavailable", "not_configured")

_CONFIG_DATABASE_TABLES = ("product_models", "product_series", "config_items", "config_values")


def _checked_at() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _directory_state(path: Path | None) -> tuple[str, str]:
    """只证明"能不能读"，不做全量扫描：打开目录读第一个条目即可。"""
    if path is None:
        return "not_configured", "未配置路径"
    if not path.exists():
        return "unavailable", "路径不存在"
    if not path.is_dir():
        return "unavailable", "路径不是目录"
    try:
        with os.scandir(path) as entries:
            next(entries, None)
    except PermissionError:
        return "unavailable", "目录不可读（权限不足）"
    except OSError as error:
        return "unavailable", f"目录无法读取（{error.strerror}）"
    return "available", "目录可读"


def _config_database_state(path: Path | None) -> tuple[str, str]:
    """只读打开并核对需要的表，不写源库、不做全表统计。"""
    if path is None:
        return "not_configured", "未配置路径"
    if not path.is_file():
        return "unavailable", "文件不存在"
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only = ON")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            connection.close()
    except sqlite3.Error as error:
        return "unavailable", f"只读打开失败（{error}）"

    missing = sorted(set(_CONFIG_DATABASE_TABLES) - tables)
    if missing:
        return "degraded", f"只读可打开，但缺少表：{', '.join(missing)}"
    return "available", "只读可打开，表结构匹配"


def _release_note_state(database: Database, project_id: int) -> dict[str, Any]:
    sources = [
        source for source in database.get_project(project_id)["sources"] if source["enabled"]
    ]
    registered_versions = len(database.list_releases(project_id))
    if not sources:
        return {
            "status": "not_configured",
            "detail": f"该项目未登记来源目录 · 已登记 {registered_versions} 个版本",
            "paths": [],
        }

    paths = []
    for source in sources:
        status, detail = _directory_state(Path(source["path"]))
        paths.append({"path": source["path"], "status": status, "detail": detail})

    statuses = {item["status"] for item in paths}
    if statuses == {"available"}:
        status, detail = "available", f"{len(paths)} 个来源目录全部可读"
    elif "available" in statuses:
        status, detail = "degraded", "部分来源目录不可读"
    else:
        status, detail = "unavailable", "全部来源目录不可读"
    return {
        "status": status,
        "detail": f"{detail} · 已登记 {registered_versions} 个版本（登记数，非实时扫描）",
        "paths": paths,
    }


def sources_status(
    *,
    database: Database,
    project_id: int,
    product_config_database: str | Path | None = None,
    controlled_materials_root: str | Path | None = None,
    training_root: str | Path | None = None,
) -> dict[str, Any]:
    """逐个来源检查存在性与可读性。任一来源不可用只影响它自己，不抛异常、不写源库。"""
    release_notes = _release_note_state(database, project_id)
    config_status, config_detail = _config_database_state(
        Path(product_config_database) if product_config_database else None
    )
    materials_status, materials_detail = _directory_state(
        Path(controlled_materials_root) if controlled_materials_root else None
    )
    training_status, training_detail = _directory_state(
        Path(training_root) if training_root else None
    )

    return {
        "checked_at": _checked_at(),
        "sources": [
            {
                "id": "release_notes",
                "title": "Release Note 原件",
                "kind": "directory",
                "path": release_notes["paths"][0]["path"] if release_notes["paths"] else None,
                "paths": release_notes["paths"],
                "status": release_notes["status"],
                "detail": release_notes["detail"],
            },
            {
                "id": "product_config",
                "title": "产品配置管理系统主库",
                "kind": "sqlite_read_only",
                "path": str(product_config_database) if product_config_database else None,
                "paths": [],
                "status": config_status,
                "detail": config_detail,
            },
            {
                "id": "controlled_materials",
                "title": "受控材料（Obsidian Vault）",
                "kind": "directory",
                "path": str(controlled_materials_root) if controlled_materials_root else None,
                "paths": [],
                "status": materials_status,
                "detail": materials_detail,
            },
            {
                "id": "training",
                "title": "培训材料",
                "kind": "directory",
                "path": str(training_root) if training_root else None,
                "paths": [],
                "status": training_status,
                "detail": training_detail,
            },
        ],
    }


TRAINING_MAX_ENTRIES = 200  # 每层列出的上限：避免大目录拖慢响应，超出部分如实标注


def _listing(path: Path, *, depth: int, prefix: str = "") -> tuple[list[dict[str, Any]], bool]:
    """列目录清单：跳过隐藏项（.build/.chart-data-* 这类构建产物），限制层数与条数。"""
    try:
        children = sorted(
            (child for child in path.iterdir() if not child.name.startswith(".")),
            key=lambda child: (child.is_file(), child.name.casefold()),
        )
    except OSError:
        return [], False

    truncated = len(children) > TRAINING_MAX_ENTRIES
    entries: list[dict[str, Any]] = []
    for child in children[:TRAINING_MAX_ENTRIES]:
        item: dict[str, Any] = {
            "name": child.name,
            "path": f"{prefix}{child.name}",
            "kind": "directory" if child.is_dir() else "file",
        }
        if item["kind"] == "file":
            try:
                item["size"] = child.stat().st_size
            except OSError:
                item["size"] = None
        elif depth > 1:
            item["children"], child_truncated = _listing(
                child, depth=depth - 1, prefix=f"{item['path']}/"
            )
            truncated = truncated or child_truncated
        entries.append(item)
    return entries, truncated


def _filter_listing(entries: list[dict[str, Any]], needle: str) -> list[dict[str, Any]]:
    if not needle:
        return entries
    kept: list[dict[str, Any]] = []
    for item in entries:
        children = _filter_listing(item.get("children", []), needle)
        if needle in item["path"].casefold() or children:
            kept.append({**item, "children": children} if "children" in item else item)
    return kept


def training_assets(training_root: str | Path | None, query: str = "") -> dict[str, Any]:
    """培训与图文资料目录：只列清单，不返回文件内容，也不做全量递归。

    教学材料不自动作为产品正式依据——该声明同时写在页面上。
    """
    root = Path(training_root) if training_root else None
    status, detail = _directory_state(root)
    payload: dict[str, Any] = {
        "checked_at": _checked_at(),
        "root": str(root) if root else None,
        "status": status,
        "detail": detail,
        "query": query,
        "truncated": False,
        "entries": [],
    }
    if status != "available":
        return payload

    entries, truncated = _listing(root, depth=2)
    needle = query.strip().casefold()
    payload["entries"] = _filter_listing(entries, needle)
    payload["truncated"] = truncated
    payload["detail"] = "目录可读（最多两层，跳过隐藏项）"
    if truncated:
        payload["detail"] += f"；条目超过 {TRAINING_MAX_ENTRIES} 已截断"
    return payload
CONFIG_SYSTEM_PROBE_TIMEOUT = 1.5  # 秒：探活要短，不能让首页等外部系统
CONFIG_SYSTEM_START_HINT = (
    "请先启动产品配置管理系统（其前端默认使用 3006 端口），"
    "或在配置项 product_config_system_url 指向实际地址。"
)


def config_system_entry(
    url: str | None,
    *,
    timeout: float = CONFIG_SYSTEM_PROBE_TIMEOUT,
) -> dict[str, Any]:
    """探测外部配置管理系统入口。

    只做一次短超时的 GET：连不上就如实说「未启动」，**不给出可点链接**；
    任何异常都收敛成状态，不向页面抛错。本工作台始终只读它的数据，不回写。
    """
    payload: dict[str, Any] = {
        "checked_at": _checked_at(),
        "url": url or None,
        "status": "not_configured",
        "detail": "未配置入口地址",
        "response_ms": None,
        "start_hint": CONFIG_SYSTEM_START_HINT,
    }
    if not url:
        return payload

    started = time.monotonic()
    try:
        with urlopen(url, timeout=timeout) as response:
            status_code = getattr(response, "status", None) or response.getcode()
    except HTTPError as error:  # 有响应但状态码非 2xx：服务是活的
        status_code = error.code
    except (URLError, OSError, ValueError) as error:
        payload["status"] = "unreachable"
        payload["detail"] = f"未启动或不可达（{_short_reason(error)}）"
        payload["response_ms"] = round((time.monotonic() - started) * 1000)
        return payload

    payload["status"] = "available"
    payload["detail"] = f"已响应（HTTP {status_code}）"
    payload["response_ms"] = round((time.monotonic() - started) * 1000)
    return payload


def _short_reason(error: Exception) -> str:
    reason = getattr(error, "reason", None) or error
    return str(reason).splitlines()[0][:80]
