"""受控资料清单服务：提供版本与真实文件格式，不在清单响应中暴露本机路径。

口径（沿用交接文档的裁定）：

- 受控原件以 Obsidian Vault 为准；抽取用 docx、正式引用用 PDF，两者登记在同一版本行；
- 版本不可覆盖：同一资料的多个版本各自成行，用 `supersedes_version_id` 表达替代关系；
- **未复核与缺证据必须看得见**：`verified_at` 为空即标「未复核」，没有证据即标「缺证据」，
  不能因为字段为空就默认它是已确认的正式依据；
- 文件正文预览由统一搜索索引提供，并通过配置根目录重新解析来源。

本模块只读，不写任何数据。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from tracker.database import Database
from tracker.services.document_scopes import matches_model_scope
from tracker.services.document_scope_suggestions import suggestion_matches
from tracker.services.search_index import format_info


def _checked_at() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _has(value: Any) -> bool:
    return bool(str(value or "").strip())


def _version_payload(version: dict[str, Any], evidence_count: int, *, fingerprint_current: bool) -> dict[str, Any]:
    has_extract_source = _has(version["path_docx"])
    has_registered_file = _has(version["path_pdf"])
    files = [
        {"role": "extract_source" if field == "path_docx" else "registered_file",
         "preview_id": f"controlled:{version['id']}:{field.removeprefix('path_')}",
         **format_info(version[field])}
        for field in ("path_docx", "path_pdf")
        if _has(version[field])
    ]
    return {
        "id": version["id"],
        "version_label": version["version_label"] or "",
        "effective_date": version["effective_date"] or "",
        "status": version["status"] or "",
        "verified_at": version["verified_at"] or "",
        "verified": _has(version["verified_at"]) and fingerprint_current,
        "sha256": version["sha256"] or "",
        "sha256_short": (version["sha256"] or "")[:12],
        "has_extract_source": has_extract_source,
        "has_registered_file": has_registered_file,
        "files": files,
        # 兼容旧字段名：双轨表示有抽取源和登记文件，不假定实际扩展名。
        "dual_track": has_extract_source and has_registered_file,
        "supersedes_version_id": version["supersedes_version_id"],
        "evidence_count": evidence_count,
        "has_evidence": evidence_count > 0,
    }


def knowledge_documents(
    database: Database,
    *,
    query: str = "",
    doc_type: str = "",
    track: str = "",
    evidence: str = "",
    verification: str = "",
    model: str = "",
    market: str = "",
    scope_suggester: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """列出受控资料及其版本链。

    `track` 取值 `dual`（抽取源 + 登记文件）/ `registered_only`；旧值 `pdf_only` 仍可用；
    `evidence` 取值 `present`/`missing`；
    `verification` 取值 `verified`/`unverified`。
    """
    evidence_counts = database.count_document_version_evidence()
    needle = query.strip().casefold()
    documents: list[dict[str, Any]] = []
    counts = {"dual_track": 0, "registered_only": 0, "without_evidence": 0, "unverified": 0}
    all_documents = database.list_documents()

    for document in all_documents:
        versions = [
            _version_payload(version, evidence_counts.get(version["id"], 0),
                             fingerprint_current=database.document_version_fingerprint_current(version))
            for version in database.list_document_versions(document["id"])
        ]
        dual_track = any(version["dual_track"] for version in versions)
        total_evidence = sum(version["evidence_count"] for version in versions)
        verified = any(version["verified"] and version["id"] == document["current_version_id"]
                       for version in versions)

        if dual_track:
            counts["dual_track"] += 1
        else:
            counts["registered_only"] += 1
        if total_evidence == 0:
            counts["without_evidence"] += 1
        if not verified:
            counts["unverified"] += 1

        if needle and needle not in f"{document['title']} {document['doc_type']}".casefold():
            continue
        if doc_type and document["doc_type"] != doc_type:
            continue
        if market and document["scope_market"] != market:
            continue
        if track == "dual" and not dual_track:
            continue
        if track in {"pdf_only", "registered_only"} and dual_track:
            continue
        if evidence == "missing" and total_evidence:
            continue
        if evidence == "present" and not total_evidence:
            continue
        if verification == "verified" and not verified:
            continue
        if verification == "unverified" and verified:
            continue

        suggestion = scope_suggester(document) if scope_suggester and not document['model_scope'] else None
        if model and not matches_model_scope(document['model_scope'], model, include_unknown=False) and not (suggestion and suggestion_matches(suggestion, model)):
            continue

        documents.append(
            {
                "id": document["id"],
                "title": document["title"],
                "doc_type": document["doc_type"] or "",
                "scope_market": document["scope_market"] or "",
                "model_scope": document["model_scope"] or "",
                "status": document["status"] or "",
                "current_version_id": document["current_version_id"],
                "version_count": len(versions),
                "dual_track": dual_track,
                "evidence_count": total_evidence,
                "has_evidence": total_evidence > 0,
                "verified": verified,
                "versions": versions,
                "scope_suggestion": suggestion,
            }
        )

    return {
        "checked_at": _checked_at(),
        "query": query,
        "filters": {
            "doc_type": doc_type,
            "track": track,
            "evidence": evidence,
            "verification": verification,
            "model": model,
            "market": market,
        },
        "total": len(all_documents),
        "matched": len(documents),
        "counts": counts,
        "facets": {
            "doc_types": sorted({document["doc_type"] or "" for document in all_documents} - {""}),
        },
        "documents": documents,
        "note": "清单展示文件格式和版本状态，不返回本机路径；可直接打开只读预览、获取原文件或复制引用。",
    }
