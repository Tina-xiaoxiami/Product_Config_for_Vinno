"""Cross-source search orchestration for the personal product workbench."""

from __future__ import annotations

from datetime import datetime
from functools import partial
from hashlib import sha256
import os
from pathlib import Path
from typing import Any, Iterable

from tracker.database import Database
from tracker.domain import version_key
from tracker.services.search_intent import (
    validate_search_task, parse_version_selection, search_terms, in_version_range, located_version, family_mentions, family_excerpt,
)
from tracker.services.feature_families import feature_family
from tracker.services.release_evidence import release_evidence, preferred_release_detail, release_section_detail
from tracker.services.release_sections import (
    source_sections, controlled_word_sections, section_for_locator, matching_sections,
)
from tracker.services.product_strategy import ProductStrategyReader, ProductStrategySourceUnavailable
from tracker.services.search_index import (
    SearchIndex, SourceChangedDuringExtraction, extract_file, file_sha256, file_snapshot,
)
from tracker.services.search_sources import STRUCTURED_SOURCE_TYPES, search_structured_sources
from tracker.services.document_scopes import matches_model_scope
from tracker.services.document_evidence import latest_extraction_review_hashes


SEARCHABLE_SUFFIXES = {".docx", ".pdf", ".xlsx", ".xls", ".pptx", ".md", ".txt", ".png", ".jpg", ".jpeg", ".zip"}
HIDDEN_DIRECTORY_NAMES = {".build", "__pycache__"}


def _root_is_available(root: str | Path | None) -> bool:
    if not root:
        return False
    try:
        resolved = Path(root).expanduser().resolve(strict=True)
        return resolved.is_dir() and os.access(resolved, os.R_OK | os.X_OK)
    except OSError:
        return False


def _registered_file_access(path: Path, roots: Iterable[str | Path | None]) -> str:
    """Classify approved registered paths without reading outside their roots."""
    try:
        resolved = path.expanduser().resolve()
        matching_roots = [
            root for root in roots if root
            and Path(root).expanduser().resolve() in (resolved, *resolved.parents)
        ]
    except (OSError, RuntimeError):
        return "missing"
    if not matching_roots:
        return "outside_roots"
    if not any(_root_is_available(root) for root in matching_roots):
        return "unavailable_root"
    if not path.is_file() or not os.access(path, os.R_OK):
        return "missing"
    return "accessible"


def _controlled_records(
    database: Database, materials_root: str | Path | None,
    controlled_extraction_roots: Iterable[str | Path] = (),
    historical_roots: Iterable[str | Path] = (),
) -> list[dict[str, Any]]:
    records = []
    extraction_roots = tuple(controlled_extraction_roots)
    evidence_counts = database.count_document_version_evidence()
    extraction_review_hashes = _latest_extraction_review_hashes(database)
    for document in database.list_documents():
        for version in database.list_document_versions(document["id"]):
            current = version["id"] == document["current_version_id"]
            verification = "unverified"
            market_label = {"domestic": "国内", "overseas": "海外"}.get(
                str(document["scope_market"] or "").casefold(), document["scope_market"] or ""
            )
            model_scope = document["model_scope"] or ""
            scope_bits = [market_label, model_scope]
            scope = " · ".join(value for value in scope_bits if value) or "适用范围未登记"
            if market_label and not model_scope:
                scope = f"{scope} · 机型范围未登记"
            elif model_scope and not market_label:
                scope = f"{scope} · 市场范围未登记"
            version_label = version["version_label"] or f"版本 #{version['id']}"
            title = f"{document['title']} · {version_label}"
            for field in ("path_docx", "path_pdf"):
                raw_path = version.get(field)
                if not raw_path:
                    continue
                path = Path(raw_path).expanduser()
                roots = ((materials_root, *historical_roots) if document["doc_type"] == "历史补充资料" else
                         (materials_root, *extraction_roots) if field == "path_docx" else (materials_root,))
                source_id = f"controlled:{version['id']}:{field.removeprefix('path_')}"
                records.append({
                    "source_id": source_id,
                    "source_type": "controlled",
                    "title": title,
                    "path": path,
                    "scope": scope,
                    "verification": verification,
                    "is_current": current,
                    "document_version_id": version["id"],
                    "document_id": document["id"],
                    "doc_type": document["doc_type"],
                    "file_role": field.removeprefix("path_"),
                    "evidence_count": evidence_counts.get(version["id"], 0),
                    "access_status": _registered_file_access(path, roots),
                    "has_verification": bool(version["verified_at"]),
                    "verification_sha256": (
                        extraction_review_hashes.get(str(version["id"]), "")
                        if field == "path_docx" else str(version["sha256"] or "")
                    ),
                })
    return records


def _latest_extraction_review_hashes(database: Database) -> dict[str, str]:
    return latest_extraction_review_hashes(database)


def _candidate_verification(candidate: dict[str, Any], index: SearchIndex) -> str:
    """Trust reviewed bytes only while their indexed signature remains current."""
    if candidate.get("doc_type") == "历史补充资料":
        return "unverified"
    if not candidate.get("has_verification") or not candidate.get("verification_sha256"):
        return "unverified"
    source = index.source_metadata(candidate["source_id"])
    if (
        source is None or source["status"] != "indexed"
        or Path(source["path"]).resolve() != candidate["path"].resolve()
        or not index.source_signature_matches(candidate["source_id"], candidate["path"], verify_hash=False)
        or source["file_sha256"] != candidate["verification_sha256"]
    ):
        return "unverified"
    return "verified"


def _controlled_candidates(
    database: Database, materials_root: str | Path | None,
    controlled_extraction_roots: Iterable[str | Path] = (),
    historical_roots: Iterable[str | Path] = (),
) -> list[dict[str, Any]]:
    return [item for item in _controlled_records(database, materials_root, controlled_extraction_roots, historical_roots)
            if item["access_status"] == "accessible"]


