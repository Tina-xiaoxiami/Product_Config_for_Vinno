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
from app.services.cart_release_ppt import replace_tokens
from app.services.cart_release_rules import MARKET_FOLDERS, Rules, load_rules
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
    rules, _ = await _review_rules()
    return bool(changes(snapshot_view(before, rules), snapshot_view(after, rules), rules.market(series_name), rules))


async def _previous_candidate(db, version, market, template):
    version_time = CartReleaseCheck.report["version"]["created_at"].as_string()
    return await db.scalar(select(CartReleaseCheck).where(
        or_(CartReleaseCheck.version_id < version.id,
            and_(CartReleaseCheck.version_id == version.id, version_time < _version_time(version))),
        CartReleaseCheck.report["market"].as_string() == market,
        CartReleaseCheck.report["template"]["sha256"].as_string() == template.sha256,
        CartReleaseCheck.artifact_sha256.is_not(None),
    ).order_by(CartReleaseCheck.version_id.desc(), version_time.desc()).limit(1))


async def _assess(db, version, origin, previous_report, rollback_target):
    series = await db.get(ProductSeries, version.series_id)
    series_name = series.name if series else f"系列 #{version.series_id}"
    rules, rules_error = await _review_rules()
    market = rules.market(series_name)
    prior = await _prior_version(db, version)
    template = rules.templates.get(market)
    report = {
        "ruleset": rules.version, "status": "pending", "series": series_name, "market": market,
        "origin": origin, "version": source_ref(version), "previous": source_ref(prior),
        "rollback_target": previous_report.get("rollback_target") if previous_report else source_ref(rollback_target),
        "template": {
            "file": template.filename, "sha256": template.sha256, "review_notes": template.review_notes,
        } if template else None,
        "changes": [], "baseline_changes": [], "updates": [], "context": {}, "reason": None,
    }
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
        if not report["changes"]:
            return {**report, "status": "checked", "reason": "已检查，未发现影响 Cart 发货资料的变更"}, None
        if not template or series_name not in {anchor.series for anchor in template.anchors}:
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
        if uncovered:
            for change in report["baseline_changes"]:
                change["needs_review"] = (change["series"], tuple(change["identity"])) in uncovered
            return {**report, "reason": "有配置或型号变更缺少可核验映射，或同市场快照证据不一致"}, None
        restoring = []
        if not patches:
            candidate = await _previous_candidate(db, version, market, template)
            if candidate is None or candidate.artifact_sha256 == template.sha256:
                return {**report, "status": "checked", "reason": "配置与已绑定快照一致，沿用原模板"}, None
            restoring = [
                {**change, "before": change["after"], "after": change["before"]}
                for change in candidate.report["updates"]
            ]
    except SNAPSHOT_ERRORS as error:
        logger.warning("Cart check for version %s could not read snapshot evidence: %s", version.id, error)
        return {**report, "reason": "快照或机型身份无法安全核验"}, None

    report["updates"] = [
        {"before": rule.original, "after": replacement, "pages": [page for page, _ in rule.targets]}
        for rule, replacement in patches
    ] + restoring
    try:
        original = await _template_bytes(db, market, template)
        content = await asyncio.to_thread(replace_tokens, original, patches)
    except (CitationSourceError, BadZipFile, XMLSyntaxError, ValueError) as error:
        return {**report, "reason": str(error)}, None
    return {**report, "status": "generated", "reason": "已生成供核对的 PPT 候选"}, content


async def get_cart_check(db, version):
    return await db.get(CartReleaseCheck, version_key(version), populate_existing=True)


async def reserve_cart_backfill(db):
    # Acquire SQLite's write lock before reading the versions to backfill.
    await db.execute(update(CartReleaseCheck).where(
        CartReleaseCheck.version_key == "",
    ).values(version_key=""))


async def save_cart_check(db, version, origin, *, rollback_target=None):
    """Persist the check and any PPT in the same transaction as its snapshot."""
    await db.flush()
    key = version_key(version)
    existing = await get_cart_check(db, version)
    if existing is not None and existing.report["status"] != "pending":
        return existing
    report, content = await _assess(db, version, existing.report["origin"] if existing else origin,
                                    existing.report if existing else None, rollback_target)
    digest = None
    if content is not None:
        digest = sha256(content).hexdigest()
        await db.execute(insert(CartReleaseArtifact).values(sha256=digest, data=content)
                         .on_conflict_do_nothing(index_elements=["sha256"]))
    if existing is None:
        existing = CartReleaseCheck(version_key=key, version_id=version.id, report=report, artifact_sha256=digest)
        db.add(existing)
    else:
        existing.report = report
        existing.artifact_sha256 = digest
        existing.checked_at = utcnow()
    await db.flush()
    return existing


def check_payload(check):
    return {
        **check.report,
        "artifact_sha256": check.artifact_sha256,
        "checked_at": check.checked_at.isoformat(),
    }
