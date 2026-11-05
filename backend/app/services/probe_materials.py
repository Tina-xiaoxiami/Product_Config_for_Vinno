"""Read-only material identities from machine configuration, without editing probe masters."""
from app.services.registration_rules import normalize_business_name


def clean_name(value):
    return normalize_business_name(value).replace('【启用】', '').replace('【停用】', '').strip()


def extend_material_catalog(cat, items):
    probes = {p['id']: p for p in cat['probes']}
    by_name = {}
    by_ipn = {}
    for probe in probes.values():
        by_name.setdefault(clean_name(probe['name']).casefold(), []).append(probe)
    for variant in cat['variants']:
        if variant.get('ipn'):
            by_ipn.setdefault(normalize_business_name(variant['ipn']), []).append(variant)
    materials = []
    for item in items:
        ipn = normalize_business_name(item['ipn'])
        matches = by_ipn.get(ipn, []) if ipn else []
        physical = {(v['probe_model_id'], v['internal_model'], v.get('notes') or '') for v in matches}
        canonical = min(matches, key=lambda v: v['id']) if len(physical) == 1 else None
        named = {p['id']: p for field in ('en_desc', 'rd_name') for p in by_name.get(clean_name(item[field]).casefold(), [])}
        parent = probes[canonical['probe_model_id']] if canonical else next(iter(named.values())) if len(named) == 1 and not matches else None
        source_id = -item['id']
        # Stable source identities stay resolvable if a probe master is registered later.
        # They exist only in JSON catalogs/drafts, never as rows in probe master tables.
        source_probe = {'id': source_id, 'name': clean_name(item['rd_name']) or clean_name(item['en_desc']) or f"物料 {item['id']}",
                        'category_id': parent['category_id'] if parent else None,
                        'config_item_id': item['id'], 'selectable': canonical is None}
        source_variant = {'id': source_id, 'probe_model_id': source_id, 'ipn': ipn or None,
                          'internal_model': clean_name(item['rd_name']), 'notes': None, 'config_item_id': item['id']}
        cat['probes'].append(source_probe)
        cat['variants'].append(source_variant)
        materials.append({'config_item_id': item['id'],
                          'probe_model_id': canonical['probe_model_id'] if canonical else source_id,
                          'variant_id': canonical['id'] if canonical else source_id,
                          'name': source_probe['name'], 'ipn': ipn or '',
                          'category_pending': parent is None})
    cat['config_materials'] = materials
    return cat