def training_source_id(relative_name: str) -> str:
    return "training:" + sha256(relative_name.encode("utf-8")).hexdigest()[:24]


def training_source_path(root: Path, relative_name: str) -> Path | None:
    """Share file eligibility between training listing and index candidates."""
    relative = Path(relative_name)
    if relative.is_absolute() or any(part == ".." or part.startswith(".") or part in HIDDEN_DIRECTORY_NAMES
                                    for part in relative.parts):
        return None
    try:
        path = root
        for part in relative.parts:
            path = path / part
            if path.is_symlink():
                return None
        resolved = path.resolve(strict=True)
        if root not in resolved.parents or not resolved.is_file() or path.suffix.casefold() not in SEARCHABLE_SUFFIXES:
            return None
        return resolved
    except (OSError, RuntimeError):
        return None


def _training_candidates(training_root: str | Path | None) -> list[dict[str, Any]]:
    if not training_root:
        return []
    root = Path(training_root).expanduser()
    try:
        resolved_root = root.resolve(strict=True)
        if not resolved_root.is_dir():
            return []
    except OSError:
        return []
    candidates = []
    for path in resolved_root.rglob("*"):
        relative = path.relative_to(resolved_root)
        relative_name = relative.as_posix()
        resolved = training_source_path(resolved_root, relative_name)
        if resolved is None:
            continue
        source_id = training_source_id(relative_name)
        candidates.append({
            "source_id": source_id,
            "source_type": "training",
            "title": relative_name,
            "path": resolved,
            "scope": "培训资料",
            "verification": "not_applicable",
            "is_current": True,
        })
    return candidates


def refresh_search_index(
    database: Database,
    index: SearchIndex,
    *,
    materials_root: str | Path | None,
    training_root: str | Path | None,
    controlled_extraction_roots: Iterable[str | Path] = (),
    historical_roots: Iterable[str | Path] = (),
    retry_failed: bool = False,
) -> dict[str, Any]:
    """Incrementally index registered controlled files and files under the training root."""
    with index.refresh_lock:
        return _refresh_search_index(
            database, index, materials_root=materials_root, training_root=training_root,
            controlled_extraction_roots=tuple(controlled_extraction_roots),
            retry_failed=retry_failed, historical_roots=tuple(historical_roots),
        )


def _refresh_search_index(
    database: Database, index: SearchIndex, *, materials_root: str | Path | None,
    training_root: str | Path | None, controlled_extraction_roots: Iterable[str | Path],
    retry_failed: bool, historical_roots: Iterable[str | Path] = (),
) -> dict[str, Any]:
    controlled_available = any(_root_is_available(root) for root in (materials_root, *controlled_extraction_roots, *historical_roots))
    training_available = _root_is_available(training_root)
    controlled_records = _controlled_records(database, materials_root, controlled_extraction_roots, historical_roots)
    controlled_candidates = [item for item in controlled_records if item["access_status"] == "accessible"]
    training_candidates = _training_candidates(training_root) if training_available else []
    candidates = controlled_candidates + training_candidates
    counts = {"indexed": 0, "updated": 0, "unchanged": 0, "failed": 0}
    for candidate in candidates:
        source_id = candidate["source_id"]
        path = candidate["path"]
        previous = index.source_metadata(source_id)
        if candidate["source_type"] == "controlled":
            candidate["verification"] = _candidate_verification(candidate, index)
        same_path = previous is not None and Path(previous["path"]).resolve() == path.resolve()
        retry_source = retry_failed and previous is not None and previous["status"] == "error"
        if same_path and not retry_source and index.source_signature_matches(source_id, path):
            if index.update_source_metadata(
                source_id,
                title=candidate["title"],
                scope=candidate["scope"],
                verification=candidate["verification"],
                is_current=candidate["is_current"],
            ):
                counts["unchanged"] += 1
                if previous["status"] == "error":
                    counts["failed"] += 1
                continue
        try:
            existed = previous is not None
            before = file_snapshot(path)
            chunks = extract_file(path)
            index.replace_source(
                source_id=source_id,
                source_type=candidate["source_type"],
                title=candidate["title"],
                path=path,
                scope=candidate["scope"],
                verification=candidate["verification"],
                is_current=candidate["is_current"],
                chunks=chunks,
                expected_snapshot=before,
            )
            if candidate["source_type"] == "controlled":
                index.update_source_metadata(
                    source_id, title=candidate["title"], scope=candidate["scope"],
                    verification=_candidate_verification(candidate, index),
                    is_current=candidate["is_current"],
                )
            counts["updated" if existed else "indexed"] += 1
        except Exception as error:
            index.mark_source_error(
                candidate, f"索引提取失败（{type(error).__name__}）",
                cache_signature=not isinstance(error, SourceChangedDuringExtraction),
            )
            counts["failed"] += 1
    # Roots and registrations may change while files are being parsed.
    controlled_available = any(_root_is_available(root) for root in (materials_root, *controlled_extraction_roots, *historical_roots))
    training_available = _root_is_available(training_root)
    controlled_records = _controlled_records(database, materials_root, controlled_extraction_roots, historical_roots)
    training_candidates = _training_candidates(training_root) if training_available else []
    if controlled_available:
        for record in controlled_records:
            if record["access_status"] != "accessible":
                index.mark_source_unavailable(record["source_id"])
        index.remove_source_type_not_in(
            "controlled", {record["source_id"] for record in controlled_records}
        )
    if training_available:
        index.remove_source_type_not_in(
            "training", {candidate["source_id"] for candidate in training_candidates}
        )
    source_errors = {}
    if not controlled_available:
        index.mark_source_type_unavailable("controlled")
        source_errors["controlled"] = "受控资料目录未配置或当前不可访问；已隐藏旧索引，恢复目录后可刷新。"
    if not training_available:
        index.mark_source_type_unavailable("training")
        source_errors["training"] = "培训资料目录未配置或当前不可访问；已隐藏旧索引，恢复目录后可刷新。"
    return {
        **counts,
        "total_sources": len(candidates),
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": index.status(),
        "source_errors": source_errors,
        "coverage": search_source_coverage(
            database, index, materials_root=materials_root, training_root=training_root,
            controlled_extraction_roots=controlled_extraction_roots, historical_roots=historical_roots,
        ),
    }


