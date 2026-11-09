"""Save Cart checks with configuration versions and build verified regional drafts."""

import asyncio
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
from zipfile import BadZipFile

from lxml.etree import XMLSyntaxError
from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.sqlite import insert

from app.models import (
    CartReleaseArtifact, CartReleaseCheck, ConfigVersion, KnowledgeDocument, ProductSeries,
)
from app.services.cart_release_diff import changes, plan_tokens, snapshot_view
from app.services.cart_release_facts import fact_state, link_fact_impacts, plan_fact_tokens, resolve_facts
from app.services.cart_release_ppt import build_candidate
from app.services.cart_release_rules import MARKET_FOLDERS, Rules, load_rules
from app.services.cart_release_scope import excluded_series
from app.services.knowledge_sources import CitationSourceError, read_verified_source, verified_original
from app.services.version_comparison import normalize_comparison_snapshot
from app.utils.time import utcnow


logger = logging.getLogger(__name__)
SNAPSHOT_ERRORS = (ValueError, TypeError, KeyError, AttributeError)


def snapshot_sha(version):
    return sha256(version.snapshot_data.encode("utf-8")).hexdigest()


def version_key(version):
    identity = [version.id, version.series_id, _version_time(version), snapshot_sha(version)]
    return sha256(json.dumps(identity).encode("utf-8")).hexdigest()


def _version_time(version):
    timestamp = version.created_at or version.published_at
    return timestamp.isoformat() if timestamp else ""


def source_ref(version):
    if version is None:
        return None
    return {
        "id": version.id, "series_id": version.series_id, "number": version.version_number,
        "sha256": snapshot_sha(version), "key": version_key(version), "created_at": _version_time(version),
    }


async def _view(db, version, rules):
    if version is None:
        return snapshot_view({}, rules)
    snapshot = await normalize_comparison_snapshot(db, version.series_id, json.loads(version.snapshot_data))
    return snapshot_view(snapshot, rules)


async def _prior_version(db, version):
    return await db.scalar(select(ConfigVersion).where(
        ConfigVersion.series_id == version.series_id, ConfigVersion.id < version.id,
    ).order_by(ConfigVersion.id.desc()).limit(1))


async def _template_bytes(db, market, template):
    document_id = await db.scalar(select(KnowledgeDocument.id).where(
        KnowledgeDocument.sha256 == template.sha256,
        KnowledgeDocument.market == market,
        KnowledgeDocument.source_status == "active",
    ).order_by(KnowledgeDocument.id).limit(1))
    if document_id is not None:
        _, data = await verified_original(db, document_id, template.sha256)
        return data
    root = os.environ.get("CART_RELEASE_TEMPLATE_ROOT")
    if not root:
        raise CitationSourceError(404, "该市场的核验版 PPT 尚未登记")
    path = Path(root) / MARKET_FOLDERS[market] / template.filename
    return await asyncio.to_thread(read_verified_source, path, template.sha256)


async def _collect_evidence(db, template, version, after, market, rules):
    """Freeze each covered series at the time of the selected version."""
    evidence = {}
    context = {}
    names = [anchor.series for anchor in template.anchors]
    series_ids = dict((await db.execute(select(ProductSeries.name, ProductSeries.id).where(
        ProductSeries.name.in_(names),
    ))).all())
    for anchor in template.anchors:
        series_id = series_ids.get(anchor.series)
        if series_id is None:
            continue
        reference = await db.scalar(select(ConfigVersion).where(
            ConfigVersion.series_id == series_id, ConfigVersion.version_number == anchor.version,
        ))
        target = version if series_id == version.series_id else await db.scalar(
            select(ConfigVersion).where(ConfigVersion.series_id == series_id, ConfigVersion.id <= version.id)
            .order_by(ConfigVersion.id.desc()).limit(1)
        )
        context[anchor.series] = {"baseline": source_ref(reference), "target": source_ref(target)}
        if (reference is None or target is None or target.id < reference.id
                or snapshot_sha(reference) != anchor.sha256):
            continue
        baseline = await _view(db, reference, rules)
        target_view = after if series_id == version.series_id else await _view(db, target, rules)
        evidence[anchor.series] = (baseline, target_view, changes(baseline, target_view, market, rules))
    return evidence, context


