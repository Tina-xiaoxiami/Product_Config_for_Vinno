"""知识条目与探头-版本关系的只读查询服务。

设计口径（与交接文档的裁定一致）：

- 条目编码有两种来源：配置系统的 `v_code`（如 `V30762`）与知识中枢自建码（`KH-`）。
  页面上必须能区分——**自建码不代表配置系统已有对应项**。
- 每条结论都要能回溯到来源证据；**没有证据的条目也要显示出来**（标注清楚），
  不能因为"没有证据"就从列表里消失，那等于静默通过。
- 探头-版本关系双向可查：按探头查它的引入/停用版本，也能按系列与版本查探头。

本模块只读，不写任何数据。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from tracker.database import Database

SELF_BUILT_PREFIX = "KH-"
CODE_TYPE_LABELS = {"v_code": "配置系统 V 代码", "self_built": "知识中枢自建码（KH-）"}
TAG_LAYER_LABELS = {"probe": "探头", "function": "功能", "application": "应用"}
PROBE_STATE_LABELS = {"added": "引入", "discontinued": "停用", "replaced": "替代"}


def _checked_at() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _code_type(code: str) -> str:
    return "self_built" if str(code).startswith(SELF_BUILT_PREFIX) else "v_code"


def _category_path(categories: dict[str, dict[str, Any]], code: str) -> dict[str, Any]:
    names: list[str] = []
    current = code
    seen: set[str] = set()
    while current and current not in seen and current in categories:
        seen.add(current)
        names.append(categories[current]["name"])
        current = categories[current]["parent_code"] or ""
    return {"code": code, "path": " / ".join(reversed(names)) or code}


def knowledge_items(
    database: Database,
    *,
    query: str = "",
    category: str = "",
    code_type: str = "",
    evidence: str = "",
) -> dict[str, Any]:
    """列出知识条目（含三层标签、证据链、问题与审核留痕）。

    `evidence="missing"` 只列没有证据的条目——这类条目必须能被看见。
    """
    categories = {row["code"]: row for row in database.list_knowledge_categories()}
    tags: dict[int, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in database.list_item_tags():
        tags[row["item_id"]][row["field"]].append(row["value"])

    issues_by_ref: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in database.list_knowledge_issues():
        if issue["subject_type"] == "item":
            issues_by_ref[issue["subject_ref"]].append(
                {
                    "issue_type": issue["issue_type"],
                    "severity": issue["severity"],
                    "status": issue["status"],
                    "detail": issue["detail"],
                }
            )

    reviews_by_ref: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in database.list_review_records():
        reviews_by_ref[record["subject_ref"]].append(
            {
                "decision": record["decision"],
                "bucket": record["bucket"],
                "reviewer": record["reviewer"],
                "decided_at": record["decided_at"],
            }
        )

    needle = query.strip().casefold()
    items: list[dict[str, Any]] = []
    for row in database.list_knowledge_items(category or None):
        code = row["code"]
        item_tags = tags.get(row["id"], {})
        item_evidence = database.list_item_evidence(row["id"])
        has_evidence = bool(item_evidence)
        if needle and needle not in f"{code} {row['name_cn']} {row['name_en']}".casefold():
            continue
        if code_type and _code_type(code) != code_type:
            continue
        if evidence == "missing" and has_evidence:
            continue
        if evidence == "present" and not has_evidence:
            continue
        items.append(
            {
                "id": row["id"],
                "code": code,
                "code_type": _code_type(code),
                "code_type_label": CODE_TYPE_LABELS[_code_type(code)],
                "name_cn": row["name_cn"],
                "name_en": row["name_en"],
                "category": _category_path(categories, row["category_code"] or ""),
                "software_version": row["software_version"] or "",
                "scope_market": row["scope_market"] or "",
                "status": row["status"] or "",
                "source_kind": row["source_kind"] or "",
                "tags": {
                    field: item_tags.get(field, [])
                    for field in ("probe", "function", "application")
                },
                "has_evidence": has_evidence,
                "evidence_count": len(item_evidence),
                "evidence": item_evidence,
                "issues": issues_by_ref.get(code, []),
                "reviews": reviews_by_ref.get(code, []),
            }
        )

    all_items = database.list_knowledge_items(category or None)
    without_evidence = sum(
        1 for row in all_items if not database.list_item_evidence(row["id"])
    )
    return {
        "checked_at": _checked_at(),
        "query": query,
        "filters": {"category": category, "code_type": code_type, "evidence": evidence},
        "total": len(all_items),
        "matched": len(items),
        "without_evidence": without_evidence,
        "code_type_counts": {
            "v_code": sum(1 for row in all_items if _code_type(row["code"]) == "v_code"),
            "self_built": sum(1 for row in all_items if _code_type(row["code"]) == "self_built"),
        },
        "categories": [
            {"code": row["code"], "name": row["name"], "level": row["level"]}
            for row in database.list_knowledge_categories()
        ],
        "items": items,
    }


def probe_versions(
    database: Database,
    *,
    probe: str = "",
    series: str = "",
    version: str = "",
) -> dict[str, Any]:
    """探头-版本关系，双向可查：按探头查版本，或按系列/版本查探头。"""
    rows = database.list_probe_versions(
        series_code=series or None,
        software_version=version or None,
        probe_code=probe or None,
    )
    everything = database.list_probe_versions()

    by_probe: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["probe_code"]].append(row)
    for probe_code, entries in sorted(grouped.items()):
        by_probe.append(
            {
                "probe_code": probe_code,
                "probe_model": entries[0]["probe_model"],
                "series": sorted({entry["series_code"] for entry in entries}),
                "history": [
                    {
                        "software_version": entry["software_version"],
                        "series_code": entry["series_code"],
                        "state": entry["state"],
                        "state_label": PROBE_STATE_LABELS.get(entry["state"], entry["state"]),
                        "replaces_probe_code": entry["replaces_probe_code"] or "",
                    }
                    for entry in sorted(entries, key=lambda item: item["software_version"])
                ],
            }
        )

    return {
        "checked_at": _checked_at(),
        "filters": {"probe": probe, "series": series, "version": version},
        "total": len(rows),
        "rows": rows,
        "by_probe": by_probe,
        "facets": {
            "probes": sorted({row["probe_code"] for row in everything}),
            "series": sorted({row["series_code"] for row in everything}),
            "versions": sorted({row["software_version"] for row in everything}),
        },
    }