def sync_search_roots_and_metadata(
    database: Database,
    index: SearchIndex,
    *,
    materials_root: str | Path | None,
    training_root: str | Path | None,
    controlled_extraction_roots: Iterable[str | Path] = (),
    historical_roots: Iterable[str | Path] = (),
) -> dict[str, str]:
    """Sync current controlled metadata and hide indexed results if a source root is unavailable."""
    extraction_roots = tuple(controlled_extraction_roots)
    controlled_available = any(_root_is_available(root) for root in (materials_root, *extraction_roots, *historical_roots))
    training_available = _root_is_available(training_root)
    records = _controlled_records(database, materials_root, extraction_roots, historical_roots) if controlled_available else []
    training_candidates = _training_candidates(training_root) if training_available else []
    with index.maintenance_lock:
        return _sync_search_roots_and_metadata(
            index, controlled_available=controlled_available, records=records,
            training_available=training_available, training_candidates=training_candidates,
        )


def _sync_search_roots_and_metadata(
    index: SearchIndex, *, controlled_available: bool, records: list[dict[str, Any]],
    training_available: bool, training_candidates: list[dict[str, Any]],
) -> dict[str, str]:
    unavailable: dict[str, str] = {}
    if not controlled_available:
        index.mark_source_type_unavailable("controlled")
        unavailable["controlled"] = "受控资料目录未配置或当前不可访问；恢复目录后可更新索引。"
    else:
        active_ids = {record["source_id"] for record in records}
        for candidate in records:
            source_id = candidate["source_id"]
            previous = index.source_metadata(source_id)
            if previous is None:
                continue
            if candidate["access_status"] != "accessible":
                index.mark_source_unavailable(source_id)
                continue
            index.update_source_metadata(
                source_id,
                title=candidate["title"],
                scope=candidate["scope"],
                verification=_candidate_verification(candidate, index),
                is_current=candidate["is_current"],
            )
            if Path(previous["path"]).resolve() != candidate["path"].resolve():
                index.mark_source_stale(source_id)
            else:
                index.mark_source_available(source_id)
        index.remove_source_type_not_in("controlled", active_ids)
    if not training_available:
        index.mark_source_type_unavailable("training")
        unavailable["training"] = "培训资料目录未配置或当前不可访问；恢复目录后可更新索引。"
    else:
        for candidate in training_candidates:
            index.mark_source_available(candidate["source_id"])
    return unavailable


def resolve_source_candidate(
    database: Database,
    source_id: str,
    *,
    materials_root: str | Path | None,
    training_root: str | Path | None,
    controlled_extraction_roots: Iterable[str | Path] = (),
    historical_roots: Iterable[str | Path] = (),
) -> dict[str, Any] | None:
    """Resolve an opaque index ID through live configured roots and current DB rows."""
    if source_id.startswith("controlled:"):
        candidates = _controlled_candidates(database, materials_root, controlled_extraction_roots, historical_roots)
    elif source_id.startswith("training:"):
        candidates = _training_candidates(training_root)
    else:
        return None
    return next((item for item in candidates if item["source_id"] == source_id), None)


def controlled_source_candidates(database: Database, *, materials_root: str | Path | None,
                                 training_root: str | Path | None = None,
                                 controlled_extraction_roots: Iterable[str | Path] = (),
                                 historical_roots: Iterable[str | Path] = ()) -> dict[str, dict[str, Any]]:
    """Resolve one current allowlist snapshot for a batch of controlled previews."""
    return {item['source_id']: item for item in _controlled_candidates(database, materials_root, controlled_extraction_roots, historical_roots)}


_COVERAGE_ACTIONS = {
    "outside_roots": "在资料来源设置中确认并登记允许的抽取目录。",
    "missing": "确认原文件可访问，或登记替代文件作为新版本。",
    "unavailable_root": "恢复已登记的资料目录后更新索引。",
    "failed": "检查文件能否正常打开，修复后更新索引。",
    "empty_text": "此文件只支持名称检索；补充有文字层的版本可支持正文检索。",
    "pending": "更新资料索引后可检索正文。",
    "stale": "文件已变化，更新资料索引后再引用正文。",
}


def _source_coverage(records: list[dict[str, Any]], index: SearchIndex,
                     version_labels: dict[str, list[str]]) -> dict[str, Any]:
    counts = {
        "registered_files": len(records), "accessible_files": 0, "outside_roots": 0,
        "missing_files": 0, "unavailable_root_files": 0, "indexed_files": 0,
        "failed_files": 0, "empty_text_files": 0, "pending_files": 0, "stale_files": 0,
    }
    items = []
    version_files = []
    for record in records:
        access = record.get("access_status", "accessible")
        reason = ""
        if access != "accessible":
            field = {"outside_roots": "outside_roots", "missing": "missing_files", "unavailable_root": "unavailable_root_files"}[access]
            counts[field] += 1
            reason = access
        else:
            counts["accessible_files"] += 1
            previous = index.source_metadata(record["source_id"])
            if previous is None:
                counts["pending_files"] += 1
                reason = "pending"
            elif previous["status"] == "error":
                counts["failed_files"] += 1
                reason = "failed"
            elif previous["status"] != "indexed" or Path(previous["path"]).resolve() != record["path"].resolve():
                counts["stale_files"] += 1
                reason = "stale"
            else:
                counts["indexed_files"] += 1
                if not previous["has_text_content"]:
                    counts["empty_text_files"] += 1
                    reason = "empty_text"
        if reason:
            item = {"source_id": record["source_id"], "title": record["title"],
                    "reason": reason, "action": _COVERAGE_ACTIONS[reason]}
            for key in ("document_id", "document_version_id", "file_role"):
                if key in record:
                    item[key] = record[key]
            items.append(item)
        # A changed or inaccessible file retains only its registered version label;
        # old worksheet labels cannot establish the coverage of replacement bytes.
        registered_version = located_version('', record['title'])
        versions = (version_labels.get(record['source_id'], []) if not reason or reason == 'empty_text' else [])
        version_files.append({'versions': versions or ([registered_version] if registered_version else []),
                              'status': reason or 'ready'})
    return {**counts, "items": items, "version_files": version_files}