def _preserves_context(old, new):
    # Newly supplied evidence may resolve a gap. Evidence already used by the
    # check must still identify the same snapshots, even after a label edit.
    for series, entries in old.items():
        for kind, ref in entries.items():
            if ref:
                current = new.get(series, {}).get(kind)
                if not current or current["key"] != ref["key"]:
                    return False
    return True


async def _review_rules():
    try:
        return await asyncio.to_thread(load_rules), False
    except (OSError, ValueError) as error:
        logger.warning("Cart rules unavailable: %s", type(error).__name__)
        return Rules(), True


async def has_cart_changes(before, after, series_name):
    """Allow Cart metadata-only saves through the normal version no-op check."""
    if excluded_series(series_name):
        return False
    rules, _ = await _review_rules()
    return bool(changes(snapshot_view(before, rules), snapshot_view(after, rules), rules.market(series_name), rules))


async def _previous_check(db, version, market, template, *, artifact_only):
    version_time = CartReleaseCheck.report["version"]["created_at"].as_string()
    query = select(CartReleaseCheck).where(
        or_(CartReleaseCheck.version_id < version.id,
            and_(CartReleaseCheck.version_id == version.id, version_time < _version_time(version))),
        CartReleaseCheck.report["market"].as_string() == market,
        CartReleaseCheck.report["template"]["sha256"].as_string() == template.sha256,
    )
    if artifact_only:
        query = query.where(CartReleaseCheck.artifact_sha256.is_not(None))
    return await db.scalar(query.order_by(
        CartReleaseCheck.version_id.desc(), version_time.desc(), CartReleaseCheck.checked_at.desc(),
    ).limit(1))


