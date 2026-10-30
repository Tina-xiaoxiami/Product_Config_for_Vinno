const state = { activeView: null, strategyProblem: null, registrationProblem: null, projects: [], activeProjectId: null, releases: [], activeReleaseVersion: null, activeCandidateVersion: null, activeCandidateCategory: 'all', terms: [], candidates: [], rejectedCandidates: [], features: [], categories: [], editingFeature: null, reviewIssues: [], suspectedPairs: [], selectedCandidateIds: new Set(), configurationTables: [], releaseArchive: null, effectiveConfiguration: null, archiveType: 'all', archiveMarket: 'domestic', comparisonKey: null, projectHealth: null, importBatches: [], candidateRecommendations: {}, candidateOverrides: {}, recommendationKey: '', searchPage: 1, searchSourceGroup: 'release_note', searchReleaseCategory: 'all', searchWhitepaperModel: '', searchWhitepaperSelectionMode: 'auto', searchRequest: 0, searchPreviewRequest: 0, searchTimer: 0 };
const scenarioState = { task: 'feature', domain: 'feature', drafts: {feature: '', probe: ''}, featureTask: 'feature', code: '', series: '', model: '', document: '', section: '', request: 0, result: null };
const workbenchConfig = window.__WORKBENCH__ || {};
function workbenchUrl(path) {
  if (!path || /^(?:[a-z]+:)?\/\//i.test(path)) return path;
  const base = String(workbenchConfig.basePath || '').replace(/\/$/, '');
  return `${base}${path.startsWith('/') ? path : `/${path}`}`;
}
function integratedMode() { return Boolean(workbenchConfig.integrated); }
const savedSearchStorageKey = 'featureTracker.savedSearches.v2';
// 批量动作一次影响多少条才需要二次确认：小批次直接提交，避免每次都被弹窗打断。
const BULK_ACTION_CONFIRM_THRESHOLD = 20;
const labels = { home: '首页', search: '全局搜索', model: '机型工作页', features: '功能库', terms: '术语词典', releases: '版本中心', compare: '版本对比', strategy: '正式策略查询', product_states: '产品状态', registration: '注册查询', materials: '受控资料', qa: '正式问答', items: '知识条目', probe_versions: '探头-版本', issues: '待处理问题', training: '培训资料', review: '导入与审核' };
const SEARCH_SOURCE_LABELS = { config: '正式配置', release: '版本与功能', controlled: '受控资料', training: '培训资料', term: '术语词典', registration: '注册范围', product_state: '产品状态', probe_version: '探头版本', knowledge: '知识条目', qa: '正式问答' };
const PROJECT_SCOPED_VIEWS = new Set(['home', 'search', 'review', 'releases', 'compare', 'features', 'terms']);
const GLOBAL_SCOPE_LABELS = {
  model: '机型资料 · 保留各来源适用范围',
  strategy: '全局配置数据 · 不随项目切换',
  product_states: '全局知识库 · 保留所选国家',
  registration: '全局注册资料 · 保留所选国家',
  materials: '全局受控资料 · 不随项目切换',
  qa: '全局正式问答 · 中国国内版试点',
  items: '全局知识库 · 不随项目切换',
  probe_versions: '全局知识库 · 探头版本',
  issues: '全局问题清单 · 不随项目切换',
  training: '全局资料目录 · 不随项目切换',
};
const categoryLabels = { function: '功能', image: '图像', bug: 'Bug', config: '配置', config_note: '配置/兼容性说明', probe: '探头', remark: '备注', unclassified: '待确认', source: 'Release Note 原文' };
const releaseTableTypeLabels = { configuration_matrix: '配置矩阵', support_scope: '支持范围', material_change: '物料变更', ui_comparison: '界面对照', image_comparison: '图像对照', effective_configuration: '截至本版本配置' };
const marketLabels = { domestic: '国内配置', overseas: '海外配置', unknown: '未识别市场' };
let featureMatchTimer;
let featureMatchRequest = 0;

async function api(path, options = {}) {
  const response = await fetch(workbenchUrl(path), { headers: { 'Content-Type': 'application/json' }, ...options });
  const payload = await response.json();
  if (!response.ok || !payload.success) {
    // 带上 code 与 HTTP 状态：页面要区分「来源不可用(503)」和「范围不支持(400)」。
    const error = new Error(payload.error?.message || '请求失败');
    error.code = payload.error?.code || '';
    error.status = response.status;
    throw error;
  }
  return payload.data;
}

function projectPath(path) {
  if (!state.activeProjectId) return path;
  return `${path}${path.includes('?') ? '&' : '?'}project_id=${encodeURIComponent(state.activeProjectId)}`;
}

function activeProject() {
  return state.projects.find(project => Number(project.id) === Number(state.activeProjectId));
}

function updateViewScope(view) {
  const scope = document.querySelector('#view-scope');
  const projectActions = document.querySelector('#project-context-actions');
  const searchToggle = document.querySelector('#search-toggle');
  if (!scope || !projectActions) return;
  const projectScoped = PROJECT_SCOPED_VIEWS.has(view);
  projectActions.hidden = !projectScoped;
  if (searchToggle) searchToggle.hidden = false;
  scope.classList.toggle('global', !projectScoped);
  scope.textContent = projectScoped
    ? `当前项目 · ${activeProject()?.name || '正在载入'}`
    : (GLOBAL_SCOPE_LABELS[view] || '全局工作台');
}

function formatDateTime(value) {
  const parsed = new Date(value);
  if (!value || Number.isNaN(parsed.getTime())) return value || '未记录';
  const pad = part => String(part).padStart(2, '0');
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

function renderProjectList() {
  const container = document.querySelector('#project-list');
  if (!container) return;
  container.innerHTML = state.projects.map(project => `<article class="project-list-item ${Number(project.id) === Number(state.activeProjectId) ? 'active' : ''}"><div><strong>${escapeHtml(project.name)}</strong><span>${escapeHtml(project.code)} · ${project.release_count} 个版本 · ${project.review_count} 条待审核</span>${project.sources.length ? project.sources.map(source => `<small title="${escapeAttribute(source.path)}">${escapeHtml(source.path)}</small>`).join('') : '<small>尚未绑定 Release Note 文件夹</small>'}</div><button type="button" class="ghost-button" data-project-preview="${project.id}">扫描预览</button></article>`).join('');
}

async function loadProjects() {
  state.projects = await api('/api/v1/projects');
  const remembered = Number(localStorage.getItem('featureTracker.activeProject'));
  const selected = state.projects.find(project => Number(project.id) === remembered)
    || state.projects.find(project => project.is_default)
    || state.projects[0];
  state.activeProjectId = selected?.id || null;
  const switcher = document.querySelector('#project-switcher');
  switcher.innerHTML = state.projects.map(project => `<option value="${project.id}">${escapeHtml(project.name)}</option>`).join('');
  switcher.value = state.activeProjectId || '';
  renderProjectList();
  updateViewScope(state.activeView);
}

async function switchProject(projectId) {
  if (!state.projects.some(project => Number(project.id) === Number(projectId))) return;
  state.activeProjectId = Number(projectId);
  scenarioState.request++; scenarioState.code = ''; scenarioState.series = ''; scenarioState.model = ''; scenarioState.document = ''; scenarioState.section = '';
  document.querySelector('#scenario-result').innerHTML = '';
  document.querySelector('#scenario-model').innerHTML = '<option value="">自动选择</option>';
  state.reviewStage = 'overview';
  state.candidates = [];
  state.importBatches = [];
  renderReviewOverview();
  state.searchPage = 1;
  localStorage.setItem('featureTracker.activeProject', String(state.activeProjectId));
  document.querySelector('#project-switcher').value = String(state.activeProjectId);
  state.activeReleaseVersion = null;
  state.activeCandidateVersion = null;
  state.activeCandidateCategory = 'all';
  state.selectedCandidateIds = new Set();
  state.comparisonKey = null;
  renderProjectList();
  updateViewScope(state.activeView);
  await refreshAll({ includeExperience: true });
  if (state.activeView === 'search' && document.querySelector('#advanced-search-wrap').open && document.querySelector('#release-search').value.trim()) {
    await searchUnified();
  }
  showNotice(`已切换到 ${activeProject()?.name || '所选项目'}。`);
}

async function previewProject(projectId) {
  const container = document.querySelector('#project-preview');
  container.className = 'project-preview empty-state compact';
  container.textContent = '正在只读扫描文件夹…';
  const preview = await api(`/api/v1/projects/${projectId}/scan-preview`);
  container.className = 'project-preview';
  const importAction = preview.ready_pairs
    ? `<div class="project-preview-actions"><span>${preview.needs_review ? `${preview.needs_review} 个问题版本会保留在预览中，不会导入。` : '所有版本均已通过文件配对检查。'}</span><button type="button" class="primary-button" data-project-import="${projectId}">导入/更新 ${preview.ready_pairs} 个完整版本</button></div>`
    : '<p class="project-preview-blocked">没有可导入的完整中英文版本，请先补齐或整理文件。</p>';
  container.innerHTML = `<div class="project-preview-summary"><strong>扫描预览</strong><span>发现 ${preview.versions_found} 个版本 · 完整 ${preview.ready_pairs} · 需选择 ${preview.needs_review}</span></div>${preview.versions.length ? `<div class="project-preview-list">${preview.versions.map(version => `<article class="${version.status === 'ready' ? '' : 'needs-review'}"><strong>${escapeHtml(version.version)}</strong><span>中文：${escapeHtml(version.chinese_file || '未识别')}</span><span>英文：${escapeHtml(version.english_file || '未识别')}</span>${[...version.issues, ...version.warnings].map(issue => `<small>${escapeHtml(issue)}</small>`).join('')}</article>`).join('')}</div>${importAction}` : '<p>没有找到符合版本号目录和最终版规则的文件。</p>'}`;
}

async function importPreviewedProject(projectId, button) {
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = '正在导入完整版本…';
  try {
    const result = await api('/api/v1/import-batches/scan', {
      method: 'POST',
      body: JSON.stringify({ project_id: Number(projectId), ready_only: true }),
    });
    localStorage.setItem('featureTracker.activeProject', String(projectId));
    await loadProjects();
    await switchProject(projectId);
    document.querySelector('#project-dialog').close();
    showNotice(`已导入/更新 ${result.ready_pairs} 个完整版本；${result.needs_review} 个问题版本未导入。${scanWarningText(result)}`);
  } catch (error) {
    button.disabled = false;
    button.textContent = originalLabel;
    throw error;
  }
}

async function loadProjectHealth() {
  if (!state.activeProjectId) return;
  state.projectHealth = await api(`/api/v1/projects/${state.activeProjectId}/health`);
  const health = state.projectHealth;
  const container = document.querySelector('#project-health-panel');
  const attention = health.status === 'attention';
  container.className = `project-health-panel ${attention ? 'attention' : 'healthy'}`;
  const sourceIssueSummary = health.source_issues.length
    ? `${health.source_issues.slice(0, 2).map(item => `${item.version}：${[...item.issues, ...item.warnings].join('、')}`).join('；')}${health.source_issues.length > 2 ? `；另 ${health.source_issues.length - 2} 个` : ''}`
    : '中英文最终版配对正常';
  // 一行说清"项目资料现在什么状态"，不再放评分大数字（它既不是任务也读不懂）
  container.innerHTML = `<div class="health-facts"><strong>${attention ? '有需要优先处理的项目' : '项目资料状态良好'}</strong><span>${health.scan.ready_pairs} 个完整双语版本 · ${health.scan.needs_review} 个文件问题 · ${health.review_risk.high} 条高风险待审</span><small title="${escapeAttribute(sourceIssueSummary)}">${escapeHtml(sourceIssueSummary)}</small></div><div class="health-actions">${health.review_risk.high ? '<button type="button" class="primary-button" data-health-review>先处理高风险</button>' : ''}<button type="button" class="ghost-button" data-health-manage>查看数据源</button></div>`;
}

function scanWarningText(result = {}) {
  // 扫描结果里「已经发生、但无法自动处置」的计数。与 manage.py 的 scan_warnings
  // 同一口径：这些信号此前被 API 丢掉，操作者永远看不到，等于静默通过。
  const parts = [];
  if (result.review_decisions_unmatched) parts.push(`${result.review_decisions_unmatched} 条人工结论已对不上当前候选，需复核`);
  if (result.versions_skipped_empty) parts.push(`${result.versions_skipped_empty} 个版本目录没有可用的最终版文件，未建立版本行`);
  return parts.length ? `注意：${parts.join('；')}。` : '';
}

function renderImportBatches() {
  const container = document.querySelector('#import-batch-list');
  if (!container) return;
  container.innerHTML = state.importBatches.length
    ? state.importBatches.map(batch => {
      const statusLabels = { completed: '已完成', undone: '已撤销', failed: '失败', running: '处理中' };
      const stats = batch.stats || {};
      const safeNote = batch.undoable ? '未经人工处理，可安全撤销' : batch.status === 'completed' ? '更新了已有版本或已进入人工流程' : statusLabels[batch.status];
      // 警告常驻在批次记录里：showNotice 4 秒后自动消失，不适合承载"需人工复核"。
      const warning = scanWarningText(stats);
      return `<article><div><strong>${escapeHtml(batch.versions.join('、') || '未产生版本')}</strong><span class="pill ${batch.status === 'failed' ? 'warning' : ''}">${escapeHtml(statusLabels[batch.status] || batch.status)}</span></div><span>发现 ${stats.versions_found || 0} 个版本 · 新增 ${stats.candidates_created || 0} 条候选</span><small>${escapeHtml(safeNote)}</small>${warning ? `<small class="batch-warning">${escapeHtml(warning)}</small>` : ''}${batch.undoable ? `<button type="button" class="text-button danger" data-undo-import-batch="${batch.id}">撤销本次导入</button>` : ''}</article>`;
    }).join('')
    : '<p class="empty-state compact">还没有可追溯的导入批次；下次扫描后将自动记录。</p>';
}

async function loadImportBatches() {
  if (!state.activeProjectId) return;
  const project = state.activeProjectId;
  const batches = await api(projectPath('/api/v1/import-batches'));
  if (project !== state.activeProjectId) return;
  state.importBatches = batches;
  renderImportBatches();
  renderReviewOverview();
}

async function undoImportBatch(batchId) {
  if (!window.confirm('确定撤销这次导入吗？本批次新建的版本、候选和结构化记录将被删除。')) return;
  const result = await api(`/api/v1/import-batches/${batchId}/undo`, { method: 'POST', body: JSON.stringify({}) });
  showNotice(`已撤销本次导入，移除 ${result.releases_removed} 个全新版本。`);
  await refreshAll({ includeExperience: true });
}

function escapeHtml(value = '') {
  const node = document.createElement('span'); node.textContent = value; return node.innerHTML;
}

function escapeAttribute(value = '') {
  return escapeHtml(value).replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

function highlightSearchText(value = '', query = '') {
  const text = String(value || '');
  const needle = String(query || '').trim();
  if (!needle) return escapeHtml(text);
  const literal = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const family = needle.match(/^(V(?:Aid|Aim))(?:\s*([+＋]|Plus))?$/i);
  const pattern = family ? `(?<![A-Za-z0-9])${family[1]}${family[2] ? '\\s*(?:[+＋]|Plus\\b)' : ''}(?![A-Za-z0-9+＋]|\\s*(?:[+＋]|Plus\\b))` : literal;
  let html = '', offset = 0;
  for (const match of text.matchAll(new RegExp(pattern, 'gi'))) {
    html += escapeHtml(text.slice(offset, match.index)) + `<mark>${escapeHtml(match[0])}</mark>`;
    offset = match.index + match[0].length;
  }
  return html + escapeHtml(text.slice(offset));
}

function toggleSearchComparison(current, candidate) {
  const same = item => item.preview_id === candidate.preview_id && item.locator === candidate.locator && item.version === candidate.version;
  if (current.some(same)) return current.filter(item => !same(item));
  if (current.length >= 4) throw new Error('最多对照 4 处原文，请先移除一项。');
  return [...current, candidate];
}

// Only selection metadata stays in this tab; opening/copying still rechecks the source.
function normalizeSearchComparison(items) {
  if (!Array.isArray(items)) return [];
  const fields = ['preview_id', 'locator', 'title', 'scope', 'version', 'query', 'originalQuery', 'evidence_kind', 'source_label'];
  const result = [];
  for (const item of items.slice(0, 20)) {
    if (!item || fields.some(key => item[key] !== undefined && (typeof item[key] !== 'string' || item[key].length > 2000))) continue;
    if (!/^(controlled:\d+:(pdf|docx)|training:[a-f0-9]+|release:(source|change|candidate|feature|table):\d+)$/.test(item.preview_id || '') || !item.locator) continue;
    if (result.some(row => row.preview_id === item.preview_id && row.locator === item.locator && row.version === (item.version || ''))) continue;
    result.push(Object.fromEntries(fields.map(key => [key, item[key] || ''])));
    if (result.length === 4) break;
  }
  return result;
}

function restoreSearchComparison(key) {
  try {
    const raw = sessionStorage.getItem('featureTracker.searchComparison') || '';
    if (!raw || raw.length > 80000) return [];
    const saved = JSON.parse(raw);
    return saved?.version === 1 && saved.key === key ? normalizeSearchComparison(saved.items) : [];
  } catch (_error) { return []; }
}

function saveSearchComparison() {
  try {
    sessionStorage.setItem('featureTracker.searchComparison', JSON.stringify({version: 1,
      key: state.searchComparisonKey, items: normalizeSearchComparison(state.searchComparison || [])}));
  } catch (_error) {
    if (!state.comparisonStorageWarning) showNotice('浏览器未允许保存对照选择，刷新后需重新选择。');
    state.comparisonStorageWarning = true;
  }
}

function evidenceLink(selection, searchUrl) {
  if (!selection.preview_id || !searchUrl) return searchUrl;
  const url = new URL(searchUrl);
  const location = parseLocation(url.hash);
  const params = location.view === 'search' ? location.params : {project: location.params.project, q: selection.originalQuery || selection.query || ''};
  Object.assign(params, {preview: selection.preview_id, locator: selection.locator || '',
    preview_query: selection.query || '', preview_input: selection.originalQuery || selection.query || ''});
  url.hash = buildHash('search', params);
  return url.href;
}

async function restoreEvidenceLocation(params) {
  if (params.preview) await openSearchPreview(params.preview, params.locator || '', params.preview_query || '', params.preview_input || params.preview_query || '');
}

function searchQueryOrigin(query, originalQuery) {
  if (!query) return '';
  const related = originalQuery && query.toLocaleLowerCase() !== originalQuery.toLocaleLowerCase();
  return `<p class="search-query-origin">${related ? '关联词' : '输入词'}：<strong>${escapeHtml(query)}</strong>${related ? ` · 输入词：${escapeHtml(originalQuery)} · 关联线索需核对含义` : ''}；文字片段中的对应词已高亮。</p>`;
}

function versionHitDescription(row, coverage = {}) {
  const counts = `原词 ${row.direct_count || 0} · 关联 ${row.related_count || 0}${row.stale_count ? ` · 待更新线索 ${row.stale_count}` : ''}`;
  let status = '';
  if (coverage.status === 'unknown') status = '来源查询未完成';
  else if (!row.total) status = ({no_materials: '未登记资料', pending_index: '资料待索引或待更新',
    unavailable: '资料不可读取', unsearchable: '资料无可检索文字', partial: '资料仍有缺口'})[coverage.status] || (row.stale_count ? '需更新索引后核对' : '当前条件未找到提及');
  else if (!row.direct_count && row.related_count) status = '仅关联词线索，需核对含义';
  return counts + (status ? ` · ${status}` : '');
}

function focusSearchVersion(version) {
  document.querySelector('#release-search-versions').value = version;
  document.querySelector('#release-search-version-from').value = '';
  document.querySelector('#release-search-version-to').value = '';
  state.searchPage = 1;
  syncVersionChoices();
  return searchUnified();
}

function searchFiltersMarkup(params) {
  const filters = [];
  if (params.versions) filters.push(['versions', `版本：${params.versions}`]);
  if (params.version_from || params.version_to) filters.push(['range', `版本范围：${params.version_from ? params.version_from + ' 起' : '不限起点'}${params.version_to ? '，至 ' + params.version_to : ''}`]);
  if (params.market) filters.push(['market', `市场：${marketLabel(params.market)}`]);
  if (params.model) filters.push(['model', `机型：${params.model}`]);
  if (params.country) filters.push(['country', `国家：${params.country}`]);
  if (params.verification) filters.push(['verification', `复核：${verificationLabel(params.verification)}`]);
  if (params.current_only === 'true') filters.push(['current', '仅当前资料']);
  const sources = (params.sources || '').split(',').filter(Boolean);
  if (Object.keys(SEARCH_SOURCE_LABELS).some(source => !sources.includes(source))) filters.push(['sources', `来源：${sources.map(source => SEARCH_SOURCE_LABELS[source] || source).join('、') || '未选择来源'}`]);
  if (!filters.length) return '';
  return `<strong>当前筛选</strong>${filters.map(([key, label]) => `<button type="button" class="ghost-button compact-button" data-search-remove-filter="${key}" aria-label="${escapeAttribute((key === 'sources' ? '恢复全部来源，当前' : '移除筛选：') + label)}">${escapeHtml(label)} ×</button>`).join('')}<button type="button" class="text-button" data-search-remove-filter="all">清除版本和高级筛选</button>`;
}

function renderSearchFilters() {
  if (state.activeView !== 'search') return;
  const container = document.querySelector('#search-active-filters');
  container.innerHTML = searchFiltersMarkup(currentViewParams());
  container.hidden = !container.innerHTML;
}

function removeSearchFilter(key) {
  const textFields = {versions: ['versions'], range: ['version-from', 'version-to'], market: ['market'],
    model: ['model'], country: ['country'], verification: ['verification']};
  if (key !== 'all' && !textFields[key] && !['current', 'sources'].includes(key)) return;
  const fields = key === 'all' ? Object.values(textFields).flat() : (textFields[key] || []);
  fields.forEach(field => { document.querySelector(`#release-search-${field}`).value = ''; });
  if (key === 'all' || key === 'current') document.querySelector('#release-search-current').checked = false;
  if (key === 'all' || key === 'sources') document.querySelectorAll('input[name="search-source"]').forEach(input => { input.checked = true; });
  if (document.querySelector('#release-search-task').value === 'version'
      && !['versions', 'version-from', 'version-to'].some(field => document.querySelector(`#release-search-${field}`).value.trim())) {
    restoreSearchTask({...searchTaskSettings(), task: 'search'});
    showNotice('已移除版本限制，切换为普通搜索。');
  }
  if (key === 'all' || key === 'versions' || key === 'range') syncVersionChoices();
  state.searchPage = 1;
  return searchUnified();
}

function searchEmptyMarkup(result) {
  if (result.total > 0) return `<div class="empty-state compact">当前页已超出结果范围，仍有 ${result.total} 条匹配结果。<button type="button" class="ghost-button" data-search-page="1">返回第一页</button></div>`;
  return '<div class="empty-state compact">已接入资料中没有找到匹配内容；这不表示功能不支持。可移除上方筛选条件，或查看资料覆盖与缺口、补充历史资料后再查。</div>';
}

function readableSearchEvidence(preview, locator = '') {
  if (preview.locator_status === 'unresolved') return null;
  const section = preview.section;
  if (section?.complete === true && typeof section.content === 'string' && section.content.trim() && section.locator) {
    return { locator: section.locator, text: section.content, section_number: section.section_number || '', complete: true };
  }
  const chunk = locator ? preview.chunks?.find(row => row.locator === locator) : preview.chunks?.[0];
  return chunk ? { locator: chunk.locator, text: chunk.text, complete: false } : null;
}

function formatEvidenceCitation(preview, selection = {}, searchUrl = '') {
  const locator = selection.locator || '';
  if (preview.locator_status === 'unresolved') throw new Error('原文位置不可用，请重新选择后复制。');
  const evidence = readableSearchEvidence(preview, locator);
  if (!evidence && locator) throw new Error('原文位置不可用，请重新选择后复制。');
  const query = selection.query || '', original = selection.originalQuery || query;
  const related = query.toLocaleLowerCase() !== original.toLocaleLowerCase();
  return [preview.title, selection.version ? `所选版本：${selection.version}` : '',
    `${preview.scope} · ${verificationLabel(preview.verification)}`,
    selection.source_label || '', searchEvidenceLabel(selection.evidence_kind || ''), evidence?.locator || '原文件',
    evidence?.complete ? `完整章节${evidence.section_number ? ` ${evidence.section_number}` : ''}` : '匹配片段（未核实完整章节）',
    preview.section?.has_images ? (preview.section.images_complete === false ? '章节含图，部分图片未能展示，请核对原文件。' : '章节含图，请查看原文件中的图片。') : '',
    query ? (related ? `输入词：${original}\n关联词：${query}（线索需核对含义）` : `输入词：${query}`) : '',
    evidence?.text || '无可检索文字，请核对原文件；此引用仅包含资料信息。', preview.notice || '',
    selection.preview_id ? evidenceLink({...selection, locator: evidence?.locator || locator}, searchUrl) : searchUrl].filter(Boolean).join('\n');
}

function normalizeComparisonText(value) {
  return String(value || '').replace(/\s+/gu, ' ').trim();
}

function normalizeChapterComparisonText(value, sectionNumber) {
  const text = normalizeComparisonText(value);
  const prefix = sectionNumber ? `${sectionNumber} ` : '';
  return prefix && text.startsWith(prefix) ? text.slice(prefix.length).trimStart() : text;
}

function comparisonTextStatus(entries) {
  if (entries.length < 2) return 'incomplete';
  const chunks = entries.map(entry => entry.error || !entry.preview || !entry.item.locator
    ? null : readableSearchEvidence(entry.preview, entry.item.locator));
  if (chunks.some(chunk => !chunk || typeof chunk.text !== 'string')) return 'incomplete';
  const normalized = chunks.map(chunk => normalizeChapterComparisonText(chunk.text, chunk.section_number));
  if (normalized.some(text => !text)) return 'incomplete';
  const keys = chunks.map((chunk, index) => JSON.stringify([chunk.section_number || '', normalized[index]]));
  return keys.every(key => key === keys[0]) ? 'same' : 'different';
}

function comparisonNotice(entries) {
  const status = comparisonTextStatus(entries);
  if (status === 'same' && entries.some(entry => entry.preview?.section?.has_images)) return '所选章节文字一致（仅忽略空白差异）；图片及适用范围请核对原文件。';
  if (status === 'same') return '所选原文一致（仅忽略空白差异）；请核对各自适用范围与复核状态。';
  if (status === 'different') return '原文存在表述差异；差异不自动代表新增能力，请核对适用范围与复核状态。';
  return '部分原文不可用，暂无法比较；请重新选择依据。';
}

function buildComparisonCitation(entries, searchUrl) {
  if (entries.length < 2 || entries.some(entry => entry.error || !entry.preview || !entry.item.locator || !readableSearchEvidence(entry.preview, entry.item.locator))) {
    throw new Error('部分原文位置不可用，无法复制完整对照，请重新选择依据。');
  }
  return `原文对照（${comparisonNotice(entries)}）\n\n` + entries.map((entry, index) =>
    `【${index + 1}】\n${formatEvidenceCitation(entry.preview, entry.item, searchUrl)}`).join('\n\n');
}

async function copyEvidenceCitation(text, dialog) {
  try {
    await navigator.clipboard.writeText(text);
    showNotice('已复制原文、位置、查询词和出处。');
  } catch (error) {
    const fallback = dialog.querySelector('[data-citation-fallback]');
    const textarea = fallback.querySelector('textarea');
    textarea.value = text;
    fallback.hidden = false;
    textarea.focus();
    textarea.select();
    showNotice('浏览器未允许自动复制，请复制已选中的引用文字。');
  }
}

function preferredSearchEvidence(item) {
  const detail = item.detail_evidence;
  return detail && typeof detail.source_id === 'string' && detail.source_id && typeof detail.locator === 'string' && detail.locator
    ? { preview_id: detail.source_id, locator: detail.locator } : null;
}

function searchEvidenceActions(item, query, originalQuery, buttonClass = 'ghost-button') {
  if (item.is_stale) return '<button type="button" class="ghost-button" data-search-result-refresh>更新资料索引</button>';
  const preferred = preferredSearchEvidence(item);
  const button = (source, locator, label, style) => `<button type="button" class="${style}" data-search-result-preview="${escapeAttribute(source)}" data-search-result-locator="${escapeAttribute(locator || '')}" data-search-result-query="${escapeAttribute(query || '')}" data-search-result-input-query="${escapeAttribute(originalQuery || query || '')}">${escapeHtml(label)}</button>`;
  if (preferred) {
    const detail = item.detail_evidence;
    const status = detail.verification ? verificationLabel(detail.verification) : '复核状态见预览';
    const note = detail.notice ? ` · ${detail.notice}` : '';
    const samePosition = item.preview_id === preferred.preview_id && (item.locator || '') === preferred.locator;
    const secondaryLabel = item.source_type === 'release' && item.evidence_kind === 'version_record' ? '查看变更依据' : '查看原命中位置';
    return button(preferred.preview_id, preferred.locator, '查看完整功能描述', buttonClass) + `<small class="search-detail-notice">${escapeHtml(status + note)}</small>` + (item.preview_id && !samePosition ? button(item.preview_id, item.locator, secondaryLabel, 'text-button') : '');
  }
  if (item.preview_id) return button(item.preview_id, item.locator, item.config_evidence ? '查看配置依据' : `查看命中原文${item.match_count > 1 ? `（${item.match_count} 处）` : ''}`, buttonClass);
  return '';
}

function searchComparisonButton(item, match, originalQuery) {
  if (!item.preview_id || item.is_stale) return '';
  const preferred = (!match.locator || match.locator === item.locator) ? preferredSearchEvidence(item) : null;
  const candidate = { preview_id: preferred?.preview_id || item.preview_id, title: (preferred && item.detail_evidence.title) || item.title, scope: (preferred && item.detail_evidence.scope) || item.scope,
    version: match.version || item.version || '', locator: preferred?.locator || match.locator || item.locator || '',
    query: match.query || item.matched_query || originalQuery, originalQuery,
    evidence_kind: (preferred && item.detail_evidence.evidence_kind) || item.evidence_kind || '', source_label: (preferred && item.detail_evidence.source_label) || item.source_label };
  const index = state.searchComparisonOptions.push(candidate) - 1;
  return `<button type="button" class="text-button" data-search-compare-add="${index}" aria-pressed="false">加入对照</button>`;
}

function renderSearchComparisonTray() {
  const tray = document.querySelector('#search-comparison-tray');
  if (!tray) return;
  const selected = state.searchComparison || [];
  document.querySelectorAll('[data-group-preview]').forEach(row => {
    const count = selected.filter(item => item.preview_id === row.dataset.groupPreview || (row.dataset.groupDetailPreview && item.preview_id === row.dataset.groupDetailPreview)).length;
    const label = row.querySelector('[data-group-selected]');
    if (label) label.textContent = count ? ` · 已选 ${count} 处对照` : '';
  });
  tray.innerHTML = `<strong>原文对照 · 已选 ${selected.length}/4 处</strong><span>在结果中选择不同版本的原文，可跨页选择。</span>${selected.map((item, n) => `<button type="button" class="ghost-button compact-button" data-search-compare-remove="${n}" aria-label="移除 ${escapeAttribute(item.version || item.title)} 的对照">${escapeHtml(item.version || '版本未注明')} · ${escapeHtml(item.title)} ×</button>`).join('')}<button type="button" class="primary-button" data-search-compare-open ${selected.length < 2 ? 'disabled' : ''}>并排对照原文</button>${selected.length ? '<button type="button" class="text-button" data-search-compare-clear>清空</button>' : ''}`;
  document.querySelectorAll('[data-search-compare-add]').forEach(button => {
    const candidate = state.searchComparisonOptions[Number(button.dataset.searchCompareAdd)];
    const checked = selected.some(item => item.preview_id === candidate.preview_id && item.locator === candidate.locator && item.version === candidate.version);
    button.textContent = checked ? '移出对照' : '加入对照';
    button.setAttribute('aria-pressed', String(checked));
  });
}

function comparisonPreviewNotice(preview) {
  return String(preview.notice || '').replace('本章节图片已随原文显示。', '图片请在完整预览中查看。');
}

async function openSearchComparison() {
  const selected = [...(state.searchComparison || [])];
  if (selected.length < 2) return;
  const dialog = document.querySelector('#search-compare-dialog');
  const content = document.querySelector('#search-compare-content');
  const requestId = state.searchCompareRequest = (state.searchCompareRequest || 0) + 1;
  const copyButton = document.querySelector('#copy-search-comparison');
  copyButton.disabled = true;
  copyButton.title = '';
  state.searchComparisonDocuments = [];
  state.searchComparisonUrl = window.location.href;
  dialog.querySelector('[data-citation-fallback]').hidden = true;
  content.innerHTML = '<p>正在核对原文件并读取所选位置…</p>';
  document.querySelector('#search-compare-notice').textContent = '正在核对所选原文和适用范围…';
  if (!dialog.open) dialog.showModal();
  const responses = await Promise.allSettled(selected.map(item => api(`/api/v1/workbench/search-index/sources/${encodeURIComponent(item.preview_id)}/preview?${new URLSearchParams({locator: item.locator, q: item.query})}`)));
  if (requestId !== state.searchCompareRequest || !dialog.open) return;
  state.searchComparisonDocuments = selected.map((item, index) => responses[index].status === 'fulfilled'
    ? {item, preview: responses[index].value} : {item, error: responses[index].reason.message});
  document.querySelector('#search-compare-notice').textContent = comparisonNotice(state.searchComparisonDocuments);
  try { buildComparisonCitation(state.searchComparisonDocuments, state.searchComparisonUrl); copyButton.disabled = false; }
  catch (error) { copyButton.title = error.message; }
  content.innerHTML = selected.map((item, index) => {
    const response = responses[index];
    const heading = `<h3>${escapeHtml(item.version || '版本未注明')}</h3><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.source_label)} · ${escapeHtml(item.scope)}</p><p>${escapeHtml(searchEvidenceLabel(item.evidence_kind))}</p>`;
    if (response.status === 'rejected') return `<article>${heading}<p role="alert">无法读取此处原文：${escapeHtml(response.reason.message)}。请更新索引或重新选择依据。</p></article>`;
    const preview = response.value;
    const chunk = readableSearchEvidence(preview, item.locator);
    const imageNote = preview.section?.has_images ? '<p class="strategy-note">对照仅显示文字；图片请打开完整预览核对。</p>' : '';
    const previewNotice = comparisonPreviewNotice(preview);
    return `<article>${heading}<p>${escapeHtml(verificationLabel(preview.verification))} · ${escapeHtml(chunk?.locator || item.locator)}${chunk?.complete ? ` · 完整章节${chunk.section_number ? ' ' + escapeHtml(chunk.section_number) : ''}` : ' · 匹配片段'}</p>${previewNotice ? `<p class="strategy-note">${escapeHtml(previewNotice)}</p>` : ''}${searchQueryOrigin(item.query, item.originalQuery)}${imageNote}${chunk ? `<p class="search-comparison-text">${highlightSearchText(chunk.text, item.query)}</p>` : '<p role="alert">原文位置已变化或未指定，请重新打开资料并选择依据。</p>'}<button type="button" class="ghost-button" data-search-result-preview="${escapeAttribute(item.preview_id)}" data-search-result-locator="${escapeAttribute(item.locator)}" data-search-result-query="${escapeAttribute(item.query)}" data-search-result-input-query="${escapeAttribute(item.originalQuery)}">打开完整预览</button></article>`;
  }).join('');
}

let noticeTimer;
function showNotice(message) {
  const notice = document.querySelector('#notice');
  notice.textContent = message;
  notice.hidden = false;
  // 先取消上一条的隐藏定时器：否则 4 秒内连续提示时，新提示会被旧定时器提前收起。
  window.clearTimeout(noticeTimer);
  noticeTimer = window.setTimeout(() => { notice.hidden = true; }, 4000);
}

async function loadDashboard() {
  const data = await api(projectPath('/api/v1/dashboard'));
  for (const key of ['feature', 'release', 'term', 'review']) {
    const badge = document.querySelector(`#${key}-count`);
    const value = data[`${key}_count`];
    badge.textContent = value;
    // 0 不显示："功能库 0" 只会制造噪音，看起来还像坏了
    badge.hidden = !value;
  }
  document.querySelector('#term-count').title = '顶层术语数量；子项与父项说明在词典内展开统计';
  const reviewCount = Number(data.review_count || 0);
  document.querySelectorAll('[data-review-short-count]').forEach(node => { node.textContent = reviewCount; });
  const reviewCta = document.querySelector('#release-review-cta');
  if (reviewCta) {
    reviewCta.disabled = reviewCount === 0;
    reviewCta.title = reviewCount === 0 ? '本项目暂无待审核记录' : `继续处理 ${reviewCount} 条待审核记录`;
    reviewCta.innerHTML = reviewCount === 0
      ? '本项目暂无待审核'
      : `继续审核 <span data-review-short-count>${reviewCount}</span> 条`;
  }
}

function populateProductCategorySelects() {
  const options = state.categories.map(category => `<option value="${escapeAttribute(category.name)}">${escapeHtml(category.name)}</option>`).join('');
  document.querySelectorAll('[data-product-category-select]').forEach(select => {
    const selected = select.value;
    select.innerHTML = `<option value="">未分类</option>${options}`;
    select.value = selected;
  });
  const termCategoryFilter = document.querySelector('#term-category-filter');
  if (termCategoryFilter) {
    const selected = termCategoryFilter.value;
    termCategoryFilter.innerHTML = `<option value="">全部分类</option>${options}`;
    termCategoryFilter.value = state.categories.some(category => category.name === selected) ? selected : '';
  }
}

function renderCategoryManager() {
  const container = document.querySelector('#category-list');
  if (!container) return;
  container.innerHTML = state.categories.length
    ? state.categories.map(category => `<article><input aria-label="分类名称" value="${escapeAttribute(category.name)}" data-category-name="${category.id}"><span>术语 ${category.term_count} · 功能 ${category.feature_count}</span><button type="button" class="ghost-button" data-category-save="${category.id}">保存更名</button></article>`).join('')
    : '<p class="empty-state compact">尚未建立分类。</p>';
}

async function loadProductCategories() {
  state.categories = await api('/api/v1/categories');
  populateProductCategorySelects();
  renderCategoryManager();
}

async function renameProductCategory(id, name) {
  await api(`/api/v1/categories/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) });
  await loadProductCategories();
  await Promise.all([loadTerms(document.querySelector('#term-search').value), loadFeatures(document.querySelector('#feature-search').value)]);
  showNotice('分类已更名，关联的术语和功能已同步更新。');
}

// 「说明待完善」由接口给出（description_title_only）：判据只在后端算一次，
// 前端自己判断会与后端口径漂移——补全后的正文可能以「新增…」开头而被误标。

function queryConclusionContent({ label, title, detail = '', metrics = [] }) {
  const metricMarkup = metrics.length
    ? `<dl>${metrics.map(metric => `<div><dt>${escapeHtml(metric.label)}</dt><dd>${escapeHtml(String(metric.value))}</dd></div>`).join('')}</dl>`
    : '';
  return `<div class="query-conclusion-copy"><span>${escapeHtml(label)}</span><strong>${escapeHtml(title)}</strong>${detail ? `<small>${escapeHtml(detail)}</small>` : ''}</div>${metricMarkup}`;
}

function featureConclusionMarkup(features, query = '') {
  const incomplete = features.filter(item => item.description_title_only).length;
  const title = query
    ? `找到 ${features.length} 个匹配的正式功能`
    : `当前项目已收录 ${features.length} 个正式功能`;
  const detail = features.length === 0
    ? (query ? '当前筛选没有匹配结果，可以更换关键词继续查询。' : '当前项目尚未建立正式功能，请从审核区确认候选。')
    : incomplete
      ? '说明待完善的功能仍可查看当前确认文本，但不应视为完整功能定义。'
      : '当前结果均已具备完整说明。';
  return queryConclusionContent({
    label: '功能结论',
    title,
    detail,
    metrics: [
      { label: '当前结果', value: features.length },
      { label: '说明待完善', value: incomplete },
    ],
  });
}

async function loadFeatures(query = '') {
  const features = await api(projectPath(`/api/v1/features?q=${encodeURIComponent(query)}`));
  if (!query) state.features = features;
  const summary = document.querySelector('#feature-summary');
  const incomplete = features.filter(item => item.description_title_only).length;
  summary.classList.toggle('attention', incomplete > 0);
  summary.innerHTML = featureConclusionMarkup(features, query);
  const container = document.querySelector('#feature-list');
  container.className = 'record-list';
  container.innerHTML = features.length ? features.map(item => `<article class="record">
    <div class="record-head">
      <div>
        <h3 class="record-title">${escapeHtml(item.cn_name)}</h3>
        <span class="record-sub">${escapeHtml(item.en_name)}</span>
      </div>
      <div class="record-actions">
        ${item.parent_feature_id ? `<span class="pill note">${escapeHtml(item.parent_cn_name || '子功能')}的独立子功能</span>` : ''}
        ${item.category ? `<span class="pill">${escapeHtml(item.category)}</span>` : ''}
        ${item.description_title_only ? '<span class="pill warning">说明待完善</span>' : ''}
        <button type="button" class="text-button" data-feature-timeline="${item.id}">查看演进</button>
        <button type="button" class="ghost-button" data-feature-edit="${item.id}">编辑功能</button>
      </div>
    </div>
    <div class="record-body bilingual"><div><small>中文当前确认文本</small><p>${escapeHtml(item.cn_description || '待完善')}</p></div><div><small>English confirmed text</small><p>${escapeHtml(item.en_description || 'Pending')}</p></div></div>
  </article>`).join('') : emptyMarkup({
    title: query ? '没有匹配的正式功能' : '还没有正式功能',
    hint: query ? '可以更换筛选词，或到审核区关联候选。' : '从审核区确认候选后，会自动建立并汇总功能档案。',
    action: '<button type="button" class="primary-button" data-empty-review-cta>去审核建立功能</button>',
  });
}

function renderFeatureComponents(feature) {
  document.querySelector('#feature-child-list').innerHTML = feature.children.length
    ? feature.children.map(child => `<article><strong>${escapeHtml(child.cn_name)}</strong><span>${escapeHtml(child.en_name)}</span></article>`).join('')
    : '<p>尚未添加独立子功能。</p>';
  document.querySelector('#feature-note-list').innerHTML = feature.notes.length
    ? feature.notes.map(note => `<article><strong>${escapeHtml(note.cn_content)}</strong>${note.en_content ? `<span>${escapeHtml(note.en_content)}</span>` : '<span>仅中文说明</span>'}</article>`).join('')
    : '<p>尚未添加父项说明。</p>';
}

async function openFeatureEditor(id) {
  const feature = await api(`/api/v1/features/${id}`);
  state.editingFeature = feature;
  const form = document.querySelector('#feature-edit-form');
  form.elements.feature_id.value = feature.id;
  for (const field of ['cn_name', 'en_name', 'category', 'cn_description', 'en_description']) form.elements[field].value = feature[field] || '';
  document.querySelector('#feature-edit-title').textContent = `编辑功能：${feature.cn_name}`;
  renderFeatureComponents(feature);
  const dialog = document.querySelector('#feature-edit-dialog');
  if (!dialog.open) dialog.showModal();
}

async function openFeatureTimeline(id) {
  const timeline = await api(`/api/v1/features/${id}/timeline`);
  document.querySelector('#feature-timeline-title').textContent = `${timeline.feature.cn_name} / ${timeline.feature.en_name}`;
  const releaseEvents = timeline.events.filter(event => event.kind === 'release');
  const revisionEvents = timeline.events.filter(event => event.kind === 'revision');
  const marketText = markets => markets.map(market => market === 'domestic' ? '国内' : '海外').join('、') || '未标注市场';
  document.querySelector('#feature-timeline-content').innerHTML = timeline.events.length
    ? `<section class="timeline-summary"><strong>${releaseEvents.length} 个版本变更</strong><span>${revisionEvents.length} 次最终描述修订</span></section><ol class="feature-timeline">${releaseEvents.map(event => `<li class="release-event"><span class="timeline-marker">版</span><div><div class="timeline-heading"><strong>${escapeHtml(event.version)}</strong><span>${escapeHtml(marketText(event.markets))}</span></div><div class="candidate-bilingual-columns"><section><small>中文变更</small><p>${escapeHtml(event.title_cn || event.description_cn || '缺少中文')}</p></section><section><small>English change</small><p>${escapeHtml(event.title_en || event.description_en || 'Missing English')}</p></section></div></div></li>`).join('')}${revisionEvents.map(event => `<li class="revision-event"><span class="timeline-marker">修</span><div><div class="timeline-heading"><strong>最终描述第 ${event.revision_number} 版</strong><span>${escapeHtml(event.review_status === 'approved' ? '已确认' : '待确认')}</span></div><div class="candidate-bilingual-columns"><section><small>中文最终描述</small><p>${escapeHtml(event.cn_description || '待完善')}</p></section><section><small>English final description</small><p>${escapeHtml(event.en_description || 'Pending')}</p></section></div></div></li>`).join('')}</ol>`
    : '<p class="empty-state compact">该功能还没有版本或描述修订记录。</p>';
  document.querySelector('#feature-timeline-dialog').showModal();
}

function openChildFeatureDialog() {
  const form = document.querySelector('#child-feature-form');
  form.reset();
  form.elements.parent_feature_id.value = state.editingFeature.id;
  form.elements.category.value = state.editingFeature.category || '';
  document.querySelector('#child-feature-dialog').showModal();
}

function openFeatureNoteDialog() {
  const form = document.querySelector('#feature-note-form');
  form.reset();
  form.elements.feature_id.value = state.editingFeature.id;
  document.querySelector('#feature-note-dialog').showModal();
}

async function loadTerms(query = '') {
  state.terms = await api(`/api/v1/terms?q=${encodeURIComponent(query)}`);
  renderTerms();
}

function renderTerms() {
  const statusFilter = document.querySelector('#term-status-filter')?.value || 'all';
  const categoryFilter = document.querySelector('#term-category-filter')?.value || '';
  const terms = state.terms.filter(term => {
    const statusMatches = statusFilter === 'all'
      || (statusFilter === 'review' && term.needs_review && term.entry_type !== 'note')
      || (statusFilter === 'confirmed' && !term.needs_review && term.entry_type !== 'note')
      || (statusFilter === 'note' && term.entry_type === 'note');
    return statusMatches && (!categoryFilter || term.category === categoryFilter);
  });
  const summary = document.querySelector('#term-filter-summary');
  if (summary) summary.textContent = `显示 ${terms.length} / ${state.terms.length} 条（含子项）`;
  document.querySelector('#term-list').innerHTML = terms.length ? terms.map(term => {
    const canConfirmDirectly = term.cn_name && term.en_name && term.en_name !== '—';
    const noteAction = term.parent_id ? `<button type="button" class="text-button" data-term-type="note" data-term-id="${term.id}">设为父项说明</button>` : '';
    let status;
    if (term.entry_type === 'note') {
      status = `<div class="term-actions"><span class="pill note">父项说明</span><button type="button" class="ghost-button" data-term-edit="${term.id}">编辑说明</button><button type="button" class="text-button" data-term-type="term" data-term-id="${term.id}">改为独立子功能</button></div>`;
    } else if (term.needs_review) {
      status = `<div class="term-actions"><span class="pill warning">待确认</span><button type="button" class="ghost-button" data-term-edit="${term.id}">编辑并确认</button>${canConfirmDirectly ? `<button type="button" class="text-button" data-term-confirm="${term.id}">直接确认</button>` : ''}${noteAction}</div>`;
    } else {
      status = `<div class="term-actions"><span class="pill">已确认</span><button type="button" class="ghost-button" data-term-edit="${term.id}">编辑</button>${noteAction}</div>`;
    }
    const cnName = term.parent_id ? `<span class="term-child">↳ ${escapeHtml(term.cn_name)}</span>` : escapeHtml(term.cn_name);
    return `<article class="record record-compact"><div class="record-head"><div><h3 class="record-title">${cnName}</h3><span class="record-sub">${escapeHtml(term.en_name || '—')}</span></div><div class="record-actions">${status}</div></div><span class="record-meta">${escapeHtml(term.category || '未分类')}</span></article>`;
  }).join('') : emptyMarkup({ title: '当前筛选条件下没有术语。', hint: '可以放宽状态或分类筛选。' });
}

async function confirmTerm(id, payload = {}, successMessage = '术语已确认。') {
  await api(`/api/v1/terms/${id}/confirm`, { method: 'POST', body: JSON.stringify(payload) });
  await loadTerms(document.querySelector('#term-search').value);
  showNotice(successMessage);
}

async function updateTerm(id, payload, successMessage) {
  await api(`/api/v1/terms/${id}`, { method: 'PATCH', body: JSON.stringify(payload) });
  await loadTerms(document.querySelector('#term-search').value);
  showNotice(successMessage);
}

async function setTermEntryType(id, entryType) {
  await api(`/api/v1/terms/${id}/entry-type`, { method: 'PATCH', body: JSON.stringify({ entry_type: entryType }) });
  await loadTerms(document.querySelector('#term-search').value);
  showNotice(entryType === 'note' ? '已设为父项说明，不再参与功能自动匹配。' : '已恢复为独立子功能，请核对中英文后确认。');
}

function openTermEditor(id) {
  const term = state.terms.find(item => String(item.id) === String(id));
  if (!term) return;
  const form = document.querySelector('#term-form');
  form.elements.term_id.value = term.id;
  form.elements.cn_name.value = term.cn_name;
  form.elements.en_name.value = term.en_name === '—' ? '' : term.en_name;
  form.elements.category.value = term.category;
  form.dataset.pending = term.needs_review ? 'true' : 'false';
  form.dataset.entryType = term.entry_type;
  const isNote = term.entry_type === 'note';
  form.elements.en_name.required = !isNote;
  document.querySelector('#term-en-label').firstChild.textContent = isNote ? '英文说明（可选）' : '英文名称或缩写';
  document.querySelector('#term-dialog-title').textContent = isNote ? '编辑父项说明' : term.needs_review ? '编辑并确认术语' : '编辑术语';
  document.querySelector('#term-submit-label').textContent = isNote ? '保存说明' : term.needs_review ? '保存并确认' : '保存修改';
  document.querySelector('#term-dialog-help').textContent = isNote
    ? '父项说明只补充上级功能的含义，可以仅保留中文，不参与功能建立与自动匹配。'
    : term.needs_review
      ? '保存后该词条会变为“已确认”，功能建立与自动匹配将使用核对后的中英文名称。'
      : '保存修改后继续保持“已确认”，自动匹配将使用修订后的中英文名称。';
  document.querySelector('#term-dialog').showModal();
}

function releaseConclusionMarkup(release) {
  const needsAttention = Number(release.structured_conflict_count || 0);
  const releaseDates = `国内 ${release.domestic_release_date || '待补充'} · 海外 ${release.overseas_release_date || '待补充'}`;
  return `<section class="query-conclusion${needsAttention ? ' attention' : ''}" aria-label="版本查询结论">${queryConclusionContent({
    label: '版本结论',
    title: `当前查看 ${release.version} 版本档案`,
    detail: `${release.product} · ${releaseDates}`,
    metrics: [
      { label: '文本变更', value: release.changes.length },
      { label: '结构化表', value: release.structured_table_count || 0 },
      { label: '需核对', value: needsAttention },
    ],
  })}</section>`;
}

function releasePageMarkup(release) {
  const counts = release.changes.reduce((result, change) => ({ ...result, [change.category]: (result[change.category] || 0) + 1 }), {});
  const configurationButton = release.configuration_table_count ? `<button type="button" class="ghost-button release-configuration-button" data-configuration-release="${release.id}" data-configuration-version="${escapeAttribute(release.version)}">查看版本配置表原文</button>` : '';
  const structuredSummary = release.structured_table_count ? `<section class="structured-release-summary"><div><strong>结构化变更 · ${release.structured_table_count} 张有效表</strong><span>配置矩阵、支持范围、物料、界面或图像对照已纳入版本档案${release.structured_conflict_count ? `；${release.structured_conflict_count} 项需核对` : ''}。</span></div><div class="release-row-actions"><button type="button" class="primary-button release-archive-button" data-release-archive="${release.id}" data-release-version="${escapeAttribute(release.version)}">打开版本档案</button>${configurationButton}</div></section>` : '';
  const emptyMessage = release.structured_table_count ? '此版本没有独立文本条目；主要变更已收录在上方结构化表格。' : '此版本暂无文本或结构化变更记录。';
  return `<article class="release-row" data-release-version="${escapeAttribute(release.version)}">${releaseConclusionMarkup(release)}<div class="release-row-header"><div class="change-groups">${Object.entries(counts).map(([category, count]) => `<button type="button" class="change-tag" data-release-category-filter="${escapeAttribute(category)}" aria-pressed="false">${escapeHtml(categoryLabels[category] || category)} · ${count}</button>`).join('') || '<span class="change-tag">尚无文本变更</span>'}</div><button type="button" class="release-open" data-release-toggle aria-expanded="false"><em>查看变更依据</em></button></div><div class="release-details" hidden>${structuredSummary}<div class="release-detail-toolbar"><strong data-release-filter-title>全部变更 · <span data-release-filter-count>${release.changes.length}</span> 条</strong><button type="button" class="text-button" data-release-filter-reset>显示全部</button></div><div class="release-change-list">${release.changes.map(change => `<article class="release-change" data-release-category="${escapeAttribute(change.category)}"><span class="change-tag">${escapeHtml(categoryLabels[change.category] || change.category)}</span><div><p>${escapeHtml(change.title_cn || '缺少中文')}</p><p>${escapeHtml(change.title_en || 'Missing English')}</p></div></article>`).join('') || `<p class="empty-state compact">${emptyMessage}</p>`}</div></div></article>`;
}

function renderReleaseCenter({ focusTab = false } = {}) {
  const tabs = document.querySelector('#release-version-tabs');
  const page = document.querySelector('#release-page');
  const activeIndex = state.releases.findIndex(release => release.version === state.activeReleaseVersion);
  const release = state.releases[activeIndex];
  document.querySelectorAll('[data-release-step]').forEach(button => {
    const step = Number(button.dataset.releaseStep);
    button.disabled = !release || activeIndex + step < 0 || activeIndex + step >= state.releases.length;
  });
  if (!release) {
    tabs.innerHTML = '';
    tabs.removeAttribute('role');
    tabs.removeAttribute('aria-label');
    page.className = 'release-page empty-state';
    page.removeAttribute('aria-labelledby');
    page.innerHTML = `<div class="release-empty-guidance"><strong>尚未导入版本记录</strong><span>先检查当前项目的中英文最终版文件，再导入完整版本。</span><button type="button" class="primary-button" data-empty-project-import>查看扫描预览</button></div>`;
    return;
  }
  tabs.setAttribute('role', 'tablist');
  tabs.setAttribute('aria-label', '版本号');
  tabs.innerHTML = state.releases.map(item => {
    const active = item.version === release.version;
    const tableCount = item.structured_table_count ? ` · ${item.structured_table_count} 表` : '';
    return `<button type="button" id="release-tab-${item.id}" class="release-version-tab${active ? ' active' : ''}" role="tab" data-release-version-tab="${escapeAttribute(item.version)}" aria-controls="release-page" aria-selected="${active}" tabindex="${active ? '0' : '-1'}"><span>${escapeHtml(item.version)}</span><small>${item.changes.length} 条${tableCount}</small></button>`;
  }).join('');
  page.className = 'release-page';
  page.setAttribute('aria-labelledby', `release-tab-${release.id}`);
  page.innerHTML = releasePageMarkup(release);
  const activeTab = tabs.querySelector('[aria-selected="true"]');
  activeTab?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  if (focusTab) activeTab?.focus({ preventScroll: true });
}

function selectReleaseByIndex(index, { focusTab = false } = {}) {
  const release = state.releases[index];
  if (!release) return;
  state.activeReleaseVersion = release.version;
  renderReleaseCenter({ focusTab });
}

async function loadReleases() {
  const activeVersion = state.activeReleaseVersion;
  state.releases = await api(projectPath('/api/v1/releases'));
  state.activeReleaseVersion = state.releases.some(release => release.version === activeVersion)
    ? activeVersion
    : state.releases[0]?.version || null;
  renderReleaseCenter();
  renderScenarioVersionOptions();
  if (document.querySelector('#search-version-picker').open) loadSearchVersionChoices();
  const options = state.releases.map(item => `<option value="${escapeHtml(item.version)}">${escapeHtml(item.version)}</option>`).join('');
  document.querySelector('#from-version').innerHTML = options;
  document.querySelector('#to-version').innerHTML = options;
  state.comparisonKey = null;
  if (state.releases.length > 1) document.querySelector('#to-version').selectedIndex = 0, document.querySelector('#from-version').selectedIndex = 1;
  if (document.querySelector('[data-page="compare"]').classList.contains('active')) ensureComparisonLoaded();
}

function savedSearches() {
  if (state.personal) return state.personal.saved_searches;
  try { return JSON.parse(localStorage.getItem(savedSearchStorageKey) || '[]').filter(item => item && Array.isArray(item.sources)); }
  catch (_error) { return []; }
}

function selectedSearchSources() {
  return [...document.querySelectorAll('input[name="search-source"]:checked')].map(input => input.value);
}

function renderSavedSearches() {
  const container = document.querySelector('#saved-searches');
  const searches = savedSearches();
  container.hidden = !searches.length;
  container.innerHTML = searches.length
    ? `<span>已保存</span>${searches.map((search, index) => `<button type="button" class="saved-search-chip" data-saved-search="${index}">${escapeHtml(search.name || search.query)}<small>${search.scope === 'all' ? '全部项目' : '指定项目'} · ${escapeHtml(search.sources.map(source => SEARCH_SOURCE_LABELS[source] || source).join('、'))}</small></button><button type="button" class="saved-search-remove" data-remove-saved-search="${index}" aria-label="删除已保存搜索 ${escapeAttribute(search.query)}">×</button>`).join('')}`
    : '';
}

function saveCurrentSearch() {
  return savePersonalSearch().catch(error => showNotice(error.message));
}

function searchTaskSettings() {
  return {
    task: document.querySelector('#release-search-task').value,
    versions: document.querySelector('#release-search-versions').value.trim(),
    expandRelated: document.querySelector('#release-search-expand').checked,
    versionFrom: document.querySelector('#release-search-version-from').value.trim(),
    versionTo: document.querySelector('#release-search-version-to').value.trim(),
  };
}

function scheduleUnifiedSearch() {
  window.clearTimeout(state.searchTimer);
  state.searchController?.abort();
  ++state.searchRequest;
  state.searchTimer = window.setTimeout(() => {
    state.searchPage = 1;
    searchUnified().catch(error => showNotice(error.message));
  }, 300);
}

function selectedVersionTokens() {
  return document.querySelector('#release-search-versions').value.trim().split(/[,，、;；\s]+/).filter(Boolean);
}

function syncVersionChoices() {
  const selected = new Set(selectedVersionTokens());
  document.querySelectorAll('[data-search-version-choice]').forEach(input => { input.checked = selected.has(input.value); });
}

async function loadSearchVersionChoices() {
  const container = document.querySelector('#search-version-options');
  const requestId = (state.versionOptionsRequest || 0) + 1;
  state.versionOptionsRequest = requestId;
  container.innerHTML = '<p role="status">正在读取已入库版本…</p>';
  const projects = document.querySelector('#release-search-scope').value === 'all'
    ? state.projects : state.projects.filter(project => Number(project.id) === Number(state.activeProjectId));
  try {
    // Reuse the release API; never read original files just to populate a picker.
    const groups = await Promise.all(projects.map(async project => ({ project,
      releases: await api(`/api/v1/releases?project_id=${encodeURIComponent(project.id)}`) })));
    if (requestId !== state.versionOptionsRequest) return;
    container.innerHTML = groups.map(({ project, releases }) => `<fieldset class="search-source-filters"><legend>${escapeHtml(project.name)}</legend>${releases.length ? releases.map(release => `<label><input type="checkbox" data-search-version-choice value="${escapeAttribute(release.version)}">${escapeHtml(release.version)}</label>`).join('') : '<p>此项目尚无入库版本。</p>'}</fieldset>`).join('') + '<p class="strategy-note">这里列出版本库已收录的版本。历史补充资料中的其他版本仍可直接输入；输入系列时无需逐个勾选。</p>';
    syncVersionChoices();
  } catch (error) {
    if (requestId === state.versionOptionsRequest) container.innerHTML = `<p class="search-source-error">无法读取版本：${escapeHtml(error.message)}。仍可直接填写版本或重新展开重试。</p>`;
  }
}

function searchTaskParams() {
  const settings = searchTaskSettings();
  return { task: settings.task, expand_related: String(settings.expandRelated),
    version_from: settings.versionFrom, version_to: settings.versionTo, versions: settings.versions };
}

function restoreSearchTask(settings = {}) {
  const task = ['earliest', 'version', 'family'].includes(settings.task) ? settings.task : 'search';
  document.querySelector('#release-search-task').value = task;
  document.querySelector('#release-search-versions').value = settings.versions || '';
  document.querySelector('#search-version-range').open = Boolean(settings.versionFrom || settings.versionTo);
  document.querySelector('#search-version-picker').open = false;
  document.querySelector('#release-search-expand').checked = Boolean(settings.expandRelated);
  document.querySelector('#release-search-version-from').value = settings.versionFrom || '';
  document.querySelector('#release-search-version-to').value = settings.versionTo || '';
  document.querySelectorAll('[data-search-task]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.searchTask === task)));
  document.querySelector('#search-task-hint').textContent = ({
    search: '输入关键词，或选择上方常见查询任务。版本范围只筛选有明确版本的记录和资料。',
    earliest: '按项目和版本时间查找最早记载；关联词线索不参与判断。可填写起止版本缩小范围。',
    version: '选择一个或多个版本，也可输入 1.14.XX 系列。结果按版本列出命中数量，未找到提及不表示不支持。',
    family: '输入功能族名称，例如 VAid+。汇总明确提及和已登记子能力，并列出原文线索。',
  })[task];
}

function searchTaskSummary(result) {
  const expansion = result.query_expansion;
  const terms = expansion?.terms?.length ? `<p><strong>本次关联词：</strong>${expansion.terms.map(escapeHtml).join('、')}。${escapeHtml(expansion.notice)}</p>` : '';
  const family = result.feature_family;
  const members = family?.members || [];
  const familyMarkup = family ? `<section class="search-family-summary"><h3>功能族与子能力 · ${members.length} 项档案关联</h3><p>${escapeHtml(family.notice)}</p>${members.length ? members.map(member => `<article class="search-family-member"><strong>${escapeHtml(member.title)}</strong><span class="pill">${member.relation === 'explicit_mention' ? '档案明确提及' : '已登记子能力 · 归属待核对'}</span><p>${escapeHtml(member.project_name)}${member.parent_name ? ` · 所属功能：${escapeHtml(member.parent_name)}` : ''} · ${escapeHtml(verificationLabel(member.verification))}</p><p>${escapeHtml(member.excerpt)}</p><p>${member.codes.length ? `V 代码：${escapeHtml(member.codes.join('、'))} · ` : ''}档案关联版本：${escapeHtml(member.linked_versions.join('、') || '尚未登记')}（不代表子能力首次支持）</p><button type="button" class="text-button" data-search-result-preview="${escapeAttribute(member.preview_id)}" data-search-result-locator="${escapeAttribute(member.locator)}" data-search-result-query="${escapeAttribute(result.query)}">查看功能档案原文</button></article>`).join('') : '<p>功能档案暂无明确关联；下方原文仍可能包含尚未整理为功能条目的能力。</p>'}</section>` : '';
  const coverageByVersion = new Map((result.coverage?.versions || []).map(row => [row.version, row]));
  const summary = result.version_summary?.length ? `<section class="search-version-summary"><h3>所选版本命中概览</h3><p>按记录或文件计数；同一文件在同一版本只计一次，原词优先。关联词是待核对线索，失效索引不计入有效命中。点击版本可聚焦该版本，其他条件保留。</p><div class="search-version-counts">${result.version_summary.map(row => `<button type="button" class="ghost-button ${row.total ? '' : 'warning'}" data-search-focus-version="${escapeAttribute(row.version)}"><strong>${escapeHtml(row.version.replace('.*', '.XX'))}</strong> · ${escapeHtml(versionHitDescription(row, coverageByVersion.get(row.version)))}</button>`).join('')}</div></section>` : '';
  return `<p class="strategy-note">${escapeHtml(result.task_notice || '')}</p>${summary}${terms}${familyMarkup}`;
}

function currentSearchSettings() {
  const query = document.querySelector('#release-search').value.trim();
  if (!query) throw new Error('请先输入要保存的搜索词。');
  const search = {
    query,
    scope: document.querySelector('#release-search-scope').value,
    ...searchTaskSettings(),
    sources: selectedSearchSources(),
    market: document.querySelector('#release-search-market').value,
    model: document.querySelector('#release-search-model').value.trim(),
    verification: document.querySelector('#release-search-verification').value,
    currentOnly: document.querySelector('#release-search-current').checked,
    country: document.querySelector('#release-search-country').value.trim().toUpperCase(),
    projectId: state.activeProjectId,
    name: document.querySelector('#saved-search-name').value.trim() || query,
  };
  return search;
}

async function applySavedSearch(search) {
  if (!search) return;
  if (search.projectId && Number(search.projectId) !== Number(state.activeProjectId)) {
    if (!state.projects.some(project => Number(project.id) === Number(search.projectId))) return showNotice('此常用搜索绑定的项目不存在，请重新保存。');
    await switchProject(search.projectId);
  }
  switchView('search');
  document.querySelector('#release-search').value = search.query;
  document.querySelector('#release-search-scope').value = search.scope || 'current';
  document.querySelector('#release-search-market').value = search.market || '';
  document.querySelector('#release-search-model').value = search.model || '';
  document.querySelector('#release-search-country').value = search.country || '';
  document.querySelector('#saved-search-name').value = search.name || search.query;
  document.querySelector('#release-search-verification').value = search.verification || '';
  document.querySelector('#release-search-current').checked = Boolean(search.currentOnly);
  document.querySelectorAll('input[name="search-source"]').forEach(input => { input.checked = search.sources.includes(input.value); });
  restoreSearchTask(search);
  state.searchPage = 1;
  searchUnified().catch(error => showNotice(error.message));
}

function searchIndexStatusLabel(status) {
  if (!status || !status.total_sources) return '尚未建立本地索引；使用“更新资料索引”开始。';
  const last = status.last_indexed_at ? formatDateTime(status.last_indexed_at) : '时间未记录';
  const empty = status.empty_text_sources ? ` · ${status.empty_text_sources} 份没有可检索文字（扫描件/图片不做 OCR）` : '';
  const stale = status.stale_sources ? ` · ${status.stale_sources} 份索引待更新` : '';
  const failedNames = (status.failed_items || []).slice(0, 3).map(item => item.title).join('、');
  const failed = status.failed_sources ? ` · ${status.failed_sources} 份读取失败${failedNames ? `：${failedNames}` : ''}` : '';
  return `已收录 ${status.indexed_sources}/${status.total_sources} 份资料 · 最近更新 ${last}${stale}${empty}${failed}`;
}

async function loadSearchIndexStatus() {
  const status = await api('/api/v1/workbench/search-index');
  document.querySelector('#search-index-status').textContent = searchIndexStatusLabel(status);
  return status;
}

async function refreshSearchIndex(button = null) {
  if (button) { button.disabled = true; button.textContent = '正在更新…'; }
  const status = document.querySelector('#search-index-status');
  status.textContent = '正在读取已登记的受控资料和培训目录…';
  try {
    const result = await api('/api/v1/workbench/search-index/refresh', { method: 'POST', body: '{}' });
    if (result.skipped && result.reason === 'already_running') {
      await loadSearchIndexStatus();
      showNotice('后台正在更新资料，可以继续查询。');
      return;
    }
    status.textContent = searchIndexStatusLabel(result.status);
    const sourceWarnings = Object.values(result.source_errors || {}).join(' ');
    showNotice(`资料索引已更新：新增 ${result.indexed}、更新 ${result.updated}、未变 ${result.unchanged}、失败 ${result.failed}。${sourceWarnings ? ` ${sourceWarnings}` : ''}`);
    if (document.querySelector('#release-search').value.trim()) await searchUnified();
  } catch (error) {
    status.textContent = `索引更新失败：${error.message}`;
    showNotice(error.message);
  } finally {
    if (button) { button.disabled = false; button.textContent = '更新资料索引'; }
  }
}

function verificationLabel(value) {
  return ({ verified: '已复核', unverified: '未复核', not_applicable: '未设复核状态', source_live: '实时只读', approved: '已确认', pending_review: '待确认', expired: '已过复核期限', superseded: '历史记录' })[value] || '状态未标记';
}

function fileFormatLabel(value) {
  return ({ docx: 'Word', pdf: 'PDF', xlsx: 'Excel', xls: 'Excel 97–2003', pptx: 'PowerPoint', md: 'Markdown', txt: '文本', png: '图片', jpg: '图片', jpeg: '图片', zip: '压缩包' })[value] || '';
}

function searchEvidenceLabel(kind) {
  return ({ current_description: '当前功能说明 · 关联版本不代表当时支持', bug_fix: '缺陷修复线索', pending: '待审核线索', source_snapshot: 'Release Note 原文提及', version_record: '当时版本记录' })[kind] || '';
}

function searchCoverageMarkup(coverage) {
  if (!coverage) return '';
  const projects = (coverage.release?.projects || []).map(project => `<p><strong>${escapeHtml(project.name)}</strong>：${project.versions.length ? escapeHtml(project.versions.join('、')) : '尚未收录版本'}</p>`).join('');
  const files = coverage.controlled || {};
  const issues = files.items || [];
  const statusLabels = { no_materials: '未登记该版本资料', pending_index: '资料尚未索引或待更新', no_match: '已有可检索资料，当前条件未命中', matched: '当前条件有命中', partial: '部分资料可检索，仍有缺口', unavailable: '资料不可读取或抽取失败', unsearchable: '已登记，但没有可检索文字', unknown: '搜索来源异常，暂不能判断' };
  const versions = coverage.versions || [];
  const versionMarkup = versions.length ? `<section class="search-version-coverage"><h3>按版本查看资料覆盖</h3><p>仅统计所选来源；版本记录按项目范围统计，受控/培训资料保留各自适用范围。资料数量表示已登记覆盖，命中数量还受机型、市场、复核状态等当前条件影响。未命中不代表不支持。</p><div class="search-coverage-grid">${versions.map(row => `<article><button type="button" class="text-button" data-search-focus-version="${escapeAttribute(row.version)}">${escapeHtml(row.version.replace('.*', '.XX'))} · 只看此版本</button><p>${escapeHtml(statusLabels[row.status] || '状态待确认')}</p><small>可检索 ${row.ready_count} · 待索引/更新 ${row.pending_count} · 不可读取 ${row.unavailable_count} · 无文字 ${row.empty_count}</small><p>${escapeHtml(versionHitDescription(row, row))}</p>${row.pending_count ? '<button type="button" class="text-button" data-search-result-refresh>更新资料索引</button>' : ''}${row.status === 'no_materials' || row.empty_count || row.unavailable_count ? '<button type="button" class="text-button" data-search-coverage-register>补充该版本资料</button>' : ''}</article>`).join('')}</div>${coverage.unversioned_files ? `<p>另有 ${coverage.unversioned_files} 份资料无法确定版本，未计入上表；多版本文件需完成索引后才能识别工作表版本。</p>` : ''}${coverage.versions_truncated ? '<p>仅展示前 200 个版本，请缩小版本范围查看其余版本。</p>' : ''}</section>` : '';
  return `${versionMarkup}<details class="search-coverage"><summary>资料覆盖与缺口 · ${files.indexed_files || 0}/${files.registered_files || 0} 份已登记资料已索引${issues.length ? ` · ${issues.length} 项待处理` : ''}</summary><p>版本记载仅覆盖下列已入库版本；补充资料按文件独立检索。未找到描述不能据此判断不支持。</p>${projects}${issues.slice(0, 12).map(item => `<p><strong>${escapeHtml(item.title)}</strong>：${escapeHtml(item.action)}</p>`).join('')}${issues.length > 12 ? `<p>另有 ${issues.length - 12} 项，可在受控资料页查看。</p>` : ''}<p>此清单不包含尚未登记的磁盘文件。可用“补充历史资料”接入缺失材料。</p></details>`;
}

function setSearchFiltersVisible(visible) {
  const panel = document.querySelector('#search-filters-panel');
  const button = document.querySelector('#search-filters-toggle');
  if (!panel || !button) return;
  panel.hidden = !visible;
  button.setAttribute('aria-expanded', String(Boolean(visible)));
  button.textContent = visible ? '收起筛选' : '筛选';
}

function positionSearchProject(view) {
  document.body.classList.toggle('review-focused', view === 'review');
  if (!workbenchConfig.embedded) return;
  const context = document.querySelector('#project-context-actions');
  const target = document.querySelector(view === 'search' ? '.scenario-controls' : '.topbar-actions');
  if (context && target && context.parentElement !== target) {
    const queryLabel = view === 'search' ? target.querySelector?.('#scenario-query-label') : null;
    if (queryLabel) target.insertBefore(context, queryLabel);
    else target.prepend(context);
  }
  document.body.classList.toggle('search-focused', view === 'search');
}

function compactSearchSourceNotice(result) {
  const problems = Object.entries(result.source_errors || {});
  if (!problems.length) return '';
  return `<details class="compact-source-notice"><summary>${problems.length} 类来源受限，结果可能不完整 · 查看说明</summary><ul>${problems.map(([source, reason]) => `<li><strong>${escapeHtml(SEARCH_SOURCE_LABELS[source] || source)}</strong>：${escapeHtml(reason)}</li>`).join('')}</ul></details>`;
}

function compactSearchCard(item, result, action, familyEvidence, evidenceMatches = []) {
  const query = item.matched_query || result.query || '';
  const text = item.detail_evidence?.excerpt || item.matched_text || item.title || '';
  const title = item.config_evidence ? item.title : item.source_type === 'release' && item.version ? `版本 ${item.version}` : item.title;
  const verification = item.verification || 'not_applicable';
  const cautious = ['unverified', 'pending_review'].includes(verification);
  const evidence = item.evidence_kind ? searchEvidenceLabel(item.evidence_kind) : '';
  const version = item.source_type !== 'release' && item.version ? `<span class="compact-source-version">版本 ${escapeHtml(item.version)}</span>` : '';
  const format = item.file_format ? `<span>${escapeHtml(fileFormatLabel(item.file_format))}</span>` : '';
  const detailLabel = item.detail_evidence?.excerpt ? `原文章节节选（${item.detail_evidence.verification ? verificationLabel(item.detail_evidence.verification) : '状态见预览'}）：` : '';
  const excerpt = text !== title ? `<p class="compact-result-excerpt${item.config_evidence ? ' config-record-excerpt' : ''}">${detailLabel ? `<small>${escapeHtml(detailLabel)}</small>` : ''}${highlightSearchText(text, query)}</p>` : '';
  const compare = evidenceMatches.length <= 1 ? searchComparisonButton(item, evidenceMatches[0] || {}, result.query) : '';
  const limitations = [item.match_kind === 'related' ? '关联线索' : '', item.is_stale ? '索引待更新' : '', evidence, item.detail_evidence_notice || ''].filter(Boolean);
  const details = `<details class="compact-result-details"><summary>更多信息${evidenceMatches.length > 1 ? ` · ${evidenceMatches.length} 处依据` : ''}</summary><div><p>${escapeHtml(item.scope || '适用范围未登记')} · ${escapeHtml(item.locator || '位置未注明')}</p>${text.length > 220 ? `<p class="compact-full-text">${highlightSearchText(text, query)}</p>` : ''}${familyEvidence}</div></details>`;
  return `<article class="unified-search-result compact-search-result"><header><h3>${escapeHtml(title || '来源资料')}</h3><span class="pill ${cautious ? 'warning' : ''}">${escapeHtml(verificationLabel(verification))}</span></header><div class="compact-result-context"><span>${escapeHtml(item.source_label || '资料')}</span>${format}${version}<span>${escapeHtml(item.scope || '适用范围未登记')}</span>${limitations.map(label => `<span class="compact-evidence-note">${escapeHtml(label)}</span>`).join('')}</div>${excerpt}<footer><div class="search-result-actions">${action}${compare}</div>${details}</footer></article>`;
}

function compactSearchAnswer(result, groups = []) {
  const records = result.earliest_records || [];
  if (!records.length) return '';
  return `<section class="compact-search-answer" aria-label="查询结论"><span class="answer-eyebrow">版本库最早记载</span>${records.map(item => {
    const suffix = item.version ? ` · ${item.version}` : '';
    const project = suffix && item.scope?.endsWith(suffix) ? item.scope.slice(0, -suffix.length) : item.scope;
    const viewItem = state.searchSourceGroup === 'release_note' && ['config', 'config_note'].includes(state.searchReleaseCategory) ? {...item, detail_evidence:null} : item;
    const action = resultGroupCoversDetail(viewItem, groups) ? '' : searchEvidenceActions(viewItem, result.query, result.query, 'text-button');
    const notice = item.detail_evidence_notice ? `<small>${escapeHtml(item.detail_evidence_notice)}</small>` : '';
    return `<div class="answer-record"><strong>${escapeHtml(item.version || item.scope || '版本待核对')}</strong><span>${escapeHtml(project || '项目未注明')}</span>${action}${notice}</div>`;
  }).join('')}<p>仅限当前检索范围的版本库记录，不代表首次支持；历史补充资料需另行核对。</p></section>`;
}

function searchEvidenceGroupKey(item) {
  const id = String(item.chapter_group_id || '');
  return /^[0-9a-f]{64}$/.test(id) && !item.is_stale && preferredSearchEvidence(item) ? id : null;
}

function groupSearchResults(items) {
  const groups = [], byKey = new Map();
  for (const item of items) {
    const key = searchEvidenceGroupKey(item);
    if (key && byKey.has(key)) byKey.get(key).items.push(item);
    else {
      const group = { key, items: [item] };
      groups.push(group);
      if (key) byKey.set(key, group);
    }
  }
  return groups;
}

function searchGroupItemSummary(item, originalQuery = '') {
  const format = fileFormatLabel(item.file_format) || (item.evidence_kind === 'source_snapshot' ? 'Release 快照' : item.evidence_kind === 'version_record' ? '版本记录' : '资料');
  const labels = [item.source_label || '资料', format, verificationLabel(item.verification || 'not_applicable'), item.is_stale ? '索引待更新' : '', item.is_current === false ? '历史版本' : '', item.match_kind === 'related' ? '关联线索' : '', item.evidence_kind ? searchEvidenceLabel(item.evidence_kind) : '', item.scope || '适用范围未登记', item.locator || '位置未注明', item.detail_evidence_notice || '', item.detail_evidence?.notice || ''].filter(Boolean);
  const original = { ...item, detail_evidence: null };
  const matches = item.version_matches?.length ? item.version_matches : (item.family_matches || []);
  const action = searchEvidenceActions(original, item.matched_query || originalQuery, originalQuery, 'text-button');
  const compare = matches.length <= 1 ? searchComparisonButton(original, matches[0] || {}, originalQuery) : '';
  const positions = matches.length > 1 ? `<div class="search-group-positions">${matches.map(match => `<p>${escapeHtml(match.version || '版本未注明')} · ${escapeHtml(match.locator || '')} ${match.text && !(state.searchReleaseCategory === 'function' && item.config_evidence && match.locator === item.locator) ? highlightSearchText(match.text, match.query || originalQuery) : ''} ${searchEvidenceActions({...original, locator:match.locator, match_count:1}, match.query || originalQuery, originalQuery, 'text-button')}${searchComparisonButton(original, match, originalQuery)}</p>`).join('')}</div>` : '';
  const text = state.searchReleaseCategory === 'function' && item.config_evidence ? item.detail_evidence?.excerpt : (item.config_evidence || item.matched_text);
  const excerpt = text ? `<p${item.config_evidence ? ' class="search-config-evidence"' : ''}>${highlightSearchText(text, item.matched_query || originalQuery)}</p>` : '';
  return `<li data-group-preview="${escapeAttribute(item.preview_id || '')}"><span>${labels.map(escapeHtml).join(' · ')}<b data-group-selected></b></span>${excerpt}<div>${action}${compare}</div>${positions}</li>`;
}

function searchConfigurationSummary(items, query) {
  if (!items.length) return '';
  const preferred = items.find(item => item.preview_id?.startsWith('release:table:')) || items[0];
  const text = preferred.config_evidence.split('\n')[0];
  const normalize = value => String(value || '').trim().replace(/\s+/g, ' ');
  const columnPattern = value => {
    const chars = Array.from(normalize(value));
    const escape = char => char.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return chars.map((char, index) => {
      const previous = chars[index - 1] || '';
      const boundary = previous && ((/[\u3400-\u9fff]/.test(previous) && /[A-Za-z0-9]/.test(char)) || (/[A-Za-z0-9]/.test(previous) && /[\u3400-\u9fff]/.test(char)));
      return (boundary ? '\\s*' : '') + (char === ' ' ? '\\s+' : escape(char));
    }).join('');
  };
  const columns = text.split('|').map(part => part.trim());
  const rowPattern = columns.length >= 5 ? new RegExp(`^${columns.map(columnPattern).join('\\s+')}$`, 'u') : null;
  const fields = columns.length >= 5 ? new Map([
    ['IPN', columns[1]], ['适用机型/探头', columns[3]], ['变更说明', columns.slice(4).join(' | ')],
  ]) : new Map();
  const duplicateTitle = columns.length >= 5 ? new Set([`${columns[0]}（${columns[2]}）`, `${columns[0]}(${columns[2]})`]) : new Set();
  const seen = new Set([normalize(text)]);
  const additional = [];
  for (const item of items) for (const raw of item.config_evidence.split('\n')) {
    const line = raw.trim(), key = normalize(line);
    if (!key || seen.has(key)) continue;
    const field = line.match(/^(IPN|适用机型\/探头|变更说明)\s*[：:]\s*(.*)$/i);
    if ((rowPattern && rowPattern.test(line)) || duplicateTitle.has(line)
        || (field && fields.has(field[1]) && normalize(fields.get(field[1])) === normalize(field[2]))
        || line === '更新后，各功能支持的探头/应用如下：') continue;
    seen.add(key); additional.push(line);
  }
  return `<p class="compact-result-excerpt config-record-excerpt"><strong>配置变更：</strong>${highlightSearchText([text, ...additional].join('\n'), query)}</p>`;
}

function renderSearchGroups(items, renderCard, originalQuery = '') {
  return groupSearchResults(items).map(group => {
    if (group.items.length === 1) return renderCard(group.items[0]);
    const first = group.items.find(item => item.evidence_kind === 'source_snapshot')
      || group.items.find(item => item.source_type === 'release') || group.items[0];
    const detail = first.detail_evidence;
    const project = group.items.find(item => item.source_type === 'release')?.scope || first.scope || '';
    const query = first.matched_query || originalQuery;
    const configItems = state.searchReleaseCategory === 'all' ? group.items.filter(item => item.config_evidence) : [];
    const configSummary = searchConfigurationSummary(configItems, originalQuery);
    const action = `<button type="button" class="ghost-button" data-search-result-preview="${escapeAttribute(detail.source_id)}" data-search-result-locator="${escapeAttribute(detail.locator)}" data-search-result-query="${escapeAttribute(query)}" data-search-result-input-query="${escapeAttribute(originalQuery)}">查看完整功能描述</button>`;
    return `<article class="search-evidence-group chapter-search-group"><header><h3>${escapeHtml(detail.title || '原文章节')}</h3><span class="pill warning">${escapeHtml(verificationLabel(detail.verification || 'unverified'))}</span></header><div class="compact-result-context"><span>${escapeHtml(project)}</span></div><p class="compact-result-excerpt">${highlightSearchText(detail.excerpt || '', query)}</p>${configSummary}<div class="search-result-actions">${action}</div><details class="search-group-details"><summary>来源依据（${group.items.length}）</summary><ul class="search-group-summaries">${group.items.map(item => searchGroupItemSummary(item, originalQuery)).join('')}</ul></details></article>`;
  }).join('');
}

function resultGroupCoversDetail(item, groups) {
  const detail = preferredSearchEvidence(item);
  return Boolean(detail && groups.some(group => group.items.length > 1 && group.items.some(member => {
    const candidate = preferredSearchEvidence(member);
    return candidate && candidate.preview_id === detail.preview_id && candidate.locator === detail.locator
      && member.preview_id === item.preview_id && member.locator === item.locator;
  })));
}

function searchTaxonomyMarkup(result) {
  const sources = result.taxonomy_counts?.sources || {};
  const categories = result.taxonomy_counts?.release_categories || {};
  const group = state.searchSourceGroup || 'release_note';
  const category = state.searchReleaseCategory || 'all';
  const tab = (key, label, count, selected, attr) => `<button type="button" role="tab" ${attr}="${escapeAttribute(key)}" aria-selected="${selected}" tabindex="${selected ? '0' : '-1'}">${escapeHtml(label)} <span>${Number(count) || 0}</span></button>`;
  const sourceTabs = [['release_note', 'Release Note'], ['whitepaper', '白皮书'], ['other', '其他资料']]
    .map(([key, label]) => tab(key, label, sources[key], key === group, 'data-search-source-group')).join('');
  const categoryTabs = group === 'release_note'
    ? `<div class="search-taxonomy-categories" role="tablist" aria-label="Release Note 分类">${tab('all', '全部', sources.release_note, category === 'all', 'data-search-release-category')}${Object.entries(categoryLabels).filter(([key]) => Number(categories[key]) > 0 || key === category).map(([key,label]) => tab(key, label, categories[key], key === category, 'data-search-release-category')).join('')}</div>` : '';
  const models = result.whitepaper_models?.options || state.searchWhitepaperOptions || [];
  const selectedModel = state.searchWhitepaperModel || result.whitepaper_models?.selected || '';
  const modelSelector = group === 'whitepaper' && models.length
    ? `<label class="search-whitepaper-model" title="型号可能取自资料名称，适用范围以原文与复核状态为准">白皮书型号 <select data-search-whitepaper-model aria-label="白皮书型号">${models.map(option => `<option value="${escapeAttribute(option.value)}" ${option.value === selectedModel ? 'selected' : ''}>${escapeHtml(option.label)}（${Number(option.count) || 0}）</option>`).join('')}</select></label>` : '';
  return `<nav class="search-taxonomy" aria-label="检索结果分类"><div class="search-taxonomy-sources" role="tablist" aria-label="资料类型">${sourceTabs}</div>${categoryTabs}${modelSelector}</nav>`;
}

function restoreSearchWhitepaperSelection(params) {
  state.searchWhitepaperModel = params.whitepaper_model || '';
  state.searchWhitepaperSelectionMode = params.whitepaper_model && params.whitepaper_model_mode !== 'auto' ? 'selected' : 'auto';
  // Bind the restored automatic choice to the first request using this URL.
  state.searchWhitepaperAutoQueryKey = null;
}

function selectSearchTaxonomy(kind, value) {
  if (kind === 'source' && ['release_note', 'whitepaper', 'other'].includes(value)) state.searchSourceGroup = value;
  else if (kind === 'category' && (value === 'all' || Object.hasOwn(categoryLabels, value))) state.searchReleaseCategory = value;
  else if (kind === 'model' && (state.searchWhitepaperOptions || []).some(option => option.value === value)) {
    state.searchWhitepaperModel = value;
    state.searchWhitepaperSelectionMode = 'selected';
  }
  else return false;
  state.searchPage = 1;
  state.searchTaxonomyFocus = { kind, value };
  searchUnified().catch(error => showNotice(error.message));
  return true;
}

function renderUnifiedSearch(result) {
  state.searchComparisonOptions = [];
  const container = document.querySelector('#release-search-result');
  renderSavedSearches();
  const sourceLabels = SEARCH_SOURCE_LABELS;
  const errors = Object.entries(result.source_errors || {}).map(([source, message]) => `<p class="search-source-error"><strong>${escapeHtml(sourceLabels[source] || source)}</strong>：${escapeHtml(message)}</p>`).join('');
  const configView = state.searchSourceGroup === 'release_note' && ['config', 'config_note'].includes(state.searchReleaseCategory);
  const renderCard = rawItem => {
    const item = configView && rawItem.config_evidence ? {...rawItem, detail_evidence:null, matched_text:rawItem.config_evidence} : rawItem;
    const verification = item.verification || 'not_applicable';
    const matchQuery = item.matched_query || result.query || '';
    const excerpt = item.detail_evidence?.excerpt || item.matched_text || '';
    const evidenceMatches = item.version_matches?.length ? item.version_matches : (item.family_matches || []);
    const familyEvidence = evidenceMatches.length > 1 ? `<section class="search-family-evidence"><strong>${item.version_matches?.length ? '所选版本的原文位置' : '本资料中提及的能力与版本'}（展示 ${evidenceMatches.length} 处，最多 200 处）</strong>${evidenceMatches.map(match => `<article><p><strong>${escapeHtml(match.version || '版本未注明')}</strong> · ${escapeHtml(match.locator)}</p><p>${highlightSearchText(match.text, match.query)}</p>${searchQueryOrigin(match.query, result.query)}${searchComparisonButton(item, match, result.query)}<button type="button" class="text-button" data-search-result-preview="${escapeAttribute(item.preview_id)}" data-search-result-locator="${escapeAttribute(match.locator)}" data-search-result-query="${escapeAttribute(match.query)}" data-search-result-input-query="${escapeAttribute(result.query)}">查看此处原文</button></article>`).join('')}</section>` : '';
    const previewActions = searchEvidenceActions(item, matchQuery, result.query);
    const action = previewActions || (item.source_type === 'release'
      ? `<button type="button" class="ghost-button" data-search-release-version="${escapeAttribute(item.version || '')}" data-search-project-id="${escapeAttribute(item.project_id || '')}">打开版本</button>`
      : item.source_type === 'config'
        ? `<button type="button" class="ghost-button" data-search-result-config="${escapeAttribute(item.scope || '')}">打开配置查询</button>`
        : item.detail_action
          ? `<a class="ghost-button" href="${escapeAttribute(buildHash(item.detail_action.view, item.detail_action.params))}">查看来源详情</a>`
          : item.source_type === 'term'
            ? '<button type="button" class="ghost-button" data-search-result-term>打开术语词典</button>' : '');
    if (typeof workbenchConfig !== 'undefined' && workbenchConfig.embedded) return compactSearchCard(item, result, action, familyEvidence, evidenceMatches);
    return `<article class="unified-search-result"><div class="unified-search-result-meta"><span class="pill">${escapeHtml(item.source_label)}</span><span class="pill ${verification === 'unverified' || verification === 'pending_review' || item.is_stale ? 'warning' : ''}">${escapeHtml(verificationLabel(verification))}</span>${item.source_status === 'source_live' ? '<span class="pill">实时只读</span>' : ''}${item.is_stale ? '<span class="pill warning">索引待更新</span>' : ''}${item.file_format ? `<span class="change-tag">${escapeHtml(fileFormatLabel(item.file_format))}</span>` : ''}<span class="search-result-scope">${escapeHtml(item.scope)}</span></div><h3>${escapeHtml(item.title)}</h3><p class="strategy-note">${item.match_kind === 'related' ? '关联线索' : '原词命中'} · ${escapeHtml(matchQuery)}${item.version ? ` · 版本 ${escapeHtml(item.version)}` : ''}</p>${item.evidence_kind ? `<p class="strategy-note">${escapeHtml(searchEvidenceLabel(item.evidence_kind))}</p>` : ''}${item.detail_evidence_notice ? `<p class="strategy-note">${escapeHtml(item.detail_evidence_notice)}</p>` : ''}<p class="search-result-locator">${escapeHtml(item.locator || '')}</p>${excerpt ? `<p class="release-search-match"><small>${item.detail_evidence?.excerpt ? '原文章节节选' : '匹配原文'}</small><span>${highlightSearchText(excerpt, matchQuery)}</span></p>` : ''}${familyEvidence}${evidenceMatches.length <= 1 ? searchComparisonButton(item, evidenceMatches[0] || {}, result.query) : ''}${action ? `<div class="search-result-actions">${action}</div>` : ''}</article>`;
  };
  const groups = groupSearchResults(result.results);
  const cards = renderSearchGroups(result.results, renderCard, result.query || '');
  const hasGroupedChapters = groups.some(group => group.items.length > 1);
  const pageCount = Math.max(1, Math.ceil(result.total / result.page_size));
  const groupNote = hasGroupedChapters && pageCount > 1 ? '<p class="search-group-note">仅合并本页同章来源，其他页可能还有相关来源。</p>' : '';
  const pagination = pageCount > 1 ? `<nav class="search-pagination" aria-label="搜索结果分页"><button type="button" class="ghost-button" data-search-page="${result.page - 1}" ${result.page <= 1 ? 'disabled' : ''}>上一页</button><span>第 ${result.page} / ${pageCount} 页 · 共 ${result.total} 条</span><button type="button" class="ghost-button" data-search-page="${result.page + 1}" ${result.page >= pageCount ? 'disabled' : ''}>下一页</button></nav>` : '';
  const pageSummary = hasGroupedChapters ? `本页 <strong>${groups.length}</strong> 项内容 · ${result.results.length} 条来源` : `<strong>${result.total}</strong> 条结果`;
  const count = `<div class="release-search-summary">${pageSummary} · ${result.scope === 'all' ? '全部项目' : escapeHtml(activeProject()?.name || '当前项目')}</div>`;
  const taxonomy = searchTaxonomyMarkup(result);
  const earliest = (result.earliest_records || []).map(item => `<p><strong>版本库内最早记载：${escapeHtml(item.scope)}</strong> · ${escapeHtml(searchEvidenceLabel(item.evidence_kind))} ${resultGroupCoversDetail(item, groups) ? '' : searchEvidenceActions(configView ? {...item,detail_evidence:null} : item, result.query, result.query, 'text-button')} ${item.detail_evidence_notice ? escapeHtml(item.detail_evidence_notice) : ''}</p>`).join('');
  const evidenceSummary = earliest ? `<section class="search-evidence-summary">${earliest}<p>依据当时版本记录，不使用当前功能说明回推历史；历史补充资料需另行核对。最早记载不等于首次支持，仍需核对原文、资料覆盖和适用范围。</p></section>` : '';
  if (typeof workbenchConfig !== 'undefined' && workbenchConfig.embedded) {
    const answer = state.searchSourceGroup === 'release_note' ? compactSearchAnswer(result, groups) : '';
    const compactCount = `<div class="release-search-summary">${pageSummary}</div>`;
    const showTaskSummary = ['family', 'version'].includes(result.task);
    const taskSummary = showTaskSummary ? searchTaskSummary(result) : '';
    const diagnostics = `<details class="search-evidence-details"><summary>检索说明与资料覆盖</summary>${showTaskSummary ? '' : searchTaskSummary(result)}${searchCoverageMarkup(result.coverage)}</details>`;
    container.innerHTML = `${compactSearchSourceNotice(result)}${taxonomy}${answer}${compactCount}${taskSummary}<section id="search-comparison-tray" class="search-comparison-tray" aria-label="待对照原文" aria-live="polite"></section>${cards ? `${groupNote}<div class="release-search-results">${cards}</div>${pagination}` : searchEmptyMarkup(result)}${diagnostics}`;
    renderSearchComparisonTray();
    restoreTaxonomyFocus(container);
    return;
  }
  container.innerHTML = `${taxonomy}${count}${errors}${searchTaskSummary(result)}${state.searchSourceGroup === 'release_note' ? evidenceSummary : ''}${searchCoverageMarkup(result.coverage)}<section id="search-comparison-tray" class="search-comparison-tray" aria-label="待对照原文" aria-live="polite"></section>${cards ? `${groupNote}<div class="release-search-results">${cards}</div>${pagination}` : searchEmptyMarkup(result)}`;
  renderSearchComparisonTray();
  restoreTaxonomyFocus(container);
}

function restoreTaxonomyFocus(container) {
  const target = state.searchTaxonomyFocus;
  if (!target) return;
  const selector = target.kind === 'model' ? '[data-search-whitepaper-model]' : target.kind === 'source'
    ? `[data-search-source-group="${target.value}"]` : `[data-search-release-category="${target.value}"]`;
  container.querySelector(selector)?.focus();
  state.searchTaxonomyFocus = null;
}

function focusedTaxonomyControl(container) {
  const active = document.activeElement;
  if (!active || !container.contains(active)) return null;
  if (active.hasAttribute('data-search-whitepaper-model')) return { kind: 'model', value: active.value };
  if (active.hasAttribute('data-search-source-group')) return { kind: 'source', value: active.getAttribute('data-search-source-group') };
  if (active.hasAttribute('data-search-release-category')) return { kind: 'category', value: active.getAttribute('data-search-release-category') };
  return null;
}

async function searchUnified(query = document.querySelector('#release-search').value) {
  const needle = query.trim();
  renderSearchFilters();
  const requestId = ++state.searchRequest;
  window.clearTimeout(state.searchTimer);
  state.searchController?.abort();
  state.searchController = new AbortController();
  const container = document.querySelector('#release-search-result');
  if (!needle) {
    state.searchComparison = [];
    state.searchComparisonKey = '';
    saveSearchComparison();
    container.innerHTML = '<p class="empty-state compact">输入关键词开始搜索。结果会显示来源、复核状态和原文位置。</p>';
    syncLocation();
    return;
  }
  const sources = selectedSearchSources();
  if (!sources.length) {
    container.innerHTML = '<p class="empty-state compact">请至少选择一个搜索来源。</p>';
    return;
  }
  const params = new URLSearchParams({
    q: needle,
    sources: [...sources].sort().join(','),
    scope: document.querySelector('#release-search-scope').value,
    market: document.querySelector('#release-search-market').value,
    model: document.querySelector('#release-search-model').value.trim(),
    country: document.querySelector('#release-search-country').value.trim().toUpperCase(),
    verification: document.querySelector('#release-search-verification').value,
    current_only: String(document.querySelector('#release-search-current').checked),
    page: String(state.searchPage),
    page_size: '40',
    source_group: state.searchSourceGroup || 'release_note',
    release_category: state.searchSourceGroup === 'release_note' ? (state.searchReleaseCategory || 'all') : 'all',
    whitepaper_model: state.searchWhitepaperModel || '',
    ...searchTaskParams(),
  });
  const comparisonKey = JSON.stringify({ query: needle, project: state.activeProjectId, filters: [...params].filter(([key]) => !['page', 'source_group', 'release_category', 'whitepaper_model'].includes(key)) });
  if (state.searchWhitepaperSelectionMode !== 'selected') {
    if (state.searchWhitepaperAutoQueryKey && comparisonKey !== state.searchWhitepaperAutoQueryKey) {
      state.searchWhitepaperModel = '';
      params.set('whitepaper_model', '');
    }
    state.searchWhitepaperAutoQueryKey = comparisonKey;
  }
  if (comparisonKey !== state.searchComparisonKey) state.searchComparison = restoreSearchComparison(comparisonKey);
  state.searchComparisonKey = comparisonKey;
  saveSearchComparison();
  const pendingFocus = state.searchTaxonomyFocus;
  const taxonomy = pendingFocus && state.searchTaxonomyKey === comparisonKey
    ? searchTaxonomyMarkup({ taxonomy_counts: state.searchTaxonomyCounts }) : '';
  container.innerHTML = `${taxonomy}<p class="empty-state compact" role="status"><span class="loading-dot"></span>正在搜索已接入来源…</p>`;
  restoreTaxonomyFocus(container);
  if (pendingFocus) syncLocation();
  try {
    const result = await api(projectPath(`/api/v1/workbench/search?${params.toString()}`), { signal: state.searchController.signal });
    if (requestId !== state.searchRequest) return;
    state.searchTaxonomyKey = comparisonKey;
    state.searchTaxonomyCounts = result.taxonomy_counts;
    state.searchWhitepaperModel = result.whitepaper_models?.selected || '';
    state.searchWhitepaperOptions = result.whitepaper_models?.options || [];
    state.searchTaxonomyFocus = focusedTaxonomyControl(container);
    renderUnifiedSearch(result);
    document.querySelector('#search-index-status').textContent = searchIndexStatusLabel(result.index);
    syncLocation();
  } catch (error) {
    if (error.name !== 'AbortError' && requestId === state.searchRequest) {
      state.searchTaxonomyFocus = focusedTaxonomyControl(container);
      container.innerHTML = `${taxonomy}<p class="empty-state compact" role="alert">搜索失败：${escapeHtml(error.message)}</p>`;
      restoreTaxonomyFocus(container);
    }
  }
}

function mergeSectionTextBlocks(blocks) {
  const result = [];
  for (const block of blocks) {
    const last = result[result.length - 1];
    if (block.type === 'text' && last?.type === 'text' && block.locator && block.locator === last.locator) {
      last.text += String(block.text || '');
    } else {
      result.push({ ...block, ...(block.type === 'text' ? { text: String(block.text || '') } : {}) });
    }
  }
  return result;
}

function sourceImageMarkup(block, alt) {
  const data = String(block.data_url || '');
  if (data.length > 11000000 || !/^data:image\/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/]+={0,2}$/i.test(data)) return '';
  return `<figure class="source-document-figure"><img src="${escapeAttribute(data)}" alt="${escapeAttribute(alt)}" loading="lazy"></figure>`;
}

function searchPreviewSectionMarkup(preview, query) {
  const section = preview.section;
  if (preview.locator_status === 'unresolved' || !section?.complete || !section.locator || typeof section.content !== 'string' || !section.content.trim()) return '';
  let omittedImage = false;
  const blocks = Array.isArray(section.blocks) && section.blocks.length ? mergeSectionTextBlocks(section.blocks).map(block => {
    if (block.type === 'text') return `<p>${highlightSearchText(String(block.text || ''), query)}</p>`;
    if (block.type === 'image') {
      const markup = sourceImageMarkup(block, `章节 ${section.section_number || ''} 原文图片`);
      if (markup) return markup;
      omittedImage = true;
      return '';
    }
    return '';
  }).join('') : `<p>${highlightSearchText(section.content, query)}</p>`;
  const imageNotice = (section.has_images && section.images_complete === false) || omittedImage
    ? '<p role="alert" class="search-section-image-warning">部分章节图片无法显示，请打开原文件核对。</p>' : '';
  const heading = (section.has_images && section.images_complete === false) || omittedImage ? '完整章节文本（图片不完整）' : '完整章节';
  return `<section class="search-preview-section" aria-label="${heading}"><strong>${heading}${section.section_number ? ` ${escapeHtml(section.section_number)}` : ''} · ${escapeHtml(section.locator)}</strong>${blocks}${imageNotice}<details><summary>章节位置</summary><p>${escapeHtml(section.locator)}${section.start && section.end ? ` · ${escapeHtml(section.start)} 至 ${escapeHtml(section.end)}` : ''}</p></details></section>`;
}

function previewSelectedLocator(preview, locator) {
  return locator || preview.matches?.[0]?.locator || '';
}

function previewMatchNavigation(preview, locator) {
  const matches = preview.matches || [];
  if (!matches.length) return '';
  const index = matches.findIndex(chunk => chunk.locator === locator);
  const button = (chunk, label) => `<button type="button" class="text-button" data-preview-locator="${escapeAttribute(chunk.locator)}">${escapeHtml(label)}</button>`;
  return `<nav class="search-match-navigation" aria-label="文件内命中位置"><strong>本文件 ${preview.match_count} 处匹配${index >= 0 ? ` · 第 ${index + 1} / ${preview.match_count} 处` : ''}</strong>${preview.match_count > matches.length ? `<span>仅列出前 ${matches.length} 处，后续位置请在原文件中查找。</span>` : ''}${index > 0 ? button(matches[index - 1], '上一处') : ''}${index >= 0 && index + 1 < matches.length ? button(matches[index + 1], '下一处') : ''}${index < 0 ? button(matches[0], '跳到第一处匹配') : ''}<details><summary>选择命中位置</summary>${matches.map(chunk => `<button type="button" class="text-button" data-preview-locator="${escapeAttribute(chunk.locator)}"${chunk.locator === locator ? ' aria-current="location"' : ''}>${escapeHtml(chunk.locator)}</button>`).join('')}</details></nav>`;
}

async function openSearchPreview(sourceId, locator = '', query = '', originalQuery = query) {
  const dialog = document.querySelector('#search-preview-dialog');
  const content = document.querySelector('#search-preview-content');
  const title = document.querySelector('#search-preview-title');
  const meta = document.querySelector('#search-preview-meta');
  const requestId = ++state.searchPreviewRequest;
  const requestedLocator = locator;
  if (state.activeView === 'search') {
    state.previewLocation = {preview: sourceId, locator, preview_query: query, preview_input: originalQuery};
    syncLocation();
  }
  title.textContent = '资料预览';
  meta.textContent = '正在读取索引…';
  state.preview = null;
  dialog.querySelector('[data-citation-fallback]').hidden = true;
  document.querySelector('#search-preview-actions').innerHTML = '';
  content.innerHTML = '<p class="empty-state compact"><span class="loading-dot"></span>正在安全检查并读取资料…</p>';
  if (!dialog.open) dialog.showModal();
  try {
    const params = new URLSearchParams({ locator, q: query });
    const preview = await api(`/api/v1/workbench/search-index/sources/${encodeURIComponent(sourceId)}/preview?${params}`);
    if (requestId !== state.searchPreviewRequest || !dialog.open) return;
    locator = previewSelectedLocator(preview, locator);
    if (state.activeView === 'search') {
      state.previewLocation = {preview: sourceId, locator, preview_query: query, preview_input: originalQuery};
      syncLocation();
    }
    title.textContent = preview.title;
    meta.textContent = `${fileFormatLabel(preview.file_format)} · ${preview.scope} · ${verificationLabel(preview.verification)}`;
    updatePreviewTools({ ...preview, query, originalQuery }, sourceId, locator);
    const missingLocation = locator && (preview.locator_status === 'unresolved' || (preview.locator_status !== 'toc_redirect' && !preview.chunks.some(chunk => chunk.locator === locator)));
    const queryOrigin = (missingLocation ? '<p role="alert">链接指定的原文位置不可用，请核对原文件并重新选择位置。</p>' : '') + searchQueryOrigin(query, originalQuery);
    const notice = preview.notice ? `<p class="strategy-note">${escapeHtml(preview.notice)}</p>` : '';
    const matchNavigation = previewMatchNavigation(preview, locator);
    const matchedChunk = preview.chunks.find(chunk => chunk.locator === locator);
    const sectionMarkup = searchPreviewSectionMarkup(preview, query);
    const sectionNoticeText = preview.section?.has_images && preview.section.images_complete
      ? String(preview.notice || '').replace('本章节包含图片，请在完整预览中查看。', '').trim()
      : preview.notice || '';
    const sectionNotice = sectionNoticeText ? `<p class="search-preview-notice">${escapeHtml(sectionNoticeText)}</p>` : '';
    const sectionContext = queryOrigin || matchNavigation ? `<details class="search-preview-context"><summary>其他命中与定位</summary>${queryOrigin}${matchNavigation}</details>` : '';
    const sectionReading = sectionNotice + sectionMarkup + sectionContext;
    const fallback = '<p class="strategy-note">未能核实完整章节；以下为匹配片段，其他片段不代表连续正文，请核对原文件。</p>';
    const matchMarkup = matchedChunk ? `<article class="search-preview-chunk search-preview-match"><strong>${escapeHtml(matchedChunk.locator)} · 命中位置</strong><p>${highlightSearchText(matchedChunk.text, query)}</p></article>` : '';
    if (['pdf', 'png', 'jpg', 'jpeg'].includes(preview.file_format)) {
      const pageNumber = searchPdfPageLocator(preview, locator, requestedLocator).match(/第 (\d+) 页/);
      const url = workbenchUrl(`/api/v1/workbench/search-index/sources/${encodeURIComponent(sourceId)}/preview?file=1${preview.file_format === 'pdf' && pageNumber ? `#page=${pageNumber[1]}` : ''}`);
      content.innerHTML = preview.file_format === 'pdf'
        ? searchPdfPreviewMarkup(url, preview.title, sectionMarkup ? sectionReading : notice + queryOrigin + matchNavigation + fallback + matchMarkup, missingLocation ? '<p role="alert">链接指定的原文位置不可用，请核对原文件并重新选择位置。</p>' : '')
        : `<img class="search-preview-image" alt="${escapeAttribute(preview.title)}" src="${escapeAttribute(url)}">`;
      return;
    }
    const otherChunks = preview.chunks.filter(chunk => chunk !== matchedChunk).map(chunk => `<article class="search-preview-chunk"><strong>${escapeHtml(chunk.locator)}</strong><p>${highlightSearchText(chunk.text, query)}</p></article>`).join('');
    content.innerHTML = sectionMarkup
      ? sectionReading
      : preview.chunks.length
        ? notice + queryOrigin + matchNavigation + fallback + matchMarkup + (matchedChunk && otherChunks ? `<details><summary>展开其他已提取原文片段</summary>${otherChunks}</details>` : otherChunks)
        : notice + queryOrigin + '<p class="empty-state compact">文件已登记，但没有可检索的文字层。扫描版文档和图片目前不提供 OCR。</p>';
    if (preview.truncated && !sectionMarkup) content.insertAdjacentHTML('beforeend', '<p class="search-preview-truncated">仅显示命中位置及部分原文，共最多 200 段。</p>');
  } catch (error) {
    if (requestId === state.searchPreviewRequest) content.innerHTML = `<p class="empty-state compact">无法预览：${escapeHtml(error.message)}。若原文件已更新，请先刷新资料索引。</p>`;
  }
}

function searchPdfPageLocator(preview, locator, requestedLocator) {
  if (preview.section?.complete && preview.section.locator && (preview.locator_status === 'toc_redirect' || !requestedLocator)) return preview.section.locator;
  return locator || '';
}

function searchPdfPreviewMarkup(url, title, auxiliary, warning = '') {
  return `${warning}<iframe class="search-preview-frame" title="${escapeAttribute(title)}" src="${escapeAttribute(url)}"></iframe>${auxiliary ? `<details class="search-pdf-auxiliary"><summary>命中与章节内容</summary>${auxiliary}</details>` : ''}`;
}

async function openGlobalSearchConfig(scope) {
  await switchView('strategy');
  setSelectValue('#strategy-market', 'domestic');
  await loadProductStrategyModels();
  const model = scope.split(' · ').slice(1).join(' · ');
  if (model) setSelectValue('#strategy-model', model);
  document.querySelector('#strategy-query').value = document.querySelector('#release-search').value.trim();
  await loadProductStrategies();
}

async function openGlobalSearchVersion(version, projectId = null) {
  if (projectId && Number(projectId) !== Number(state.activeProjectId)) {
    await switchProject(Number(projectId));
  }
  const releaseIndex = state.releases.findIndex(release => release.version === version);
  if (releaseIndex >= 0) {
    state.activeReleaseVersion = version;
    renderReleaseCenter();
  }
  document.querySelector('#global-search-panel').hidden = true;
  switchView('releases');
  window.requestAnimationFrame(() => document.querySelector(`[data-release-version-tab="${CSS.escape(version)}"]`)?.focus({ preventScroll: true }));
}

async function loadCandidates() {
  const project = state.activeProjectId;
  const [candidates, rejectedCandidates] = await Promise.all([
    api(projectPath('/api/v1/import-candidates')),
    api(projectPath('/api/v1/import-candidates?status=rejected')),
  ]);
  if (project !== state.activeProjectId) return;
  state.candidates = candidates;
  state.rejectedCandidates = rejectedCandidates;
  const versions = candidateVersions();
  state.activeCandidateVersion = versions.includes(state.activeCandidateVersion)
    ? state.activeCandidateVersion
    : versions[0] || null;
  state.selectedCandidateIds = new Set([...state.selectedCandidateIds].filter(id => candidates.some(item => String(item.id) === String(id))));
  renderCandidateReview();
  const rejectedContainer = document.querySelector('#rejected-candidate-list');
  const rejectedCount = document.querySelector('#rejected-count');
  if (rejectedCount) rejectedCount.textContent = rejectedCandidates.length;
  if (rejectedContainer) rejectedContainer.innerHTML = rejectedCandidates.length ? rejectedCandidates.map(item => `<article class="candidate-card rejected"><div><span class="pill warning">${escapeHtml(item.version || '')} · 已拒绝</span></div>${renderCandidateBilingual(item)}<div class="candidate-actions"><button class="ghost-button" data-review="restore" data-id="${item.id}">撤销拒绝</button></div></article>`).join('') : '<div class="empty-state compact">没有已拒绝记录。</div>';
}

function candidateQuality(item) {
  if (!item.title_cn || !item.title_en) return 'missing';
  return item.confidence >= .8 ? 'ready' : 'low';
}

function candidateVersions() {
  return [...new Set(state.candidates.map(item => item.version || '未标注'))];
}

function renderCandidateVersionTabs({ focusTab = false } = {}) {
  const versions = candidateVersions();
  const tabs = document.querySelector('#candidate-version-tabs');
  document.querySelectorAll('[data-candidate-version-step]').forEach(button => {
    const activeIndex = versions.indexOf(state.activeCandidateVersion);
    const targetIndex = activeIndex + Number(button.dataset.candidateVersionStep);
    button.disabled = !versions.length || targetIndex < 0 || targetIndex >= versions.length;
  });
  tabs.innerHTML = versions.map(version => {
    const active = version === state.activeCandidateVersion;
    const count = state.candidates.filter(item => (item.version || '未标注') === version).length;
    return `<button type="button" role="tab" class="release-version-tab ${active ? 'active' : ''}" data-candidate-version-tab="${escapeAttribute(version)}" aria-controls="candidate-version-page" aria-selected="${active}" tabindex="${active ? '0' : '-1'}"><span>${escapeHtml(version)}</span><small title="${count} 条待审核">${count} 条</small></button>`;
  }).join('');
  const activeTab = tabs.querySelector('[aria-selected="true"]');
  activeTab?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  if (focusTab) activeTab?.focus();
}

function selectCandidateVersion(version, { focusTab = false } = {}) {
  if (!candidateVersions().includes(version)) return;
  state.activeCandidateVersion = version;
  state.activeCandidateCategory = 'all';
  state.selectedCandidateIds = new Set();
  renderCandidateReview({ focusTab });
}

function currentVersionCandidates() {
  return state.candidates.filter(item => (item.version || '未标注') === state.activeCandidateVersion);
}

function candidateCategories(candidates = currentVersionCandidates()) {
  const present = new Set(candidates.map(item => item.category || 'remark'));
  const preferred = Object.keys(categoryLabels).filter(category => present.has(category));
  return [...preferred, ...[...present].filter(category => !preferred.includes(category))];
}

function renderCandidateCategoryTabs({ focusTab = false } = {}) {
  const versionCandidates = currentVersionCandidates();
  const categories = candidateCategories(versionCandidates);
  if (state.activeCandidateCategory !== 'all' && !categories.includes(state.activeCandidateCategory)) state.activeCandidateCategory = 'all';
  const tabs = document.querySelector('#candidate-category-tabs');
  tabs.innerHTML = ['all', ...categories].map(category => {
    const active = category === state.activeCandidateCategory;
    const count = category === 'all' ? versionCandidates.length : versionCandidates.filter(item => item.category === category).length;
    const label = category === 'all' ? '全部' : categoryLabels[category] || category;
    return `<button type="button" role="tab" class="${active ? 'active' : ''}" data-candidate-category-tab="${escapeAttribute(category)}" aria-controls="candidate-version-page" aria-selected="${active}" tabindex="${active ? '0' : '-1'}">${escapeHtml(label)} · ${count}</button>`;
  }).join('');
  if (focusTab) tabs.querySelector('[aria-selected="true"]')?.focus();
}

function selectCandidateCategory(category, { focusTab = false } = {}) {
  if (category !== 'all' && !candidateCategories().includes(category)) return;
  state.activeCandidateCategory = category;
  state.selectedCandidateIds = new Set();
  renderCandidateReview({ focusCategoryTab: focusTab });
}

function filteredCandidates() {
  const query = document.querySelector('#candidate-search').value.trim().toLocaleLowerCase();
  const quality = document.querySelector('#candidate-quality-filter').value;
  const priority = document.querySelector('#review-priority-filter').value;
  const versionItems = currentVersionCandidates();
  const focusHasRisk = versionItems.some(item => item.review_bucket !== 'ready');
  return state.candidates.filter(item => {
    const searchable = [item.version, item.title_cn, item.title_en, item.raw_cn, item.raw_en]
      .filter(Boolean).join(' ').toLocaleLowerCase();
    return (item.version || '未标注') === state.activeCandidateVersion
      && (!query || searchable.includes(query))
      && (state.activeCandidateCategory === 'all' || item.category === state.activeCandidateCategory)
      && (!quality || candidateQuality(item) === quality)
      && (priority === 'all' || (priority === 'focus' ? !focusHasRisk || item.review_bucket !== 'ready' : item.review_bucket === priority));
  });
}

function reviewStageFromParams(params) {
  if (params.review_mode === 'overview') return 'overview';
  return params.review_mode === 'confirm' || ['version', 'category', 'quality', 'priority', 'q'].some(key => params[key]) ? 'confirm' : 'overview';
}

function setReviewStage(stage, { sync = true } = {}) {
  state.reviewStage = stage === 'confirm' ? 'confirm' : 'overview';
  renderCandidateReview();
  if (sync) syncLocation();
}

function reviewOverviewMarkup(project, candidates, batches) {
  const sources = (project?.sources || []).filter(source => source.enabled !== 0 && source.enabled !== false);
  const paths = sources.length ? sources.map(source => `<p class="review-source-path">${escapeHtml(source.path)}</p>`).join('') : '<p>尚未设置发布目录，请先设置目录。</p>';
  const latest = batches[0];
  const labels = { completed: '最近同步', failed: '同步失败', undone: '最近同步已撤销', running: '正在同步' };
  const recent = latest ? `<p class="review-sync-state">${escapeHtml(labels[latest.status] || '最近同步状态未知')} · ${escapeHtml(formatDateTime(latest.completed_at || latest.created_at))}${latest.status === 'completed' ? ` · 本次新增 ${Number(latest.stats?.candidates_created) || 0} 条待确认` : ''}</p>` : '<p class="review-sync-state">暂无同步记录。</p>';
  const versions = new Set(candidates.map(item => item.version || '未标注'));
  return { source: paths + recent, pending: candidates.length
    ? `<p>待确认总计 ${candidates.length} 条 · ${versions.size} 个版本（含历史记录）</p><button type="button" class="primary-button" data-review-confirm>处理待确认内容</button>`
    : '<p>没有待确认内容。</p>' };
}

function renderReviewOverview() {
  const overview = document.querySelector('#review-overview');
  const detail = document.querySelector('#review-detail');
  const confirming = state.reviewStage === 'confirm';
  if (overview) overview.hidden = confirming;
  if (detail) detail.hidden = !confirming;
  const project = activeProject();
  const markup = reviewOverviewMarkup(project, state.candidates, state.importBatches || []);
  const source = document.querySelector('#review-source-summary');
  const pending = document.querySelector('#review-pending-summary');
  if (source) source.innerHTML = markup.source;
  if (pending) pending.innerHTML = markup.pending;
  const scan = document.querySelector('#scan-notes');
  if (scan) {
    scan.disabled = Boolean(state.reviewSyncing) || !(project?.sources || []).some(item => item.enabled !== 0 && item.enabled !== false);
    scan.textContent = state.reviewSyncing ? '正在同步…' : '扫描并同步文件';
  }
}

function renderCandidateReview({ focusTab = false, focusCategoryTab = false } = {}) {
  renderReviewOverview();
  const versions = candidateVersions();
  const hasCandidates = state.candidates.length > 0;
  const navigation = document.querySelector('.candidate-version-navigation');
  const filters = document.querySelector('.candidate-filter-panel');
  const page = document.querySelector('#candidate-version-page');
  if (navigation) navigation.hidden = versions.length < 2;
  if (filters) filters.hidden = !hasCandidates;
  const filterOptions = document.querySelector('#review-filter-options');
  if (filterOptions) filterOptions.hidden = !hasCandidates;
  page?.classList.toggle('is-empty', !hasCandidates);
  if (!versions.includes(state.activeCandidateVersion)) state.activeCandidateVersion = versions[0] || null;
  renderCandidateVersionTabs({ focusTab });
  renderCandidateCategoryTabs({ focusTab: focusCategoryTab });
  const candidates = filteredCandidates();
  const versionCandidates = currentVersionCandidates();
  const categoryCandidates = state.activeCandidateCategory === 'all'
    ? versionCandidates
    : versionCandidates.filter(item => item.category === state.activeCandidateCategory);
  const categoryTotal = categoryCandidates.length;
  const paired = candidates.filter(item => item.title_cn && item.title_en).length;
  const missingCn = candidates.filter(item => !item.title_cn).length;
  const missingEn = candidates.filter(item => !item.title_en).length;
  const highRisk = candidates.filter(item => item.risk_level === 'high').length;
  const mediumRisk = candidates.filter(item => item.risk_level === 'medium').length;
  document.querySelector('#candidate-filter-summary').textContent = state.activeCandidateVersion
    ? `显示 ${candidates.length}/${categoryTotal} · 高风险 ${highRisk} · 待核对 ${mediumRisk} · 缺中 ${missingCn} · 缺英 ${missingEn}`
    : '没有待审核记录';
  const context = document.querySelector('#review-detail-context');
  if (context) context.textContent = state.activeCandidateVersion ? `版本 ${state.activeCandidateVersion} · 显示 ${candidates.length}/${categoryTotal} 条` : '暂无待确认内容';
  const container = document.querySelector('#candidate-list');
  container.innerHTML = state.reviewStage !== 'confirm' ? '' : candidates.length
    ? renderCandidateHierarchy(candidates, versionCandidates, categoryCandidates)
    : hasCandidates ? '<div class="empty-state compact">当前筛选条件下没有待审核记录。</div>' : '<div class="empty-state compact">暂无待审核记录。</div>';
  // 推荐处置按“当前可见候选”批量取一次，避免每张卡片各发一次请求。
  if (state.reviewStage === 'confirm') ensureCandidateRecommendations(candidates);
}

const candidateRecommendationRequests = { key: '', pending: null };

function ensureCandidateRecommendations(items) {
  const ids = [...new Set(items.map(item => item.id))].sort((a, b) => a - b);
  const key = ids.join(',');
  if (!ids.length) {
    state.candidateRecommendations = {};
    candidateRecommendationRequests.key = '';
    return;
  }
  if (integratedMode()) {
    state.candidateRecommendations = Object.fromEntries(
      items.map(item => [String(item.id), { candidate_id: item.id, action: 'record_only' }])
    );
    candidateRecommendationRequests.key = key;
    return;
  }
  if (key === candidateRecommendationRequests.key) return;
  candidateRecommendationRequests.key = key;
  candidateRecommendationRequests.pending = api('/api/v1/import-candidates/recommendations', {
    method: 'POST',
    body: JSON.stringify({ candidate_ids: ids }),
  }).then(result => {
    const known = new Set(state.candidates.map(item => String(item.id)));
    state.candidateRecommendations = Object.fromEntries(
      result.recommendations
        .filter(recommendation => known.has(String(recommendation.candidate_id)))
        .map(recommendation => [String(recommendation.candidate_id), recommendation])
    );
    renderCandidateReview();
  }).catch(error => {
    candidateRecommendationRequests.key = '';
    showNotice(`推荐处置获取失败：${error.message}`);
  });
}

async function submitCandidate(id) {
  const item = candidateById(id);
  if (!item) return;
  const recommendation = candidateRecommendation(item) || { action: 'record_only' };
  const action = activeCandidateAction(item);
  const defaultMarkets = ['domestic', 'overseas'];
  let payload = {};
  if (action === 'enhance_feature') {
    if (!recommendation.feature_id) return openFeaturePromotion(id);
    payload = {
      promote_to_feature: true,
      feature_id: recommendation.feature_id,
      cn_name: recommendation.cn_name,
      en_name: recommendation.en_name,
      markets: defaultMarkets,
    };
  } else if (action === 'create_feature') {
    const cnName = recommendation.cn_name || item.title_cn;
    const enName = recommendation.en_name || item.title_en;
    if (!cnName || !enName) return openFeaturePromotion(id);
    payload = { promote_to_feature: true, cn_name: cnName, en_name: enName, markets: defaultMarkets };
  }
  await api(`/api/v1/import-candidates/${id}/approve`, { method: 'POST', body: JSON.stringify(payload) });
  delete state.candidateOverrides[String(id)];
  candidateRecommendationRequests.key = '';
  showNotice(action === 'record_only' ? '已记入版本变更。' : `已按推荐提交：${candidateActionLabels[action]}。`);
  await refreshAll();
}

async function confirmCandidates(candidateIds) {
  const ids = [...new Set(candidateIds)];
  if (!ids.length) return showNotice('请先选择待审核记录。');
  if (ids.length >= BULK_ACTION_CONFIRM_THRESHOLD && !window.confirm(`将按推荐处置提交 ${ids.length} 条待审核记录：能建立/关联功能的建档，其余记入版本变更。继续吗？`)) return;
  const result = await api('/api/v1/import-candidates/batch/confirm', { method: 'POST', body: JSON.stringify({ candidate_ids: ids }) });
  state.selectedCandidateIds = new Set();
  ids.forEach(id => delete state.candidateOverrides[String(id)]);
  candidateRecommendationRequests.key = '';
  const skipped = result.skipped_candidates.length;
  const merged = result.merged_candidates.length;
  showNotice(`已按推荐提交 ${result.submitted_candidate_ids.length} 条${merged ? `（其中 ${merged} 条与同版本已有变更记录重复，已合并）` : ''}${skipped ? `；${skipped} 条未能建立功能，已保留待审核。` : '。'}`);
  await refreshAll();
}

async function changeCandidateCategory(id, category) {
  const item = candidateById(id);
  if (!item) return;
  await api(`/api/v1/import-candidates/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ category, title_cn: item.title_cn, title_en: item.title_en }),
  });
  // 分类变了，推荐处置也要重算。
  candidateRecommendationRequests.key = '';
  delete state.candidateOverrides[String(id)];
  showNotice(`分类已改为「${categoryLabels[category] || category}」。`);
  await refreshAll();
}

function candidateIdsAttribute(items) { return items.map(item => item.id).join(','); }

function parseCandidateIds(value = '') {
  return value.split(',').filter(Boolean).map(Number).filter(Number.isInteger);
}

function renderScopeControls(items, scope) {
  const ids = candidateIdsAttribute(items);
  const labels = scope === 'version'
    ? { select: `全选本版本（${items.length} 条）`, confirm: '本版本全部按推荐提交', approve: '本版本全部记入版本' }
    : scope === 'project'
      ? {
        select: `全选全部待审核（${items.length} 条）`,
        confirm: `全部 ${items.length} 条按推荐提交`,
        approve: `全部 ${items.length} 条记入版本`,
      }
      : { select: `全选本分类（${items.length} 条）`, confirm: '本分类全部按推荐提交', approve: '本分类全部记入版本' };
  const confirm = integratedMode() ? '' : `<button class="ghost-button" data-batch-confirm="${ids}" aria-label="${escapeAttribute(`${labels.confirm}，共 ${items.length} 条`)}">${labels.confirm}</button>`;
  return `<div class="candidate-scope-controls" role="toolbar" aria-label="${escapeAttribute(labels.select)}的批量操作"><label><input type="checkbox" data-select-scope="${ids}" ${items.every(item => state.selectedCandidateIds.has(String(item.id))) ? 'checked' : ''}> ${labels.select}</label>${confirm}<button class="ghost-button" data-batch-approve="${ids}" aria-label="${escapeAttribute(`${labels.approve}，共 ${items.length} 条`)}">${labels.approve}</button></div>`;
}

function candidateDetailLines(title, raw) {
  const lines = String(raw || '').split('\n').map(line => line.trim()).filter(Boolean);
  const head = String(title || '').trim();
  return head && lines.length && lines[0] === head ? lines.slice(1) : lines;
}

function renderConfigDetailLines(title, raw) {
  const details = candidateDetailLines(title, raw);
  return details.length
    ? `<ul class="candidate-detail-lines">${details.map(line => `<li>${escapeHtml(line)}</li>`).join('')}</ul>`
    : '';
}

function renderCandidateBilingual(item, evidence = '') {
  const chineseDetail = item.category === 'config' ? renderConfigDetailLines(item.title_cn, item.raw_cn) : '';
  const englishDetail = item.category === 'config' ? renderConfigDetailLines(item.title_en, item.raw_en) : '';
  return `<div class="candidate-bilingual-columns"><section class="candidate-language-column" lang="zh-CN"><small>中文内容</small><p class="${item.title_cn ? '' : 'missing'}">${escapeHtml(item.title_cn || '缺少中文')}</p>${chineseDetail}</section><section class="candidate-language-column" lang="en"><small>English</small><p class="${item.title_en ? '' : 'missing'}">${escapeHtml(item.title_en || 'Missing English')}</p>${englishDetail}</section>${evidence}</div>`;
}

function candidateCategoryOptions(current) {
  return Object.entries(categoryLabels)
    .filter(([value]) => value !== 'source')
    .map(([value, label]) => `<option value="${value}" ${value === current ? 'selected' : ''}>${escapeHtml(label)}</option>`)
    .join('');
}

const candidateActionLabels = {
  record_only: '记入版本变更',
  create_feature: '新建功能',
  enhance_feature: '增强已有功能',
};

function candidateRecommendation(item) {
  return state.candidateRecommendations[String(item.id)] || null;
}

function activeCandidateAction(item) {
  return state.candidateOverrides[String(item.id)]
    || candidateRecommendation(item)?.action
    || 'record_only';
}

function renderCandidateRecommendation(item) {
  if (integratedMode()) return '';
  const recommendation = candidateRecommendation(item);
  if (!recommendation) {
    return '<p class="candidate-recommendation pending"><span>推荐：</span><strong>正在生成…</strong></p>';
  }
  const override = state.candidateOverrides[String(item.id)];
  const action = activeCandidateAction(item);
  const label = override ? candidateActionLabels[override] : recommendation.label;
  const overridden = override && override !== recommendation.action;
  return `<p class="candidate-recommendation"><span>推荐：</span><strong>${escapeHtml(label || candidateActionLabels[action])}</strong><small>${escapeHtml(recommendation.reason || '')}</small>${overridden ? '<em class="candidate-override-note">已改</em>' : ''}</p>`;
}

function renderCandidateCard(item) {
  const quality = candidateQuality(item);
  const qualityLabel = quality === 'ready' ? '语义一致（自动）' : quality === 'missing' ? `缺少${item.title_cn ? '英文' : '中文'}` : '语义匹配待确认';
  // 配置表条目的适用配置与说明已直接显示在卡片上（见 renderConfigDetailLines），
  // 不再折叠进“查看 Word 原文说明”，避免审核时要点开才知道核心内容。
  const hasEvidence = item.category !== 'config' && (item.raw_cn !== item.title_cn || item.raw_en !== item.title_en);
  const evidence = hasEvidence ? `<details class="candidate-evidence"><summary>查看 Word 原文说明</summary>${item.raw_cn ? `<p>${escapeHtml(item.raw_cn)}</p>` : ''}${item.raw_en ? `<p>${escapeHtml(item.raw_en)}</p>` : ''}</details>` : '';
  const configurationButton = item.category === 'config' && item.configuration_table_count ? `<button class="ghost-button" data-configuration-release="${item.release_id}" data-configuration-version="${escapeAttribute(item.version)}">查看配置表</button>` : '';
  const riskLabel = item.risk_level === 'high' ? '高风险' : item.risk_level === 'medium' ? '待核对' : '可快速确认';
  const currentAction = activeCandidateAction(item);
  // 分类就地可选：审核时主要是确认分类，不该埋在「更多 → 编辑内容」里。
  const categoryField = `<label class="candidate-category-field"><span>分类</span><select data-candidate-category="${item.id}">${candidateCategoryOptions(item.category)}</select></label>`;
  const overrideField = integratedMode() ? '' : `<label class="candidate-override-field"><span>改推荐</span><select data-candidate-override="${item.id}"><option value="">按推荐</option><option value="record_only" ${currentAction === 'record_only' && state.candidateOverrides[String(item.id)] ? 'selected' : ''}>记入版本变更</option><option value="create_feature" ${currentAction === 'create_feature' && state.candidateOverrides[String(item.id)] ? 'selected' : ''}>新建功能…</option><option value="enhance_feature">关联到已有功能…</option></select></label>`;
  const promoteAction = integratedMode() ? '' : `<button class="text-button" data-action="promote" data-id="${item.id}">手工建立/关联功能</button>`;
  const selected = state.selectedCandidateIds.has(String(item.id));
  return `<article class="candidate-card risk-${item.risk_level || 'low'}"><label class="candidate-select"><input type="checkbox" data-candidate-select="${item.id}" ${selected ? 'checked' : ''}><span class="sr-only">选择该记录</span></label><div class="candidate-card-meta">${categoryField}<span class="pill risk-pill ${item.risk_level || 'low'}">${escapeHtml(riskLabel)}</span><span class="pill ${quality === 'ready' ? '' : 'warning'}">${qualityLabel}</span><small class="confidence-note">置信度 ${Math.round(item.confidence * 100)}%${item.risk_reasons?.length ? ` · ${escapeHtml(item.risk_reasons.join('、'))}` : ''}</small></div>${renderCandidateBilingual(item, evidence)}<div class="candidate-actions">${renderCandidateRecommendation(item)}<div class="candidate-action-buttons"><button class="primary-button" data-action="confirm" data-id="${item.id}">确认提交</button>${overrideField}${configurationButton}<details class="candidate-more-actions"><summary>更多</summary><div><button class="text-button" data-action="edit" data-id="${item.id}">编辑内容</button>${promoteAction}<button class="text-button danger" data-review="reject" data-id="${item.id}">拒绝记录</button></div></details></div></div></article>`;
}

function renderConfigurationTables(query = '') {
  const container = document.querySelector('#configuration-table-content');
  const folded = query.trim().toLocaleLowerCase();
  const sections = state.configurationTables.flatMap(source => source.tables.map(table => {
    const rows = table.rows.filter(row => !folded || row.some(cell => String(cell).toLocaleLowerCase().includes(folded)));
    if (folded && !rows.length) return '';
    const heading = table.headers.join(' · ');
    return `<section class="configuration-table-section"><div><h3>${escapeHtml(heading)}</h3><small>${rows.length} / ${table.rows.length} 行</small></div><div class="configuration-table-wrap"><table><thead><tr>${table.headers.map(header => `<th>${escapeHtml(header)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></section>`;
  }));
  container.innerHTML = sections.filter(Boolean).join('') || '<p class="empty-state compact">没有匹配的配置行。</p>';
}

async function openConfigurationTables(releaseId, version) {
  state.configurationTables = await api(`/api/v1/releases/${releaseId}/configuration-tables`);
  document.querySelector('#configuration-dialog-title').textContent = `版本 ${version} 配置表`;
  document.querySelector('#configuration-dialog-source').textContent = state.configurationTables.map(item => item.filename).join('、');
  const search = document.querySelector('#configuration-table-search');
  search.value = '';
  renderConfigurationTables();
  document.querySelector('#configuration-dialog').showModal();
}

function archiveMarketRowCount(market) {
  return state.releaseArchive.tables
    .filter(table => table.market === market)
    .reduce((total, table) => total + table.records.length, 0);
}

function archiveEffectiveCount(market) {
  return state.effectiveConfiguration.markets[market]?.records.length || 0;
}

function availableArchiveMarkets() {
  return ['domestic', 'overseas', 'unknown'].filter(market => archiveMarketRowCount(market) || archiveEffectiveCount(market));
}

function archiveTypeCount(type, market = state.archiveMarket) {
  if (type === 'effective_configuration') return archiveEffectiveCount(market);
  return state.releaseArchive.tables
    .filter(table => table.market === market && (type === 'all' || table.table_type === type))
    .reduce((total, table) => total + table.records.length, 0);
}

function renderArchiveMarketTabs() {
  const markets = availableArchiveMarkets();
  if (!markets.includes(state.archiveMarket)) state.archiveMarket = markets.includes('domestic') ? 'domestic' : markets[0] || 'domestic';
  const labels = { domestic: '国内', overseas: '海外', unknown: '未识别市场' };
  document.querySelector('#release-archive-market-tabs').innerHTML = markets.map(market => {
    const active = market === state.archiveMarket;
    return `<button type="button" role="tab" class="${active ? 'active' : ''}" data-archive-market="${market}" aria-controls="release-archive-content" aria-selected="${active}" tabindex="${active ? '0' : '-1'}">${labels[market]} · ${archiveMarketRowCount(market)} 行</button>`;
  }).join('');
}

function archiveModeLabel(snapshotMode) {
  return snapshotMode === 'full_snapshot' ? '完整快照' : snapshotMode === 'partial_update' ? '增量更新' : snapshotMode === 'delta' ? '变更清单' : '前后对照';
}

function renderOriginalArchiveTable(table, records) {
  const sourceRows = records.map(record => ({ record, cells: table.rows[record.row_index] || [] }));
  const columnCount = Math.max(table.headers.length, ...sourceRows.map(item => item.cells.length), 1);
  const headers = Array.from({ length: columnCount }, (_value, index) => table.headers[index] || `列 ${index + 1}`);
  const sourceLabel = marketLabels[table.market] || (table.language === 'cn' ? '中文' : table.language === 'en' ? '英文' : '未知语言');
  return `<section class="archive-table-section"><div class="archive-table-heading"><span><strong>${escapeHtml(releaseTableTypeLabels[table.table_type] || table.table_type)}</strong><small>${escapeHtml(table.filename)} · 原表 ${table.table_index + 1} · ${escapeHtml(sourceLabel)} · ${records.length} 行</small></span><em>${escapeHtml(archiveModeLabel(table.snapshot_mode))}</em></div><div class="archive-original-table-wrap"><table class="archive-original-table"><thead><tr><th class="archive-source-row">原表行</th>${headers.map(header => `<th>${escapeHtml(header)}</th>`).join('')}</tr></thead><tbody>${sourceRows.map(({ record, cells }) => `<tr class="${record.pair_status === 'conflict' ? 'has-conflict' : ''}"><td class="archive-source-row"><b>${record.row_index + 2}</b>${record.pair_status === 'conflict' ? '<span class="pill warning">需核对</span>' : ''}</td>${headers.map((_header, index) => `<td>${cells[index] ? escapeHtml(String(cells[index])) : '<span class="archive-cell-empty">—</span>'}</td>`).join('')}</tr>`).join('')}</tbody></table></div></section>`;
}

function renderEffectiveConfigurationTable(query) {
  const marketData = state.effectiveConfiguration.markets[state.archiveMarket];
  if (!marketData) return '<p class="empty-state compact">该市场截至本版本没有配置记录。</p>';
  const folded = query.toLocaleLowerCase();
  const records = marketData.records.filter(record => !folded || [record.stable_key, record.item_code, record.item_name, ...Object.entries(record.values).flat()].join(' ').toLocaleLowerCase().includes(folded));
  if (!records.length) return '<p class="empty-state compact">截至该版本没有匹配的配置项。</p>';
  const valueHeaders = [...new Set(records.flatMap(record => Object.keys(record.values)))];
  return `<section class="archive-table-section"><div class="archive-table-heading"><span><strong>${escapeHtml(marketData.label || marketLabels[state.archiveMarket])}</strong><small>${state.archiveMarket === 'domestic' ? '来自中文 Release Note，仅代表国内发布配置。' : '来自英文 Release Note，仅代表海外发布配置。'}</small></span><em>截至本版本</em></div><div class="archive-original-table-wrap"><table class="archive-original-table effective-configuration-table"><thead><tr><th>功能/探头</th><th>V代码</th><th>最近变更</th>${valueHeaders.map(header => `<th>${escapeHtml(header)}</th>`).join('')}</tr></thead><tbody>${records.map(record => `<tr><td><b>${escapeHtml(record.item_name || record.stable_key)}</b></td><td>${escapeHtml(record.item_code || record.stable_key)}</td><td>${escapeHtml(record.last_changed_version)}</td>${valueHeaders.map(header => `<td>${record.values[header] ? escapeHtml(String(record.values[header])) : '<span class="archive-cell-empty">—</span>'}</td>`).join('')}</tr>`).join('')}</tbody></table></div></section>`;
}

function renderReleaseArchive() {
  if (!state.releaseArchive || !state.effectiveConfiguration) return;
  const query = document.querySelector('#release-archive-search').value.trim();
  renderArchiveMarketTabs();
  if (state.archiveType !== 'all' && !archiveTypeCount(state.archiveType)) state.archiveType = 'all';
  const tabs = document.querySelector('#release-archive-tabs');
  tabs.innerHTML = `<button type="button" class="${state.archiveType === 'all' ? 'active' : ''}" data-archive-type="all">全部 · ${archiveTypeCount('all')}</button>${Object.entries(releaseTableTypeLabels).map(([type, label]) => {
    const count = archiveTypeCount(type);
    return `<button type="button" class="${state.archiveType === type ? 'active' : ''}" data-archive-type="${type}" ${count ? '' : 'disabled'}>${escapeHtml(label)} · ${count}</button>`;
  }).join('')}`;
  const content = document.querySelector('#release-archive-content');
  if (state.archiveType === 'effective_configuration') {
    content.innerHTML = renderEffectiveConfigurationTable(query);
    return;
  }
  const folded = query.toLocaleLowerCase();
  const tables = state.releaseArchive.tables.filter(table => table.market === state.archiveMarket && (state.archiveType === 'all' || table.table_type === state.archiveType)).map(table => ({
    ...table,
    visibleRecords: table.records.filter(record => !folded || [record.item_code, record.item_name, record.summary, ...Object.entries(record.data).flat()].join(' ').toLocaleLowerCase().includes(folded)),
  })).filter(table => table.visibleRecords.length);
  content.innerHTML = tables.length ? tables.map(table => renderOriginalArchiveTable(table, table.visibleRecords)).join('') : '<p class="empty-state compact">该市场没有匹配的结构化表格行。</p>';
}

async function openReleaseArchive(releaseId, version) {
  [state.releaseArchive, state.effectiveConfiguration] = await Promise.all([
    api(`/api/v1/releases/${releaseId}/archive`),
    api(`/api/v1/releases/${releaseId}/effective-configuration`),
  ]);
  state.archiveType = 'all';
  const markets = availableArchiveMarkets();
  state.archiveMarket = markets.includes('domestic') ? 'domestic' : markets[0] || 'domestic';
  document.querySelector('#release-archive-title').textContent = `版本 ${version} 档案`;
  const summary = state.releaseArchive.summary;
  document.querySelector('#release-archive-summary').textContent = `${summary.table_count} 张有效表 · ${summary.row_count} 条结构化记录${summary.conflict_count ? ` · ${summary.conflict_count} 条中英文内容需核对` : ''}`;
  document.querySelector('#release-archive-search').value = '';
  renderReleaseArchive();
  document.querySelector('#release-archive-dialog').showModal();
}

function renderCandidateHierarchy(candidates, versionCandidates = candidates, categoryCandidates = candidates) {
  const selectedCount = state.selectedCandidateIds.size;
  const selectedIds = [...state.selectedCandidateIds].join(',');
  const recommendedSubmit = integratedMode() ? '' : `<button class="primary-button" data-batch-confirm="${selectedIds}">按推荐提交 ${selectedCount} 条</button>`;
  const selectionToolbar = `<div class="selected-candidate-toolbar" role="toolbar" aria-label="已选记录的批量操作" aria-live="polite" ${selectedCount ? '' : 'hidden'}><span>已选择 ${selectedCount} 条</span>${recommendedSubmit}<button class="ghost-button" data-batch-approve="${selectedIds}">记入版本 ${selectedCount} 条</button><button class="text-button" data-clear-selection>取消选择</button></div>`;
  const categoryControls = state.activeCandidateCategory === 'all'
    ? ''
    : renderScopeControls(categoryCandidates, 'category');
  // 待审核记录分散在多个版本里，逐版本点过去同样费力：本项目还有别的版本待审时，
  // 额外给一个覆盖全部待审核的一次性入口（数量写进按钮文案，避免误点）。
  const projectControls = state.candidates.length > versionCandidates.length
    ? renderScopeControls(state.candidates, 'project')
    : '';
  return `${selectionToolbar}<details class="review-bulk-tools"><summary>批量处理</summary>${projectControls}${renderScopeControls(versionCandidates, 'version')}${categoryControls}</details><div class="candidate-page-items">${candidates.map(renderReviewItem).join('')}</div>`;
}

function renderReviewItem(item) {
  const missing = !item.title_cn ? '缺中文' : !item.title_en ? '缺英文' : '待确认';
  return `<details class="review-item"><summary><span>${escapeHtml(categoryLabels[item.category] || item.category || '其他')}</span><strong>${escapeHtml(item.title_cn || item.title_en || '未命名记录')}</strong><small>${escapeHtml(missing)}</small></summary>${renderCandidateCard(item)}</details>`;
}

async function approveCandidates(candidateIds) {
  const ids = [...new Set(candidateIds)];
  if (!ids.length) return showNotice('请先选择待审核记录。');
  if (ids.length >= BULK_ACTION_CONFIRM_THRESHOLD && !window.confirm(`将把 ${ids.length} 条记录直接记入各自版本变更（不建立功能）。继续吗？`)) return;
  const result = await api('/api/v1/import-candidates/batch/approve', { method: 'POST', body: JSON.stringify({ candidate_ids: ids }) });
  state.selectedCandidateIds = new Set();
  const merged = result.merged_candidates.length;
  showNotice(`已将 ${result.approved_candidate_ids.length} 条记录仅加入版本${merged ? `（其中 ${merged} 条与已有变更记录重复，已合并）` : ''}。`);
  await refreshAll();
}

async function promoteCandidates(candidateIds) {
  const ids = [...new Set(candidateIds)];
  if (!ids.length) return showNotice('请先选择待审核记录。');
  const result = await api('/api/v1/import-candidates/batch/promote', { method: 'POST', body: JSON.stringify({ candidate_ids: ids }) });
  state.selectedCandidateIds = new Set();
  const skipped = result.skipped_candidates.length;
  showNotice(`已建立 ${result.approved_candidate_ids.length} 个功能档案${skipped ? `；${skipped} 条因无法唯一确认术语而保留待审核。` : '。'}`);
  await refreshAll();
}

function renderSuspectedPairSection() {
  const pairs = state.suspectedPairs || [];
  if (!pairs.length) return '';
  return `<details class="suspected-pair-panel" open><summary><span><b>疑似同一变更（可确认合并）</b><small>中英各一条、两侧条数相等：确认后合并为一条，两种语言的原文都保留</small></span><strong>${pairs.length} 组</strong><em>展开查看</em></summary><div class="suspected-pair-list">${pairs.map(pair => `<article><span class="pill">${escapeHtml(pair.version || '')} · ${escapeHtml(categoryLabels[pair.category] || pair.category)}</span><p>${escapeHtml(pair.cn_excerpt)}<br>${escapeHtml(pair.en_excerpt)}</p><button type="button" class="primary-button" data-merge-pair="${pair.cn_candidate_id}:${pair.en_candidate_id}" data-confirm-merge="确定这两条是同一条变更吗？确认后合并为一条（中英文原文都保留，可撤销）。">确认是同一变更，合并</button></article>`).join('')}</div></details>`;
}

async function loadReviewIssues() {
  state.reviewIssues = await api(projectPath('/api/v1/review-issues'));
  state.suspectedPairs = (await api(projectPath('/api/v1/import-candidates/suspected-pairs'))).pairs;
  const container = document.querySelector('#review-issue-list');
  if (!container) return;
  const pairsSection = renderSuspectedPairSection();
  // 「疑似同一变更」由上面可操作的配对区负责，提醒面板里不再重复列一遍。
  const issues = state.reviewIssues.filter(issue => !issue.message.includes('疑似同一变更'));
  if (!issues.length) { container.innerHTML = pairsSection; return; }
  const byVersion = new Map();
  issues.forEach(issue => {
    const version = issue.version || '未关联版本';
    if (!byVersion.has(version)) byVersion.set(version, []);
    byVersion.get(version).push(issue);
  });
  const pendingCount = issues.reduce((total, issue) => total + (issue.pending_count || 0), 0);
  container.innerHTML = `${pairsSection}<details class="review-issue-panel"><summary><span><b>导入核对提醒</b><small>系统未强行配对无法证实同义的中英文原文</small></span><strong>${byVersion.size} 个版本 · ${issues.length} 项提醒${pendingCount ? ` · ${pendingCount} 条待定位` : ''}</strong><em>展开查看</em></summary><p class="review-issue-explanation">这些提醒用于防止中文条目误配英文。点击分类可直接定位到该版本中仍缺少中文或英文的待审核记录。</p><div class="review-issue-versions">${[...byVersion.entries()].map(([version, issues]) => `<article><strong>${escapeHtml(version)}</strong><div>${issues.map(issue => issue.category ? `<button type="button" class="ghost-button" data-review-issue-target data-version="${escapeAttribute(issue.version || '')}" data-category="${escapeAttribute(issue.category)}">${escapeHtml(categoryLabels[issue.category] || issue.category)} · ${issue.pending_count} 条待核对</button>` : `<span class="review-file-issue">${escapeHtml(issue.message)}</span>`).join('')}</div></article>`).join('')}</div></details>`;
}

async function mergeSuspectedPair(cnCandidateId, enCandidateId) {
  const result = await api('/api/v1/import-candidates/merge', { method: 'POST', body: JSON.stringify({ cn_candidate_id: cnCandidateId, en_candidate_id: enCandidateId }) });
  showNotice(`已合并为一条，中英文原文都保留；该分类还剩 ${result.remaining_suspected_pairs} 组疑似配对。`);
  await refreshAll();
}

async function reviewCandidate(id, decision) {
  await api(`/api/v1/import-candidates/${id}/${decision}`, { method: 'POST', body: '{}' });
  await refreshAll();
}

function candidateById(id) { return state.candidates.find(item => String(item.id) === String(id)); }

function hideFeatureMatches() {
  const list = document.querySelector('#feature-match-list');
  if (!list) return;
  list.hidden = true;
  list.innerHTML = '';
}

function applyFeatureMatch(match) {
  const form = document.querySelector('#promote-form');
  form.elements.feature_id.value = match.source === 'feature' ? String(match.id) : '';
  form.elements.cn_name.value = match.cn_name;
  form.elements.en_name.value = match.en_name;
  form.elements.category.value = match.category || '';
  form.elements.cn_name.dataset.autofilled = 'true';
  form.elements.en_name.dataset.autofilled = 'true';
  cancelFeatureMatchSearch();
}

function cancelFeatureMatchSearch() {
  window.clearTimeout(featureMatchTimer);
  featureMatchRequest += 1;
  hideFeatureMatches();
}

function renderFeatureMatches(matches) {
  const list = document.querySelector('#feature-match-list');
  if (!list) return;
  list.innerHTML = matches.map((match, index) => `<button type="button" class="feature-match-option" data-match-index="${index}"><span><strong>${escapeHtml(match.cn_name)}</strong><small>${escapeHtml(match.en_name)}</small></span><em>${match.conflict ? '名称冲突 · 请明确选择' : match.source === 'feature' ? '现有功能' : '术语词典'}</em></button>`).join('');
  list.hidden = matches.length === 0;
  list._matches = matches;
}

function scheduleFeatureMatch(value) {
  window.clearTimeout(featureMatchTimer);
  const request = ++featureMatchRequest;
  const query = value.trim();
  if (!query) return hideFeatureMatches();
  featureMatchTimer = window.setTimeout(async () => {
    try {
      const matches = await api(projectPath(`/api/v1/feature-matches?q=${encodeURIComponent(query)}`));
      if (request !== featureMatchRequest) return;
      if (matches[0]?.exact && !matches[0].conflict) applyFeatureMatch(matches[0]);
      else renderFeatureMatches(matches);
    } catch (error) {
      if (request === featureMatchRequest) showNotice(error.message);
    }
  }, 180);
}

function openCandidateEditor(id) {
  const candidate = candidateById(id), form = document.querySelector('#candidate-form');
  form.elements.candidate_id.value = candidate.id; form.elements.category.value = candidate.category;
  form.elements.title_cn.value = candidate.title_cn; form.elements.title_en.value = candidate.title_en;
  document.querySelector('#candidate-dialog').showModal();
}

function openFeaturePromotion(id) {
  const candidate = candidateById(id), form = document.querySelector('#promote-form');
  form.reset(); form.elements.candidate_id.value = candidate.id;
  delete form.elements.cn_name.dataset.autofilled;
  delete form.elements.en_name.dataset.autofilled;
  cancelFeatureMatchSearch();
  form.elements.feature_id.innerHTML = '<option value="">新建功能档案</option>' + state.features.map(feature => `<option value="${feature.id}">${escapeHtml(feature.cn_name)} / ${escapeHtml(feature.en_name)}</option>`).join('');
  const isSingleLanguage = !candidate.title_cn || !candidate.title_en;
  document.querySelector('#promote-dialog-title').textContent = isSingleLanguage ? '关联功能修改' : '建立或关联正式功能';
  if (isSingleLanguage) {
    form.elements.cn_name.value = candidate.title_cn;
    form.elements.en_name.value = candidate.title_en;
    scheduleFeatureMatch(candidate.title_cn || candidate.title_en);
  }
  form.elements.cn_description.value = candidate.title_cn; form.elements.en_description.value = candidate.title_en;
  form.elements.domestic.checked = true; form.elements.overseas.checked = true;
  document.querySelector('#promote-dialog').showModal();
}

async function scanNotes() {
  if (state.reviewSyncing) return;
  const project = state.activeProjectId;
  state.reviewSyncing = true;
  renderReviewOverview();
  try {
    const result = await api('/api/v1/import-batches/scan', { method: 'POST', body: JSON.stringify({ project_id: project }) });
    showNotice(`同步完成：新增 ${result.candidates_created} 条待确认。${scanWarningText(result)}`);
    if (project === state.activeProjectId) await refreshAll({ includeExperience: true });
  } finally {
    state.reviewSyncing = false;
    renderReviewOverview();
  }
}

async function compareVersions() {
  const from = document.querySelector('#from-version').value, to = document.querySelector('#to-version').value;
  if (!from || !to) return showNotice('请先导入至少两个版本。');
  const requestId = state.comparisonRequest = (state.comparisonRequest || 0) + 1;
  const project = state.activeProjectId;
  const isCurrent = () => requestId === state.comparisonRequest && project === state.activeProjectId
    && document.querySelector('#from-version').value === from && document.querySelector('#to-version').value === to;
  const container = document.querySelector('#compare-result');
  const button = document.querySelector('#compare-button');
  const originalLabel = button.dataset.idleLabel || button.textContent;
  button.dataset.idleLabel = originalLabel;
  state.comparisonKey = null;
  container.className = 'empty-state compact';
  container.textContent = '正在比较两个版本，请稍候…';
  button.disabled = true;
  button.textContent = '正在比较…';
  let data;
  try {
    data = await api(projectPath(`/api/v1/comparisons?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`));
    if (!isCurrent()) return;
    state.comparisonKey = `${project}:${from}::${to}`;
  } catch (error) {
    if (isCurrent()) {
      container.textContent = '比较失败，请重试。';
      throw error;
    }
    return;
  } finally {
    if (requestId === state.comparisonRequest) {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  }
  const buckets = [['added','目标版本新增'],['removed','起始版本独有'],['common','两个版本共有']];
  const structuredBuckets = [['added','目标版本新增'],['modified','值发生变化'],['removed','起始版本独有']];
  container.className = 'comparison-sections';
  container.innerHTML = `<section><h3>文本变更</h3><div class="diff-grid">${buckets.map(([key,title]) => `<article class="diff-column"><h3>${title}</h3>${Object.entries(data[key]).map(([category,items]) => items.length ? `<p><b>${escapeHtml(category)}</b> · ${items.length}</p><ul>${items.slice(0,8).map(item => `<li>${escapeHtml(item.title_cn || item.title_en || item.canonical_key)}</li>`).join('')}</ul>${items.length > 8 ? `<small>另有 ${items.length - 8} 条</small>` : ''}` : '').join('') || '<p>无</p>'}</article>`).join('')}</div></section><section><h3>表格结构化变更</h3><p>国内、海外配置分别按各自截至版本的累计状态比较，两个市场之间不互相核对。</p><div class="diff-grid">${structuredBuckets.map(([key, title]) => `<article class="diff-column"><h3>${title}</h3>${data.structured[key].length ? `<ul>${data.structured[key].slice(0,12).map(item => `<li><b>${escapeHtml(releaseTableTypeLabels[item.table_type] || item.table_type)}${item.market ? ` · ${escapeHtml(marketLabels[item.market])}` : ''}</b> · ${escapeHtml(item.item_name || item.item_code || item.stable_key)}</li>`).join('')}</ul>${data.structured[key].length > 12 ? `<small>另有 ${data.structured[key].length - 12} 条</small>` : ''}` : '<p>无</p>'}</article>`).join('')}</div></section>`;
}

function ensureComparisonLoaded() {
  const from = document.querySelector('#from-version').value;
  const to = document.querySelector('#to-version').value;
  if (!from || !to || state.comparisonKey === `${state.activeProjectId}:${from}::${to}`) return;
  compareVersions().catch(error => showNotice(error.message));
}

async function refreshAll({ includeExperience = false } = {}) {
  try {
    if (!integratedMode()) await loadProductCategories();
    const tasks = integratedMode()
      ? [loadReleases(), loadCandidates(), loadReviewIssues()]
      : [loadDashboard(), loadFeatures(), loadTerms(), loadReleases(), loadCandidates(), loadReviewIssues()];
    if (includeExperience) tasks.push(loadProjectHealth(), loadImportBatches());
    await Promise.all(tasks);
    if (isActiveView('home')) await loadWorkbenchHome();
  } catch (error) { showNotice(error.message); }
}

async function refreshActiveView() {
  if (PROJECT_SCOPED_VIEWS.has(state.activeView)) {
    await refreshAll({ includeExperience: true });
    return;
  }
  const globalLoaders = {
    strategy: loadProductStrategies,
    product_states: loadProductStates,
    registration: loadRegistration,
    materials: loadKnowledgeDocuments,
    qa: loadQaWorkbench,
    items: loadKnowledgeItems,
    probe_versions: loadProbeVersions,
    issues: loadKnowledgeIssues,
    training: loadTrainingAssets,
  };
  const loader = globalLoaders[state.activeView];
  if (loader) await loader();
}

const MODULE_STATUS_LABELS = { ready: '可用', partial: '部分可用', planned: '建设中', blocked: '受阻' };

function isActiveView(view) {
  const page = document.querySelector(`[data-page="${view}"]`);
  return Boolean(page && page.classList.contains('active'));
}

function moduleCard(module) {
  const reachable = module.status === 'ready' || module.status === 'partial';
  const statusLabel = MODULE_STATUS_LABELS[module.status] || module.status;
  const content = `<span class="home-status ${escapeHtml(module.status)}">${escapeHtml(statusLabel)}</span><strong>${escapeHtml(module.title)}</strong><small>${escapeHtml(module.note || '')}</small>`;
  return module.view && reachable && labels[module.view]
    ? `<button type="button" class="home-card" data-view-target="${module.view}">${content}</button>`
    : `<div class="home-card muted">${content}</div>`;
}

async function loadWorkbenchHomeModules() {
  const container = document.querySelector('#home-modules');
  if (!container) return;
  try {
    const data = await api('/api/v1/workbench/modules');
    container.innerHTML = data.groups.map(group => `<section class="home-module-group"><h4>${escapeHtml(group.title)}</h4><div class="home-card-grid">${group.modules.map(moduleCard).join('')}</div></section>`).join('');
  } catch (error) {
    container.innerHTML = `<p class="empty-state compact">模块清单载入失败：${escapeHtml(error.message)}</p>`;
  }
}

const HOME_TODO_PRIORITY_LABELS = {
  high: '优先确认',
  medium: '重点检查',
  normal: '常规处理',
};

function homeTodoCard(todo) {
  const priority = HOME_TODO_PRIORITY_LABELS[todo.priority] || '待处理';
  return `<button type="button" class="home-todo-row priority-${escapeAttribute(todo.priority)}" data-view-target="${escapeAttribute(todo.view)}"><span class="home-todo-priority">${escapeHtml(priority)}</span><span class="home-todo-copy"><strong>${escapeHtml(todo.title)}</strong><small>${escapeHtml(todo.impact)}</small></span><span class="scope-chip">${escapeHtml(todo.scope_label)}</span><span class="home-todo-count"><strong>${escapeHtml(String(todo.count))}</strong><small>${escapeHtml(todo.state_label)}</small></span><span class="home-todo-action">${escapeHtml(todo.action_label)} →</span></button>`;
}

async function loadWorkbenchHomeTodos() {
  const container = document.querySelector('#home-todos');
  if (!container) return;
  container.setAttribute('aria-busy', 'true');
  container.innerHTML = loadingMarkup('正在核对待办范围与状态…');
  try {
    const projectQuery = state.activeProjectId ? `?project_id=${state.activeProjectId}` : '';
    const data = await api(`/api/v1/workbench/overview${projectQuery}`);
    const actionable = data.todos.filter(todo => todo.actionable && todo.view && labels[todo.view]);
    container.innerHTML = actionable.length
      ? `<p class="home-todo-summary"><strong>${actionable.length} 类事项需要处理</strong><span>已按决策影响排序</span></p>${actionable.map(homeTodoCard).join('')}`
      : `<div class="home-todo-feedback clear"><span class="home-todo-feedback-icon" aria-hidden="true">✓</span><div><strong>当前没有待处理事项</strong><p>当前项目与全局知识库暂无待处理事项，可以继续常用查询。</p></div></div>`;
  } catch (error) {
    container.innerHTML = `<div class="home-todo-feedback error" role="alert"><div><strong>待办暂时无法载入</strong><p>${escapeHtml(error.message)}</p></div><button type="button" class="ghost-button compact-button" data-home-todos-retry>重新加载</button></div>`;
  } finally {
    container.setAttribute('aria-busy', 'false');
  }
}

const SOURCE_STATUS_LABELS = {
  available: '可用',
  degraded: '部分可用',
  unavailable: '不可用',
  not_configured: '未配置',
};

function sourceCard(source) {
  const label = SOURCE_STATUS_LABELS[source.status] || source.status;
  // 路径这类"要看细节才需要"的信息收进折叠，卡片默认只留状态 + 名称 + 一行说明
  const path = source.path
    ? `<details><summary>路径</summary><small title="${escapeAttribute(source.path)}">${escapeHtml(source.path)}</small></details>`
    : '';
  const nested = source.paths.length > 1
    ? `<details class="strategy-row-more"><summary>${source.paths.length} 个来源目录</summary><div class="strategy-source-values">${source.paths.map(item => `<span>${escapeHtml(item.detail)}：${escapeHtml(item.path)}</span>`).join('')}</div></details>`
    : '';
  return `<div class="home-card"><span class="home-status ${escapeHtml(source.status)}">${escapeHtml(label)}</span><strong>${escapeHtml(source.title)}</strong><small>${escapeHtml(source.detail)}</small>${path}${nested}</div>`;
}

const EXTERNAL_STATUS_LABELS = {
  available: '已启动',
  unreachable: '未启动',
  not_configured: '未配置',
};

async function loadConfigSystemEntry() {
  const container = document.querySelector('#home-external');
  if (!container) return;
  container.innerHTML = loadingMarkup('正在探活…');
  try {
    const data = await api('/api/v1/workbench/config-system');
    const reachable = data.status === 'available' && Boolean(data.url);
    const content = `<span class="home-status ${escapeHtml(data.status)}">${escapeHtml(EXTERNAL_STATUS_LABELS[data.status] || data.status)}</span>`
      + '<strong>产品配置管理系统</strong>'
      + `<small>${escapeHtml(data.detail)}${data.response_ms === null ? '' : ` · ${data.response_ms} ms`}</small>`
      + (data.url ? `<small>${escapeHtml(data.url)}</small>` : '')
      // 未启动或未配置时给启动说明，且不渲染可点链接
      + (reachable ? '' : `<small>${escapeHtml(data.start_hint)}</small>`);
    container.innerHTML = reachable
      ? `<a class="home-card" href="${escapeAttribute(data.url)}" target="_blank" rel="noopener noreferrer">${content}<small class="home-card-action">在新标签页打开 →</small></a>`
      : `<div class="home-card muted">${content}</div>`;
  } catch (error) {
    container.innerHTML = `<p class="empty-state compact">外部系统探活失败：${escapeHtml(error.message)}</p>`;
  }
}

async function loadWorkbenchSources() {
  const container = document.querySelector('#home-sources');
  if (!container) return;
  try {
    const projectQuery = state.activeProjectId ? `?project_id=${state.activeProjectId}` : '';
    const data = await api(`/api/v1/workbench/sources${projectQuery}`);
    const attention = data.sources.filter(
      source => source.status === 'unavailable' || source.status === 'degraded'
    ).length;
    container.innerHTML = `<p class="home-sources-summary">检查时间 ${escapeHtml(formatDateTime(data.checked_at))} · 共 ${data.sources.length} 个来源${attention ? ` · ${attention} 个需要处理` : ' · 全部正常'}</p>`
      + data.sources.map(sourceCard).join('');
  } catch (error) {
    container.innerHTML = `<p class="empty-state compact">来源状态检查失败：${escapeHtml(error.message)}</p>`;
  }
}

function refreshWorkbenchSources() {
  return Promise.all([loadWorkbenchSources(), loadConfigSystemEntry()]);
}

// 待办、模块清单与来源状态各自独立加载：任一块失败，另外两块照常渲染。
async function loadWorkbenchHome() {
  if (!document.querySelector('[data-page="home"]')) return;
  await Promise.all([
    loadWorkbenchHomeTodos(),
    loadWorkbenchHomeModules(),
    refreshWorkbenchSources(),
  ]);
}

// URL 定位：#<view>?<key>=<value>。每个视图只接受自己用得到的参数，其余忽略并提示；
// `project` 是全局范围，所有视图都接受。
const VIEW_PARAMS = {
  home: ['project'],
  search: ['project', 'q', 'scope', 'sources', 'market', 'model', 'country', 'verification', 'current_only', 'page', 'task', 'expand_related', 'version_from', 'version_to', 'versions', 'preview', 'locator', 'preview_query', 'preview_input', 'source_group', 'release_category', 'whitepaper_model', 'whitepaper_model_mode', 'scenario', 'scenario_domain', 'scenario_q', 'scenario_model', 'scenario_code', 'scenario_series', 'scenario_target', 'scenario_base', 'scenario_document', 'scenario_section'],
  model: ['model', 'market', 'country', 'series'],
  releases: ['project', 'version'],
  compare: ['project', 'a', 'b'],
  features: ['project', 'q'],
  strategy: ['market', 'model', 'q'],
  product_states: ['market', 'model'],
  registration: ['country', 'model'],
  materials: ['q', 'doc_type', 'track', 'evidence', 'verification', 'model', 'market'],
  qa: ['market', 'country', 'model', 'probe', 'item', 'q'],
  items: ['q', 'category', 'code_type', 'evidence'],
  // 待处理问题是知识中枢的全局清单（kh_issues 无项目维度），因此不带 project。
  issues: ['q', 'severity', 'status', 'issue_type'],
  probe_versions: ['probe', 'series', 'version'],
  training: ['q'],
  terms: ['project', 'q', 'status', 'category'],
  review: ['project', 'version', 'category', 'quality', 'priority', 'q', 'review_mode'],
};

function parseLocation(rawHash = window.location.hash) {
  const raw = String(rawHash || '').replace(/^#/, '');
  const [rawView, rawQuery = ''] = raw.split('?');
  const params = {};
  for (const [key, value] of new URLSearchParams(rawQuery).entries()) {
    if (value !== '') params[key] = value;
  }
  return { view: rawView.trim(), params };
}

function buildHash(view, params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== '' && value !== null && value !== undefined) search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `#${view}?${query}` : `#${view}`;
}

// 当前界面范围 → 链接参数，用于把用户操作后的状态同步进地址栏。
function currentViewParams() {
  const view = state.activeView;
  const params = {};
  const allowed = VIEW_PARAMS[view] || ['project'];
  if (state.activeProjectId && allowed.includes('project')) params.project = String(state.activeProjectId);
  const text = selector => {
    const node = document.querySelector(selector);
    return node ? node.value.trim() : '';
  };
  if (view === 'releases' && state.activeReleaseVersion) params.version = state.activeReleaseVersion;
  if (view === 'search') {
    if (!document.querySelector('#advanced-search-wrap').open) {
      params.scenario = scenarioState.task;
      params.scenario_domain = scenarioState.domain || 'feature';
      if (text('#scenario-query')) params.scenario_q = text('#scenario-query');
      if (scenarioState.model) params.scenario_model = scenarioState.model;
      if (scenarioState.document) params.scenario_document = scenarioState.document;
      if (scenarioState.section) params.scenario_section = scenarioState.section;
      if (scenarioState.code) params.scenario_code = scenarioState.code;
      if (scenarioState.series) params.scenario_series = scenarioState.series;
      if (text('#scenario-target')) params.scenario_target = text('#scenario-target');
      if (text('#scenario-base')) params.scenario_base = text('#scenario-base');
      Object.assign(params, state.previewLocation || {});
      return params;
    }
    if (text('#release-search')) params.q = text('#release-search');
    params.scope = document.querySelector('#release-search-scope').value;
    params.sources = selectedSearchSources().sort().join(',');
    if (text('#release-search-market')) params.market = text('#release-search-market');
    if (text('#release-search-model')) params.model = text('#release-search-model');
    if (text('#release-search-country')) params.country = text('#release-search-country').toUpperCase();
    if (text('#release-search-verification')) params.verification = text('#release-search-verification');
    if (document.querySelector('#release-search-current').checked) params.current_only = 'true';
    Object.assign(params, searchTaskParams());
    params.source_group = state.searchSourceGroup || 'release_note';
    params.release_category = state.searchReleaseCategory || 'all';
    if (state.searchWhitepaperModel) {
      params.whitepaper_model = state.searchWhitepaperModel;
      params.whitepaper_model_mode = state.searchWhitepaperSelectionMode === 'selected' ? 'selected' : 'auto';
    }
    if (state.searchPage > 1) params.page = String(state.searchPage);
    Object.assign(params, state.previewLocation || {});
  }
  if (view === 'model') {
    for (const key of ['model', 'market', 'country', 'series']) if (text(`#workspace-${key}`)) params[key] = text(`#workspace-${key}`);
  }
  if (view === 'features' && text('#feature-search')) params.q = text('#feature-search');
  if (view === 'compare') {
    const from = text('#from-version'), to = text('#to-version');
    if (from) params.a = from;
    if (to) params.b = to;
  }
  if (view === 'materials') {
    if (text('#materials-query')) params.q = text('#materials-query');
    if (text('#materials-model')) params.model = text('#materials-model');
    if (text('#materials-market')) params.market = text('#materials-market');
    if (text('#materials-doc-type')) params.doc_type = text('#materials-doc-type');
    if (text('#materials-track')) params.track = text('#materials-track');
    if (text('#materials-verification')) params.verification = text('#materials-verification');
    if (text('#materials-evidence')) params.evidence = text('#materials-evidence');
  }
  if (view === 'qa') {
    if (text('#qa-market')) params.market = text('#qa-market');
    if (text('#qa-country')) params.country = text('#qa-country').toUpperCase();
    if (text('#qa-model')) params.model = text('#qa-model');
    if (text('#qa-probe')) params.probe = text('#qa-probe');
    if (text('#qa-item')) params.item = text('#qa-item');
    if (text('#qa-question')) params.q = text('#qa-question');
  }
  if (view === 'items') {
    if (text('#items-query')) params.q = text('#items-query');
    if (text('#items-category')) params.category = text('#items-category');
    if (text('#items-code-type')) params.code_type = text('#items-code-type');
    if (text('#items-evidence')) params.evidence = text('#items-evidence');
  }
  if (view === 'issues') {
    if (text('#issues-query')) params.q = text('#issues-query');
    if (text('#issues-severity')) params.severity = text('#issues-severity');
    // 默认范围是「待处理」，等于默认值时不必写进地址栏；显式选了「全部」则写空串
    // 是写不进去的（buildHash 会跳过空值），因此用 all 表示不限状态。
    const status = text('#issues-status');
    if (status !== 'open') params.status = status === '' ? 'all' : status;
    if (text('#issues-type')) params.issue_type = text('#issues-type');
  }
  if (view === 'probe_versions') {
    if (text('#probe-versions-probe')) params.probe = text('#probe-versions-probe');
    if (text('#probe-versions-series')) params.series = text('#probe-versions-series');
    if (text('#probe-versions-version')) params.version = text('#probe-versions-version');
  }
  if (view === 'registration') {
    const model = text('#registration-model');
    if (model) params.model = model;
    const country = text('#registration-country');
    if (country && country !== 'CN') params.country = country;
  }
  if (view === 'product_states') {
    const market = text('#product-states-market');
    if (market && market !== 'CN') params.market = market;
    const model = text('#product-states-model');
    if (model) params.model = model;
  }
  if (view === 'training' && text('#training-query')) params.q = text('#training-query');
  if (view === 'strategy') {
    const market = text('#strategy-market');
    if (market && market !== 'domestic') params.market = market;
    const model = text('#strategy-model');
    if (model) params.model = model;
    if (text('#strategy-query')) params.q = text('#strategy-query');
  }
  if (view === 'terms') {
    if (text('#term-search')) params.q = text('#term-search');
    if (text('#term-status-filter')) params.status = text('#term-status-filter');
    if (text('#term-category-filter')) params.category = text('#term-category-filter');
  }
  if (view === 'review') {
    params.review_mode = state.reviewStage === 'confirm' ? 'confirm' : 'overview';
    if (params.review_mode === 'overview') return params;
    if (state.activeCandidateVersion) params.version = state.activeCandidateVersion;
    if (state.activeCandidateCategory !== 'all') params.category = state.activeCandidateCategory;
    if (text('#candidate-quality-filter')) params.quality = text('#candidate-quality-filter');
    if (text('#review-priority-filter') && text('#review-priority-filter') !== 'focus') params.priority = text('#review-priority-filter');
    if (text('#candidate-search')) params.q = text('#candidate-search');
  }
  return params;
}

function reportNavigationProblem(message) {
  console.warn(`[工作台] ${message}`);
  showNotice(message);
}

// 未知视图或白名单外参数：给出可见提示，不静默失败。
function locationProblems({ view, params }) {
  // 没有视图名＝按默认视图打开（例如桌面入口的裸地址），不是错误。
  if (!view) return [];
  if (!labels[view]) return [`未知工作区「${view}」`];
  const allowed = VIEW_PARAMS[view] || ['project'];
  const problems = [];
  for (const key of Object.keys(params)) {
    if (key === 'project') continue;  // 全局范围：所有视图都接受
    if (!allowed.includes(key)) {
      const usable = allowed.filter(item => item !== 'project');
      problems.push(`「${labels[view]}」不支持参数 ${key}${usable.length ? `（可用：${usable.join('、')}）` : ''}`);
    }
  }
  if (params.project && !Number.isInteger(Number(params.project))) {
    problems.push(`参数 project 需要项目编号，收到「${params.project}」`);
  }
  return problems;
}

function setSelectValue(selector, value) {
  const node = document.querySelector(selector);
  if (!node) return false;
  if (![...node.options].some(option => option.value === value)) return false;
  node.value = value;
  return true;
}

async function applyProjectParam(value) {
  // 返回是否真的切换了项目：调用方要据此决定还需不需要自己加载一次数据。
  const requested = Number(value);
  if (!Number.isInteger(requested)) return false;
  if (!state.projects.some(project => Number(project.id) === requested)) {
    showNotice(`链接里的项目 ${value} 不存在，已保持当前项目。`);
    return false;
  }
  if (Number(state.activeProjectId) === requested) return false;
  await switchProject(requested);
  return true;
}

// 把链接参数套用到界面上；无法落地的取值一律提示，不假装成功。
async function applyViewParams(view, params = {}, { skipProject = false } = {}) {
  const missed = [];
  const navigation = state.evidenceNavigation = (state.evidenceNavigation || 0) + 1;
  state.searchPreviewRequest++;
  document.querySelector('#search-preview-dialog').close();
  state.previewLocation = null;
  if (!skipProject && params.project) await applyProjectParam(params.project);
  if (navigation !== state.evidenceNavigation) return;

  if (view === 'releases' && params.version) {
    if (state.releases.some(release => release.version === params.version)) {
      state.activeReleaseVersion = params.version;
      renderReleaseCenter();
    } else missed.push(`版本 ${params.version}`);
  }

  if (view === 'search') {
    const advanced = document.querySelector('#advanced-search-wrap');
    advanced.open = !params.scenario && Boolean(params.q);
    if (params.scenario) {
      scenarioState.request++;
      document.querySelector('#scenario-result').innerHTML = '';
      state.previewLocation = null;
      scenarioState.domain = params.scenario_domain === 'probe' ? 'probe' : 'feature';
      setScenarioTask(params.scenario);
      document.querySelector('#scenario-query').value = params.scenario_q || '';
      scenarioState.code = params.scenario_code || '';
      scenarioState.series = params.scenario_series || '';
      scenarioState.model = params.scenario_model || '';
      scenarioState.document = params.scenario_document || '';
      scenarioState.section = params.scenario_section || '';
      renderScenarioVersionOptions(params.scenario_target || '', params.scenario_base || '');
      if (params.scenario_q || (scenarioState.task === 'version' && params.scenario_target)) await runScenario();
      if (navigation === state.evidenceNavigation) await restoreEvidenceLocation(params);
      return;
    }
    state.previewLocation = null;
    document.querySelector('#release-search').value = params.q || '';
    document.querySelector('#release-search-scope').value = params.scope === 'all' ? 'all' : 'current';
    setSelectValue('#release-search-market', params.market || '');
    document.querySelector('#release-search-model').value = params.model || '';
    document.querySelector('#release-search-country').value = params.country || '';
    setSelectValue('#release-search-verification', params.verification || '');
    document.querySelector('#release-search-current').checked = params.current_only === 'true';
    const allowedSources = new Set(Object.keys(SEARCH_SOURCE_LABELS));
    const sources = new Set((params.sources || Object.keys(SEARCH_SOURCE_LABELS).join(',')).split(',').filter(value => allowedSources.has(value)));
    document.querySelectorAll('input[name="search-source"]').forEach(input => { input.checked = sources.has(input.value); });
    state.searchSourceGroup = ['release_note', 'whitepaper', 'other'].includes(params.source_group) ? params.source_group : 'release_note';
    state.searchReleaseCategory = params.release_category === 'all' || Object.hasOwn(categoryLabels, params.release_category || '') ? params.release_category : 'all';
    restoreSearchWhitepaperSelection(params);
    state.searchPage = Math.max(1, Number.parseInt(params.page || '1', 10) || 1);
    restoreSearchTask({ task: params.task, expandRelated: params.expand_related === 'true', versionFrom: params.version_from, versionTo: params.version_to, versions: params.versions });
    const search = params.q ? searchUnified(params.q) : null;
    const searchRequest = state.searchRequest;
    if (search) await search;
    else document.querySelector('#release-search-result').innerHTML = '<p class="empty-state compact">输入关键词开始搜索。结果会显示来源、复核状态和原文位置。</p>';
    if (navigation === state.evidenceNavigation && searchRequest === state.searchRequest) await restoreEvidenceLocation(params);
  }
  if (view === 'model') {
    for (const key of ['model', 'country', 'series']) document.querySelector(`#workspace-${key}`).value = params[key] || '';
    setSelectValue('#workspace-market', params.market || 'domestic');
    if (params.model) await loadModelWorkspace();
  }

  if (view === 'review') {
    state.reviewStage = reviewStageFromParams(params);
    const version = params.version || candidateVersions()[0] || null;
    if (version) {
      if (candidateVersions().includes(version)) selectCandidateVersion(version);
      else missed.push(`版本 ${version}`);
    }
    const category = params.category || 'all';
    if (category === 'all' || candidateCategories().includes(category)) selectCandidateCategory(category);
    else missed.push(`分类 ${category}`);
    if (!setSelectValue('#candidate-quality-filter', params.quality || '')) missed.push(`双语质量 ${params.quality}`);
    if (!setSelectValue('#review-priority-filter', params.priority || 'focus')) missed.push(`处理优先级 ${params.priority}`);
    document.querySelector('#candidate-search').value = params.q || '';
    document.querySelector('#review-filter-options').open = Boolean(params.category || params.quality || params.priority || params.q);
    renderCandidateReview();
  }

  // 注意：链接驱动的跳转里，URL 就是范围的唯一事实源——链接没写的筛选条件要清空，
  // 否则会拿上一个链接的关键词去查新链接的机型（实测返回过空结果）。
  if (view === 'features') {
    const query = params.q || '';
    document.querySelector('#feature-search').value = query;
    await loadFeatures(query);
  }

  if (view === 'terms') {
    document.querySelector('#term-search').value = params.q || '';
    if (!setSelectValue('#term-status-filter', params.status || 'review')) missed.push(`状态 ${params.status}`);
    if (!setSelectValue('#term-category-filter', params.category || '')) missed.push(`分类 ${params.category}`);
    await loadTerms(params.q || '');
  }

  if (view === 'probe_versions') {
    // 同理：系列/版本/探头下拉要先填充，链接参数才落得下去
    await ensureProbeVersionsFacets();
    if (params.probe) setSelectValue('#probe-versions-probe', params.probe);
    if (params.series) setSelectValue('#probe-versions-series', params.series);
    if (params.version) setSelectValue('#probe-versions-version', params.version);
    await loadProbeVersions();
  }

  if (view === 'materials') {
    // 同样先备好下拉选项，再套链接参数（否则参数会被静默忽略）
    await ensureMaterialsOptions();
    document.querySelector('#materials-query').value = params.q || '';
    document.querySelector('#materials-model').value = params.model || '';
    setSelectValue('#materials-market', params.market || '');
    setSelectValue('#materials-doc-type', params.doc_type || '');
    setSelectValue('#materials-track', params.track || '');
    setSelectValue('#materials-verification', params.verification || '');
    setSelectValue('#materials-evidence', params.evidence || '');
    await loadKnowledgeDocuments();
  }
  if (view === 'qa') {
    if (params.market && !setSelectValue('#qa-market', params.market)) missed.push(`市场 ${params.market}`);
    document.querySelector('#qa-country').value = params.country || '';
    document.querySelector('#qa-model').value = params.model || '';
    document.querySelector('#qa-probe').value = params.probe || '';
    document.querySelector('#qa-item').value = params.item || '';
    document.querySelector('#qa-question').value = params.q || '';
    if (params.q) await searchQa();
  }

  if (view === 'items') {
    // 下拉必须先有选项，否则链接里的分类参数套不上去（会被静默忽略）
    await ensureItemsOptions();
    document.querySelector('#items-query').value = params.q || '';
    setSelectValue('#items-category', params.category || '');
    setSelectValue('#items-code-type', params.code_type || '');
    setSelectValue('#items-evidence', params.evidence || '');
    await loadKnowledgeItems();
  }

  if (view === 'issues') {
    // 类型下拉要先有选项，否则链接里的类型参数套不上去（会被静默忽略）
    await ensureIssuesOptions();
    document.querySelector('#issues-query').value = params.q || '';
    if (params.severity && !setSelectValue('#issues-severity', params.severity)) missed.push(`严重度 ${params.severity}`);
    // 地址栏用 all 表示"不限状态"（空值无法写进 hash），这里翻译回下拉的空值。
    setSelectValue('#issues-status', params.status === 'all' ? '' : params.status || 'open');
    if (params.issue_type && !setSelectValue('#issues-type', params.issue_type)) missed.push(`问题类型 ${params.issue_type}`);
    await loadKnowledgeIssues();
  }

  if (view === 'registration') {
    const country = (params.country || 'CN').toUpperCase();
    if (!/^[A-Z]{2}$/.test(country)) throw new Error('注册查询国家必须为两位代码。');
    if (!setSelectValue('#registration-country', country)) {
      const option = document.createElement('option');
      option.value = country;
      option.textContent = country;
      document.querySelector('#registration-country').append(option);
      setSelectValue('#registration-country', country);
    }
    await loadRegistrationModels();
    if (params.model && !setSelectValue('#registration-model', params.model)) {
      // 链接里的机型不在已登记清单里：照样按它查询，让接口如实回答「待确认」。
      // 绝不能悄悄换成清单里的第一个机型——那会把别的机型的注册数据当成它的答案。
      const select = document.querySelector('#registration-model');
      const option = document.createElement('option');
      option.value = params.model;
      option.textContent = `${params.model}（不在已登记机型清单里）`;
      select.append(option);
      select.value = params.model;
    }
    await loadRegistration();
  }

  if (view === 'product_states') {
    await loadProductStateOptions();
    if (params.market && !setSelectValue('#product-states-market', params.market)) {
      if (!/^[A-Za-z]{2}$/.test(params.market)) throw new Error('产品状态国家必须为两位代码。');
      const option = document.createElement('option');
      option.value = params.market.toUpperCase();
      option.textContent = `${option.value}（暂无状态记录）`;
      document.querySelector('#product-states-market').append(option);
      setSelectValue('#product-states-market', option.value);
    }
    if (params.model && !setSelectValue('#product-states-model', params.model)) {
      const select = document.querySelector('#product-states-model');
      const option = document.createElement('option');
      option.value = params.model;
      option.textContent = `${params.model}（没有状态记录）`;
      select.append(option);
      select.value = params.model;
    }
    await loadProductStates();
  }

  if (view === 'training') {
    document.querySelector('#training-query').value = params.q || '';
    await loadTrainingAssets();
  }

  if (view === 'strategy') {
    if (params.market && !setSelectValue('#strategy-market', params.market)) missed.push(`市场 ${params.market}`);
    document.querySelector('#strategy-query').value = params.q || '';
    await loadProductStrategyModels();
    if (params.model && !setSelectValue('#strategy-model', params.model)) missed.push(`机型 ${params.model}`);
    await loadProductStrategies();
  }

  if (view === 'compare') {
    const versions = state.releases.map(release => release.version);
    const from = params.a || versions[1] || versions[0] || '';
    const to = params.b || versions[0] || '';
    if (from && !setSelectValue('#from-version', from)) missed.push(`起始版本 ${params.a}`);
    if (to && !setSelectValue('#to-version', to)) missed.push(`目标版本 ${params.b}`);
    if (from && to) await compareVersions();
  }

  if (missed.length) showNotice(`链接里的 ${missed.join('、')} 不在可选范围，已忽略。`);
}

let locationSyncTimer;
function scheduleLocationSync() {
  notifyEmbeddedLocation(buildHash(state.activeView, currentViewParams()));
  window.clearTimeout(locationSyncTimer);
  locationSyncTimer = window.setTimeout(syncLocation, 200);
}

function notifyEmbeddedLocation(hash) {
  if (!state.activeView || !workbenchConfig.embedded || window.parent === window) return;
  window.parent.postMessage({ type: 'release-workbench:location', url: `${window.location.origin}/release-workbench/${hash}` }, window.location.origin);
}

// 视图切换用 pushState（新增一条历史），页内筛选变化用 replaceState（原地更新）。
function syncLocation() {
  if (!state.activeView) return;
  renderSearchFilters();
  const target = buildHash(state.activeView, currentViewParams());
  if (window.location.hash !== target) window.history.replaceState(null, '', target);
  appliedLocation = window.location.href;
  notifyEmbeddedLocation(target);
}

let appliedLocation = null;
async function applyLocation() {
  if (window.location.href === appliedLocation) return;
  appliedLocation = window.location.href;
  const location = parseLocation();
  const problems = locationProblems(location);
  if (problems.length) reportNavigationProblem(`已忽略链接中的：${problems.join('；')}`);
  const view = labels[location.view] ? location.view : defaultView();
  if (switchView(view, { updateHash: false }) !== false) {
    await applyViewParams(view, location.params);
  }
}

async function ensureMaterialsOptions() {
  const select = document.querySelector('#materials-doc-type');
  if (!select || select.dataset.loaded === 'true') return;
  const data = await api('/api/v1/knowledge-hub/documents/options');
  select.innerHTML = '<option value="">全部类型</option>' + data.doc_types
    .map(docType => `<option value="${escapeAttribute(docType)}">${escapeHtml(docType)}</option>`)
    .join('');
  select.dataset.loaded = 'true';
}

function documentVersionLine(version) {
  const files = (version.files || []).map(file => `${file.label} · ${file.role === 'extract_source' ? '抽取源' : '登记文件'}`).join(' + ');
  const flags = [
    `<span class="pill ${version.dual_track ? '' : 'note'}">${escapeHtml(files || '未登记文件')}</span>`,
    `<span class="pill ${version.verified ? '' : 'warning'}">${version.verified ? `已复核 ${escapeHtml(version.verified_at)}` : '未复核'}</span>`,
    `<span class="pill ${version.has_evidence ? '' : 'warning'}">${version.has_evidence ? `证据 ${version.evidence_count}` : '缺证据'}</span>`,
  ].join('');
  const technical = version.sha256_short ? `SHA-256 ${escapeHtml(version.sha256_short)}…` : '';
  const actions = (version.files || []).filter(file => file.preview_id).map(file => `<button class="ghost-button compact-button" type="button" data-search-result-preview="${escapeAttribute(file.preview_id)}">预览 ${escapeHtml(file.label)}${file.role === 'extract_source' ? '抽取源' : '登记文件'}</button>`).join('');
  return `<div class="material-version"><div class="strategy-row-meta"><span class="scope-chip">版本 ${escapeHtml(version.version_label || String(version.id))}</span>${flags}${version.supersedes_version_id ? `<span>替代版本 #${version.supersedes_version_id}</span>` : ''}</div><div class="workspace-actions">${actions}</div>${technical ? `<details class="material-technical-details"><summary>文件校验信息</summary><small class="strategy-note">${technical}</small></details>` : ''}</div>`;
}

function marketLabel(market) {
  return { domestic: '国内', overseas: '海外' }[market] || market || '';
}

function documentCard(document) {
  const versions = document.versions.map(documentVersionLine).join('');
  const hasExtractSource = document.versions.some(version => version.files?.some(file => file.role === 'extract_source'));
  const hasRegisteredFile = document.versions.some(version => version.files?.some(file => file.role === 'registered_file'));
  const trackLabel = hasExtractSource && hasRegisteredFile ? '抽取源 + 登记文件' : hasRegisteredFile ? '仅登记文件' : hasExtractSource ? '仅抽取源' : '未关联文件';
  const suggestion = document.scope_suggestion;
  const suggestionNames = suggestion ? [...suggestion.models, ...(suggestion.families || []).map(family => `${family} 系列（具体机型待确认）`)] : [];
  const suggestionLabel = suggestionNames.length ? `<p class="strategy-note"><span class="pill warning">${suggestion.status === 'conflict' ? '匹配冲突' : '智能匹配 · 待确认'}</span> ${escapeHtml(suggestionNames.join('、'))} · 可信度${{ high: '高', medium: '中', low: '低' }[suggestion.confidence] || '待确认'}</p>` : suggestion ? `<p class="strategy-note">${escapeHtml(suggestion.message)}</p>` : '';
  return `<article class="strategy-row">
    <div class="strategy-row-head"><strong>${escapeHtml(document.title)}</strong><span class="pill ${document.dual_track ? '' : 'note'}">${trackLabel}</span></div>
    <div class="strategy-row-meta"><span>${escapeHtml(document.doc_type)}</span><span>${document.version_count} 个版本</span><span class="pill ${document.verified ? '' : 'warning'}">${document.verified ? '已复核' : '未复核'}</span><span class="pill ${document.has_evidence ? '' : 'warning'}">${document.has_evidence ? `证据 ${document.evidence_count}` : '缺证据'}</span>${document.scope_market ? `<span>${escapeHtml(marketLabel(document.scope_market))}</span>` : ''}</div>
    <p class="strategy-note">适用机型：${escapeHtml(document.model_scope || '尚未确认')}</p>${suggestionLabel}${versions}
    <div class="workspace-actions"><button class="ghost-button" type="button" data-document-append="${document.id}">追加版本</button>${document.current_version_id ? `<button class="ghost-button" type="button" data-document-review="${document.id}" data-document-version="${document.current_version_id}" data-document-scope="${escapeAttribute(document.model_scope)}" data-document-market="${escapeAttribute(document.scope_market)}">复核当前版本</button>` : ''}</div>
  </article>`;
}

async function loadKnowledgeDocuments() {
  const list = document.querySelector('#materials-list');
  const summary = document.querySelector('#materials-summary');
  if (!list) return;
  await ensureMaterialsOptions();
  list.innerHTML = loadingMarkup('正在载入受控资料…');
  const params = new URLSearchParams({
    q: document.querySelector('#materials-query').value.trim(),
    doc_type: document.querySelector('#materials-doc-type').value,
    track: document.querySelector('#materials-track').value,
    verification: document.querySelector('#materials-verification').value,
    evidence: document.querySelector('#materials-evidence').value,
    model: document.querySelector('#materials-model').value.trim(),
    market: document.querySelector('#materials-market').value,
  });
  try {
    const data = await api(`/api/v1/knowledge-hub/documents?${params.toString()}`);
    const needsAttention = data.counts.unverified > 0 || data.counts.without_evidence > 0;
    summary.classList.toggle('attention', needsAttention);
    summary.innerHTML = queryConclusionContent({
      label: '资料结论',
      title: needsAttention ? '受控资料库仍有待补齐项' : '受控资料库均已复核且有证据',
      detail: `${data.note} 当前筛选匹配 ${data.matched} / ${data.total} 份。`,
      metrics: [
        { label: '当前匹配', value: data.matched },
        { label: '全库未复核', value: data.counts.unverified },
        { label: '全库缺证据', value: data.counts.without_evidence },
      ],
    });
    list.innerHTML = data.documents.length
      ? limitedListMarkup('materials', data.documents, documentCard)
      : '<p class="empty-state compact">没有匹配的资料。</p>';
  } catch (error) {
    summary.textContent = '';
    list.innerHTML = strategyProblemMarkup(error);
  }
}

function ensureMaterialsLoaded() {
  const list = document.querySelector('#materials-list');
  if (!list || list.dataset.loaded === 'true') return;
  loadKnowledgeDocuments().then(() => { list.dataset.loaded = 'true'; }).catch(error => showNotice(error.message));
}

// 空态 / 加载 / 错误只有一套写法，避免每页自己造
function loadingMarkup(textLabel) {
  return `<p class="loading"><span class="loading-dot"></span>${escapeHtml(textLabel)}</p>`;
}

function emptyMarkup({ title, hint = '', action = '' } = {}) {
  return `<div class="empty"><strong>${escapeHtml(title)}</strong>${hint ? `<p>${escapeHtml(hint)}</p>` : ''}${action}</div>`;
}

const LIST_RENDER_LIMIT = 50;
const expandedLists = new Set();

function listOverflowNotice(key, total) {
  if (total <= LIST_RENDER_LIMIT || expandedLists.has(key)) return '';
  const containerId = key === 'strategy' ? 'strategy-result' : `${key}-list`;
  return `<p class="list-overflow" role="status">已显示前 ${LIST_RENDER_LIMIT} 条，共 ${total} 条 <button type="button" class="text-button" data-expand-list="${key}" aria-controls="${containerId}">显示其余 ${total - LIST_RENDER_LIMIT} 条</button>（也可先用上方筛选缩小范围）</p>`;
}

function limitedListMarkup(key, items, renderItem, { wrap = false } = {}) {
  const initial = items.slice(0, LIST_RENDER_LIMIT).map(renderItem).join('');
  const remainder = expandedLists.has(key)
    ? `<div class="expanded-list-items" data-expanded-list-start="${key}" tabindex="-1">${items.slice(LIST_RENDER_LIMIT).map(renderItem).join('')}</div>`
    : '';
  const content = `${initial}${remainder}`;
  return `${wrap ? `<div class="strategy-list">${content}</div>` : content}${listOverflowNotice(key, items.length)}`;
}

function focusExpandedList(key) {
  const start = document.querySelector(`[data-expanded-list-start="${key}"]`);
  if (!start) return;
  start.focus({ preventScroll: true });
  start.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

const CODE_TYPE_CLASSES = { v_code: '', self_built: 'note' };
const TAG_LAYER_LABELS = { probe: '探头', function: '功能', application: '应用' };

function itemTagLine(tags) {
  const parts = Object.entries(TAG_LAYER_LABELS)
    .filter(([field]) => (tags[field] || []).length)
    .map(([field, label]) => `${label}：${tags[field].map(value => escapeHtml(value)).join('、')}`);
  return parts.length ? parts.join(' · ') : '未打标签';
}

function itemEvidenceList(item) {
  if (!item.has_evidence) {
    return '<small class="strategy-note warning">该条目没有登记来源证据——需补证据后才能作为正式依据，系统不会当作已核实。</small>';
  }
  return `<details class="strategy-row-more"><summary>来源证据（${item.evidence_count} 条）</summary><div class="strategy-source-values">${item.evidence.map(evidence => `<span>${escapeHtml(evidence.document_title || '未命名资料')}${evidence.sheet ? ` · 工作表 ${escapeHtml(evidence.sheet)}` : ''}${evidence.cell_range ? ` · 单元格 ${escapeHtml(evidence.cell_range)}` : ''}${evidence.page ? ` · 第 ${evidence.page} 页` : ''}</span><span>${escapeHtml(evidence.excerpt || '')}</span>`).join('')}</div></details>`;
}

function itemCard(item) {
  const review = item.reviews.length
    ? `<small class="strategy-note">审核：${item.reviews.map(record => `${escapeHtml(record.decision)}（${escapeHtml(record.reviewer || '未署名')} · ${escapeHtml(record.decided_at || '')}）`).join('；')}</small>`
    : '<small class="strategy-note">尚无审核留痕</small>';
  const issues = item.issues.length
    ? `<small class="strategy-note warning">待处理问题 ${item.issues.length} 条：${item.issues.map(issue => escapeHtml(issue.detail || issue.issue_type)).join('；')}</small>`
    : '';
  return `<article class="strategy-row">
    <div class="strategy-row-head"><strong>${escapeHtml(item.name_cn || item.name_en || item.code)}</strong><span class="pill ${CODE_TYPE_CLASSES[item.code_type] || ''}">${escapeHtml(item.code_type_label)}</span></div>
    <div class="strategy-row-meta"><span class="scope-chip">${escapeHtml(item.code)}</span><span>${escapeHtml(item.category.path)}</span>${item.name_en ? `<span>${escapeHtml(item.name_en)}</span>` : ''}<span class="pill ${item.has_evidence ? '' : 'warning'}">${item.has_evidence ? `证据 ${item.evidence_count}` : '缺证据'}</span></div>
    <small class="strategy-note">${itemTagLine(item.tags)}</small>
    ${itemEvidenceList(item)}
    ${issues}${review}
  </article>`;
}

async function ensureItemsOptions() {
  const select = document.querySelector('#items-category');
  if (!select || select.dataset.loaded === 'true') return;
  const data = await api('/api/v1/knowledge-hub/items/options');
  select.innerHTML = '<option value="">全部分类</option>' + data.categories
    .map(category => `<option value="${escapeAttribute(category.code)}">${escapeHtml('　'.repeat(Math.max(0, Number(category.level) - 1)) + category.name)}</option>`)
    .join('');
  select.dataset.loaded = 'true';
}

async function loadKnowledgeItems() {
  const list = document.querySelector('#items-list');
  const summary = document.querySelector('#items-summary');
  if (!list) return;
  await ensureItemsOptions();
  list.innerHTML = loadingMarkup('正在载入条目…');
  const params = new URLSearchParams({
    q: document.querySelector('#items-query').value.trim(),
    category: document.querySelector('#items-category').value,
    code_type: document.querySelector('#items-code-type').value,
    evidence: document.querySelector('#items-evidence').value,
  });
  try {
    const data = await api(`/api/v1/knowledge-hub/items?${params.toString()}`);
    summary.textContent = `共 ${data.total} 个条目 · 匹配 ${data.matched} 条 · 配置系统 V 代码 ${data.code_type_counts.v_code} / 自建码 ${data.code_type_counts.self_built} · 缺证据 ${data.without_evidence} 条 · 检查时间 ${formatDateTime(data.checked_at)}`;
    list.innerHTML = data.items.length
      ? limitedListMarkup('items', data.items, itemCard, { wrap: true })
      : '<p class="empty-state compact">没有匹配的条目。</p>';
  } catch (error) {
    summary.textContent = '';
    list.innerHTML = strategyProblemMarkup(error);
  }
}

function ensureItemsLoaded() {
  const list = document.querySelector('#items-list');
  if (!list || list.dataset.loaded === 'true') return;
  loadKnowledgeItems().then(() => { list.dataset.loaded = 'true'; }).catch(error => showNotice(error.message));
}

// 待处理问题：只读呈现，不提供「标记为已解决」——结论归业务负责人。
const ISSUE_SEVERITY_CLASSES = { high: 'warning', medium: 'note', low: '' };

function issueCard(issue) {
  const subject = issue.subject_ref
    ? `${escapeHtml(issue.subject_type_label)} · ${escapeHtml(issue.subject_ref)}`
    : escapeHtml(issue.subject_type_label);
  // 词典里没有的类型照实显示原始编码，并说明为何是英文——不因为"没中文名"就消失。
  const typePill = issue.issue_type_known
    ? `<span class="pill">${escapeHtml(issue.issue_type_label)}</span>`
    : `<span class="pill warning" title="该问题类型尚未登记中文名，此处显示原始编码">${escapeHtml(issue.issue_type_label)}</span>`;
  return `<article class="strategy-row">
    <div class="strategy-row-head"><strong>${subject}</strong><span class="pill ${ISSUE_SEVERITY_CLASSES[issue.severity] || ''}">严重度 ${escapeHtml(issue.severity_label)}</span></div>
    <div class="strategy-row-meta">${typePill}<span>#${escapeHtml(String(issue.id))}</span>${issue.status !== 'open' ? `<span class="pill">${escapeHtml(issue.status_label)}</span>` : ''}<span>登记于 ${escapeHtml(issue.created_at)}</span></div>
    <small class="strategy-note">${escapeHtml(issue.detail)}</small>
  </article>`;
}

async function ensureIssuesOptions() {
  const select = document.querySelector('#issues-type');
  if (!select || select.dataset.loaded === 'true') return;
  // 类型下拉覆盖**全部**状态的类型，否则切到「已解决」时选不到对应类型。
  const data = await api('/api/v1/knowledge-hub/issues?status=');
  select.innerHTML = '<option value="">全部类型</option>' + data.types
    .map(type => `<option value="${escapeAttribute(type.key)}">${escapeHtml(type.label)}（${type.count}）</option>`)
    .join('');
  select.dataset.loaded = 'true';
}

async function loadKnowledgeIssues() {
  const list = document.querySelector('#issues-list');
  const summary = document.querySelector('#issues-summary');
  if (!list) return;
  await ensureIssuesOptions();
  list.innerHTML = loadingMarkup('正在载入待处理问题…');
  const params = new URLSearchParams({
    q: document.querySelector('#issues-query').value.trim(),
    severity: document.querySelector('#issues-severity').value,
    status: document.querySelector('#issues-status').value,
    issue_type: document.querySelector('#issues-type').value,
  });
  try {
    const data = await api(`/api/v1/knowledge-hub/issues?${params.toString()}`);
    const bySeverity = data.severity_counts.map(entry => `${entry.label} ${entry.count}`).join(' · ');
    summary.textContent = `待处理 ${data.open_total} 条（${bySeverity}）· 已解决 ${data.resolved_total} 条 · 本次匹配 ${data.matched} 条 · 全局统计，不随项目切换 · 检查时间 ${formatDateTime(data.checked_at)}`;
    list.innerHTML = data.issues.length
      ? limitedListMarkup('issues', data.issues, issueCard, { wrap: true })
      : '<p class="empty-state compact">当前筛选没有问题条目。</p>';
  } catch (error) {
    summary.textContent = '';
    list.innerHTML = strategyProblemMarkup(error);
  }
}

function ensureIssuesLoaded() {
  const list = document.querySelector('#issues-list');
  if (!list || list.dataset.loaded === 'true') return;
  loadKnowledgeIssues().then(() => { list.dataset.loaded = 'true'; }).catch(error => showNotice(error.message));
}

function qaEvidenceLabel(evidence) {
  if (!evidence) return '来源待核对';
  const location = [evidence.page != null ? `第 ${evidence.page} 页` : '', evidence.sheet ? `工作表 ${evidence.sheet}` : '', evidence.cell_range ? `单元格 ${evidence.cell_range}` : ''].filter(Boolean).join(' · ');
  return `${evidence.document_title} · ${evidence.version_label || '未标版本'}${location ? ` · ${location}` : ''}`;
}

function qaAnswerMarkup(answer) {
  const evidence = answer.evidence || {};
  return `<article class="qa-answer strategy-row"><span class="pill">已审核发布</span><h3>${escapeHtml(answer.standard_question)}</h3><p class="qa-direct">${escapeHtml(answer.answer_text)}</p><dl>
    <div><dt>适用范围</dt><dd>${escapeHtml(answer.country_code)} · ${escapeHtml(answer.market_code === 'domestic' ? '国内版' : answer.market_code)} · ${escapeHtml(answer.model_name)}</dd></div>
    <div><dt>注册检查</dt><dd>${escapeHtml(answer.registration_result)}</dd></div>
    <div><dt>产品策略</dt><dd>${escapeHtml(answer.strategy_result)}</dd></div>
    <div><dt>受控依据</dt><dd>${escapeHtml(qaEvidenceLabel(evidence))}<small>${escapeHtml(evidence.excerpt || '')}</small></dd></div>
    <div><dt>知识状态与核验</dt><dd>已发布 · ${escapeHtml(answer.verified_at || '未记录')}</dd></div>
    <div><dt>限制条件</dt><dd>${escapeHtml(answer.limitations)}</dd></div>
  </dl></article>`;
}

function qaJointMarkup(joint) {
  if (joint.state === 'needs_clarification') return `<p class="empty-state compact">请补充 ${escapeHtml(joint.missing.join('、'))} 后再核对。</p>`;
  if (joint.state === 'unanswered') return `<p class="empty-state compact">${escapeHtml(joint.reason)}</p>`;
  const registration = joint.registration;
  const registrationLabels = { registered: '已注册', unregistered: '未注册', conflict: '资料冲突，待确认', pending: '待确认', not_applicable: '不涉及探头注册' };
  const units = registration.units.map(unit => `<li>${escapeHtml(unit.certificate_no)} · ${escapeHtml(unit.state)}${unit.evidence_current ? '' : ' · 证据版本或复核状态待确认'}${unit.evidence.map(evidence => ` · ${escapeHtml(qaEvidenceLabel(evidence))}`).join('')}</li>`).join('');
  const strategy = joint.strategy.item;
  const strategySource = strategy ? `${strategy.code || strategy.name} · 配置项 #${strategy.item_id}` : '没有唯一对应配置项';
  const status = joint.state === 'resolved' ? '结构化核对' : joint.state === 'blocked' ? '注册红线' : '待负责人复核';
  return `<article class="qa-answer strategy-row"><span class="pill ${joint.state === 'needs_review' ? 'warning' : ''}">${status}</span><h3>联合核对结果</h3><p class="qa-direct">${escapeHtml(joint.conclusion)}</p><dl>
    <div><dt>适用范围</dt><dd>${escapeHtml(joint.scope.country)} · ${escapeHtml(joint.scope.model)}${joint.scope.registration_model && joint.scope.registration_model !== joint.scope.model ? ` · 注册用基础型号 ${escapeHtml(joint.scope.registration_model)}` : ''}</dd></div>
    <div><dt>注册检查</dt><dd>${registration.probe ? `${escapeHtml(registration.probe)} · ` : ''}${escapeHtml(registrationLabels[registration.state] || registration.state)}${units ? `<ul>${units}</ul>` : ''}</dd></div>
    <div><dt>产品策略</dt><dd>${escapeHtml(joint.strategy.label)} · ${escapeHtml(strategySource)}</dd></div>
    <div><dt>资料来源</dt><dd>${escapeHtml(joint.source.registration)}；${escapeHtml(joint.source.strategy)}</dd></div>
    <div><dt>知识状态与核验</dt><dd>${escapeHtml(joint.knowledge_status)} · ${escapeHtml(formatDateTime(joint.checked_at))}</dd></div>
    <div><dt>限制条件</dt><dd>${escapeHtml(joint.limitations)}</dd></div>
  </dl></article>`;
}

function qaAdminAnswerMarkup(answer) {
  const statusLabels = { draft: '草稿', in_review: '待审核', published: '已发布', needs_review: '来源变化，待复核', retired: '已失效' };
  const actions = answer.status === 'draft'
    ? `<button type="button" class="ghost-button" data-qa-review="${answer.id}">提交审核</button>`
    : answer.status === 'in_review'
      ? `<form class="qa-inline-actions" data-qa-publish="${answer.id}"><label>审核人<input name="reviewer" required></label><label>最后核验日期<input name="verified_at" type="date" required></label><button type="submit" class="primary-button">审核并发布</button></form>`
      : answer.status === 'retired' ? '' : `${answer.status === 'needs_review' ? `<button type="button" class="ghost-button" data-qa-redraft="${answer.id}">复制为新草稿</button>` : ''}<form class="qa-inline-actions" data-qa-retire="${answer.id}"><label>失效原因<input name="reason" required></label><button type="submit" class="ghost-button">确认失效</button></form>`;
  return `<article class="strategy-row qa-admin-answer"><div class="strategy-row-head"><strong>${escapeHtml(answer.standard_question)}</strong><span class="pill ${answer.status === 'needs_review' ? 'warning' : ''}">${escapeHtml(statusLabels[answer.status] || answer.status)}</span></div><small>${escapeHtml(answer.country_code)} · ${escapeHtml(answer.model_name)} · ${escapeHtml(qaEvidenceLabel(answer.evidence))}</small><p>${escapeHtml(answer.answer_text)}</p><div class="qa-inline-actions">${actions}</div></article>`;
}

async function loadQaWorkbench() {
  await api('/api/v1/knowledge-hub/qa/revalidate', { method: 'POST', body: '{}' });
  const [questions, answers, evidence, modelOptions] = await Promise.all([
    api('/api/v1/knowledge-hub/qa/questions?status=open'),
    api('/api/v1/knowledge-hub/qa/answers'),
    api(`/api/v1/knowledge-hub/qa/evidence-options?q=${encodeURIComponent(document.querySelector('#qa-evidence-query').value.trim())}`),
    api('/api/v1/knowledge-hub/product-states/options'),
  ]);
  document.querySelector('#qa-inbox').innerHTML = questions.length
    ? questions.map(item => `<article class="strategy-row"><strong>${escapeHtml(item.question)}</strong><small>${escapeHtml(item.country_code || '国家待补')} · ${escapeHtml(item.model_name || '机型待补')} · ${escapeHtml(item.requester)} · ${escapeHtml(formatDateTime(item.created_at))}</small><p>${item.reason_code === 'material_gap' ? '现有材料未涉及' : '尚无正式答案'}${item.context_note ? ` · ${escapeHtml(item.context_note)}` : ''}</p>${item.market_code === 'domestic' && item.country_code === 'CN' && item.model_name ? `<button type="button" class="text-button" data-qa-use-question="${item.id}">以此问题起草</button>` : '<small>待补充适用范围或该国家/市场资料后起草</small>'}</article>`).join('')
    : '<p class="empty-state compact">暂无待处理提问。</p>';
  document.querySelector('#qa-answer-list').innerHTML = answers.length
    ? answers.map(qaAdminAnswerMarkup).join('')
    : '<p class="empty-state compact">尚无答案草稿。</p>';
  document.querySelector('#qa-draft-evidence').innerHTML = '<option value="">选择可定位证据</option>'
    + evidence.map(item => `<option value="${item.id}">${escapeHtml(qaEvidenceLabel(item))}</option>`).join('');
  document.querySelector('#qa-model-options').innerHTML = modelOptions.models.map(model => `<option value="${escapeAttribute(model)}"></option>`).join('');
  state.qaOpenQuestions = questions;
  state.qaAnswers = answers;
}

async function loadQaEvidenceOptions() {
  const query = document.querySelector('#qa-evidence-query').value.trim();
  const evidence = await api(`/api/v1/knowledge-hub/qa/evidence-options?q=${encodeURIComponent(query)}`);
  const select = document.querySelector('#qa-draft-evidence');
  const selected = select.value;
  select.innerHTML = '<option value="">选择可定位证据</option>'
    + evidence.map(item => `<option value="${item.id}">${escapeHtml(qaEvidenceLabel(item))}</option>`).join('');
  if (evidence.some(item => String(item.id) === selected)) select.value = selected;
}

async function searchQa() {
  const result = document.querySelector('#qa-result');
  const submit = document.querySelector('#qa-submit-form');
  const params = new URLSearchParams({
    q: document.querySelector('#qa-question').value.trim(),
    market: document.querySelector('#qa-market').value,
    country: document.querySelector('#qa-country').value.trim().toUpperCase(),
    model: document.querySelector('#qa-model').value.trim(),
    probe: document.querySelector('#qa-probe').value.trim(),
    item: document.querySelector('#qa-item').value.trim(),
  });
  result.innerHTML = loadingMarkup('正在核对正式答案与来源…');
  submit.hidden = true;
  try {
    const data = await api(`/api/v1/knowledge-hub/qa/search?${params}`);
    if (data.state === 'answered') {
      result.innerHTML = qaAnswerMarkup(data.answer);
    } else if (data.state === 'joint') {
      result.innerHTML = qaJointMarkup(data.joint);
      submit.hidden = !['needs_review', 'unanswered'].includes(data.joint.state);
      if (data.joint.reason_code === 'material_gap') document.querySelector('#qa-reason').value = 'material_gap';
    } else if (data.state === 'needs_clarification') {
      result.innerHTML = `<p class="empty-state compact">请补充 ${escapeHtml(data.missing.join('、'))} 后再查询；材料未涉及的问题可先登记。</p>`;
      submit.hidden = false;
      document.querySelector('#qa-reason').value = 'material_gap';
    } else {
      result.innerHTML = `<p class="empty-state compact">${escapeHtml(data.reason)}</p>`;
      submit.hidden = false;
    }
  } catch (error) {
    result.innerHTML = strategyProblemMarkup(error);
  }
}

function ensureQaLoaded() {
  loadQaWorkbench().catch(error => showNotice(error.message));
}

function probeVersionRow(item) {
  const history = item.history
    .map(entry => `<span>${escapeHtml(entry.software_version)}（${escapeHtml(entry.series_code)}）· ${escapeHtml(entry.state_label)}${entry.replaces_probe_code ? ` · 替代 ${escapeHtml(entry.replaces_probe_code)}` : ''}</span>`)
    .join('');
  return `<article class="strategy-row">
    <div class="strategy-row-head"><strong>${escapeHtml(item.probe_code)}</strong><span class="pill">${escapeHtml(item.probe_model || '未标注型号')}</span></div>
    <div class="strategy-row-meta"><span>系列 ${item.series.map(escapeHtml).join('、')}</span><span>${item.history.length} 条版本记录</span></div>
    <div class="strategy-source-values">${history}</div>
  </article>`;
}

async function ensureProbeVersionsFacets() {
  const select = document.querySelector('#probe-versions-probe');
  if (!select || select.dataset.loaded === 'true') return;
  const data = await api('/api/v1/knowledge-hub/probe-versions');
  select.innerHTML = '<option value="">全部探头</option>' + data.facets.probes.map(probe => `<option value="${escapeAttribute(probe)}">${escapeHtml(probe)}</option>`).join('');
  document.querySelector('#probe-versions-series').innerHTML = '<option value="">全部系列</option>' + data.facets.series.map(series => `<option value="${escapeAttribute(series)}">${escapeHtml(series)}</option>`).join('');
  document.querySelector('#probe-versions-version').innerHTML = '<option value="">全部版本</option>' + data.facets.versions.map(version => `<option value="${escapeAttribute(version)}">${escapeHtml(version)}</option>`).join('');
  select.dataset.loaded = 'true';
}

async function loadProbeVersions() {
  const list = document.querySelector('#probe-versions-list');
  const summary = document.querySelector('#probe-versions-summary');
  if (!list) return;
  await ensureProbeVersionsFacets();
  list.innerHTML = loadingMarkup('正在载入探头-版本关系…');
  const query = new URLSearchParams({
    probe: document.querySelector('#probe-versions-probe').value,
    series: document.querySelector('#probe-versions-series').value,
    version: document.querySelector('#probe-versions-version').value,
  });
  try {
    const data = await api(`/api/v1/knowledge-hub/probe-versions?${query.toString()}`);
    summary.textContent = `共 ${data.total} 条关系 · ${data.by_probe.length} 个探头 · 检查时间 ${formatDateTime(data.checked_at)}`;
    list.innerHTML = data.by_probe.length
      ? data.by_probe.map(probeVersionRow).join('')
      : '<p class="empty-state compact">没有匹配的探头-版本关系。</p>';
  } catch (error) {
    summary.textContent = '';
    list.innerHTML = strategyProblemMarkup(error);
  }
}

function ensureProbeVersionsLoaded() {
  const list = document.querySelector('#probe-versions-list');
  if (!list || list.dataset.loaded === 'true') return;
  loadProbeVersions().then(() => { list.dataset.loaded = 'true'; }).catch(error => showNotice(error.message));
}

function productStateHistoryRow(row) {
  const review = row.reviewed_at
    ? `最后核验 ${escapeHtml(row.reviewed_at)} · ${escapeHtml(row.reviewed_by || '未登记审核人')}`
    : '尚未审核';
  const validity = row.valid_until ? ` · 复核期限 ${escapeHtml(row.valid_until)}` : ' · 未设置复核期限';
  const invalidation = row.invalidation_reason
    ? `<span class="product-state-warning">失效：${escapeHtml(row.invalidation_reason)}${row.invalidated_at ? `（${escapeHtml(row.invalidated_at)}）` : ''}</span>`
    : '';
  return `<li>
    <div><strong>${escapeHtml(row.software_version)}</strong><span class="pill product-state-${escapeAttribute(row.freshness)}">${escapeHtml(row.freshness_label)}</span></div>
    <span>${escapeHtml(row.release_status_label)} · 生效 ${escapeHtml(row.effective_date)} · ${review}${validity}</span>
    <small>依据：${escapeHtml(row.evidence_excerpt)}</small>
    <small title="${escapeAttribute(row.source_ref)}">来源：${escapeHtml(row.source_ref)}</small>
    ${invalidation}
  </li>`;
}

function productStateRow(model) {
  const row = model.current || model.latest || model.pending[0];
  if (!row) return '';
  const isCurrent = Boolean(model.current);
  const statusClass = row.freshness === 'current' ? 'ok' : 'warning';
  const headline = isCurrent
    ? `<div class="product-state-primary"><span><small>当前正式版本</small><strong>${escapeHtml(row.software_version)}</strong></span><span><small>当前发布状态</small><strong>${escapeHtml(row.release_status_label)}</strong></span></div>`
    : `<div class="product-state-problem"><strong>${row.freshness === 'expired' ? '已过复核期限' : '没有当前有效状态'}</strong><span>请先核验依据，不要使用版本中心的最大版本号替代当前状态。</span></div>`;
  const pending = model.pending.length
    ? `<div class="product-state-pending"><strong>${model.pending.length} 条待审核</strong><span>审核通过前不会覆盖当前状态。</span></div>`
    : '';
  const verification = row.reviewed_at
    ? `最后核验 ${escapeHtml(row.reviewed_at)} · ${escapeHtml(row.reviewed_by || '未登记审核人')}`
    : '尚未审核';
  return `<article class="product-state-row">
    <header><div><strong>${escapeHtml(model.model_name)}</strong><span>${escapeHtml(row.effective_date)} 起生效</span></div><span class="pill ${statusClass}">${escapeHtml(row.freshness_label)}</span></header>
    ${headline}
    <div class="product-state-trust"><span>${verification}</span><span>${row.valid_until ? `复核期限 ${escapeHtml(row.valid_until)}` : '未设置复核期限'}</span><small>${escapeHtml(row.evidence_excerpt)}</small></div>
    ${pending}
    <details class="product-state-history"><summary>状态历史（${model.history.length} 条）</summary><ol>${model.history.map(productStateHistoryRow).join('')}</ol></details>
  </article>`;
}

async function loadProductStateOptions() {
  const marketSelect = document.querySelector('#product-states-market');
  const modelSelect = document.querySelector('#product-states-model');
  if (!marketSelect || !modelSelect) return;
  const previousMarket = marketSelect.value || 'CN';
  const previousModel = modelSelect.value;
  const data = await api('/api/v1/knowledge-hub/product-states/options');
  const markets = data.markets.length ? data.markets : [{ code: 'CN', label: '中国国内版' }];
  marketSelect.innerHTML = markets.map(item => `<option value="${escapeAttribute(item.code)}">${escapeHtml(item.label)}</option>`).join('');
  if ([...marketSelect.options].some(option => option.value === previousMarket)) marketSelect.value = previousMarket;
  modelSelect.innerHTML = `<option value="">全部机型</option>${data.models.map(name => `<option value="${escapeAttribute(name)}">${escapeHtml(name)}</option>`).join('')}`;
  if ([...modelSelect.options].some(option => option.value === previousModel)) modelSelect.value = previousModel;
  modelSelect.dataset.loaded = 'true';
}

async function loadProductStates() {
  const summary = document.querySelector('#product-states-summary');
  const list = document.querySelector('#product-states-list');
  if (!summary || !list) return;
  summary.innerHTML = loadingMarkup('正在核对产品状态…');
  list.innerHTML = '';
  const query = new URLSearchParams({
    market: document.querySelector('#product-states-market').value || 'CN',
    model: document.querySelector('#product-states-model').value,
  });
  try {
    const data = await api(`/api/v1/knowledge-hub/product-states?${query.toString()}`);
    const needsAttention = data.summary.models === 0 || data.summary.expired > 0 || data.summary.pending_review > 0 || data.summary.without_current > 0;
    const conclusion = data.summary.models === 0
      ? '当前范围没有已登记的产品状态'
      : data.summary.expired > 0 || data.summary.without_current > 0
        ? '存在需要复核或补录当前状态的机型'
        : data.summary.pending_review > 0
          ? '存在待审核记录，审核前不会覆盖当前状态'
          : '当前范围内的登记机型均有已核验状态';
    summary.classList.toggle('attention', needsAttention);
    summary.innerHTML = queryConclusionContent({
      label: '状态结论',
      title: conclusion,
      detail: `${data.scope.market_label} · ${data.scope.model || `${data.summary.models} 个机型`} · 查询时间 ${formatDateTime(data.checked_at)} · 结论来自显式审核记录`,
      metrics: [
        { label: '当前已核验', value: data.summary.current },
        { label: '已过复核期限', value: data.summary.expired },
        { label: '待审核', value: data.summary.pending_review },
        { label: '无当前状态', value: data.summary.without_current },
      ],
    });
    list.innerHTML = data.models.length
      ? data.models.map(productStateRow).join('')
      : `<div class="strategy-problem"><strong>没有已登记状态</strong><p>${escapeHtml(data.empty_reason)}</p></div>`;
  } catch (error) {
    summary.textContent = '';
    list.innerHTML = strategyProblemMarkup(error);
  }
}

function ensureProductStatesLoaded() {
  const modelSelect = document.querySelector('#product-states-model');
  if (!modelSelect || modelSelect.dataset.loaded === 'true') return;
  loadProductStateOptions()
    .then(() => loadProductStates())
    .catch(error => showNotice(error.message));
}

function registrationEvidence(evidence) {
  if (!evidence) return '<span>未登记原文位置</span>';
  const location = [evidence.sheet ? `工作表 ${evidence.sheet}` : '', evidence.cell_range ? `单元格 ${evidence.cell_range}` : '', evidence.page ? `第 ${evidence.page} 页` : ''].filter(Boolean).join(' · ');
  return `<span>${escapeHtml(evidence.document_title || '未命名资料')}${location ? ` · ${escapeHtml(location)}` : ''}</span><span>${escapeHtml(evidence.excerpt || '')}</span>`;
}

function registrationUnit(unit) {
  const conflict = unit.exclusion_consistent
    ? ''
    : `<small class="strategy-note warning">排除项没有证书维度：本证书全集里有 ${unit.excluded_total} 项型号排除，其中只有 ${unit.excluded_reflected} 项反映到了派生结果；差额需人工核对，系统不擅自择一。</small>`;
  return `<article class="strategy-row">
    <div class="strategy-row-head"><strong>${escapeHtml(unit.certificate_no)}</strong><span class="pill ${unit.exclusion_consistent ? '' : 'warning'}">${unit.exclusion_consistent ? '一致' : '待核对'}</span></div>
    <div class="registration-math"><span>注册全集 <b>${unit.scope_size}</b></span><span>本证书排除项 <b>${unit.excluded_total}</b></span><span>派生结果 <b>${unit.derived_total}</b></span><span>已注册 <b>${unit.registered}</b></span><span>未注册 <b>${unit.unregistered}</b></span>${unit.all_applicable ? '<span class="pill">探头全适用</span>' : ''}</div>
    ${conflict}
    <details class="strategy-row-more"><summary>派生探头明细（${unit.probes.length} 项）</summary><div class="strategy-source-values">${unit.probes.map(probe => `<span>${escapeHtml(probe.probe_code)}：${escapeHtml(probe.state)} · ${escapeHtml(probe.rule || '')}</span>`).join('')}</div></details>
    ${unit.excluded_probes.length ? `<details class="strategy-row-more"><summary>型号排除项（${unit.excluded_probes.length} 项）</summary><div class="strategy-source-values">${unit.excluded_probes.map(item => `<span>${escapeHtml(item.probe_code)}：${escapeHtml(item.reason)}${item.reflected ? '（已反映到派生结果）' : '（未反映到本证书派生结果）'}</span>`).join('')}</div></details>` : ''}
    <details class="strategy-row-more"><summary>原文位置（${unit.evidence.length} 条）</summary><div class="strategy-source-values">${unit.evidence.map(registrationEvidence).join('')}</div></details>
  </article>`;
}

async function loadRegistrationModels() {
  const select = document.querySelector('#registration-model');
  if (!select) return;
  try {
    const data = await api(`/api/v1/knowledge-hub/registrations/models?country=${encodeURIComponent(document.querySelector('#registration-country').value)}`);
    const options = [
      ...data.base_models.map(name => `<option value="${escapeAttribute(name)}">${escapeHtml(name)}</option>`),
      ...data.derived_models.map(item => `<option value="${escapeAttribute(item.derived_model)}">${escapeHtml(item.derived_model)}（衍生 → ${escapeHtml(item.base_model)}）</option>`),
    ];
    select.innerHTML = options.length ? options.join('') : '<option value="">该国家下没有可查询机型</option>';
    select.dataset.loaded = 'true';
  } catch (error) {
    select.innerHTML = '<option value="">机型清单不可用</option>';
    renderRegistrationProblem(error);
  }
}

async function loadRegistration() {
  const units = document.querySelector('#registration-units');
  const verdict = document.querySelector('#registration-verdict');
  if (!units) return;
  const model = document.querySelector('#registration-model').value;
  if (!model) {
    if (state.registrationProblem) renderRegistrationProblem(state.registrationProblem);
    else units.innerHTML = '<p class="empty-state compact">请先选择机型。</p>';
    return;
  }
  units.innerHTML = loadingMarkup('正在查询注册资料…');
  const country = document.querySelector('#registration-country').value;
  try {
    const data = await api(`/api/v1/knowledge-hub/registrations?country=${encodeURIComponent(country)}&model=${encodeURIComponent(model)}`);
    const derived = data.derived ? `<span class="pill note">衍生型号 → 注册按 ${escapeHtml(data.registration_model)}</span>` : '';
    const conflicts = data.units.filter(unit => !unit.exclusion_consistent).length;
    const pending = data.state !== 'resolved' || data.units.length === 0;
    verdict.classList.toggle('attention', pending || conflicts > 0);
    const redLines = data.red_lines.length
      ? `<details class="query-conclusion-details"><summary>查询口径与红线（${data.red_lines.length} 条）</summary><div>${data.red_lines.map(line => `<span>${escapeHtml(line)}</span>`).join('')}</div></details>`
      : '';
    verdict.innerHTML = queryConclusionContent({
      label: '注册结论',
      title: pending ? `${data.queried_model} 的注册资料待确认` : `${data.queried_model} 已定位 ${data.units.length} 个注册单元`,
      detail: `${data.country.label} · 按注册单元分别呈现，不合并计算 · 查询时间 ${formatDateTime(data.checked_at)}`,
      metrics: [
        { label: '注册单元', value: data.units.length },
        { label: '待人工核对', value: conflicts },
      ],
    }) + `<div class="query-conclusion-notes">${derived}${data.mapping_source ? `<small>映射依据：${escapeHtml(data.mapping_source)}</small>` : ''}${data.reason ? `<small>${escapeHtml(data.reason)}</small>` : ''}${redLines}</div>`;
    units.innerHTML = data.units.length
      ? data.units.map(registrationUnit).join('')
      : '<div class="strategy-problem"><strong>待确认</strong><p>当前资料中查不到该机型的注册记录——这不等于「未注册」，需要补充注册资料或确认机型映射。</p></div>';
  } catch (error) {
    verdict.innerHTML = '';
    units.innerHTML = strategyProblemMarkup(error);
  }
}

function renderRegistrationProblem(error) {
  state.registrationProblem = error;
  const units = document.querySelector('#registration-units');
  const verdict = document.querySelector('#registration-verdict');
  if (verdict) verdict.innerHTML = '';
  if (units) units.innerHTML = strategyProblemMarkup(error);
}

function ensureRegistrationLoaded() {
  const select = document.querySelector('#registration-model');
  if (!select || select.dataset.loaded === 'true') return;
  loadRegistrationModels().then(() => {
    if (select.value) return loadRegistration();
    return null;
  }).catch(error => showNotice(error.message));
}

const TRAINING_MAX_DEPTH_NOTE = '最多两层';

function formatBytes(size) {
  if (size === null || size === undefined) return '';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function trainingNodes(entries) {
  return entries.map(item => item.kind === 'directory'
    ? `<li class="training-node directory"><div><strong>${escapeHtml(item.name)}</strong><span>${(item.children || []).length} 项</span></div>${item.children && item.children.length ? `<ul>${trainingNodes(item.children)}</ul>` : ''}</li>`
    : `<li class="training-node file"><div><span>${escapeHtml(item.name)}</span><span class="training-size">${escapeHtml(formatBytes(item.size))}</span>${item.preview_id ? `<button type="button" class="text-button" data-search-result-preview="${escapeAttribute(item.preview_id)}">预览</button>` : ''}</div></li>`).join('');
}

async function loadTrainingAssets() {
  const container = document.querySelector('#training-list');
  const meta = document.querySelector('#training-meta');
  if (!container) return;
  const query = document.querySelector('#training-query').value.trim();
  container.innerHTML = loadingMarkup('正在读取培训资料目录…');
  try {
    const data = await api(`/api/v1/workbench/training?q=${encodeURIComponent(query)}`);
    meta.innerHTML = `<div class="strategy-source-row"><strong>资料目录</strong><span>${escapeHtml(data.root || '未配置')}</span><small>${escapeHtml(data.detail)} · 检查时间 ${escapeHtml(formatDateTime(data.checked_at))}${data.truncated ? ' · 条目已截断' : ''}</small></div>`;
    if (data.status !== 'available') {
      container.innerHTML = `<div class="strategy-problem"><strong>培训资料目录不可用</strong><p>${escapeHtml(data.detail)}</p><small>请在配置项 training_root 指向只读目录；本页只列清单，不预览文件内容。</small></div>`;
      return;
    }
    container.innerHTML = data.entries.length
      ? `<ul class="training-tree">${trainingNodes(data.entries)}</ul>`
      : '<p class="empty-state compact">没有匹配的资料。</p>';
  } catch (error) {
    meta.innerHTML = '';
    container.innerHTML = `<div class="strategy-problem"><strong>读取失败</strong><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function ensureTrainingLoaded() {
  const container = document.querySelector('#training-list');
  if (!container || container.dataset.loaded === 'true') return;
  loadTrainingAssets().then(() => { container.dataset.loaded = 'true'; }).catch(error => showNotice(error.message));
}

const STRATEGY_STATUS_LABELS = {
  published: '正式策略',
  pending_confirmation: '待确认',
  conflict: '资料冲突，待确认',
  registration_check_required: '待注册资料核对',
};

function renderStrategyProblem(error) {
  state.strategyProblem = error;
  const source = document.querySelector('#strategy-source');
  const container = document.querySelector('#strategy-result');
  if (source) source.innerHTML = '';
  if (container) container.innerHTML = strategyProblemMarkup(error);
}

function strategyProblemMarkup(error) {
  const message = escapeHtml(error.message || '查询失败');
  if (error.status === 503 || error.code === 'source_unavailable') {
    return `<div class="strategy-problem"><strong>配置库当前不可用</strong><p>${message}</p><small>本页只做只读查询，不会写源库。请确认配置管理系统主库可读（配置项 product_config_database），或改用只读副本。<button type="button" class="ghost-button compact-button" id="strategy-retry">重试</button></small></div>`;
  }
  if (error.status === 400 || error.code === 'validation_error') {
    return `<div class="strategy-problem"><strong>该范围暂不支持</strong><p>${message}</p><small>阶段0 只开放国内版；机型名称需要与配置系统一致。</small></div>`;
  }
  return `<div class="strategy-problem"><strong>查询失败</strong><p>${message}</p></div>`;
}

async function loadProductStrategyModels() {
  const select = document.querySelector('#strategy-model');
  if (!select) return;
  try {
    const data = await api('/api/v1/knowledge-hub/product-strategies/models');
    select.innerHTML = data.models.length
      ? data.models.map(model => `<option value="${escapeAttribute(model.name)}">${escapeHtml(model.name)}</option>`).join('')
      : '<option value="">该市场下没有可用机型</option>';
    select.dataset.loaded = 'true';
    state.strategyProblem = null;
  } catch (error) {
    select.innerHTML = '<option value="">机型清单不可用</option>';
    renderStrategyProblem(error);
  }
}

function renderStrategySource(data) {
  const source = document.querySelector('#strategy-source');
  const snapshot = data.source.snapshot;
  const snapshotRow = snapshot
    ? `<span>${escapeHtml(snapshot.snapshot_id)} · 采集于 ${escapeHtml(formatDateTime(snapshot.collected_at))}</span><small>快照哈希 ${escapeHtml(String(snapshot.source_sha256).slice(0, 12))}…。快照只作参照：本次结果来自上面的实时只读读取，且源库每次启动都会改写文件头，两者哈希不可比。</small>`
    : '<span>未登记过一致性快照</span><small>结果仍来自上面的实时只读读取。</small>';
  source.innerHTML = `
    <div class="strategy-source-row"><strong>本次读取</strong><span>${escapeHtml(data.source.system)} · 只读直连 · 字段 ${escapeHtml(data.source.selection_field)}</span><small>读取时间：${escapeHtml(formatDateTime(data.source.checked_at))}</small></div>
    <div class="strategy-source-row"><strong>最近一次一致性快照</strong>${snapshotRow}</div>
    <div class="strategy-source-row"><strong>查询范围</strong><span>${escapeHtml(data.scope.market_label)} · ${escapeHtml(data.scope.series)} · ${escapeHtml(data.scope.model)}</span><small>注册型号：${escapeHtml(data.scope.registration_model)} · 来源机型：${data.scope.source_models.map(model => escapeHtml(model.name)).join('、')}</small></div>`;
}

function strategyRow(item) {
  const status = item.knowledge_status;
  const pillClass = status === 'published' ? '' : status === 'conflict' ? 'warning' : 'note';
  const notes = [];
  if (item.registration_marker) {
    notes.push('<small class="strategy-note">「#」只表示需要与注册资料核对，<b>不等于未注册</b>；正式注册结论以注册差异表计算为准。</small>');
  }
  if (item.conflicting_selection_configs.length) {
    notes.push(`<small class="strategy-note warning">来源取值不一致：${item.conflicting_selection_configs.map(value => escapeHtml(value)).join(' / ')} —— 系统不擅自择一，需人工确认。</small>`);
  }
  if (item.current_config_note) {
    notes.push(`<small class="strategy-note">研发内部状态：${escapeHtml(item.current_config || '—')}（${escapeHtml(item.current_config_note)}）</small>`);
  }
  if (status === 'pending_confirmation') {
    notes.push('<small class="strategy-note">没有可用的正式选型值，需人工确认。</small>');
  }
  return `<article class="strategy-row">
    <div class="strategy-row-head"><strong>${escapeHtml(item.name || item.code || '未命名条目')}</strong><span class="pill ${pillClass}">${escapeHtml(STRATEGY_STATUS_LABELS[status] || status)}</span></div>
    <div class="strategy-row-meta"><span class="scope-chip">${escapeHtml(item.code || '—')}</span><span>${escapeHtml(item.category || '')}</span><span>${escapeHtml(item.zh_description || '')}</span></div>
    ${notes.join('')}
    <details class="strategy-row-more"><summary>来源取值（${item.source_values.length} 个来源机型）</summary><div class="strategy-source-values">${item.source_values.map(value => `<span>${escapeHtml(value.model_name)}：selection=${escapeHtml(value.selection_config || '未定义')} · current=${escapeHtml(value.current_config || '未定义')}</span>`).join('')}</div></details>
  </article>`;
}

async function loadProductStrategies() {
  const container = document.querySelector('#strategy-result');
  if (!container) return;
  const modelSelect = document.querySelector('#strategy-model');
  const model = modelSelect ? modelSelect.value : '';
  if (!model) {
    // 机型清单本身就是因为来源不可用才空的：保留那条提示，不要用「请先选择机型」顶掉它。
    if (state.strategyProblem) renderStrategyProblem(state.strategyProblem);
    else container.innerHTML = '<p class="empty-state compact">请先选择机型。</p>';
    return;
  }
  container.innerHTML = loadingMarkup('正在读取正式策略…');
  const market = document.querySelector('#strategy-market').value;
  const query = document.querySelector('#strategy-query').value.trim();
  try {
    const data = await api(`/api/v1/knowledge-hub/product-strategies?market=${encodeURIComponent(market)}&model=${encodeURIComponent(model)}&q=${encodeURIComponent(query)}`);
    renderStrategySource(data);
    if (!data.items.length) {
      container.innerHTML = '<p class="empty-state compact">该条件下没有正式策略记录。</p>';
      return;
    }
    const counts = data.items.reduce((accumulator, item) => {
      accumulator[item.knowledge_status] = (accumulator[item.knowledge_status] || 0) + 1;
      return accumulator;
    }, {});
    const summary = Object.entries(counts)
      .map(([status, count]) => `${escapeHtml(STRATEGY_STATUS_LABELS[status] || status)} ${count}`)
      .join(' · ');
    container.innerHTML = `<div class="strategy-summary">共 ${data.items.length} 条 · ${summary}</div>${limitedListMarkup('strategy', data.items, strategyRow, { wrap: true })}`;
  } catch (error) {
    renderStrategyProblem(error);
  }
}

function ensureStrategyLoaded() {
  const select = document.querySelector('#strategy-model');
  if (!select || select.dataset.loaded === 'true') return;
  loadProductStrategyModels().then(() => {
    if (select.value) return loadProductStrategies();
    return null;
  }).catch(error => showNotice(error.message));
}

function renderScenarioVersionOptions(target = null, base = null) {
  const targetNode = document.querySelector('#scenario-target');
  const baseNode = document.querySelector('#scenario-base');
  if (!targetNode || !baseNode) return;
  target = target ?? targetNode.value;
  base = base ?? baseNode.value;
  const options = state.releases.map(item => `<option value="${escapeAttribute(item.version)}">${escapeHtml(item.version)}</option>`).join('');
  targetNode.innerHTML = `<option value="">${['feature', 'whitepaper'].includes(scenarioState.task) ? '截至最新版本' : '选择目标版本'}</option>${options}`;
  baseNode.innerHTML = `<option value="">不对比</option>${options}`;
  targetNode.value = target || '';
  baseNode.value = base || '';
}

function setScenarioTask(task) {
  if (!['first', 'probe', 'feature', 'version', 'whitepaper'].includes(task)) task = 'feature';
  scenarioState.task = task;
  if (!['probe', 'whitepaper'].includes(task)) scenarioState.featureTask = task;
  if (task !== 'whitepaper') scenarioState.domain = task === 'probe' ? 'probe' : 'feature';
  const probe = scenarioState.domain === 'probe';
  document.querySelectorAll('[data-scenario-domain]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.scenarioDomain === (probe ? 'probe' : 'feature'))));
  document.querySelectorAll('[data-scenario-task]').forEach(button => {
    button.hidden = task === 'whitepaper' || (probe ? button.dataset.scenarioTask !== 'probe' : button.dataset.scenarioTask === 'probe');
    button.setAttribute('aria-pressed', String(button.dataset.scenarioTask === task));
  });
  document.querySelectorAll('[data-scenario-source]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.scenarioSource === (task === 'whitepaper' ? 'whitepaper' : 'release'))));
  document.querySelector('.scenario-tasks').hidden = task === 'whitepaper';
  const queryLabel = document.querySelector('#scenario-query-label');
  queryLabel.hidden = false;
  queryLabel.firstChild.textContent = probe ? '探头名称' : '功能名称或关键词';
  document.querySelector('#scenario-query').placeholder = probe ? '例如 F4-9E' : '例如 VAid GYN、子宫畸形分类';
  document.querySelector('#scenario-model-label').hidden = task !== 'whitepaper';
  document.querySelector('#scenario-target-label').hidden = probe || task === 'first' || task === 'whitepaper';
  document.querySelector('#scenario-base-label').hidden = task !== 'version';
  renderScenarioVersionOptions();
}

function changeScenarioTask(task) {
  const query = document.querySelector('#scenario-query');
  const previousDomain = scenarioState.domain || (scenarioState.task === 'probe' ? 'probe' : 'feature');
  const domain = task === 'whitepaper' ? previousDomain : task === 'probe' ? 'probe' : 'feature';
  scenarioState.drafts[previousDomain] = query.value;
  if (previousDomain !== domain) {
    query.value = scenarioState.drafts[domain] || '';
    scenarioState.model = ''; scenarioState.document = ''; scenarioState.section = '';
    const model = document.querySelector('#scenario-model');
    if (model) model.innerHTML = '<option value="">自动选择</option>';
  }
  if (domain === 'feature' && task !== 'whitepaper') scenarioState.featureTask = task;
  scenarioState.domain = domain;
  scenarioState.request++;
  scenarioState.code = ''; scenarioState.series = ''; scenarioState.result = null;
  document.querySelector('#advanced-search-wrap').open = false;
  document.querySelector('#scenario-result').innerHTML = '';
  setScenarioTask(task);
  syncLocation();
}

function scenarioFirstMarkup(data, query) {
  const records = data.earliest_records || [];
  if (!records.length) return '<section class="scenario-answer"><h3>未找到可核实的历史记录</h3><p>可换用功能名称、曾用名或关键词继续查询。</p></section>';
  return `<section class="scenario-answer"><h3>最早记载 · ${escapeHtml(records[0].version)}</h3><p>这是已收录资料中的最早记载，尚不能据此认定为首次支持。</p>${records.map(item => `<article><h4>${escapeHtml(item.title || query)}</h4><div class="scenario-content">${escapeHtml(item.config_evidence || item.matched_text || item.snippet || '')}</div>${scenarioPreviewButton(item.preview_id, item.locator, query, '查看原文依据')}</article>`).join('')}</section>`;
}

function filterScenarioVersion(data, query) {
  if (!query) return data;
  const matches = row => [row.title_cn, row.title_en, row.description_cn, row.description_en].some(value => String(value || '').toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const filtered = {...data, target: data.target ? {...data.target, changes: (data.target.changes || []).filter(matches)} : null};
  if (data.comparison) filtered.comparison = Object.fromEntries(Object.entries(data.comparison).map(([key, groups]) => [key, ['added', 'removed', 'common'].includes(key) ? Object.fromEntries(Object.entries(groups || {}).map(([category, rows]) => [category, rows.filter(matches)])) : groups]));
  return filtered;
}

function scenarioPreviewButton(source, locator, query, label = '查看原文') {
  return `<button type="button" class="ghost-button compact-button" data-scenario-preview="${escapeAttribute(source)}" data-scenario-locator="${escapeAttribute(locator || '')}" data-scenario-query="${escapeAttribute(query || '')}">${escapeHtml(label)}</button>`;
}

function scenarioProbeMarkup(data, query) {
  if (!data.identities.length) return '<p class="empty-state compact">未找到该名称的探头记录。资料缺失不代表不支持。</p>';
  if (!data.selected) return `<section class="scenario-answer"><h3>请选择探头身份</h3><p>同名探头存在多个 V 代码或系列。</p>${data.identities.map(item => `<button type="button" class="ghost-button compact-button" data-scenario-code="${escapeAttribute(item.code)}" data-scenario-series="${escapeAttribute(item.series)}">${escapeHtml(item.model)} · ${escapeHtml(item.code)} · ${escapeHtml(item.series)}</button>`).join(' ')}</section>`;
  const selected = data.selected;
  const evidence = data.evidence;
  const conclusion = evidence ? `<h3>最早可证实新增支持 · ${escapeHtml(evidence.version)}</h3><p>${escapeHtml(selected.model)} · ${escapeHtml(selected.code)} · ${escapeHtml(selected.series)}</p>${scenarioPreviewButton(evidence.preview_id, evidence.locator, query, '查看版本原文')}` : `<h3>尚无可核实的新增支持原文</h3><p>${escapeHtml(selected.model)} · ${escapeHtml(selected.code)} · ${escapeHtml(selected.series)}</p>${data.candidates.length ? `<p>关系记录：${data.candidates.map(row => escapeHtml(row.software_version)).join('、')}，需核对原文。</p>` : ''}`;
  return `<section class="scenario-answer">${conclusion}${data.identities.length > 1 ? '<button type="button" class="text-button" data-scenario-reselect>重新选择身份</button>' : ''}<details><summary>依据与覆盖范围</summary><p>仅限当前项目和所选系列。已登记资料可能不完整，最早可证实记录不等于已确认的绝对首次；未找到记录不代表不支持。</p></details></section>`;
}

function scenarioDescriptionMarkup(description) {
  const status = description.edited ? '手工修订' : description.status === 'ready' ? '大模型整理 · 未复核' : '原说明 · 待自动整理';
  return `<div class="scenario-description-heading"><h3>整理后的功能说明</h3><span>${escapeHtml(status)}</span><button type="button" class="ghost-button compact-button" data-description-edit>编辑</button></div>
    ${description.error ? `<p role="status">${escapeHtml(description.error)}</p>` : ''}
    ${description.sources_changed ? '<p role="status">资料已更新，已保留手工修订。可参考最新自动稿继续编辑。</p>' : ''}
    <div class="scenario-content">${escapeHtml(description.content)}</div>
    ${description.edited ? `<details><summary>查看最新自动整理稿</summary><div class="scenario-content">${escapeHtml(description.automatic_content)}</div></details>` : ''}
    ${description.unresolved?.length ? `<details><summary>整理中需核对的内容（${description.unresolved.length}）</summary>${description.unresolved.map(value => `<p>${escapeHtml(value)}</p>`).join('')}</details>` : ''}
    <dialog data-description-editor class="scenario-description-editor"><form data-description-form>
      <div class="dialog-heading"><h2>编辑功能说明</h2><button type="button" data-description-cancel aria-label="关闭">×</button></div>
      <label>功能说明<textarea rows="16" data-description-content maxlength="100000" required>${escapeHtml(description.content)}</textarea></label>
      <p data-description-status role="alert"></p><div class="dialog-actions">
        <button type="button" class="ghost-button" data-description-automatic>使用自动稿</button>
        <button type="button" class="ghost-button" data-description-cancel>取消</button>
        <button type="submit" class="primary-button" data-description-save>保存修订</button>
      </div></form></dialog>`;
}

function scenarioFeatureMarkup(data, query) {
  const item = data.baseline, section = data.section;
  if (!item || !section) {
    if ((data.documents || []).length > 1 && !data.selected_document) return `<section class="scenario-answer"><h3>请选择资料范围</h3><p>这些资料未登记为同一版本链，请按市场和语言选择。</p>${data.documents.map(doc => `<button type="button" class="ghost-button compact-button" data-scenario-document="${escapeAttribute(doc.value)}">${escapeHtml(doc.label)} · ${escapeHtml(doc.scope)}</button>`).join(' ')}</section>`;
    if ((data.section_options || []).length) return `<section class="scenario-answer"><h3>请选择原文章节</h3><p>同版章节内容不同，请核对后选择。</p>${data.section_options.map(option => `<button type="button" class="ghost-button compact-button" data-scenario-section="${escapeAttribute(option.value)}">${escapeHtml(option.label)} · ${escapeHtml(option.version)} · ${escapeHtml(option.scope)}</button>`).join(' ')}</section>`;
    return `<p class="empty-state compact">未找到可核实的完整章节。请检查型号、资料范围或使用高级检索查看原文。${data.coverage_complete ? '' : '部分来源受限或候选过多，结果可能不完整。'}</p>`;
  }
  const detail = item.detail_evidence;
  const heading = data.latest_certified ? '所选资料链中已检索的最新完整描述' : '完整描述候选（较新资料或范围待核对）';
  const changes = data.later_changes || [];
  const later = changes.length ? `<details><summary>${data.description ? '整理依据' : '后续变更待整合'}（${changes.length}）</summary>${changes.map(change => `<article><p><strong>${escapeHtml(change.version)} · ${escapeHtml(categoryLabels[change.category] || change.category || '变更')}</strong> · ${escapeHtml(change.evidence_type === 'clue' ? (change.status || '原文线索，未确认') : (change.review_status || '状态未登记'))}</p><p>${escapeHtml(change.description_cn || change.description_en || change.matched_text || change.title_cn || change.title_en || '')}</p>${scenarioPreviewButton(change.preview_id, change.locator || (change.description_cn || change.title_cn ? '中文记录' : 'English record'), query, '查看变更原文')}</article>`).join('')}</details>` : '<p>未找到后续相关变更；资料覆盖仍需核对。</p>';
  if (data.description) {
    const description = data.description;
    const sources = (description.evidence || []).map(source => `<article><p><strong>${escapeHtml(source.versions.join('、'))}</strong> · ${escapeHtml(source.state)}</p><p>${escapeHtml(source.text)}</p>${scenarioPreviewButton(source.preview_id, source.locator, query, '查看引用原文')}</article>`).join('');
    return `<section class="scenario-answer">${scenarioDescriptionMarkup(description)}<p>${escapeHtml(detail.scope || item.scope || '适用范围未登记')} · 基线 ${escapeHtml(item.version)}</p>
      <details><summary>原文章节</summary><div class="scenario-content">${escapeHtml(section.content)}</div>${scenarioPreviewButton(detail.source_id, section.locator || detail.locator, query, '查看完整原文')}</details>
      <details><summary>整理引用与版本</summary>${sources}</details>${later}
      <details class="scenario-method"><summary>整理范围与用量</summary><p class="strategy-note">自动稿按已入库资料整理；原文引用已校验，内容含义仍可手工修订。${description.excluded_count ? `${description.excluded_count} 条其他语言、重复或非正文记录保留在依据中。` : ''}未登记和未索引的资料不在整理范围内。</p>
      ${description.usage ? `<p class="strategy-note">今日自动整理：${description.usage.today_requests} 次请求 · 已返回用量 ${description.usage.today_tokens} tokens（未返回用量的请求按预留预算计）。</p>` : ''}</details></section>`;
  }
  return `<section class="scenario-answer"><h3>${heading} · ${escapeHtml(item.version)}</h3><p>${escapeHtml(detail.title || item.title)} · ${escapeHtml(verificationLabel(detail.verification || 'unverified'))} · ${escapeHtml(detail.scope || item.scope || '适用范围未登记')}</p><div class="scenario-content">${escapeHtml(section.content)}</div><p>以上为完整章节文本；图片和原始版式可在原文预览中查看。未索引或未登记的资料不在本次结论中。</p>${scenarioPreviewButton(detail.source_id, section.locator || detail.locator, query, '查看完整原文')}${later}<details><summary>来源与适用范围</summary><p>${escapeHtml(detail.scope || item.scope || '适用范围未登记')} · ${escapeHtml(item.title)}</p><p>资料型号取自登记信息或资料名称，未登记的适用范围需要核对；后续变化不会自动合并到正文。</p></details></section>`;
}

function scenarioDocumentMarkup(text, additions = [], imageMarkup = '') {
  const headings = /^(临床意义|功能描述|功能说明|参数|测量结果|操作步骤|效果图示|适用范围)[：:]?$/;
  const lines = String(text || '').split(/\r?\n/);
  const groups = [{title: '', lines: []}];
  const updatesByVersion = new Map();
  let currentGroup = groups[0];
  for (const line of lines) {
    const trimmed = line.trim();
    const heading = trimmed.match(headings);
    const addition = additions.find(row => row.operation === 'append' && String(row.after || '').trim() === trimmed);
    if (heading) {
      currentGroup = {title: heading[1], lines: []};
      groups.push(currentGroup);
    } else if (addition) {
      const version = String(addition.version || '未标注');
      if (!updatesByVersion.has(version)) {
        const group = {title: `版本 ${version} 补充`, lines: [], updated: true};
        updatesByVersion.set(version, group);
        groups.push(group);
      }
      currentGroup = updatesByVersion.get(version);
      currentGroup.lines.push(line);
    } else currentGroup.lines.push(line);
  }
  return `<div class="feature-document">${groups.filter(group => group.title || group.lines.some(line => line.trim())).map(group => {
    const content = group.lines.filter(line => line.trim());
    let body;
    if (group.title === '操作步骤') body = `<ol class="feature-steps">${content.map(line => `<li>${escapeHtml(line)}</li>`).join('')}</ol>`;
    else if (group.title === '参数') body = `<ul class="feature-parameters">${content.map(line => `<li>${escapeHtml(line)}</li>`).join('')}</ul>`;
    else body = content.map((line, index) => {
      const scope = line.match(/^(适用探头\/应用|适用探头|适用机型|适用应用)[：:](.*)$/);
      if (scope) return `<p class="feature-scope" data-release-review-text="${escapeAttribute(line)}"><strong>${escapeHtml(scope[1])}</strong><span>${escapeHtml(scope[2])}</span></p>`;
      if (!group.title && index === 0 && line.length < 120) return `<h4 class="feature-document-title">${escapeHtml(line)}</h4>`;
      return `<p>${escapeHtml(line)}</p>`;
    }).join('');
    if (group.title === '效果图示' && imageMarkup) { body += imageMarkup; imageMarkup = ''; }
    return `<section class="feature-document-section${group.updated ? ' is-update' : ''}">${group.title ? `<h4>${escapeHtml(group.title)}</h4>` : ''}${body}</section>`;
  }).join('')}${imageMarkup}</div>`;
}

function scenarioBaselineImagesMarkup(baseline, query, latest = false) {
  const section = baseline.section;
  if (!section?.has_images) return '';
  const blocks = (section.blocks || []).filter(block => block.type === 'image');
  let omitted = false;
  const images = blocks.map((block, index) => {
    const markup = sourceImageMarkup(block, `${baseline.version} ${latest ? '最近版本' : '起始版本'}图示 ${index + 1}`);
    if (!markup) omitted = true;
    return markup ? `<div class="feature-image-item">${markup}<p>图 ${index + 1} · ${escapeHtml(baseline.version)} 原文</p></div>` : '';
  }).join('');
  return `<section class="feature-image-section"><h4>${latest ? '最近版本图示' : '起始版本图示'} <span>${escapeHtml(baseline.version)}</span></h4><p>${latest ? `来源：${escapeHtml(baseline.title || '对应功能章节')}，图片版本与正文起点分别标注。` : '图片来自起始章节；后续版本中的效果变化请查看对应变更原文。'}</p><div class="feature-image-gallery">${images}</div>${section.images_complete === false || omitted || !images ? '<p role="alert">部分图片无法展示，请查看原文核对。</p>' : ''}${scenarioPreviewButton(baseline.source_id, baseline.locator, query, '查看图文原文')}</section>`;
}

function scenarioUnverifiedSourcesMarkup(sources, query) {
  const unique = [...new Map((sources || []).map(item => [`${item.source_id}|${item.locator || ''}`, item])).values()];
  if (!unique.length) return '';
  if (unique.length === 1) {
    const item = unique[0];
    return scenarioPreviewButton(item.source_id, item.locator || '', query, `核对 ${item.version} 原文`);
  }
  return `<details class="feature-original-sources"><summary>核对原文（${unique.length} 份资料）</summary><div>${unique.map(item => {
    const id = String(item.source_id || '').split(':').pop();
    const label = `${item.version} · ${item.filename || item.source_label || '发布资料'} · #${id}`;
    return scenarioPreviewButton(item.source_id, item.locator || '', query, label);
  }).join('')}</div></details>`;
}

function scenarioIllustrationsMarkup(data, query) {
  if (!Array.isArray(data.illustrations)) return scenarioBaselineImagesMarkup(data.baseline, query);
  return data.illustrations.map(item => scenarioBaselineImagesMarkup(item, query, true)).join('')
    + (data.illustration_notice ? `<p class="strategy-note" role="status">${escapeHtml(data.illustration_notice)}</p>` : '')
    + scenarioUnverifiedSourcesMarkup(data.illustrations_unverified_sources, query);
}

function scenarioWhitepaperMarkup(data, query) {
  const item = data.baseline, section = data.section;
  if (!item || !section) return `<section class="scenario-answer"><h3>最新白皮书中未找到可核实的对应章节</h3><p>不会回退展示旧版白皮书，也不使用Release Note补充此处内容。</p>${(data.documents || []).map(doc => `<button type="button" class="ghost-button" data-scenario-document="${escapeAttribute(doc.value)}">${escapeHtml(doc.label)}</button>`).join('')}${(data.section_options || []).map(option => `<button type="button" class="ghost-button" data-scenario-section="${escapeAttribute(option.value)}">${escapeHtml(option.label)}</button>`).join('')}</section>`;
  return `<section class="scenario-answer"><h3>最新白皮书 · ${escapeHtml(item.version)}</h3><p>${escapeHtml(item.title || '')} · ${escapeHtml(item.scope || '范围待核对')}</p><div class="scenario-content">${escapeHtml(section.content)}</div>${scenarioPreviewButton(item.detail_evidence.source_id, section.locator, query, '查看白皮书原文')}</section>`;
}

function scenarioEvolutionMarkup(data, query) {
  const baseline = data.baseline;
  if (!baseline) return `<section class="scenario-answer"><h3>${data.status === 'baseline_conflict' ? '起始版本的完整章节存在冲突' : '缺少Release Note完整起始章节'}</h3><p>暂不生成完整描述；不会使用白皮书或模型摘要代替。</p><p>${escapeHtml(data.coverage_notice)}</p>${(data.section_options || []).map(row => `<article><p>${escapeHtml(row.version)} · ${escapeHtml(row.title)}</p>${scenarioPreviewButton(row.source_id, row.locator, query)}</article>`).join('')}</section>`;
  const labels = {baseline:'起始完整章节',append:'补充',replace:'修改',delete:'删除',replace_full:'整体替换',pending:'待核对'};
  const pending = data.unresolved_changes || [];
  return `<section class="scenario-answer"><header class="feature-answer-heading"><h3>${pending.length || data.baseline_gap ? '功能描述 · 尚有变更待核对' : '功能描述 · 已应用明确变更'}</h3><span class="feature-review-badge">${pending.length ? `${pending.length} 项待核对` : '按原文逐版更新'}</span></header><p class="feature-version-summary">Release Note 起点 ${escapeHtml(baseline.version)} · 截至 ${escapeHtml(data.target_version || '最新已收录版本')} · 已应用 ${(data.applied_changes || []).length} 项变更</p>${releaseReviewWorkspaceMarkup(data, query)}<details><summary>版本演进与原文依据</summary>${(data.timeline || []).map(row => `<article><h4>${escapeHtml(row.version)} · ${escapeHtml(labels[row.operation] || row.operation)}</h4><div class="scenario-content">${escapeHtml(row.content || row.text)}</div>${row.before ? `<p>原内容：${escapeHtml(row.before)}</p>` : ''}${row.after ? `<p>更新为：${escapeHtml(row.after)}</p>` : ''}${scenarioPreviewButton(row.source_id, row.locator, query)}</article>`).join('')}</details><p>${escapeHtml(data.coverage_notice)}</p></section>`;
}

function scenarioVersionMarkup(data) {
  if (!data.target) return '<p class="empty-state compact">请选择当前项目已登记的目标版本。</p>';
  const release = data.target;
  const changes = release.changes || [];
  const comparison = data.comparison;
  const counts = comparison ? ['added', 'removed', 'common'].map(key => Object.values(comparison[key] || {}).reduce((sum, rows) => sum + rows.length, 0)) : null;
  return `<section class="scenario-answer"><h3>版本 ${escapeHtml(release.version)} · ${changes.length} 条变化</h3>${counts ? `<p>对比基准：新增 ${counts[0]} · 基准独有 ${counts[1]} · 共有 ${counts[2]}（文本条目）</p><button type="button" class="ghost-button compact-button" data-scenario-compare>查看完整对比</button>` : ''}<details><summary>查看版本变化（${changes.length}）</summary>${changes.map(change => `<article><p><strong>${escapeHtml(categoryLabels[change.category] || change.category || '变更')} · ${escapeHtml(change.title_cn || change.title_en || '未命名')}</strong> · ${escapeHtml(change.review_status || '状态未登记')}</p><p>${escapeHtml(change.description_cn || change.description_en || '')}</p>${scenarioPreviewButton(`release:change:${change.id}`, change.description_cn || change.title_cn ? '中文记录' : 'English record', '', '查看版本原文')}</article>`).join('') || '<p>该版本暂无已登记变化。</p>'}</details></section>`;
}

async function runScenario() {
  document.querySelector('#advanced-search-wrap').open = false;
  const task = scenarioState.task;
  const query = document.querySelector('#scenario-query').value.trim();
  const target = document.querySelector('#scenario-target').value;
  const base = document.querySelector('#scenario-base').value;
  const container = document.querySelector('#scenario-result');
  const requestId = ++scenarioState.request;
  const project = state.activeProjectId;
  if ((task !== 'version' && !query) || (task === 'version' && !target)) {
    container.innerHTML = '<p class="empty-state compact">请先填写查询内容。</p>';
    return;
  }
  const params = new URLSearchParams({ task, q: query });
  if (task === 'probe' && scenarioState.code) { params.set('code', scenarioState.code); params.set('series', scenarioState.series); }
  if (task === 'whitepaper' && scenarioState.model) params.set('model', scenarioState.model);
  if (task === 'whitepaper' && scenarioState.document) params.set('document', scenarioState.document);
  if (task === 'whitepaper' && scenarioState.section) params.set('section', scenarioState.section);
  if (target && ['feature', 'version'].includes(task)) params.set('target', target);
  if (base && task === 'version') params.set('base', base);
  container.innerHTML = loadingMarkup('正在查询资料…');
  syncLocation();
  try {
    const result = task === 'first'
      ? await api(projectPath(`/api/v1/workbench/search?${new URLSearchParams({q: query, task: 'earliest', sources: 'release,controlled', scope: 'current', source_group: 'release_note'})}`))
      : await api(projectPath(`/api/v1/workbench/scenario?${params}`));
    if (requestId !== scenarioState.request || task !== scenarioState.task || project !== state.activeProjectId) return;
    if (task === 'feature') scenarioState.result = result;
    if (task === 'whitepaper') {
      const model = document.querySelector('#scenario-model');
      const options = result.models?.options || [];
      model.innerHTML = options.map(option => `<option value="${escapeAttribute(option.value)}">${escapeHtml(option.label)}</option>`).join('') || '<option value="">暂无匹配型号</option>';
      scenarioState.model = result.models?.selected || '';
      scenarioState.document = result.selected_document || '';
      model.value = scenarioState.model;
      scenarioState.result = result;
      container.innerHTML = scenarioWhitepaperMarkup(result, query);
    } else container.innerHTML = task === 'feature' ? scenarioEvolutionMarkup(result, query) : task === 'probe' ? scenarioProbeMarkup(result, query) : task === 'first' ? scenarioFirstMarkup(result, query) : scenarioVersionMarkup(filterScenarioVersion(result, query));
    syncLocation();
    container.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    if (requestId === scenarioState.request) container.innerHTML = `<p class="empty-state compact" role="alert">查询失败：${escapeHtml(error.message)}。请重试。</p>`;
  }
}

function switchView(view, { remember = true, updateHash = true, scroll = true } = {}) {
  const allowedViews = new Set(workbenchConfig.allowedViews || []);
  if (integratedMode() && !allowedViews.has(view)) view = 'releases';
  const page = document.querySelector(`[data-page="${view}"]`);
  const navigationItem = document.querySelector(`.nav-item[data-view="${view}"]`);
  if (!page || !navigationItem) {
    // 这里以前直接 return，表现为「点了没反应」；现在给可见提示并回报失败。
    reportNavigationProblem(`无法打开「${labels[view] || view}」：缺少${page ? '导航项' : '页面区块'}，已停留在当前工作区。`);
    return false;
  }
  state.evidenceNavigation = (state.evidenceNavigation || 0) + 1;
  state.activeView = view;
  document.querySelector('#global-search-panel').hidden = view !== 'search';
  document.querySelectorAll('.nav-item,.view').forEach(node => node.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(node => node.removeAttribute('aria-current'));
  navigationItem.classList.add('active');
  // 目标项在折叠组里时自动展开，保证"我现在在哪里"始终可见
  const collapsedGroup = navigationItem.closest('details');
  if (collapsedGroup) collapsedGroup.open = true;
  navigationItem.setAttribute('aria-current', 'page');
  page.classList.add('active');
  positionSearchProject(view);
  document.querySelector('#page-title').textContent = labels[view];
  updateViewScope(view);
  if (view === 'search') loadSearchIndexStatus().catch(error => { document.querySelector('#search-index-status').textContent = `索引状态读取失败：${error.message}`; });
  if (view === 'compare') ensureComparisonLoaded();
  if (view === 'home') loadWorkbenchHome();
  if (view === 'model') ensureModelWorkspaceOptions().catch(error => showNotice(error.message));
  if (view === 'strategy') ensureStrategyLoaded();
  if (view === 'product_states' && updateHash) ensureProductStatesLoaded();
  if (view === 'registration' && updateHash) ensureRegistrationLoaded();
  if (view === 'materials') ensureMaterialsLoaded();
  if (view === 'qa') ensureQaLoaded();
  if (view === 'items') ensureItemsLoaded();
  if (view === 'issues') ensureIssuesLoaded();
  if (view === 'probe_versions') ensureProbeVersionsLoaded();
  if (view === 'training') ensureTrainingLoaded();
  if (remember) localStorage.setItem('featureTracker.lastView', view);
  if (updateHash && window.location.hash !== `#${view}`) window.history.pushState(null, '', `#${view}`);
  if (workbenchConfig.embedded && window.parent !== window) {
    window.parent.postMessage({ type: 'release-workbench:navigate', view }, window.location.origin);
  }
  if (updateHash) syncLocation();
  if (scroll) window.scrollTo({ top: 0, behavior: 'smooth' });
  return true;
}

document.querySelectorAll('.nav-item').forEach(button => button.addEventListener('click', () => switchView(button.dataset.view)));
window.addEventListener('message', event => {
  if (!workbenchConfig.embedded || event.source !== window.parent || event.origin !== window.location.origin) return;
  const message = event.data && typeof event.data === 'object' ? event.data : {};
  const view = String(message.view || '');
  const allowedViews = new Set(workbenchConfig.allowedViews || []);
  if (message.type === 'release-workspace:activate' && allowedViews.has(view) && state.activeView !== view) {
    switchView(view);
  }
});
// 用事件委托而不是逐个绑定：首页的模块卡片是渲染之后才出现的。
document.addEventListener('click', event => {
  const target = event.target.closest('[data-view-target]');
  if (target) switchView(target.dataset.viewTarget);
  if (event.target.closest('#strategy-retry')) loadProductStrategies();
  if (event.target.closest('[data-home-todos-retry]')) loadWorkbenchHomeTodos();
  const expand = event.target.closest('[data-expand-list]');
  if (expand) {
    const key = expand.dataset.expandList;
    const loaders = {
      strategy: loadProductStrategies,
      materials: loadKnowledgeDocuments,
      items: loadKnowledgeItems,
      issues: loadKnowledgeIssues,
    };
    expandedLists.add(key);
    const loader = loaders[expand.dataset.expandList];
    if (loader) Promise.resolve(loader()).then(() => focusExpandedList(key)).catch(error => showNotice(error.message));
  }
});
document.querySelectorAll('[data-scenario-task]').forEach(button => button.addEventListener('click', () => changeScenarioTask(button.dataset.scenarioTask)));
document.querySelectorAll('[data-scenario-domain]').forEach(button => button.addEventListener('click', () => changeScenarioTask(button.dataset.scenarioDomain === 'probe' ? 'probe' : scenarioState.featureTask)));
document.querySelectorAll('[data-scenario-source]').forEach(button => button.addEventListener('click', () => {
  changeScenarioTask(button.dataset.scenarioSource === 'whitepaper' ? 'whitepaper' : scenarioState.domain === 'probe' ? 'probe' : scenarioState.featureTask);
  if (document.querySelector('#scenario-query').value.trim()) runScenario();
}));
document.querySelector('#scenario-query').addEventListener('input', () => { scenarioState.code = ''; scenarioState.series = ''; scenarioState.model = ''; scenarioState.document = ''; scenarioState.section = ''; scenarioState.request++; document.querySelector('#scenario-model').innerHTML = '<option value="">自动选择</option>'; document.querySelector('#scenario-result').innerHTML = ''; });
for (const id of ['#scenario-target', '#scenario-base']) document.querySelector(id).addEventListener('change', () => { scenarioState.request++; document.querySelector('#scenario-result').innerHTML = ''; });
document.querySelector('#scenario-form').addEventListener('submit', event => { event.preventDefault(); runScenario(); });
document.querySelector('#scenario-model').addEventListener('change', event => { scenarioState.model = event.target.value; scenarioState.document = ''; scenarioState.section = ''; runScenario(); });
function closeDescriptionEditor(dialog) {
  if (dialog.dataset.saving === 'true') return false;
  if (dialog.querySelector('[data-description-content]').value !== dialog.dataset.original && !window.confirm('修订尚未保存，放弃本次编辑吗？')) return false;
  dialog.querySelector('[data-description-content]').value = dialog.dataset.original;
  dialog.close(); return true;
}

async function saveScenarioDescription(event) {
  if (!event.target.matches('[data-description-form]')) return;
  event.preventDefault();
  const dialog = event.target.closest('dialog');
  if (dialog.dataset.saving === 'true') return;
  const result = scenarioState.result, description = result?.description;
  if (!description) return;
  const request = scenarioState.request, project = state.activeProjectId;
  const status = dialog.querySelector('[data-description-status]');
  const button = dialog.querySelector('[data-description-save]');
  dialog.dataset.saving = 'true'; button.disabled = true; status.textContent = '正在保存…';
  try {
    const saved = await api(projectPath('/api/v1/workbench/scenario/feature-description'), {method: 'PUT', body: JSON.stringify({
      ...description.context, content: dialog.querySelector('[data-description-content]').value,
      revision: description.revision, source_fingerprint: description.source_fingerprint,
    })});
    if (request !== scenarioState.request || project !== state.activeProjectId) return;
    result.description = saved;
    dialog.close();
    document.querySelector('#scenario-result').innerHTML = scenarioFeatureMarkup(result, description.context.q);
    showNotice('手工修订已保存。');
  } catch (error) { status.textContent = `保存失败：${error.message}`; }
  finally { dialog.dataset.saving = 'false'; button.disabled = false; }
}

document.querySelector('#scenario-result').addEventListener('submit', saveScenarioDescription);
window.addEventListener('beforeunload', event => {
  const editor = document.querySelector('[data-description-editor][open]');
  if (editor && editor.querySelector('[data-description-content]').value !== editor.dataset.original) { event.preventDefault(); event.returnValue = ''; }
});
document.querySelector('#scenario-result').addEventListener('click', event => {
  const dialog = document.querySelector('[data-description-editor]');
  if (event.target.closest('[data-description-edit]') && dialog) {
    const field = dialog.querySelector('[data-description-content]');
    dialog.dataset.original = field.value;
    if (!dialog.dataset.guarded) {
      dialog.addEventListener('cancel', event => { if (!closeDescriptionEditor(dialog)) event.preventDefault(); });
      dialog.dataset.guarded = 'true';
    }
    dialog.showModal(); return;
  }
  if (event.target.closest('[data-description-cancel]') && dialog) { closeDescriptionEditor(dialog); return; }
  if (event.target.closest('[data-description-automatic]') && dialog) {
    dialog.querySelector('[data-description-content]').value = scenarioState.result.description.automatic_content; return;
  }
  if (event.target.closest('[data-scenario-reselect]')) { scenarioState.code = ''; scenarioState.series = ''; runScenario(); return; }
  const doc = event.target.closest('[data-scenario-document]');
  if (doc) { scenarioState.document = doc.dataset.scenarioDocument; scenarioState.section = ''; runScenario(); return; }
  const section = event.target.closest('[data-scenario-section]');
  if (section) { scenarioState.section = section.dataset.scenarioSection; runScenario(); return; }
  const identity = event.target.closest('[data-scenario-code]');
  if (identity) { scenarioState.code = identity.dataset.scenarioCode; scenarioState.series = identity.dataset.scenarioSeries; runScenario(); return; }
  const preview = event.target.closest('[data-scenario-preview]');
  if (preview) { openSearchPreview(preview.dataset.scenarioPreview, preview.dataset.scenarioLocator, preview.dataset.scenarioQuery).catch(error => showNotice(error.message)); return; }
  if (event.target.closest('[data-scenario-compare]')) {
    const target = document.querySelector('#scenario-target').value, base = document.querySelector('#scenario-base').value;
    document.querySelector('#from-version').value = base; document.querySelector('#to-version').value = target;
    switchView('compare');
  }
});
document.querySelector('#advanced-search-wrap').addEventListener('toggle', () => { if (state.activeView === 'search') syncLocation(); });
const searchToggle = document.querySelector('#search-toggle');
const searchForm = document.querySelector('#release-search-form');
if (searchToggle && searchForm) {
  searchToggle.addEventListener('click', () => {
    switchView('search');
    document.querySelector('#advanced-search-wrap').open = true;
    document.querySelector('#release-search').focus();
    if (document.querySelector('#release-search').value.trim()) searchUnified().catch(error => showNotice(error.message));
  });
}

const homeRefreshButton = document.querySelector('#home-refresh');
if (homeRefreshButton) homeRefreshButton.addEventListener('click', () => loadWorkbenchHomeTodos());
// 一个「重新检查」覆盖整个系统状态区：来源与外部系统一起刷新，少一个按钮少一份噪音
const homeSourcesRefresh = document.querySelector('#home-sources-refresh');
if (homeSourcesRefresh) homeSourcesRefresh.addEventListener('click', () => refreshWorkbenchSources());
const strategyForm = document.querySelector('#strategy-form');
if (strategyForm) strategyForm.addEventListener('submit', event => { event.preventDefault(); loadProductStrategies(); syncLocation(); });
const strategyModelSelect = document.querySelector('#strategy-model');
if (strategyModelSelect) strategyModelSelect.addEventListener('change', () => loadProductStrategies());
const trainingForm = document.querySelector('#training-form');
if (trainingForm) trainingForm.addEventListener('submit', event => { event.preventDefault(); loadTrainingAssets(); syncLocation(); });
const registrationForm = document.querySelector('#registration-form');
if (registrationForm) registrationForm.addEventListener('submit', event => { event.preventDefault(); loadRegistration(); syncLocation(); });
const registrationModelSelect = document.querySelector('#registration-model');
if (registrationModelSelect) registrationModelSelect.addEventListener('change', () => loadRegistration());
const productStatesForm = document.querySelector('#product-states-form');
if (productStatesForm) productStatesForm.addEventListener('submit', event => { event.preventDefault(); loadProductStates(); syncLocation(); });
['#product-states-market', '#product-states-model'].forEach(selector => {
  const node = document.querySelector(selector);
  if (node) node.addEventListener('change', () => loadProductStates());
});
function bindLongListFilters({ formSelector, selectSelectors, key, load }) {
  const form = document.querySelector(formSelector);
  const apply = () => {
    expandedLists.delete(key);
    load();
    syncLocation();
  };
  if (form) {
    form.addEventListener('submit', event => { event.preventDefault(); apply(); });
    form.addEventListener('reset', () => setTimeout(apply, 0));
  }
  selectSelectors.forEach(selector => {
    const node = document.querySelector(selector);
    if (node) node.addEventListener('change', apply);
  });
}

bindLongListFilters({
  formSelector: '#materials-form',
  selectSelectors: ['#materials-doc-type', '#materials-track', '#materials-verification', '#materials-evidence'],
  key: 'materials',
  load: loadKnowledgeDocuments,
});
bindLongListFilters({
  formSelector: '#items-form',
  selectSelectors: ['#items-category', '#items-code-type', '#items-evidence'],
  key: 'items',
  load: loadKnowledgeItems,
});
bindLongListFilters({
  formSelector: '#issues-form',
  selectSelectors: ['#issues-severity', '#issues-status', '#issues-type'],
  key: 'issues',
  load: loadKnowledgeIssues,
});

document.querySelector('#qa-search-form')?.addEventListener('submit', event => {
  event.preventDefault();
  syncLocation();
  searchQa().catch(error => showNotice(error.message));
});
document.querySelector('#qa-submit-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const result = await api('/api/v1/knowledge-hub/qa/questions', {
      method: 'POST', body: JSON.stringify({
        question: document.querySelector('#qa-question').value.trim(),
        market: document.querySelector('#qa-market').value,
        country: document.querySelector('#qa-country').value.trim().toUpperCase(),
        model: document.querySelector('#qa-model').value.trim(),
        requester: document.querySelector('#qa-requester').value.trim(),
        reason_code: document.querySelector('#qa-reason').value,
        context_note: document.querySelector('#qa-context').value.trim(),
      }),
    });
    document.querySelector('#qa-result').innerHTML = `<p class="qa-submitted" role="status">问题 #${result.id} 已登记，等待负责人核对。</p>`;
    form.hidden = true;
    await loadQaWorkbench();
  } catch (error) { showNotice(error.message); }
});
document.querySelector('#qa-draft-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api('/api/v1/knowledge-hub/qa/answers', {
      method: 'POST', body: JSON.stringify({
        standard_question: document.querySelector('#qa-draft-question').value.trim(),
        similar_questions: document.querySelector('#qa-draft-similar').value.split('\n').map(value => value.trim()).filter(Boolean),
        answer_text: document.querySelector('#qa-draft-answer').value.trim(),
        market: document.querySelector('#qa-draft-market').value,
        country: document.querySelector('#qa-draft-country').value,
        model: document.querySelector('#qa-draft-model').value.trim(),
        registration_result: document.querySelector('#qa-draft-registration').value.trim(),
        strategy_result: document.querySelector('#qa-draft-strategy').value.trim(),
        limitations: document.querySelector('#qa-draft-limitations').value.trim(),
        evidence_id: Number(document.querySelector('#qa-draft-evidence').value),
      }),
    });
    form.reset();
    showNotice('答案草稿已保存，可提交审核。');
    await loadQaWorkbench();
  } catch (error) { showNotice(error.message); }
});
document.querySelector('#qa-evidence-query')?.addEventListener('input', () => {
  window.clearTimeout(state.qaEvidenceTimer);
  state.qaEvidenceTimer = window.setTimeout(() => loadQaEvidenceOptions().catch(error => showNotice(error.message)), 250);
});
document.querySelector('#qa-inbox')?.addEventListener('click', event => {
  const button = event.target.closest('[data-qa-use-question]');
  if (!button) return;
  const question = (state.qaOpenQuestions || []).find(item => item.id === Number(button.dataset.qaUseQuestion));
  if (!question) return;
  document.querySelector('#qa-draft-question').value = question.question;
  document.querySelector('#qa-draft-market').value = question.market_code;
  document.querySelector('#qa-draft-country').value = question.country_code;
  document.querySelector('#qa-draft-model').value = question.model_name;
  document.querySelector('#qa-draft-question').focus();
});
document.querySelector('#qa-answer-list')?.addEventListener('click', async event => {
  const redraft = event.target.closest('[data-qa-redraft]');
  if (redraft) {
    const answer = (state.qaAnswers || []).find(item => item.id === Number(redraft.dataset.qaRedraft));
    if (!answer) return;
    document.querySelector('#qa-draft-question').value = answer.standard_question;
    document.querySelector('#qa-draft-similar').value = answer.similar_questions.join('\n');
    document.querySelector('#qa-draft-market').value = answer.market_code;
    document.querySelector('#qa-draft-country').value = answer.country_code;
    document.querySelector('#qa-draft-model').value = answer.model_name;
    document.querySelector('#qa-draft-answer').value = answer.answer_text;
    document.querySelector('#qa-draft-registration').value = answer.registration_result;
    document.querySelector('#qa-draft-strategy').value = answer.strategy_result;
    document.querySelector('#qa-draft-limitations').value = answer.limitations;
    document.querySelector('#qa-draft-evidence').value = '';
    document.querySelector('#qa-draft-question').focus();
    showNotice('已复制为草稿内容；请重新核对注册、策略和受控证据后保存。');
    return;
  }
  const button = event.target.closest('[data-qa-review]');
  if (!button) return;
  try {
    await api(`/api/v1/knowledge-hub/qa/answers/${button.dataset.qaReview}/review`, { method: 'POST', body: '{}' });
    showNotice('已提交审核。');
    await loadQaWorkbench();
  } catch (error) { showNotice(error.message); }
});
document.querySelector('#qa-answer-list')?.addEventListener('submit', async event => {
  const form = event.target;
  if (!form.matches('[data-qa-publish], [data-qa-retire]')) return;
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form));
  const publish = form.dataset.qaPublish;
  const action = publish ? 'publish' : 'retire';
  const answerId = publish || form.dataset.qaRetire;
  try {
    await api(`/api/v1/knowledge-hub/qa/answers/${answerId}/${action}`, { method: 'POST', body: JSON.stringify(data) });
    showNotice(publish ? '正式答案已发布，相关提问人已有站内消息。' : '答案已失效，后续查询不会命中。');
    await loadQaWorkbench();
  } catch (error) { showNotice(error.message); }
});
document.querySelector('#qa-notifications-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const requester = document.querySelector('#qa-notification-requester').value.trim();
  const container = document.querySelector('#qa-notifications');
  try {
    const [questions, notifications] = await Promise.all([
      api(`/api/v1/knowledge-hub/qa/questions?requester=${encodeURIComponent(requester)}`),
      api(`/api/v1/knowledge-hub/qa/notifications?requester=${encodeURIComponent(requester)}`),
    ]);
    const own = questions;
    container.innerHTML = own.length ? own.map(item => {
      const notification = notifications.find(message => message.question_id === item.id);
      const current = notification?.answer_state === 'current';
      const progress = current ? '已有站内结果' : notification ? '原答案已失效，等待重新核对' : '等待负责人答复';
      return `<article class="strategy-row"><strong>${escapeHtml(item.question)}</strong><small>${escapeHtml(item.model_name)} · ${progress}</small>${current ? `<p>${escapeHtml(notification.answer_text)}</p><form class="qa-inline-actions" data-qa-feedback="${item.id}"><label>结果是否解决问题<select name="helpful"><option value="true">已解决</option><option value="false">仍需补充</option></select></label><label>补充说明<input name="detail"></label><button type="submit" class="ghost-button">提交反馈</button></form>` : ''}</article>`;
    }).join('') : '<p class="empty-state compact">没有找到该标识的提问。</p>';
  } catch (error) { container.innerHTML = strategyProblemMarkup(error); }
});
document.querySelector('#qa-notifications')?.addEventListener('submit', async event => {
  const form = event.target.closest('[data-qa-feedback]');
  if (!form) return;
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form));
  try {
    await api(`/api/v1/knowledge-hub/qa/questions/${form.dataset.qaFeedback}/feedback`, {
      method: 'POST', body: JSON.stringify({ helpful: data.helpful === 'true', detail: data.detail }),
    });
    showNotice('反馈已记录。');
  } catch (error) { showNotice(error.message); }
});
const probeVersionsForm = document.querySelector('#probe-versions-form');
if (probeVersionsForm) probeVersionsForm.addEventListener('submit', event => { event.preventDefault(); loadProbeVersions(); syncLocation(); });
['#probe-versions-probe', '#probe-versions-series', '#probe-versions-version'].forEach(selector => {
  const node = document.querySelector(selector);
  if (node) node.addEventListener('change', () => loadProbeVersions());
});
// 视图与查询范围都进地址栏：前进/后退行为一致，且不重复堆积历史条目。
window.addEventListener('hashchange', () => { applyLocation(); });
window.addEventListener('popstate', () => { applyLocation(); });
document.addEventListener('input', scheduleLocationSync);
document.addEventListener('change', scheduleLocationSync);
document.addEventListener('click', scheduleLocationSync);
document.querySelector('#feature-search').addEventListener('input', event => loadFeatures(event.target.value));
document.querySelector('#term-search').addEventListener('input', event => loadTerms(event.target.value));
document.querySelector('#term-status-filter').addEventListener('change', renderTerms);
document.querySelector('#term-category-filter').addEventListener('change', renderTerms);
document.querySelector('#release-search').addEventListener('input', () => {
  scheduleUnifiedSearch();
});
document.querySelector('#release-search-form').addEventListener('submit', event => {
  event.preventDefault();
  state.searchPage = 1;
  searchUnified().catch(error => showNotice(error.message));
});
document.querySelector('#search-filters-toggle')?.addEventListener('click', () => {
  setSearchFiltersVisible(document.querySelector('#search-filters-panel').hidden);
});
document.querySelector('#search-version-picker').addEventListener('toggle', event => {
  if (event.currentTarget.open) loadSearchVersionChoices();
});
document.querySelector('#search-version-options').addEventListener('change', event => {
  const input = event.target.closest('[data-search-version-choice]');
  if (!input) return;
  const selected = new Set(selectedVersionTokens());
  input.checked ? selected.add(input.value) : selected.delete(input.value);
  document.querySelector('#release-search-versions').value = [...selected].join(',');
  document.querySelector('#release-search-version-from').value = '';
  document.querySelector('#release-search-version-to').value = '';
  syncVersionChoices();
  scheduleUnifiedSearch();
});
document.querySelectorAll('[data-search-task]').forEach(button => button.addEventListener('click', () => {
  const settings = searchTaskSettings();
  const task = button.dataset.searchTask;
  restoreSearchTask({ ...settings, task,
    versionTo: task === 'version' ? settings.versionFrom : settings.versionTo });
  if (task !== 'search') {
    document.querySelectorAll('input[name="search-source"]').forEach(input => {
      input.checked = ['release', 'controlled'].includes(input.value);
    });
    document.querySelector('#release-search-current').checked = false;
  }
  state.searchPage = 1;
  if (task === 'version' && !settings.versionFrom && !settings.versions) {
    setSearchFiltersVisible(true);
    document.querySelector('#release-search-versions').focus();
    syncLocation();
  } else if (document.querySelector('#release-search').value.trim()) {
    searchUnified().catch(error => showNotice(error.message));
  } else {
    document.querySelector('#release-search').focus();
    syncLocation();
  }
}));
document.querySelector('#search-index-refresh').addEventListener('click', event => refreshSearchIndex(event.currentTarget));
['#release-search-versions', '#release-search-version-from', '#release-search-version-to', '#release-search-expand', '#release-search-scope', '#release-search-market', '#release-search-verification', '#release-search-current', '#release-search-model', '#release-search-country'].forEach(selector => {
  const control = document.querySelector(selector);
  const eventName = control.tagName === 'INPUT' && control.type !== 'checkbox' ? 'input' : 'change';
  control.addEventListener(eventName, () => {
    if (selector === '#release-search-version-from' && searchTaskSettings().task === 'version') {
      document.querySelector('#release-search-version-to').value = control.value;
    }
    if (selector === '#release-search-versions' && control.value.trim()) {
      document.querySelector('#release-search-version-from').value = '';
      document.querySelector('#release-search-version-to').value = '';
    } else if (['#release-search-version-from', '#release-search-version-to'].includes(selector) && control.value.trim()) {
      document.querySelector('#release-search-versions').value = '';
    }
    syncVersionChoices();
    if (selector === '#release-search-scope' && document.querySelector('#search-version-picker').open) loadSearchVersionChoices();
    if (eventName === 'input') scheduleUnifiedSearch();
    else { state.searchPage = 1; searchUnified().catch(error => showNotice(error.message)); }
  });
});
document.querySelectorAll('input[name="search-source"]').forEach(control => control.addEventListener('change', () => {
  state.searchPage = 1;
  if (document.querySelector('#release-search').value.trim()) searchUnified().catch(error => showNotice(error.message));
  else syncLocation();
}));
document.querySelector('#review-directory-settings')?.addEventListener('click', () => document.querySelector('#manage-projects')?.click());
document.querySelector('[data-page="review"]').addEventListener('click', event => {
  if (event.target.closest('[data-review-confirm]')) setReviewStage('confirm');
  if (event.target.closest('[data-review-overview]')) setReviewStage('overview');
  if (event.target.closest('[data-review-releases]')) switchView('releases');
  if (event.target.closest('[data-review-query]')) switchView('search');
});
document.querySelector('#global-search-panel').addEventListener('change', event => {
  const selector = event.target.closest('[data-search-whitepaper-model]');
  if (!selector) return;
  selectSearchTaxonomy('model', selector.value);
});
document.querySelector('#global-search-panel').addEventListener('keydown', event => {
  const current = event.target.closest('[role="tab"]');
  if (!current || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  const tabs = [...current.closest('[role="tablist"]').querySelectorAll('[role="tab"]')];
  const index = tabs.indexOf(current);
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
  event.preventDefault();
  tabs[next]?.click();
});
document.querySelector('#global-search-panel').addEventListener('click', event => {
  const sourceTab = event.target.closest('[data-search-source-group]');
  const categoryTab = event.target.closest('[data-search-release-category]');
  if (sourceTab || categoryTab) {
    selectSearchTaxonomy(sourceTab ? 'source' : 'category', sourceTab?.dataset.searchSourceGroup || categoryTab.dataset.searchReleaseCategory);
    return;
  }
  const removeFilter = event.target.closest('[data-search-remove-filter]');
  if (removeFilter) {
    Promise.resolve(removeSearchFilter(removeFilter.dataset.searchRemoveFilter)).catch(error => showNotice(error.message));
    return;
  }
  const focusVersion = event.target.closest('[data-search-focus-version]');
  if (focusVersion) {
    focusSearchVersion(focusVersion.dataset.searchFocusVersion).catch(error => showNotice(error.message));
    return;
  }
  const compareAdd = event.target.closest('[data-search-compare-add]');
  const compareRemove = event.target.closest('[data-search-compare-remove]');
  if (compareAdd || compareRemove || event.target.closest('[data-search-compare-clear]')) {
    try {
      if (compareAdd) state.searchComparison = toggleSearchComparison(state.searchComparison || [], state.searchComparisonOptions[Number(compareAdd.dataset.searchCompareAdd)]);
      else if (compareRemove) state.searchComparison = state.searchComparison.filter((_, n) => n !== Number(compareRemove.dataset.searchCompareRemove));
      else state.searchComparison = [];
      saveSearchComparison();
      renderSearchComparisonTray();
    } catch (error) { showNotice(error.message); }
    return;
  }
  if (event.target.closest('[data-search-compare-open]')) {
    openSearchComparison().catch(error => showNotice(error.message));
    return;
  }
  if (event.target.closest('[data-search-coverage-register]')) {
    document.querySelector('#register-historical-document').click();
    return;
  }
  if (event.target.closest('[data-search-result-refresh]')) {
    refreshSearchIndex(document.querySelector('#search-index-refresh'));
    return;
  }
  const previewButton = event.target.closest('[data-search-result-preview]');
  if (previewButton) {
    openSearchPreview(previewButton.dataset.searchResultPreview, previewButton.dataset.searchResultLocator, previewButton.dataset.searchResultQuery || '', previewButton.dataset.searchResultInputQuery || previewButton.dataset.searchResultQuery || '').catch(error => showNotice(error.message));
    return;
  }
  const versionButton = event.target.closest('[data-search-release-version]');
  if (versionButton) openGlobalSearchVersion(
    versionButton.dataset.searchReleaseVersion,
    versionButton.dataset.searchProjectId,
  ).catch(error => showNotice(error.message));
  const configButton = event.target.closest('[data-search-result-config]');
  if (configButton) openGlobalSearchConfig(configButton.dataset.searchResultConfig).catch(error => showNotice(error.message));
  if (event.target.closest('[data-search-result-term]')) {
    document.querySelector('#term-search').value = document.querySelector('#release-search').value.trim();
    switchView('terms');
    loadTerms(document.querySelector('#term-search').value).catch(error => showNotice(error.message));
  }
  const pageButton = event.target.closest('[data-search-page]');
  if (pageButton && !pageButton.disabled) {
    state.searchPage = Number(pageButton.dataset.searchPage);
    searchUnified().catch(error => showNotice(error.message));
  }
});
document.querySelector('#copy-search-comparison').addEventListener('click', () => {
  try {
    const citation = buildComparisonCitation(state.searchComparisonDocuments || [], state.searchComparisonUrl || '');
    copyEvidenceCitation(citation, document.querySelector('#search-compare-dialog'));
  } catch (error) { showNotice(error.message); }
});
document.querySelector('[data-save-search]').addEventListener('click', saveCurrentSearch);
document.querySelector('#saved-searches').addEventListener('click', event => {
  const remove = event.target.closest('[data-remove-saved-search]');
  if (remove) {
    persistPersonalSearches(savedSearches().filter((_item, index) => index !== Number(remove.dataset.removeSavedSearch))).catch(error => showNotice(error.message));
    return;
  }
  const button = event.target.closest('[data-saved-search]');
  if (button) applySavedSearch(savedSearches()[Number(button.dataset.savedSearch)]).catch(error => showNotice(error.message));
});
document.querySelector('#project-switcher').addEventListener('change', event => {
  switchProject(event.target.value).catch(error => showNotice(error.message));
});
document.querySelector('#manage-projects').addEventListener('click', () => {
  renderProjectList();
  loadImportBatches().catch(error => showNotice(error.message));
  document.querySelector('#project-dialog').showModal();
});
document.querySelector('#import-batch-list').addEventListener('click', event => {
  const button = event.target.closest('[data-undo-import-batch]');
  if (button) undoImportBatch(button.dataset.undoImportBatch).catch(error => showNotice(error.message));
});
document.querySelector('#project-health-panel').addEventListener('click', event => {
  if (event.target.closest('[data-health-review]')) {
    document.querySelector('#review-priority-filter').value = 'focus';
    renderCandidateReview();
    switchView('review');
  }
  if (event.target.closest('[data-health-manage]')) {
    renderProjectList();
    loadImportBatches().catch(error => showNotice(error.message));
    document.querySelector('#project-dialog').showModal();
  }
});
document.querySelector('#project-list').addEventListener('click', event => {
  const button = event.target.closest('[data-project-preview]');
  if (button) previewProject(button.dataset.projectPreview).catch(error => showNotice(error.message));
});
document.querySelector('#project-preview').addEventListener('click', event => {
  const button = event.target.closest('[data-project-import]');
  if (button) importPreviewedProject(button.dataset.projectImport, button).catch(error => showNotice(error.message));
});
document.querySelector('#project-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  const fileKeywords = data.file_keywords.split(/[,，]/).map(value => value.trim()).filter(Boolean);
  try {
    const project = await api('/api/v1/projects', { method: 'POST', body: JSON.stringify({ ...data, file_keywords: fileKeywords }) });
    localStorage.setItem('featureTracker.activeProject', String(project.id));
    form.reset();
    await loadProjects();
    await switchProject(project.id);
    await previewProject(project.id);
    showNotice('项目已建立；请在扫描预览中确认后导入完整版本。');
  } catch (error) { showNotice(error.message); }
});

function setReleaseCategoryFilter(row, category = '') {
  const changes = [...row.querySelectorAll('.release-change')];
  let visibleCount = 0;
  changes.forEach(change => {
    const visible = !category || change.dataset.releaseCategory === category;
    change.hidden = !visible;
    if (visible) visibleCount += 1;
  });
  row.querySelectorAll('[data-release-category-filter]').forEach(button => {
    const active = Boolean(category) && button.dataset.releaseCategoryFilter === category;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  const title = row.querySelector('[data-release-filter-title]');
  title.textContent = `${category ? `${categoryLabels[category] || category} 变更` : '全部变更'} · ${visibleCount} 条`;
  const details = row.querySelector('.release-details');
  details.hidden = false;
  const toggle = row.querySelector('[data-release-toggle]');
  toggle.setAttribute('aria-expanded', 'true');
  toggle.querySelector('em').textContent = '收起变更依据';
  window.requestAnimationFrame(() => title.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
}

document.querySelector('#release-list').addEventListener('click', event => {
  if (event.target.closest('[data-empty-project-import]')) {
    renderProjectList();
    document.querySelector('#project-dialog').showModal();
    previewProject(state.activeProjectId).catch(error => showNotice(error.message));
    return;
  }
  const versionTab = event.target.closest('[data-release-version-tab]');
  if (versionTab) {
    const index = state.releases.findIndex(release => release.version === versionTab.dataset.releaseVersionTab);
    selectReleaseByIndex(index);
    return;
  }
  const stepButton = event.target.closest('[data-release-step]');
  if (stepButton) {
    const activeIndex = state.releases.findIndex(release => release.version === state.activeReleaseVersion);
    selectReleaseByIndex(activeIndex + Number(stepButton.dataset.releaseStep));
    return;
  }
  const row = event.target.closest('.release-row');
  if (!row) return;
  const archiveButton = event.target.closest('[data-release-archive]');
  if (archiveButton) {
    openReleaseArchive(archiveButton.dataset.releaseArchive, archiveButton.dataset.releaseVersion).catch(error => showNotice(error.message));
    return;
  }
  const configurationButton = event.target.closest('[data-configuration-release]');
  if (configurationButton) {
    openConfigurationTables(configurationButton.dataset.configurationRelease, configurationButton.dataset.configurationVersion).catch(error => showNotice(error.message));
    return;
  }
  const toggle = event.target.closest('[data-release-toggle]');
  if (toggle) {
    const details = row.querySelector('.release-details');
    details.hidden = !details.hidden;
    toggle.setAttribute('aria-expanded', String(!details.hidden));
    toggle.querySelector('em').textContent = details.hidden ? '查看变更依据' : '收起变更依据';
    return;
  }
  const categoryButton = event.target.closest('[data-release-category-filter]');
  if (categoryButton) {
    const category = categoryButton.dataset.releaseCategoryFilter;
    setReleaseCategoryFilter(
      row,
      categoryButton.getAttribute('aria-pressed') === 'true' ? '' : category,
    );
    return;
  }
  if (event.target.closest('[data-release-filter-reset]')) {
    setReleaseCategoryFilter(row);
  }
});
document.querySelector('#release-version-tabs').addEventListener('keydown', event => {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const activeIndex = state.releases.findIndex(release => release.version === state.activeReleaseVersion);
  if (event.key === 'Home') return selectReleaseByIndex(0, { focusTab: true });
  if (event.key === 'End') return selectReleaseByIndex(state.releases.length - 1, { focusTab: true });
  selectReleaseByIndex(activeIndex + (event.key === 'ArrowLeft' ? -1 : 1), { focusTab: true });
});
document.querySelector('#release-archive-search').addEventListener('input', renderReleaseArchive);
document.querySelector('#release-archive-tabs').addEventListener('click', event => {
  const button = event.target.closest('[data-archive-type]');
  if (!button || button.disabled) return;
  state.archiveType = button.dataset.archiveType;
  renderReleaseArchive();
});
document.querySelector('#release-archive-market-tabs').addEventListener('click', event => {
  const button = event.target.closest('[data-archive-market]');
  if (!button) return;
  state.archiveMarket = button.dataset.archiveMarket;
  renderReleaseArchive();
});
document.querySelector('#release-archive-market-tabs').addEventListener('keydown', event => {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  const markets = availableArchiveMarkets();
  if (!markets.length) return;
  event.preventDefault();
  const currentIndex = markets.indexOf(state.archiveMarket);
  const targetIndex = event.key === 'Home' ? 0 : event.key === 'End' ? markets.length - 1 : Math.max(0, Math.min(markets.length - 1, currentIndex + (event.key === 'ArrowLeft' ? -1 : 1)));
  state.archiveMarket = markets[targetIndex];
  renderReleaseArchive();
  document.querySelector(`[data-archive-market="${state.archiveMarket}"]`)?.focus();
});
document.querySelector('#term-list').addEventListener('click', event => {
  const editButton = event.target.closest('[data-term-edit]');
  if (editButton) return openTermEditor(editButton.dataset.termEdit);
  const confirmButton = event.target.closest('[data-term-confirm]');
  if (confirmButton) confirmTerm(confirmButton.dataset.termConfirm).catch(error => showNotice(error.message));
  const typeButton = event.target.closest('[data-term-type]');
  if (typeButton) setTermEntryType(typeButton.dataset.termId, typeButton.dataset.termType).catch(error => showNotice(error.message));
});
document.querySelector('#review-issue-list')?.addEventListener('click', event => {
  const mergeButton = event.target.closest('[data-merge-pair]');
  if (mergeButton) {
    if (!window.confirm(mergeButton.dataset.confirmMerge || '确定合并这两条为同一条变更吗？')) return;
    const [cnCandidateId, enCandidateId] = mergeButton.dataset.mergePair.split(':').map(Number);
    mergeSuspectedPair(cnCandidateId, enCandidateId).catch(error => showNotice(error.message));
    return;
  }
  const target = event.target.closest('[data-review-issue-target]');
  if (!target) return;
  state.reviewStage = 'confirm';
  document.querySelector('#review-filter-options').open = true;
  if (candidateVersions().includes(target.dataset.version)) state.activeCandidateVersion = target.dataset.version;
  state.activeCandidateCategory = target.dataset.category;
  state.selectedCandidateIds = new Set();
  document.querySelector('#candidate-search').value = '';
  document.querySelector('#candidate-quality-filter').value = 'missing';
  renderCandidateReview();
  document.querySelector('#candidate-filter-summary').scrollIntoView({ behavior: 'smooth', block: 'center' });
});
document.querySelector('#manage-categories')?.addEventListener('click', () => {
  renderCategoryManager();
  document.querySelector('#category-dialog').showModal();
});
document.querySelector('#category-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api('/api/v1/categories', { method: 'POST', body: JSON.stringify({ name: form.elements.name.value }) });
    form.elements.name.value = '';
    await loadProductCategories();
    showNotice('分类已新增，可在各个功能中选择。');
  } catch (error) { showNotice(error.message); }
});
document.querySelector('#category-list')?.addEventListener('click', event => {
  const button = event.target.closest('[data-category-save]');
  if (!button) return;
  const input = event.currentTarget.querySelector(`[data-category-name="${button.dataset.categorySave}"]`);
  renameProductCategory(button.dataset.categorySave, input.value).catch(error => showNotice(error.message));
});
document.querySelector('#compare-button').addEventListener('click', () => compareVersions().catch(error => showNotice(error.message)));
document.querySelector('#refresh-button').addEventListener('click', () => refreshActiveView().catch(error => showNotice(error.message)));
document.querySelector('#scan-notes').addEventListener('click', () => scanNotes().catch(error => showNotice(error.message)));
document.querySelector('#candidate-version-tabs').addEventListener('click', event => {
  const tab = event.target.closest('[data-candidate-version-tab]');
  if (tab) selectCandidateVersion(tab.dataset.candidateVersionTab);
});
document.querySelector('#candidate-version-tabs').addEventListener('keydown', event => {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  const versions = candidateVersions();
  if (!versions.length) return;
  event.preventDefault();
  const activeIndex = versions.indexOf(state.activeCandidateVersion);
  const targetIndex = event.key === 'Home'
    ? 0
    : event.key === 'End'
      ? versions.length - 1
      : Math.max(0, Math.min(versions.length - 1, activeIndex + (event.key === 'ArrowLeft' ? -1 : 1)));
  selectCandidateVersion(versions[targetIndex], { focusTab: true });
});
document.querySelectorAll('[data-candidate-version-step]').forEach(button => button.addEventListener('click', () => {
  const versions = candidateVersions();
  const activeIndex = versions.indexOf(state.activeCandidateVersion);
  const targetVersion = versions[activeIndex + Number(button.dataset.candidateVersionStep)];
  if (targetVersion) selectCandidateVersion(targetVersion, { focusTab: true });
}));
document.querySelector('#candidate-category-tabs').addEventListener('click', event => {
  const tab = event.target.closest('[data-candidate-category-tab]');
  if (tab) selectCandidateCategory(tab.dataset.candidateCategoryTab);
});
document.querySelector('#review-priority-filter').addEventListener('change', () => {
  state.selectedCandidateIds = new Set();
  renderCandidateReview();
});
document.querySelector('#candidate-quality-filter').addEventListener('change', renderCandidateReview);
document.querySelector('#candidate-search').addEventListener('input', renderCandidateReview);
document.querySelector('#candidate-category-tabs').addEventListener('keydown', event => {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  const categories = ['all', ...candidateCategories()];
  if (!categories.length) return;
  event.preventDefault();
  const activeIndex = categories.indexOf(state.activeCandidateCategory);
  const targetIndex = event.key === 'Home'
    ? 0
    : event.key === 'End'
      ? categories.length - 1
      : Math.max(0, Math.min(categories.length - 1, activeIndex + (event.key === 'ArrowLeft' ? -1 : 1)));
  selectCandidateCategory(categories[targetIndex], { focusTab: true });
});
document.querySelector('#candidate-list').addEventListener('click', event => {
  const configurationButton = event.target.closest('[data-configuration-release]');
  if (configurationButton) {
    openConfigurationTables(configurationButton.dataset.configurationRelease, configurationButton.dataset.configurationVersion).catch(error => showNotice(error.message));
    return;
  }
  const selectScope = event.target.closest('[data-select-scope]');
  if (selectScope) {
    const ids = parseCandidateIds(selectScope.dataset.selectScope);
    ids.forEach(id => selectScope.checked ? state.selectedCandidateIds.add(String(id)) : state.selectedCandidateIds.delete(String(id)));
    renderCandidateReview();
    return;
  }
  const selectCandidate = event.target.closest('[data-candidate-select]');
  if (selectCandidate) {
    const id = String(selectCandidate.dataset.candidateSelect);
    selectCandidate.checked ? state.selectedCandidateIds.add(id) : state.selectedCandidateIds.delete(id);
    renderCandidateReview();
    return;
  }
  const batchApprove = event.target.closest('[data-batch-approve]');
  if (batchApprove) {
    approveCandidates(parseCandidateIds(batchApprove.dataset.batchApprove)).catch(error => showNotice(error.message));
    return;
  }
  const batchConfirm = event.target.closest('[data-batch-confirm]');
  if (batchConfirm) {
    confirmCandidates(parseCandidateIds(batchConfirm.dataset.batchConfirm)).catch(error => showNotice(error.message));
    return;
  }
  const batchPromote = event.target.closest('[data-batch-promote]');
  if (batchPromote) {
    promoteCandidates(parseCandidateIds(batchPromote.dataset.batchPromote)).catch(error => showNotice(error.message));
    return;
  }
  if (event.target.closest('[data-clear-selection]')) {
    state.selectedCandidateIds = new Set();
    renderCandidateReview();
    return;
  }
  const button = event.target.closest('[data-review]');
  if (button) reviewCandidate(button.dataset.id, button.dataset.review).catch(error => showNotice(error.message));
  const action = event.target.closest('[data-action]');
  if (action?.dataset.action === 'edit') openCandidateEditor(action.dataset.id);
  if (action?.dataset.action === 'promote') openFeaturePromotion(action.dataset.id);
  if (action?.dataset.action === 'confirm') submitCandidate(action.dataset.id).catch(error => showNotice(error.message));
});
document.querySelector('#candidate-list')?.addEventListener('change', event => {
  const categorySelect = event.target.closest('[data-candidate-category]');
  if (categorySelect) {
    changeCandidateCategory(categorySelect.dataset.candidateCategory, categorySelect.value)
      .catch(error => { showNotice(error.message); });
    return;
  }
  const overrideSelect = event.target.closest('[data-candidate-override]');
  if (!overrideSelect) return;
  const id = overrideSelect.dataset.candidateOverride;
  if (overrideSelect.value === 'enhance_feature') {
    // 需要指定归入哪个功能，交给原有的建立/关联对话框。
    overrideSelect.value = '';
    openFeaturePromotion(id);
    return;
  }
  if (overrideSelect.value) state.candidateOverrides[String(id)] = overrideSelect.value;
  else delete state.candidateOverrides[String(id)];
  renderCandidateReview();
});
document.querySelector('#configuration-table-search')?.addEventListener('input', event => renderConfigurationTables(event.target.value));
document.querySelector('#rejected-candidate-list')?.addEventListener('click', event => {
  const button = event.target.closest('[data-review="restore"]');
  if (button) reviewCandidate(button.dataset.id, 'restore').catch(error => showNotice(error.message));
});
document.querySelector('#new-feature').addEventListener('click', () => document.querySelector('#feature-dialog').showModal());
document.querySelector('#feature-list').addEventListener('click', event => {
  if (event.target.closest('[data-empty-review-cta]')) {
    switchView('review');
    return;
  }
  const button = event.target.closest('[data-feature-edit]');
  if (button) openFeatureEditor(button.dataset.featureEdit).catch(error => showNotice(error.message));
  const timelineButton = event.target.closest('[data-feature-timeline]');
  if (timelineButton) openFeatureTimeline(timelineButton.dataset.featureTimeline).catch(error => showNotice(error.message));
});
document.querySelector('#add-child-feature')?.addEventListener('click', openChildFeatureDialog);
document.querySelector('#add-feature-note')?.addEventListener('click', openFeatureNoteDialog);
document.querySelector('#promote-form select[name=feature_id]').addEventListener('change', event => {
  const form = document.querySelector('#promote-form'), feature = state.features.find(item => String(item.id) === event.target.value);
  form.elements.cn_name.value = feature?.cn_name || ''; form.elements.en_name.value = feature?.en_name || '';
  form.elements.category.value = feature?.category || '';
  form.elements.cn_name.dataset.autofilled = feature ? 'true' : '';
  form.elements.en_name.dataset.autofilled = feature ? 'true' : '';
  cancelFeatureMatchSearch();
});
document.querySelectorAll('#promote-form input[name=cn_name],#promote-form input[name=en_name]').forEach(input => input.addEventListener('input', event => {
  const form = event.target.form;
  const counterpart = event.target.name === 'cn_name' ? form.elements.en_name : form.elements.cn_name;
  form.elements.feature_id.value = '';
  if (counterpart.dataset.autofilled === 'true') counterpart.value = '';
  delete counterpart.dataset.autofilled;
  delete event.target.dataset.autofilled;
  scheduleFeatureMatch(event.target.value);
}));
document.querySelector('#feature-match-list')?.addEventListener('click', event => {
  const button = event.target.closest('[data-match-index]');
  if (button) applyFeatureMatch(event.currentTarget._matches[Number(button.dataset.matchIndex)]);
});
document.querySelector('#feature-form').addEventListener('submit', async event => {
  if (event.submitter?.value === 'cancel') return;
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement); const data = { ...Object.fromEntries(form.entries()), project_id: state.activeProjectId };
  try { await api('/api/v1/features', { method: 'POST', body: JSON.stringify(data) }); document.querySelector('#feature-dialog').close(); formElement.reset(); await refreshAll(); } catch (error) { showNotice(error.message); }
});
document.querySelector('#feature-edit-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.currentTarget).entries());
  const id = data.feature_id;
  delete data.feature_id;
  try {
    await api(`/api/v1/features/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
    document.querySelector('#feature-edit-dialog').close();
    await refreshAll();
    showNotice('功能档案已更新，描述变更已保留修订记录。');
  } catch (error) { showNotice(error.message); }
});
document.querySelector('#child-feature-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.currentTarget).entries());
  const parentId = data.parent_feature_id;
  delete data.parent_feature_id;
  try {
    await api(`/api/v1/features/${parentId}/children`, { method: 'POST', body: JSON.stringify(data) });
    document.querySelector('#child-feature-dialog').close();
    await refreshAll();
    await openFeatureEditor(parentId);
    showNotice('独立子功能已建立，可单独关联版本记录。');
  } catch (error) { showNotice(error.message); }
});
document.querySelector('#feature-note-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.currentTarget).entries());
  const featureId = data.feature_id;
  delete data.feature_id;
  try {
    await api(`/api/v1/features/${featureId}/notes`, { method: 'POST', body: JSON.stringify(data) });
    document.querySelector('#feature-note-dialog').close();
    await openFeatureEditor(featureId);
    showNotice('父项说明已添加，不会作为独立功能参与版本统计。');
  } catch (error) { showNotice(error.message); }
});
document.querySelector('#candidate-form').addEventListener('submit', async event => {
  if (event.submitter?.value === 'cancel') return;
  event.preventDefault(); const form = new FormData(event.currentTarget), data = Object.fromEntries(form.entries()), id = data.candidate_id; delete data.candidate_id;
  try { await api(`/api/v1/import-candidates/${id}`, { method: 'PATCH', body: JSON.stringify(data) }); document.querySelector('#candidate-dialog').close(); await refreshAll(); } catch (error) { showNotice(error.message); }
});
document.querySelector('#term-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const data = Object.fromEntries(form.entries());
  const id = data.term_id;
  delete data.term_id;
  try {
    const isPending = event.currentTarget.dataset.pending === 'true';
    const isNote = event.currentTarget.dataset.entryType === 'note';
    if (isPending && !isNote) await confirmTerm(id, data, '术语已确认。');
    else await updateTerm(id, data, isNote ? '父项说明已更新。' : '术语已更新。');
    document.querySelector('#term-dialog').close();
  } catch (error) {
    showNotice(error.message);
  }
});
document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelector('#search-preview-dialog').addEventListener('close', () => {
  if (document.querySelector('#search-preview-dialog').open) return;
  state.searchPreviewRequest++;
  state.previewLocation = null;
  syncLocation();
});
document.querySelector('#promote-form').addEventListener('submit', async event => {
  if (event.submitter?.value === 'cancel') return;
  event.preventDefault(); const form = new FormData(event.currentTarget), data = Object.fromEntries(form.entries());
  if (!data.feature_id && !data.cn_name.trim() && !data.en_name.trim()) return showNotice('请填写中文名称、英文名称或从匹配结果中选择功能。');
  const payload = { promote_to_feature: true, cn_name: data.cn_name, en_name: data.en_name, category: data.category, markets: ['domestic','overseas'].filter(market => form.has(market)) };
  if (data.feature_id) payload.feature_id = Number(data.feature_id);
  try { await api(`/api/v1/import-candidates/${data.candidate_id}/approve`, { method: 'POST', body: JSON.stringify(payload) }); document.querySelector('#promote-dialog').close(); await refreshAll(); } catch (error) { showNotice(error.message); }
});

function defaultView() {
  // 首页开启时固定落首页；关闭首页时沿用上次访问的工作区。链接里的 hash 始终优先。
  const workbench = window.__WORKBENCH__ || { home: false };
  if (workbench.integrated) return 'releases';
  if (workbench.home && labels.home) return 'home';
  const rememberedView = localStorage.getItem('featureTracker.lastView');
  return labels[rememberedView] ? rememberedView : 'releases';
}

document.addEventListener('DOMContentLoaded', () => {
setScenarioTask(scenarioState.task);
const initialLocation = parseLocation();
const initialProblems = locationProblems(initialLocation);
const initialView = labels[initialLocation.view] ? initialLocation.view : defaultView();
switchView(initialView, { remember: false, updateHash: false, scroll: false });
if (initialProblems.length) reportNavigationProblem(`已忽略链接中的：${initialProblems.join('；')}`);
renderSavedSearches();
loadProjects()
  .then(async () => {
    // 先切到链接指定的项目（其内部会刷新一次）；项目本来就一致时必须自己加载一次，
    // 否则候选、版本等数据尚未就位，下面的范围参数会被误判为“不在可选范围”。
    const switchedProject = await applyProjectParam(initialLocation.params.project);
    if (!switchedProject) await refreshAll({ includeExperience: true });
    await applyViewParams(initialView, initialLocation.params, { skipProject: true });
    syncLocation();
  })
  .catch(error => showNotice(error.message));

});