def search_source_coverage(
    database: Database, index: SearchIndex, *, materials_root: str | Path | None,
    training_root: str | Path | None, controlled_extraction_roots: Iterable[str | Path] = (),
    historical_roots: Iterable[str | Path] = (),
    include_versions: bool = False,
) -> dict[str, Any]:
    """Describe actual registered-file coverage with repairable titles, never paths."""
    extraction_roots = tuple(controlled_extraction_roots)
    records = _controlled_records(database, materials_root, extraction_roots, historical_roots)
    training_candidates = _training_candidates(training_root)
    controlled_root_available = _root_is_available(materials_root)
    extraction_roots_available = sum(_root_is_available(root) for root in extraction_roots)
    training_root_available = _root_is_available(training_root)
    with index.maintenance_lock:
        index.status()
        version_labels = index.version_labels() if include_versions else {}
        controlled = _source_coverage(records, index, version_labels)
        controlled["root_available"] = controlled_root_available
        controlled["extraction_roots_configured"] = len(extraction_roots)
        controlled["extraction_roots_available"] = extraction_roots_available
        training = _source_coverage(training_candidates, index, version_labels)
        training["root_available"] = training_root_available
        if not include_versions:
            controlled.pop('version_files', None)
            training.pop('version_files', None)
        return {"controlled": controlled, "training": training}


def search_version_coverage(database: Database, coverage: dict[str, Any], result: dict[str, Any],
                            project_id: int) -> list[dict[str, Any]]:
    """Explain coverage independently of keyword hits, using registered sources only."""
    filters = result['filters']
    selected = parse_version_selection(filters.get('versions', ''))
    lower, upper = filters.get('version_from', ''), filters.get('version_to', '')
    if not (selected or lower or upper):
        return []
    inventory: dict[str, list[str]] = {}
    unknown = 0
    sources = set(filters['sources'])
    for source in sources & {'controlled', 'training'}:
        for file in coverage.get(source, {}).get('version_files', []):
            if not file['versions']:
                unknown += 1
            for version in file['versions']:
                inventory.setdefault(version, []).append(file['status'])
    if 'release' in sources:
        releases = database.release_search_coverage(project_id, all_projects=result['scope'] == 'all')
        for release in releases:
            states = inventory.setdefault(release['version'], [])
            if release['has_evidence']:
                states.append('ready')
    versions = {version for version in inventory if in_version_range(version, lower, upper, selected)}
    versions.update(version for version in selected if not version.endswith('.*'))
    if lower and lower == upper:
        versions.add(lower)
    versions.update(series for series in selected if series.endswith('.*')
                    and not any(in_version_range(version, selected_versions=(series,)) for version in versions))
    hits = {row['version']: row for row in result['version_summary']}
    rows = []
    for version in sorted(versions, key=lambda value: version_key(value.replace('.*', '.0'))):
        states = inventory.get(version, [])
        ready = states.count('ready')
        pending = sum(state in {'pending', 'stale'} for state in states)
        unavailable = sum(state in {'missing', 'outside_roots', 'unavailable_root', 'failed'} for state in states)
        empty = states.count('empty_text')
        hit = hits.get(version, {})
        total = hit.get('total', 0)
        if ready and (pending or unavailable or empty):
            status = 'partial'
        elif pending:
            status = 'pending_index'
        elif unavailable:
            status = 'unavailable'
        elif empty and not ready:
            status = 'unsearchable'
        elif any(source in result['source_errors'] for source in sources & {'release', 'controlled', 'training'}):
            status = 'unknown'
        elif total:
            status = 'matched'
        else:
            status = 'no_match' if ready else 'no_materials'
        rows.append({'version': version, 'status': status, 'total': total,
                     'direct_count': hit.get('direct_count', 0), 'related_count': hit.get('related_count', 0),
                     'stale_count': hit.get('stale_count', 0),
                     'ready_count': ready, 'pending_count': pending,
                     'unavailable_count': unavailable, 'empty_count': empty})
    coverage['unversioned_files'] = unknown
    coverage['versions_truncated'] = len(rows) > 200
    return rows[:200]


def _result(
    *, source_type: str, source_label: str, title: str, scope: str, verification: str,
    matched_text: str, locator: str = "", is_current: bool = True,
    preview_id: str | None = None, **extra: Any,
) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "source_label": source_label,
        "title": str(title or "未命名"),
        "scope": str(scope or "全局资料"),
        "verification": verification,
        "is_current": bool(is_current),
        "matched_text": str(matched_text or "")[:500],
        "locator": locator,
        "preview_id": preview_id,
        **extra,
    }


def _strategy_results(
    reader: ProductStrategyReader,
    query: str,
    *,
    model_filter: str = "",
    market: str = "",
) -> tuple[list[dict[str, Any]], str | None]:
    results = []
    try:
        if market and market != "domestic":
            return results, "当前接入的正式配置数据仅覆盖国内版。"
        models = reader.list_models()["models"]
        if model_filter:
            models = [model for model in models if matches_model_scope(model["name"], model_filter, include_unknown=False)]
        for model in models:
            payload = reader.query(market="domestic", model=model["name"], query=query)
            for item in payload["items"]:
                matched = [str(item.get(key) or "") for key in ("code", "name", "zh_description", "en_description", "category")]
                if not any(query.casefold() in value.casefold() for value in matched):
                    continue
                results.append(_result(
                    source_type="config",
                    source_label="正式配置策略",
                    title=item.get("name") or item.get("code") or "配置项",
                    scope=f"国内 · {payload['scope']['model']}",
                    verification=(
                        "approved" if item.get("knowledge_status") == "published" else "pending_review"
                    ),
                    matched_text=" · ".join(value for value in matched if query.casefold() in value.casefold()),
                    locator=item.get("code") or "正式选型类别",
                    strategy_state=item.get("knowledge_status", "pending_confirmation"),
                    source_status="source_live",
                    strategy=item,
                ))
    except (ProductStrategySourceUnavailable, ValueError, OSError):
        return results, "正式配置来源当前不可用，请检查首页的系统状态。"
    return results, None


