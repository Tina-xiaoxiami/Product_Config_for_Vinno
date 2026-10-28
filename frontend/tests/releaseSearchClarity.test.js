import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../../backend/tracker/static/app.js', import.meta.url), 'utf8')
function functions(names, context = {}) {
  const bodies = names.map(name => {
    const start = source.indexOf(`function ${name}(`)
    assert.ok(start >= 0, `Missing ${name}`)
    const next = source.slice(start + 1).search(/\n(?:async )?function /)
    return source.slice(start, next < 0 ? undefined : start + 1 + next)
  })
  return new Function(...Object.keys(context), `${bodies.join('\n')}; return {${names.join(',')}}`)(...Object.values(context))
}
const escapeHtml = text => String(text ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;')
const context = {
  escapeHtml, escapeAttribute: escapeHtml,
  highlightSearchText: escapeHtml,
  verificationLabel: value => value === 'approved' ? '已确认' : '未复核',
  searchEvidenceLabel: value => value === 'current_description' ? '当前功能说明 · 关联版本不代表当时支持' : '当时版本记录',
  searchComparisonButton: () => '<button data-compare>加入对照</button>',
}

test('compact release cards show the evidence once while retaining original-preview and comparison actions', () => {
  const { compactSearchCard } = functions(['compactSearchCard'], context)
  const text = '开启兼容模式后不支持后台导出，需等待导出完成。'
  const card = compactSearchCard({ source_type: 'release', source_label: '版本与功能', version: '1.51.90', title: text, matched_text: text, scope: 'ULTIMUS G2 · 1.51.90', verification: 'approved', locator: '中文记录' }, { query: '后台导出' }, '<button data-search-result-preview="release:change:1072">查看原文</button>', '', [])
  assert.equal(card.split(text).length - 1, 1)
  assert.match(card, /1\.51\.90/)
  assert.match(card, /data-search-result-preview="release:change:1072"/)
  assert.match(card, /加入对照/)
})

test('compact cards keep evidence limitations visible and escape source text', () => {
  const { compactSearchCard } = functions(['compactSearchCard'], context)
  const card = compactSearchCard({ source_type: 'release', source_label: '版本与功能', title: '<img src=x onerror=alert(1)>', scope: '未知范围', verification: 'pending_review', evidence_kind: 'current_description', match_kind: 'related', is_stale: true }, { query: '导出' }, '<button data-search-result-refresh>更新资料索引</button>', '', [])
  assert.doesNotMatch(card, /<img/)
  assert.match(card, /&lt;img/)
  assert.match(card, /关联线索/)
  assert.match(card, /关联版本不代表当时支持/)
  assert.match(card, /未复核/)
  assert.match(card, /data-search-result-refresh/)
})

test('the answer preserves each project earliest record and the distinction from first support', () => {
  const { compactSearchAnswer } = functions(['compactSearchAnswer'], context)
  const answer = compactSearchAnswer({ query: '导出', earliest_records: [
    { version: '1.51.36', scope: 'ULTIMUS G2 · 1.51.36', preview_id: 'release:change:603', locator: '中文记录' },
    { version: '1.14.80', scope: 'VINNO 10 · 1.14.80', preview_id: 'release:change:9', locator: '中文记录' },
  ] })
  assert.match(answer, /版本库最早记载/)
  assert.match(answer, /1\.51\.36/)
  assert.match(answer, /1\.14\.80/)
  assert.match(answer, /不代表首次支持/)
  assert.match(answer, /历史补充资料/)
  assert.match(answer, /release:change:603/)
  assert.equal(compactSearchAnswer({ earliest_records: [] }), '')
})

test('collapsing the filter panel preserves selected values and announces its expanded state', () => {
  const panel = { hidden: true }
  const button = { textContent: '', setAttribute(name, value) { this[name] = value } }
  const selectedVersion = { value: '1.51.20' }
  const document = { querySelector: key => ({ '#search-filters-panel': panel, '#search-filters-toggle': button, '#release-search-versions': selectedVersion })[key] }
  const { setSearchFiltersVisible } = functions(['setSearchFiltersVisible'], { document })
  setSearchFiltersVisible(true)
  assert.equal(panel.hidden, false)
  assert.equal(button['aria-expanded'], 'true')
  setSearchFiltersVisible(false)
  assert.equal(panel.hidden, true)
  assert.equal(button['aria-expanded'], 'false')
  assert.equal(selectedVersion.value, '1.51.20')
})

test('documents with no separate excerpt do not repeat their title and retain the format', () => {
  const { compactSearchCard } = functions(['compactSearchCard'], { ...context, fileFormatLabel: value => value.toUpperCase() })
  const card = compactSearchCard({ source_type: 'controlled', source_label: '受控资料', title: '技术发布记录', file_format: 'pdf', version: '1.50.0', verification: 'unverified' }, { query: '发布' }, '', '', [])
  assert.equal(card.split('技术发布记录').length - 1, 1)
  assert.match(card, /PDF/)
  assert.match(card, /版本 1\.50\.0/)
})

test('search and release views share the same project control with its current value', () => {
  const control = { value: 'VINNO 10', parentElement: null }
  const query = { prepend(node) { node.parentElement = this } }
  const header = { prepend(node) { node.parentElement = this } }
  control.parentElement = header
  const toggles = []
  const document = {
    querySelector: key => ({ '#project-context-actions': control, '.search-primary-row': query, '.topbar-actions': header })[key],
    body: { classList: { toggle: (...args) => toggles.push(args) } },
  }
  const { positionSearchProject } = functions(['positionSearchProject'], { document, workbenchConfig: { embedded: true } })
  positionSearchProject('search')
  assert.equal(control.parentElement, query)
  positionSearchProject('releases')
  assert.equal(control.parentElement, header)
  assert.equal(control.value, 'VINNO 10')
  assert.deepEqual(toggles, [['search-focused', true], ['search-focused', false]])
})


test('source restrictions remain visible as one expandable notice with every reason retained', () => {
  const { compactSearchSourceNotice } = functions(['compactSearchSourceNotice'], { ...context, SEARCH_SOURCE_LABELS: { config: '正式配置', qa: '正式问答' } })
  const html = compactSearchSourceNotice({ source_errors: { config: '不支持版本范围', qa: '<script>bad</script>' } })
  assert.equal((html.match(/<summary>/g) || []).length, 1)
  assert.match(html, /2 类来源受限，结果可能不完整/)
  assert.match(html, /正式配置/)
  assert.match(html, /不支持版本范围/)
  assert.match(html, /正式问答/)
  assert.doesNotMatch(html, /<script>/)
  assert.equal(compactSearchSourceNotice({}), '')
})