async def _assess(db, version, origin, previous_report, rollback_target, *, rules_result=None):
    series = await db.get(ProductSeries, version.series_id)
    series_name = series.name if series else f"系列 #{version.series_id}"
    rules, rules_error = rules_result or await _review_rules()
    market = rules.market(series_name)
    prior = await _prior_version(db, version)
    template = rules.templates.get(market)
    has_binding = template is not None and any(anchor.series == series_name for anchor in template.anchors)
    report = {
        "ruleset": rules.version, "status": "pending", "series": series_name, "market": market,
        "origin": origin, "version": source_ref(version), "previous": source_ref(prior),
        "rollback_target": previous_report.get("rollback_target") if previous_report else source_ref(rollback_target),
        "template": {
            "file": template.filename, "sha256": template.sha256, "review_notes": template.review_notes,
        } if template else None,
        "changes": [], "baseline_changes": [], "updates": [], "context": {}, "reason": None,
        "facts": {}, "fact_gaps": [], "layout_gaps": [], "affected_pages": [],
    }
    if excluded_series(series_name):
        return {**report, "status": "checked", "reason": "本系列不在 Cart 维护范围"}, None
    if previous_report:
        prior_key = report["previous"]["key"] if prior else None
        frozen = previous_report["previous"]
        if prior_key != (frozen["key"] if frozen else None):
            return {**previous_report, "reason": "前一版快照已变化或缺失，保留原检查证据"}, None
    try:
        before, after = await _view(db, prior, rules), await _view(db, version, rules)
        report["changes"] = changes(before, after, market, rules, include_models=prior is not None)
        if rules_error or (market and not rules.version):
            return {**report, "reason": "Cart 规则未配置或不可读取，无法完成核验"}, None
        if not report["changes"] and not (has_binding and template.fact_keys):
            return {**report, "status": "checked", "reason": "已检查，未发现影响 Cart 发货资料的变更"}, None
        if not has_binding:
            return {**report, "reason": "系列或市场未与 Cart 模板绑定，适用型号及页码需核对"}, None
        evidence, context = await _collect_evidence(db, template, version, after, market, rules)
        if (previous_report and previous_report["ruleset"] == rules.version and previous_report["context"]
                and not _preserves_context(previous_report["context"], context)):
            return {**previous_report, "reason": "市场关联快照已变化或缺失，保留原检查证据"}, None
        report["context"] = context
        report["baseline_changes"] = [
            {**change, "series": name}
            for name, (_, _, delta) in evidence.items() for change in delta
        ]
        if len(evidence) != len(template.anchors):
            return {**report, "reason": "缺少完整的市场快照基线，或所选版本早于已核验基线"}, None
        patches, uncovered = plan_tokens(template, evidence, rules.known_codes)
        for change in report["baseline_changes"]:
            if (change["series"], tuple(change["identity"])) in uncovered:
                change["needs_review"] = True
        if template.fact_keys:
            facts = await resolve_facts(db, market, template, context)
            fact_patches, report["fact_gaps"] = plan_fact_tokens(template, facts)
            report["facts"] = facts
            patches.extend(fact_patches)
        incomplete = bool(uncovered or report["fact_gaps"])
        if uncovered and not patches:
            return {**report, "reason": "有配置或型号变更缺少可核验映射，或同市场快照证据不一致"}, None

        restoring = []
        candidate = await _previous_check(db, version, market, template, artifact_only=True)
        if candidate:
            report["previous_candidate_key"] = candidate.version_key
        if origin != "facts" and not report["changes"] and template.fact_keys:
            prior_check = await _previous_check(db, version, market, template, artifact_only=False)
            if (prior_check and prior_check.report.get("baseline_changes") == report["baseline_changes"]
                    and fact_state(prior_check.report.get("facts", {})) == fact_state(report["facts"])):
                return {**report, "status": "checked", "reason": "已检查，本版本无需更新 Cart 文稿"}, None
        if not patches:
            if incomplete:
                return {**report, "reason": "Cart 事实或适用关系待核"}, None
            if candidate is None or candidate.artifact_sha256 == template.sha256:
                return {**report, "status": "checked", "reason": "配置与已绑定快照一致，沿用原模板"}, None
            restoring = [
                {**change, "before": change["after"], "after": change["before"]}
                for change in candidate.report["updates"]
            ]
    except SNAPSHOT_ERRORS as error:
        logger.warning("Cart check for version %s could not read snapshot evidence: %s", version.id, error)
        return {**report, "reason": "快照或机型身份无法安全核验"}, None

    try:
        original = await _template_bytes(db, market, template)
        content, patches, report["layout_gaps"] = await asyncio.to_thread(build_candidate, original, patches)
    except (CitationSourceError, BadZipFile, XMLSyntaxError, ValueError) as error:
        return {**report, "reason": str(error)}, None
    if content is None:
        return {**report, "reason": "受影响条目的版面定位或文字空间待核"}, None
    incomplete = incomplete or bool(report["layout_gaps"])
    report["updates"] = [
        {"before": rule.original, "after": replacement, "pages": [page for page, _ in rule.targets]}
        for rule, replacement in patches
    ] + restoring
    report["affected_pages"] = _affected_pages(report, content, candidate)
    if incomplete:
        return {**report, "status": "partial", "reason": "已生成已核实条目的候选，部分条目待核"}, content
    return {**report, "status": "generated", "reason": "已生成供核对的 PPT 候选"}, content


def _affected_pages(report, content, prior):
    if prior and prior.artifact_sha256 == sha256(content).hexdigest():
        return []
    def updates(value):
        return {(item["before"], item["after"], tuple(item["pages"])) for item in value.get("updates", [])}
    old = updates(prior.report) if prior else set()
    return sorted({page for _, _, pages in updates(report) ^ old for page in pages})


async def get_cart_check(db, version):
    rows = await cart_check_history(db, version, 1)
    return rows[0] if rows else None


async def cart_check_history(db, version, limit):
    return (await db.scalars(select(CartReleaseCheck).where(
        CartReleaseCheck.version_id == version.id,
        CartReleaseCheck.report["version"]["key"].as_string() == version_key(version),
    ).order_by(CartReleaseCheck.checked_at.desc(), CartReleaseCheck.version_key).limit(limit))).all()