def _matches_index_scope(item: dict[str, Any], *, model: str, market: str) -> bool:
    if item["source_type"] != "controlled":
        return True
    scope = item["scope"]
    if market:
        explicit_market = "国内" if market == "domestic" else "海外"
        other_market = "海外" if market == "domestic" else "国内"
        if other_market in scope and explicit_market not in scope:
            return False
    if model and "机型范围未登记" not in scope and "适用范围未登记" not in scope:
        if "市场范围未登记" in scope:
            model_scope = scope.split(" · ", 1)[0]
        elif " · " in scope:
            model_scope = scope.split(" · ", 1)[1].removesuffix(" · 机型范围未登记")
        else:
            model_scope = scope
        if model.casefold() not in model_scope.casefold():
            return False
    return True


def _search_exact(
    database: Database,
    index: SearchIndex,
    reader: ProductStrategyReader,
    *,
    query: str,
    sources: set[str] | None = None,
    project_id: int | None = None,
    scope: str = "current",
    verification: str = "",
    current_only: bool = False,
    model: str = "",
    market: str = "",
    country: str = "",
    unavailable_sources: dict[str, str] | None = None,
    version_from: str = "",
    version_to: str = "",
    family_query: str = "",
    selected_versions: tuple[str, ...] = (),
) -> dict[str, Any]:
    needle = query.strip()
    if not needle:
        raise ValueError("请输入要搜索的关键词。")
    if len(needle) > 200:
        raise ValueError("搜索词不能超过 200 个字符。")
    if scope not in {"current", "all"}:
        raise ValueError("搜索范围必须是 current 或 all。")
    if market not in {"", "domestic", "overseas"}:
        raise ValueError("市场筛选值不受支持。")
    if verification not in {"", "verified", "unverified", "not_applicable", "source_live", "approved", "pending_review"}:
        raise ValueError("不支持该复核状态筛选。")
    allowed_sources = {"release", "config", "controlled", "training", "term"} | STRUCTURED_SOURCE_TYPES
    selected_sources = allowed_sources if sources is None else sources
    if not selected_sources:
        raise ValueError("请至少选择一个搜索来源。")
    if not selected_sources <= allowed_sources:
        raise ValueError("搜索来源包含不支持的类型。")
    live_groups: dict[str, list[dict[str, Any]]] = {
        "release": [], "config": [], "term": [],
    }
    unavailable = unavailable_sources or {}
    source_errors: dict[str, str] = {
        source: message for source, message in unavailable.items() if source in selected_sources
    }

    release_data = {"results": []}
    if "release" in selected_sources:
        project_names = {project["id"]: project["name"] for project in database.list_projects()}
        project_filter = project_id if scope == "current" else None
        release_data = database.search_release_history(
            needle,
            project_id=project_filter,
            all_projects=(scope == "all"),
            result_type="all",
        )
        current_versions: dict[int, str] = {}
        matched_project_ids = {
            int(item["project_id"])
            for item in release_data["results"]
            if item.get("project_id") is not None
        }
        if scope == "current" and project_id is not None:
            matched_project_ids.add(int(project_id))
        for matched_project_id in matched_project_ids:
            releases = database.list_releases(matched_project_id)
            if releases:
                current_versions[matched_project_id] = releases[0]["version"]
        for item in release_data["results"]:
            if not in_version_range(item.get("version", ""), version_from, version_to, selected_versions):
                continue
            if family_query:
                evidence = release_evidence(database, item['preview_id'], limit=None)
                chunk = next((chunk for chunk in evidence['chunks']
                              if family_mentions(chunk['text'], family_query)), None) if evidence else None
                if chunk is None and not family_mentions(item.get('title_cn', '') + ' ' + item.get('title_en', ''), family_query):
                    continue
                if chunk:
                    item = {**item, 'matched_text': family_excerpt(chunk['text'], family_query), 'locator': chunk['locator']}
            project = int(item.get("project_id") or project_id or database.default_project_id())
            live_groups["release"].append(_result(
                source_type="release",
                source_label="版本与功能",
                title=item.get("title_cn") or item.get("title_en") or "Release Note 变更",
                scope=f"{item.get('project_name') or project_names.get(project, '当前项目')} · {item.get('version', '')}",
                verification=("pending_review" if item.get("status") == "待审核" else
                              "unverified" if item.get("evidence_kind") == "source_snapshot" else "approved"),
                matched_text=item.get("matched_text") or item.get("title_cn") or item.get("title_en") or needle,
                locator=item.get("locator") or f"版本 {item.get('version', '')}",
                is_current=current_versions.get(project) == item.get("version"),
                category=item.get("category"),
                version=item.get("version"),
                project_id=project,
                release_status=item.get("status"),
                evidence_kind=item.get("evidence_kind"),
                preview_id=item.get("preview_id"),
            ))

    if "term" in selected_sources:
        for term in database.list_terms(needle):
            if term.get("entry_type") == "note":
                continue
            live_groups["term"].append(_result(
                source_type="term",
                source_label="术语词典",
                title=f"{term.get('cn_name', '')} / {term.get('en_name', '')}",
                scope=term.get("category") or "全局术语",
                verification="pending_review" if term.get("needs_review") else "approved",
                matched_text=" · ".join(value for value in (term.get("cn_name"), term.get("en_name"), term.get("category")) if needle.casefold() in str(value or "").casefold()),
                locator=f"术语 #{term['id']}",
                term_id=term["id"],
            ))

    if "config" in selected_sources:
        strategy_results, error = _strategy_results(
            reader, needle, model_filter=model, market=market
        )
        live_groups["config"].extend(strategy_results)
        if error:
            source_errors["config"] = error

    index_types = (selected_sources & {"controlled", "training"}) - set(unavailable)
    structured = search_structured_sources(database, reader, query=needle, model=model, market=market,
                     country=country, verification=verification, current_only=current_only,
                     sources=selected_sources & STRUCTURED_SOURCE_TYPES)
    source_errors.update(structured["source_errors"])
    for group in live_groups.values():
        group.sort(key=lambda item: (not item["is_current"], item["title"].casefold()))
        group[:] = [
            item for item in group
            if (not verification or item["verification"] == verification
                or item.get("source_status") == verification)
            and (not current_only or item["is_current"])
        ]

    index_verification = verification if verification in {"verified", "unverified", "not_applicable"} else ""
    indexed_totals: dict[str, int] = {}
    for source_type in ("controlled", "training"):
        if source_type not in index_types or verification in {"approved", "pending_review", "source_live"}:
            indexed_totals[source_type] = 0
            continue
        indexed_totals[source_type] = index.search(
            needle,
            source_types={source_type},
            verification=index_verification,
            current_only=current_only,
            model=model,
            market=market,
            limit=0, version_from=version_from, version_to=version_to, selected_versions=selected_versions, family_query=family_query,
        )["total"]

    results = [item for group in live_groups.values() for item in group] + structured["results"]
    historical_versions = {version["id"] for document in database.list_documents()
                           if document["doc_type"] == "历史补充资料"
                           for version in database.list_document_versions(document["id"])}
    for source_type, count in indexed_totals.items():
        if not count:
            continue
        indexed = index.search(needle, source_types={source_type}, verification=index_verification,
                               current_only=current_only, model=model, market=market, limit=count,
                               version_from=version_from, version_to=version_to, selected_versions=selected_versions, family_query=family_query)
        for item in indexed["results"]:
            extra = {}
            if source_type == "controlled":
                extra["document_version_id"] = int(item["source_id"].split(":")[1])
            results.append(_result(source_type=source_type,
                source_label=("历史补充资料" if extra.get("document_version_id") in historical_versions else "受控资料") if source_type == "controlled" else "培训资料",
                title=item["title"], scope=item["scope"], verification=item["verification"],
                matched_text=item["matched_text"], locator=item["locator"], is_current=item["is_current"],
                preview_id=item["preview_id"], file_format=item.get("file_format", ""),
                version=located_version(item["locator"], item["title"]),
                family_matches=item.get('family_matches', []),
                version_matches=item.get('version_matches', []), matched_versions=item.get('matched_versions', []),
                is_stale=item.get("is_stale", False), match_count=item.get("match_count", 1), **extra))

    def relevance(item: dict[str, Any]) -> tuple:
        title = item["title"].casefold()
        exact_names = [part.strip() for part in title.replace(" / ", " · ").split(" · ")]
        exact = needle.casefold() in exact_names or needle.casefold() == str(item.get("locator", "")).casefold()
        confirmed = item["verification"] in {"verified", "approved"}
        return (bool(item.get("is_stale")), not exact, not item["is_current"], not confirmed,
                needle.casefold() not in title, title, item["source_type"], str(item.get("preview_id") or item["locator"]))

    results.sort(key=relevance)
    total = len(results)
    source_counts = {source: sum(item["source_type"] == source for item in results) for source in sorted(selected_sources)}
    return {
        "earliest_records": _earliest_records(live_groups["release"]),
        "query": needle,
        "scope": scope,
        "filters": {
            "sources": sorted(selected_sources),
            "verification": verification,
            "current_only": current_only,
            "model": model,
            "market": market,
            "country": country,
        },
        "total": total,
        "results": results,
        "source_counts": source_counts,
        "source_errors": source_errors,
    }


