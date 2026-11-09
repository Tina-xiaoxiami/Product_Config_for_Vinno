"""Consume the public facts used by knowledge answers and attach Cart impacts."""

from importlib import import_module
import re


PROVIDER = "app.services.knowledge_cart_facts"


def _provider():
    try:
        return import_module(PROVIDER)
    except ModuleNotFoundError as error:
        if error.name != PROVIDER:
            raise
        return None


async def resolve_facts(db, market, template, context):
    provider = _provider()
    config_versions = {series: refs["target"] for series, refs in context.items() if refs["target"]}
    keys = sorted(template.fact_keys)
    facts = {}
    for key in keys:
        result = await provider.resolve_cart_fact(db, key, market, config_versions) if provider else None
        facts[key] = result or {
            "key": key, "status": "missing",
            "issue": {"detail": "公共事实尚未登记，缺少可追溯的参数或物料来源"},
        }
    return facts


def _has_versioned_source(fact):
    for source in fact.get("sources", []):
        version = source.get("version_id") or source.get("sha256")
        if (isinstance(version, str) and re.fullmatch(r"[0-9a-f]{64}", version)
                and (source.get("locator") or source.get("reference"))):
            return True
    return False


def _render_value(fact):
    if fact["status"] != "confirmed" or not _has_versioned_source(fact):
        return None
    # A measured value with conditions may only use the provider's full display.
    value = fact.get("display_value") if fact.get("conditions") else fact.get("value")
    return value if isinstance(value, (str, int, float)) and not isinstance(value, bool) else None


def plan_fact_tokens(template, facts):
    patches, gaps = [], []
    for rule in template.facts:
        pages = sorted({page for page, _ in rule.targets})
        values = {}
        for alias, key in rule.facts.items():
            fact = facts[key]
            value = _render_value(fact)
            if value is not None:
                values[alias] = value
            else:
                issue = fact.get("issue") or {}
                gaps.append({"key": key, "pages": pages, "root_key": issue.get("root_key"),
                             "kind": issue.get("kind"), "detail": issue.get("detail") or "缺少可追溯的事实值或原件依据"})
        if len(values) == len(rule.facts):
            replacement = rule.replacement.format_map(values)
            if replacement != rule.original:
                patches.append((rule, replacement))
    for key, pages in template.watch_facts.items():
        fact = facts[key]
        if fact["status"] != "confirmed" or not _has_versioned_source(fact):
            issue = fact.get("issue") or {}
            gaps.append({"key": key, "pages": sorted(set(pages)), "root_key": issue.get("root_key"),
                         "kind": issue.get("kind"), "detail": issue.get("detail") or "缺少适用的原件依据"})
    return patches, gaps


def fact_state(facts):
    """A config revision alone does not change the rendered fact."""
    return {key: {field: fact.get(field) for field in ("status", "value", "display_value", "conditions", "sources", "issue")}
            for key, fact in facts.items()}


async def link_fact_impacts(db, check):
    roots = {}
    for gap in check.report.get("fact_gaps", []):
        if gap["root_key"]:
            roots.setdefault(gap["root_key"], set()).update(gap["pages"])
    if not roots:
        return
    provider = _provider()
    if provider is None:
        return
    for root, pages in sorted(roots.items()):
        await provider.link_cart_fact_impact(db, root, {
            "consumer_key": f"cart:{check.report['market']}", "market": check.report["market"],
            "pages": sorted(pages), "archive_key": check.version_key,
        })