async def reserve_cart_backfill(db):
    # Acquire SQLite's write lock before reading the versions to backfill.
    await db.execute(update(CartReleaseCheck).where(
        CartReleaseCheck.version_key == "",
    ).values(version_key=""))


async def save_cart_check(db, version, origin, *, rollback_target=None):
    """Persist the check and any PPT in the same transaction as its snapshot."""
    await db.flush()
    key = version_key(version)
    existing = await db.get(CartReleaseCheck, key, populate_existing=True)
    if origin == "backfill":
        latest = await get_cart_check(db, version)
        if latest is not None and latest.version_key != key:
            return latest
    if existing is not None and (existing.artifact_sha256 or existing.report["status"] != "pending"):
        return existing
    report, content = await _assess(db, version, existing.report["origin"] if existing else origin,
                                    existing.report if existing else None, rollback_target)
    digest = await _store_artifact(db, content)
    if existing is None:
        existing = CartReleaseCheck(version_key=key, version_id=version.id, report=report, artifact_sha256=digest)
        db.add(existing)
    else:
        existing.report = report
        existing.artifact_sha256 = digest
        existing.checked_at = utcnow()
    await db.flush()
    await link_fact_impacts(db, existing)
    return existing


async def _store_artifact(db, content):
    if content is None:
        return None
    digest = sha256(content).hexdigest()
    await db.execute(insert(CartReleaseArtifact).values(sha256=digest, data=content)
                     .on_conflict_do_nothing(index_elements=["sha256"]))
    return digest


async def _last_candidate(db, check):
    if check is None or check.artifact_sha256:
        return check
    key = check.report.get("previous_candidate_key")
    return await db.get(CartReleaseCheck, key) if key else None


async def _same_fact_candidate(db, latest, report, digest):
    if (fact_state(latest.report.get("facts", {})) != fact_state(report["facts"])
            or latest.report.get("baseline_changes") != report["baseline_changes"]):
        return False
    if latest.report["status"] == "checked" and digest:
        previous = await _last_candidate(db, latest)
        return previous is not None and previous.artifact_sha256 == digest
    return (latest.artifact_sha256, latest.report["status"], latest.report.get("reason")) == (
        digest, report["status"], report["reason"],
    )


async def refresh_cart_for_facts(db, fact_keys=None, *, version_id=None):
    """Refresh the affected current regional candidates in the caller's transaction."""
    rules, rules_error = await _review_rules()
    if rules_error:
        return []
    await db.flush()
    fact_keys = None if fact_keys is None else frozenset(fact_keys)
    results = []
    for market, template in rules.templates.items():
        if not template.fact_keys or (fact_keys is not None and template.fact_keys.isdisjoint(fact_keys)):
            continue
        names = [anchor.series for anchor in template.anchors if not excluded_series(anchor.series)]
        version = await db.scalar(select(ConfigVersion).join(ProductSeries).where(
            ProductSeries.name.in_(names)
        ).order_by(ConfigVersion.id.desc()).limit(1))
        if version is None or (version_id is not None and version.id != version_id):
            continue
        latest = await get_cart_check(db, version)
        report, content = await _assess(db, version, "facts", None, None, rules_result=(rules, rules_error))
        digest = sha256(content).hexdigest() if content is not None else None
        if latest is not None and await _same_fact_candidate(db, latest, report, digest):
            await link_fact_impacts(db, latest)
            continue
        prior = await _last_candidate(db, latest)
        if prior is not None:
            report["previous_candidate_key"] = prior.version_key
            if content is not None:
                report["affected_pages"] = _affected_pages(report, content, prior)
        identity = [version_key(version), latest.version_key if latest else None, report]
        key = sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        result = CartReleaseCheck(version_key=key, version_id=version.id, report=report,
                                  artifact_sha256=await _store_artifact(db, content))
        db.add(result)
        await db.flush()
        await link_fact_impacts(db, result)
        results.append(check_payload(result))
    return results


def check_payload(check):
    return {
        **check.report,
        "archive_key": check.version_key,
        "artifact_sha256": check.artifact_sha256,
        "checked_at": check.checked_at.isoformat(),
    }