def unified_search(
    database: Database, index: SearchIndex, reader: ProductStrategyReader, *, query: str,
    sources: set[str] | None = None, project_id: int | None = None, scope: str = 'current',
    verification: str = '', current_only: bool = False, model: str = '', market: str = '',
    country: str = '', unavailable_sources: dict[str, str] | None = None,
    page: int = 1, page_size: int = 40, task: str = 'search', expand_related: bool = False,
    version_from: str = '', version_to: str = '', versions: str = '',
    source_group: str = 'all', release_category: str = 'all',
) -> dict[str, Any]:
    """Run explicit queries through the same adapters; related hits stay separate clues."""
    groups = {'all', 'release_note', 'whitepaper', 'other'}
    categories = {'all', 'function', 'image', 'bug', 'config', 'config_note', 'probe', 'remark', 'unclassified', 'source'}
    if source_group not in groups or release_category not in categories:
        raise ValueError('不支持的资料来源或发布分类。')
    validate_search_task(task, version_from, version_to, versions)
    selected_versions = parse_version_selection(versions)
    needle = query.strip()
    selected = sources if sources is not None else {'release', 'config', 'controlled', 'training', 'term'} | STRUCTURED_SOURCE_TYPES
    scoped = bool(version_from or version_to or selected_versions)
    version_sources = {'release', 'controlled', 'training'}
    effective_sources = selected & version_sources if scoped else selected
    # Validate unsupported source values even when version filtering excludes them.
    if not selected or not selected <= version_sources | {'config', 'term'} | STRUCTURED_SOURCE_TYPES:
        raise ValueError('请至少选择一个支持的搜索来源。')
    terms = search_terms(needle, expand_related, task)
    run_query = partial(_search_exact, database, index, reader,
                project_id=project_id, scope=scope, verification=verification,
                current_only=current_only, model=model, market=market, country=country,
                unavailable_sources=unavailable_sources, version_from=version_from, version_to=version_to,
                family_query=needle if task == 'family' else '', selected_versions=selected_versions)
    payload = run_query(query=needle, sources=effective_sources or version_sources)
    results = payload['results'] if effective_sources else []
    for item in results:
        item.update(match_kind='direct', matched_query=needle)
        item['version_hit_kinds'] = {version: 'direct' for version in
                                     (item.get('matched_versions') or [item.get('version')]) if version}
    seen = {_hit_identity(item): item for item in results}
    related_sources = effective_sources & version_sources
    for term in terms[1:] if related_sources else []:
        extra = run_query(query=term, sources=related_sources)
        payload['source_errors'].update(extra['source_errors'])
        for item in extra['results']:
            item['version_hit_kinds'] = {version: 'related' for version in
                                         (item.get('matched_versions') or [item.get('version')]) if version}
            identity = _hit_identity(item)
            if identity not in seen:
                item.update(match_kind='related', matched_query=term)
                results.append(item)
                seen[identity] = item
            else:
                previous = seen[identity]
                for field in ('family_matches', 'version_matches'):
                    matches = {row['locator']: row for row in previous.get(field, [])}
                    for row in item.get(field, []):
                        matches.setdefault(row['locator'], row)
                    previous[field] = list(matches.values())[:200]
                previous['matched_versions'] = sorted(set(previous.get('matched_versions', []))
                                                      | set(item.get('matched_versions', [])))
                for version, kind in item['version_hit_kinds'].items():
                    previous['version_hit_kinds'].setdefault(version, kind)
    if task == 'family':
        results = [item for item in results if item['source_type'] in {'release', 'controlled', 'training'}
                   or family_mentions(item['title'] + ' ' + item['matched_text'], needle)]
    if task == 'earliest':
        results.sort(key=lambda row: (row['match_kind'] != 'direct', row['source_type'] != 'release',
                                     row.get('project_id', 0), version_key(row.get('version') or '99999.0.0')))
    # Classify actual registered sources before pagination; do not infer types from titles.
    document_types = {version['id']: document['doc_type']
                      for document in database.list_documents()
                      for version in database.list_document_versions(document['id'])}
    section_cache = {}
    source_cache: dict[int, Any] = {}
    for item in results:
        kind = item['source_type']
        doc_type = document_types.get(item.get('document_version_id'), '')
        item['source_group'] = ('release_note' if kind == 'release' and item.get('evidence_kind') != 'current_description'
                                or kind == 'controlled' and doc_type == '发布记录'
                                else 'whitepaper' if kind == 'controlled' and doc_type == '白皮书' else 'other')
        item['release_category'] = (item.get('category') or 'source') if item['source_group'] == 'release_note' else None
        item['release_categories'] = [item['release_category']] if item['release_category'] else []
        category_sections: dict[str, dict[str, Any]] = {}
        preview = item.get('preview_id') or ''
        if preview.startswith('release:source:'):
            source_id = int(preview.rsplit(':', 1)[1])
            if source_id not in section_cache:
                section_cache[source_id] = source_sections(database, source_id, cache=source_cache)
            sections = section_cache[source_id]
            for match in matching_sections(sections, item.get('matched_query', needle)):
                category_sections.setdefault(match['category'], match)
            # Prefer a real heading/body hit over a table of contents line.
            headings = [section for section in sections if needle.casefold() in section['title'].casefold()]
            section = headings[0] if len(headings) == 1 else None
            if section is None:
                section = section_for_locator(sections, item['locator'])
            if section:
                item['detail_evidence'] = release_section_detail(section)
                item['release_category'] = section['category']
                if needle.casefold() in section['title'].casefold():
                    item['locator'] = section['locator']
                    item['matched_text'] = section['content'][:500]
        if preview.startswith('release:table:'):
            item['detail_evidence'], item['detail_evidence_notice'] = preferred_release_detail(database, preview, locator=item.get('locator', ''), cache=source_cache)
        elif kind == 'controlled' and item['source_group'] == 'release_note' and item.get('file_format') in {'pdf', 'docx'} and not item.get('is_stale'):
            evidence = index.preview(preview, locator=item.get('locator', ''), query=item.get('matched_query', needle), include_images=False)
            section = evidence.get('section') if evidence and not evidence.get('stale') else None
            if section:
                if item['source_group'] == 'release_note' and item['file_format'] == 'docx':
                    item['release_category'] = section.get('category') or 'source'
                    meta = index.source_metadata(preview)
                    if meta:
                        word_sections = controlled_word_sections(meta['path'], meta['file_sha256'], preview)
                        for match in matching_sections(word_sections, item.get('matched_query', needle)):
                            category_sections.setdefault(match['category'], match)
                item['detail_evidence'] = {key: section[key] for key in ('source_id', 'locator', 'section_number', 'title')}
                item['detail_evidence']['excerpt'] = section['content'][:500]
                item['detail_evidence']['evidence_kind'] = 'controlled_document'
                item['detail_evidence']['source_label'] = '白皮书' if item['source_group'] == 'whitepaper' else 'Release Note 原文'
                item['detail_evidence']['verification'] = item['verification']
                item['detail_evidence']['scope'] = item['scope']
                item['detail_evidence']['has_images'] = section['has_images']
        if category_sections:
            item['release_categories'] = list(category_sections)
            item['category_sections'] = {category: {'locator': section['locator'], 'title': section['title'],
                                                   'excerpt': section['content'][:500], 'section_number': section['section_number']}
                                         for category, section in category_sections.items()}
        elif item['release_category']:
            item['release_categories'] = [item['release_category']]
    payload['taxonomy_counts'] = {
        'sources': {group: sum(item['source_group'] == group for item in results)
                    for group in ('release_note', 'whitepaper', 'other')},
        'release_categories': {category: sum(item['source_group'] == 'release_note' and category in item['release_categories'] for item in results)
                               for category in sorted(categories - {'all'})},
    }
    payload['unfiltered_total'] = len(results)
    results = [dict(item) for item in results if (source_group == 'all' or item['source_group'] == source_group)
               and (release_category == 'all' or item['source_group'] == 'release_note' and release_category in item['release_categories'])]
    if release_category != 'all':
        for item in results:
            selected_section = item.get('category_sections', {}).get(release_category)
            if selected_section:
                item['locator'] = selected_section['locator']
                item['matched_text'] = selected_section['excerpt']
                item['release_category'] = release_category
                if item.get('detail_evidence') and (item['source_type'] == 'controlled' or item.get('evidence_kind') == 'source_snapshot'):
                    item['detail_evidence'] = {**item['detail_evidence'], **selected_section}
    payload['earliest_records'] = _earliest_records([
        row for row in results if row['source_type'] == 'release' and row['match_kind'] == 'direct'])
    payload['query_expansion'] = {'enabled': expand_related, 'terms': terms[1:],
        'notice': '关联词仅用于寻找线索，不代表含义等同或已支持；不参与最早记载判断。'}
    payload['feature_family'] = feature_family(database, needle, project_id=project_id, scope=scope,
        version_from=version_from, version_to=version_to, selected_versions=selected_versions, market=market) if task == 'family' and 'release' in selected else None
    if payload['feature_family'] and (model or country or current_only or verification not in {'', 'approved'}):
        payload['feature_family']['members'] = []
        payload['feature_family']['notice'] = '功能关系汇总暂不支持机型、国家、当前版本或此复核状态筛选；请清除相应条件查看档案关联。'
    payload['task'] = task
    payload['task_notice'] = ('结果限于所选版本范围；按版本记录或文件/工作表明确标注的版本筛选，未注明版本的资料不列入。最早记载也仅针对所选范围。' if scoped else '') + '未找到提及不表示功能不支持，请同时核对资料覆盖和原文限制。'
    if scoped:
        for source in selected - version_sources:
            payload['source_errors'][source] = '此来源未接入版本范围筛选，本次未列入结果；清除版本范围可查询。'
    payload['filters'].update(sources=sorted(selected), task=task, expand_related=expand_related,
                              version_from=version_from, version_to=version_to, versions=','.join(selected_versions),
                              source_group=source_group, release_category=release_category)
    payload['version_summary'] = _version_summary(results, selected_versions) if scoped else []
    safe_page, safe_size = max(1, int(page)), min(100, max(1, int(page_size)))
    page_results = results[(safe_page - 1) * safe_size:safe_page * safe_size]
    # A title association is needed only for visible records and earliest answers.
    detail_cache: dict[tuple[str, str], tuple[dict | None, str | None]] = {}
    for item in [*page_results, *payload['earliest_records']]:
        preview = item.get('preview_id') or ''
        key = (preview, item.get('locator') or '')
        if preview.startswith('release:change:'):
            if key not in detail_cache:
                detail_cache[key] = preferred_release_detail(database, preview, locator=item.get('locator', ''), cache=source_cache)
            item['detail_evidence'], item['detail_evidence_notice'] = detail_cache[key]
    # Whitepaper detail does not affect facets; parse only the visible page.
    for item in page_results:
        if item['source_group'] != 'whitepaper' or item.get('file_format') not in {'pdf', 'docx'} or item.get('is_stale'):
            continue
        evidence = index.preview(item['preview_id'], locator=item.get('locator', ''),
                                 query=item.get('matched_query', needle), include_images=False)
        section = evidence.get('section') if evidence and not evidence.get('stale') else None
        if section:
            item['detail_evidence'] = {key: section[key] for key in ('source_id', 'locator', 'section_number', 'title')}
            item['detail_evidence'].update(excerpt=section['content'][:500], evidence_kind='controlled_document',
                                           source_label='白皮书', verification=item['verification'],
                                           scope=item['scope'], has_images=section['has_images'])
    payload.update(total=len(results), page=safe_page, page_size=safe_size,
                   results=page_results,
                   source_counts={source: sum(r['source_type'] == source for r in results) for source in sorted(selected)},
                   index=index.status())
    return payload


