import { probeRuleKey } from './probeWorkspace.js'
import { parseProbeExcludes } from './probeSupport.js'

export function newProbeMaterialRows(probeKey, catalog) {
  const [probeId, variantId] = probeKey.split(':').map(Number)
  const probe = catalog.probes.find(p => p.id === probeId)
  if (!probe || (variantId && !catalog.variants.some(v => v.id === variantId && v.probe_model_id === probeId))) throw new Error('探头已变化，请重新选择')
  return catalog.features.map(feature => {
    const template = catalog.templates?.find(t => t.category_id === probe.category_id && t.feature_id === feature.id)
    const applications = parseProbeExcludes(template?.default_excludes)
    return {probe_model_id:probeId, variant_id:variantId||null, feature_id:feature.id,
      defined_status:template?.default_support === 'supported' && applications.excludes.length ? 'conditional' : template?.default_support||(probe.category_id == null ? 'pending' : 'unsupported'), defined_excludes:applications.excludes, defined_tender:applications.tender,
      current_status:'pending', current_excludes:[], current_tender:[], priority:null, notes:''}
  })
}

export function probeMaterialExists(rows, candidate, catalog) {
  const pair = row => `${row.probe_model_id}:${row.variant_id || 0}`
  const identities = new Set([pair(candidate)])
  const variant = catalog.variants.find(v => v.id === candidate.variant_id)
  for (const material of catalog.config_materials || []) {
    const source = `${-material.config_item_id}:${-material.config_item_id}`
    const target = pair(material)
    if (identities.has(source) || identities.has(target) ||
      (candidate.probe_model_id === material.probe_model_id && variant?.ipn && variant.ipn === material.ipn)) {
      identities.add(source); identities.add(target)
    }
  }
  return rows.some(row => identities.has(pair(row)))
}

export function buildProbeMatrixRows(document, catalog, results) {
  const probes = new Map(catalog.probes.map(p => [p.id, p]))
  const variants = new Map(catalog.variants.map(v => [v.id, v]))
  const categories = new Map((catalog.categories || []).map(c => [c.id, c]))
  const calculated = results && new Map(results.map(r => [r.key, r]))
  const rows = new Map()
  for (const record of document.rows) {
    const probe = probes.get(record.probe_model_id) || {}
    const variant = variants.get(record.variant_id)
    const physicalKey = JSON.stringify([record.probe_model_id, ...(variant
      ? [variant.ipn || '', variant.internal_model || '', variant.notes || ''] : ['missing', record.variant_id || 0])])
    if (!rows.has(physicalKey)) rows.set(physicalKey, {
      key: physicalKey, probe_model_id: record.probe_model_id, variant_ids: [],
      category_id: probe.category_id, category_name: categories.get(probe.category_id)?.name || '未匹配类别',
      probe_name: probe.name || `探头 #${record.probe_model_id}`, ipn: variant?.ipn || '',
      internal_model: variant?.internal_model || '', material_notes: variant?.notes || '', cells: {},
    })
    const row = rows.get(physicalKey)
    if (!row.variant_ids.includes(record.variant_id)) row.variant_ids.push(record.variant_id)
    const key = probeRuleKey(record)
    const value = { ...record, ...(calculated?.get(key) || {}), key }
    const cell = row.cells[record.feature_id]
    if (!cell) row.cells[record.feature_id] = { ...value, keys: [key], records: [value] }
    else {
      cell.keys.push(key); cell.records.push(value)
      cell.has_override ||= value.has_override
      for (const side of ['defined', 'current']) {
        if (['status', 'excludes', 'tender'].some(field => JSON.stringify(cell[`${side}_${field}`] ?? []) !== JSON.stringify(value[`${side}_${field}`] ?? []))) cell[`${side}_status`] = 'mixed'
      }
    }
  }
  return [...rows.values()]
}

// Keep user column order; Element Plus applies fixed at the outer group level.
export function matrixColumnSegments(layout, features, groups, showRegular = true, showPOC = true) {
  const featureMap = new Map(features.map(f => [f.id, f]))
  const names = new Map(groups.map(g => [g.id, g.name]))
  const segments = []
  for (const column of layout.filter(c => c.visible)) {
    if (!column.key.startsWith('feature:')) {
      if ((column.key === 'regular' && !showRegular) || (column.key === 'poc' && !showPOC)) continue
      segments.push({key:column.key, column})
      continue
    }
    const feature = featureMap.get(Number(column.key.slice(8)))
    if (!feature) continue
    const previous = segments.at(-1)
    if (previous?.features && previous.id === feature.group_id && previous.fixed === column.fixed) previous.features.push(feature)
    else segments.push({key:column.key, id:feature.group_id, name:names.get(feature.group_id)||'其他功能', fixed:column.fixed, features:[feature]})
  }
  return segments
}
