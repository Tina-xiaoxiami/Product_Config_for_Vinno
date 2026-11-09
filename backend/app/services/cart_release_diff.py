"""Cart evidence from the same item identities and value semantics as version comparison."""

from dataclasses import dataclass
import re

from app.services.cart_release_rules import CART_TEXT
from app.services.config_history import (
    build_snapshot_item_comparison_index, build_snapshot_semantic_value_index,
)
from app.services.version_comparison import NAME_FIELDS


SHIPPING_FIELDS = ("final_config", "selection_config")
METADATA_FIELDS = ("category", *NAME_FIELDS)


@dataclass
class SnapshotView:
    models: dict
    rows: dict
    relevant: set


def snapshot_view(snapshot, rules):
    items = build_snapshot_item_comparison_index(snapshot)
    semantic = build_snapshot_semantic_value_index(snapshot)
    models = {
        str(model["id"]): model.get("_comparison_name", model.get("name")) or f"机型 #{model['id']}"
        for model in snapshot.get("models", [])
    }
    rows = {}
    relevant = set()
    known_codes, known_ipns = rules.known_codes, rules.known_ipns
    for identity, item in items.items():
        values = {
            mid: {field: value.get(field) for field in SHIPPING_FIELDS}
            for mid, value in semantic.get(identity, {}).get("values", {}).items()
            if any(value.get(field) is not None for field in SHIPPING_FIELDS)
        }
        metadata = {field: str(item.get(field) or "").strip() or None for field in METADATA_FIELDS}
        rows[identity] = {**metadata, "values": values}
        if (metadata["v_code"] in known_codes or metadata["ipn"] in known_ipns
                or CART_TEXT.search(" ".join(value for value in metadata.values() if value))):
            relevant.add(identity)
    return SnapshotView(models, rows, relevant)


def _pages(row, market, rules):
    code, ipn = row["v_code"], row["ipn"]
    if code in rules.common_pages:
        return rules.common_pages[code]
    if code in rules.market_pages.get(market, {}):
        return rules.market_pages[market][code]
    return rules.ipn_pages.get(ipn, ())


def _public_row(row, models):
    if row is None:
        return None
    return {
        **row,
        "values": [
            {"id": mid, "model": models.get(mid, f"机型 #{mid}"), **value}
            for mid, value in sorted(row["values"].items())
        ],
    }


def changes(before, after, market, rules, *, include_models=True):
    result = []
    for identity in sorted(before.relevant | after.relevant, key=str):
        old, new = before.rows.get(identity), after.rows.get(identity)
        if old == new:
            continue
        old_values = old["values"] if old else {}
        new_values = new["values"] if new else {}
        models = before.models | after.models
        affected = old_values.keys() | new_values.keys()
        if old and new and all(old[field] == new[field] for field in METADATA_FIELDS):
            affected = {mid for mid in affected if old_values.get(mid) != new_values.get(mid)}
        pages = set()
        for row in (old, new):
            if row:
                pages.update(_pages(row, market, rules))
        result.append({
            "identity": list(identity),
            "before": _public_row(old, before.models),
            "after": _public_row(new, after.models),
            "models": sorted({models.get(mid, f"机型 #{mid}") for mid in affected}),
            "pages": sorted(pages),
        })
    if include_models and market and before.models != after.models:
        for mid in sorted(before.models.keys() | after.models.keys()):
            old, new = before.models.get(mid), after.models.get(mid)
            if old != new:
                result.append({
                    "identity": ["model", mid], "before": old, "after": new,
                    "models": sorted({name for name in (old, new) if name}), "pages": [],
                })
    return result


def plan_tokens(template, evidence, known_codes):
    """Cover every net change, or leave the market draft pending with its evidence."""
    uncovered = {(series, tuple(change["identity"]))
                 for series, (_, _, delta) in evidence.items() for change in delta}
    patches = []
    for rule in template.rules:
        matches = [_rule_match(rule, *evidence[series][:2], known_codes) for series in rule.series]
        if any(match is None for match in matches):
            continue
        targets = {match[0] for match in matches}
        if len(targets) != 1:
            continue
        replacement = targets.pop()
        if replacement == rule.original:
            continue
        covered = {(series, identity) for series, match in zip(rule.series, matches)
                   for identity in match[1]}
        if not covered & uncovered:
            continue
        uncovered -= covered
        patches.append((rule, replacement))
    return patches, uncovered


def _rule_match(rule, before, after, known_codes):
    # Use the unchanged half of the verified mapping to pair an IPN addition/deletion.
    stable = "v_code" if rule.field == "ipn" else "ipn"
    key = rule.code if stable == "v_code" else rule.ipn
    old = [(identity, row) for identity, row in before.rows.items() if row[stable] == key]
    new = [(identity, row) for identity, row in after.rows.items() if row[stable] == key]
    if len(old) != 1 or len(new) != 1:
        return None
    old_id, old_row = old[0]
    new_id, new_row = new[0]
    if old_id != new_id and (new_id in before.rows or old_id in after.rows):
        return None
    if old_row["values"].keys() - before.models.keys() or new_row["values"].keys() - after.models.keys():
        return None
    replacement = new_row[rule.field]
    if old_row[rule.field] != rule.original or not replacement or not old_row["values"]:
        return None
    if rule.field == "v_code" and (
        replacement in known_codes and replacement != rule.original
        or sum(row["v_code"] == replacement for row in after.rows.values()) != 1
    ):
        return None
    # Preserve both text width and the ordering-code format of the verified label.
    pattern = "".join("[0-9]" if char.isdigit() else re.escape(char) for char in rule.original)
    if not re.fullmatch(pattern, replacement):
        return None
    if {**old_row, rule.field: replacement} != new_row:
        return None
    return replacement, {old_id, new_id}