def _version_summary(results: list[dict[str, Any]], selected: tuple[str, ...]) -> list[dict[str, Any]]:
    """Count each file once per version; direct hits win and stale hits stay separate."""
    def empty_counts() -> dict[str, int]:
        return {'total': 0, 'direct_count': 0, 'related_count': 0, 'stale_count': 0}

    counts = {version: empty_counts() for version in selected if not version.endswith('.*')}
    for item in results:
        for version, kind in item['version_hit_kinds'].items():
            count = counts.setdefault(version, empty_counts())
            if item.get('is_stale'):
                count['stale_count'] += 1
            else:
                count['total'] += 1
                count['direct_count' if kind == 'direct' else 'related_count'] += 1
    summary = [{'version': version, **count} for version, count in sorted(counts.items(), key=lambda row: version_key(row[0]))]
    summary.extend({'version': series, **empty_counts()} for series in selected if series.endswith('.*')
                   and not any(in_version_range(version, selected_versions=(series,)) for version in counts))
    return summary


def _hit_identity(item: dict[str, Any]) -> tuple:
    if item['source_type'] in {'controlled', 'training'}:
        return (item['source_type'], item['preview_id'])
    return (item['source_type'], item.get('preview_id') or item['locator'],
            item.get('version'), item.get('project_id'), item['scope'])


def _earliest_records(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First dated record per product line; never compare unrelated version lines."""
    from tracker.domain import version_key
    earliest: dict[int, dict[str, Any]] = {}
    for item in sorted(results, key=lambda item: (version_key(item["version"]), item.get("evidence_kind") == "source_snapshot")):
        if item.get("evidence_kind") in {"current_description", "bug_fix", "pending"}:
            continue
        earliest.setdefault(item["project_id"], item)
    return list(earliest.values())
