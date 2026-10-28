const EDITABLE_FIELDS = [
  'software_version', 'product_series', 'release_date', 'change_type',
  'configuration_status', 'lifecycle_status', 'review_status', 'change_note'
]

export function releaseVersionPayload(form) {
  return Object.fromEntries(EDITABLE_FIELDS.map(field => [field, form[field]]))
}

export function releaseVersionChanged(form, baseline) {
  return baseline !== null && EDITABLE_FIELDS.some(field => form[field] !== baseline[field])
}
