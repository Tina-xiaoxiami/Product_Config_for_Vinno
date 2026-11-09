"""Scope Cart evidence to the models and materials the release owner maintains."""

import re


A_MODEL = re.compile(r"^(?:vinno[\s-]*)?a(?:\s*\d+(?:\b|(?=[a-z]))|[\s_-]*系列\b)", re.I)
A_SERIES = re.compile(r"^(?:vinno[\s-]*)?a(?:[\s_-]*(?:series\b|系列)|[\s_-]*\d+\b)", re.I)
A_CART = re.compile(r"^(?:vinno\s+)?a(?:[-\s]*(?:series|系列))?[-\s]*(?:cart\b|专用(?:台车|推车|配件))", re.I)


def excluded_series(name):
    return bool(A_SERIES.search(name.strip()))


def excluded_model(name):
    return bool(A_MODEL.search((name or "").strip()))


def excluded_material(item, rules, allowed_values, excluded_values):
    if item.get("v_code") in rules.excluded_codes or item.get("ipn") in rules.excluded_ipns:
        return True
    # A shared item stays in scope when any non-A model uses it.
    if allowed_values:
        return False
    return bool(excluded_values or any(
        A_CART.search(item.get(field) or "") for field in ("zh_desc", "en_desc", "rd_name")
    ))
