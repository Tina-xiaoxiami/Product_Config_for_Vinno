/* Personal workbench flows reuse the existing query and preview services. */

async function loadPersonalWorkspace() {
  state.personal = await api('/api/v1/workbench/personal');
  if (!state.personal.recovery_required && !state.personal.saved_searches.length) {
    let legacy = [];
    try { legacy = JSON.parse(localStorage.getItem(savedSearchStorageKey) || '[]'); } catch (_error) { /* Keep corrupt browser data untouched. */ }
    if (Array.isArray(legacy) && legacy.length && !localStorage.getItem('featureTracker.shortcutsMigrated')) {
      const saved = legacy.filter(item => item && typeof item.query === 'string' && Array.isArray(item.sources))
        .map(item => ({ ...item, name: item.name || item.query, projectId: item.projectId || state.activeProjectId || null }));
      if (saved.length) state.personal = await api('/api/v1/workbench/personal', { method: 'PUT', body: JSON.stringify({ saved_searches: saved }) });
      localStorage.setItem('featureTracker.shortcutsMigrated', 'true');
    }
  }
  renderPersonalWorkspace();
  renderSavedSearches();
  await loadPersonalCoverage();
}

function renderPersonalWorkspace() {
  const shortcuts = document.querySelector('#personal-shortcuts');
  if (shortcuts) shortcuts.innerHTML = state.personal.saved_searches.length
    ? state.personal.saved_searches.map((search, index) => `<button class="home-quick-action" type="button" data-personal-search="${index}"><strong>${escapeHtml(search.name || search.query)}</strong><small>${escapeHtml([search.model, marketLabel(search.market), search.country].filter(Boolean).join(' · ')) || '已保存的查询条件'}</small></button>`).join('')
    : '<p class="empty-state compact">在全局搜索中保存条件，即可固定到这里。</p>';
  const recent = document.querySelector('#recent-documents');
  if (recent) recent.innerHTML = state.personal.recent_documents.length
    ? `<h3>最近打开的资料</h3>${state.personal.recent_documents.slice(0, 8).map(item => `<button class="text-button" type="button" data-search-result-preview="${escapeAttribute(item.preview_id)}" data-search-result-locator="${escapeAttribute(item.locator)}">${escapeHtml(item.title)}</button>`).join('')}` : '';
  const maintenance = document.querySelector('#personal-maintenance');
  if (maintenance) {
    const backup = state.personal.last_backup;
    const backupUrl = backup ? workbenchUrl(`/api/v1/workbench/backups/${encodeURIComponent(backup.id)}/download`) : '';
    maintenance.innerHTML = `${state.personal.settings_error ? `<p class="search-source-error">${escapeHtml(state.personal.settings_error)}。可使用下方“恢复常用入口”。</p>` : ''}${state.personal.backup_error ? `<p class="search-source-error">${escapeHtml(state.personal.backup_error)}</p>` : ''}<p>自动资料更新：${state.personal.index_paused ? '已暂停' : '开启，每 5 分钟增量检查'}。</p><p>${backup ? `最近备份：${escapeHtml(formatDateTime(backup.created_at))} · 完整性验证通过 · 保留最近 ${backup.retention_count} 份 <a href="${escapeAttribute(backupUrl)}">获取此备份</a>` : '尚无成功备份。'}</p>`;
  }
  const toggle = document.querySelector('#personal-index-toggle');
  if (toggle) toggle.textContent = state.personal.index_paused ? '恢复自动更新' : '暂停自动更新';
}

async function loadPersonalCoverage() {
  const status = await api('/api/v1/workbench/search-index');
  const controlled = status.coverage?.controlled;
  const container = document.querySelector('#index-coverage');
  if (container && controlled) {
    container.innerHTML = `<p>登记文件 ${controlled.registered_files} 份 · 可访问 ${controlled.accessible_files} 份 · 已索引 ${controlled.indexed_files} 份 · 待更新 ${controlled.pending_files} 份。</p><p>未接入 ${controlled.outside_roots} 份 · 暂缺 ${controlled.missing_files} 份 · 读取失败 ${controlled.failed_files} 份 · 无正文文字 ${controlled.empty_text_files} 份。</p>${status.maintenance?.running ? '<p role="status">正在后台更新，可以继续查询。</p>' : ''}${status.maintenance?.last_error ? `<p class="search-source-error">${escapeHtml(status.maintenance.last_error)}</p>` : ''}`;
  }
}

async function persistPersonalSearches(searches) {
  state.personal = await api('/api/v1/workbench/personal', { method: 'PUT', body: JSON.stringify({ saved_searches: searches }) });
  localStorage.setItem(savedSearchStorageKey, JSON.stringify(state.personal.saved_searches));
  renderPersonalWorkspace();
  renderSavedSearches();
}

async function savePersonalSearch() {
  const search = currentSearchSettings();
  await persistPersonalSearches([search, ...savedSearches().filter(item => item.name !== search.name)].slice(0, 40));
  showNotice('已保存搜索并固定到首页。');
}

function updatePreviewTools(preview, sourceId, locator) {
  state.preview = { ...preview, preview_id: sourceId, locator };
  const downloadUrl = workbenchUrl(`/api/v1/workbench/search-index/sources/${encodeURIComponent(sourceId)}/preview?download=1`);
  document.querySelector('#search-preview-actions').innerHTML = `${preview.downloadable === false ? '' : `<a class="ghost-button" href="${escapeAttribute(downloadUrl)}">获取原文件</a>`}<button class="ghost-button" type="button" id="copy-preview-reference">复制引用</button>`;
  api('/api/v1/workbench/personal/recent', { method: 'POST', body: JSON.stringify({ preview_id: sourceId, title: preview.title, locator }) })
    .then(personal => { state.personal = personal; renderPersonalWorkspace(); })
    .catch(error => showNotice(`最近资料记录未保存：${error.message}`));
}

async function ensureModelWorkspaceOptions() {
  if (state.workspaceOptionsLoaded) return;
  const responses = await Promise.allSettled([
    api('/api/v1/knowledge-hub/registrations/models?country=CN'),
    api('/api/v1/knowledge-hub/product-states/options'),
    api('/api/v1/knowledge-hub/product-strategies/models'),
  ]);
  const names = new Set();
  for (const response of responses) {
    if (response.status === 'rejected') continue;
    const data = response.value;
    for (const name of data.base_models || []) names.add(name);
    for (const item of data.derived_models || []) names.add(item.derived_model);
    for (const item of data.models || []) names.add(typeof item === 'string' ? item : item.name);
  }
  document.querySelector('#workspace-model-options').innerHTML = [...names].filter(Boolean).sort().map(name => `<option value="${escapeAttribute(name)}"></option>`).join('');
  state.workspaceOptionsLoaded = responses.every(response => response.status === 'fulfilled');
}

function modelSectionContent(key, section, scope) {
  const data = section.data;
  if (!data || section.state === 'unavailable' || section.state === 'needs_clarification') return '';
  if (key === 'documents') return data.documents.map(documentCard).join('') + ((data.suggested_documents || []).length ? `<h4>智能匹配资料 · 待确认 ${data.suggested_documents.length} 份</h4>${data.suggested_documents.map(documentCard).join('')}` : '') + ((data.family_documents || []).length ? `<h4>系列资料 · 具体适用机型待确认 ${data.family_documents.length} 份</h4>${data.family_documents.map(documentCard).join('')}` : '');
  if (key === 'product_state') return data.models.map(group => `<article class="strategy-row"><strong>${escapeHtml(group.model_name)}</strong><p>${group.current ? `当前版本 ${escapeHtml(group.current.software_version)} · ${escapeHtml(group.current.release_status_label)} · 已核验 ${escapeHtml(group.current.reviewed_at || '')}` : '当前正式版本待确认'}</p>${!group.current && group.latest ? `<small>${escapeHtml(group.latest.software_version)} · ${escapeHtml(group.latest.freshness_label)}，不作为当前结论。</small>` : ''}</article>`).join('');
  if (key === 'config') return data.items.slice(0, 20).map(item => `<article class="strategy-row"><strong>${escapeHtml(item.code)} · ${escapeHtml(item.name)}</strong><p>${escapeHtml(item.strategy_label || '')} · ${escapeHtml(STRATEGY_STATUS_LABELS[item.knowledge_status] || '待确认')}</p></article>`).join('') + (data.items.length > 20 ? `<p>另有 ${data.items.length - 20} 项，可进入详情查看。</p>` : '');
  if (key === 'registration') return data.units.map(unit => `<article class="strategy-row"><strong>${escapeHtml(unit.certificate_no || '证书号待登记')}</strong><p class="pill ${unit.verification === 'approved' ? '' : 'warning'}">${verificationLabel(unit.verification)}</p><p>${unit.derived_total} 条登记关系 · 保留本证书范围</p><details><summary>查看探头与登记状态</summary>${unit.probes.map(row => `<p>${escapeHtml(row.probe_code)} · ${escapeHtml(row.state)}</p>`).join('')}</details></article>`).join('');
  if (key === 'probe_versions') return data.rows.map(row => `<article class="strategy-row"><strong>${escapeHtml(row.probe_model || row.probe_code)}</strong><p>${escapeHtml(row.probe_code)} · ${escapeHtml(row.software_version)} · ${escapeHtml(row.state_label || row.state)}</p></article>`).join('');
  if (key === 'qa') return data.answers.map(row => `<article class="strategy-row"><strong>${escapeHtml(row.title)}</strong><p>${escapeHtml(row.matched_text)}</p><small>${escapeHtml(row.locator)}</small></article>`).join('');
  if (key === 'issues') return data.issues.map(row => `<article class="strategy-row"><strong>${escapeHtml(row.detail || row.issue_type)}</strong></article>`).join('');
  return '';
}

function renderModelWorkspace(result) {
  const titles = { product_state: '当前版本与状态', config: '正式配置', registration: '注册范围', documents: '受控资料', probe_versions: '探头版本事件', knowledge: '知识条目', qa: '正式问答', issues: '待处理问题' };
  const views = { product_state: 'product_states', config: 'strategy', registration: 'registration', documents: 'materials', probe_versions: 'probe_versions', knowledge: 'items', qa: 'qa', issues: 'issues' };
  const params = { product_state: { model: result.scope.model, market: result.scope.country }, config: { model: result.scope.model, market: result.scope.market }, registration: { model: result.scope.model, country: result.scope.country }, documents: { model: result.scope.model, market: result.scope.market }, probe_versions: { series: result.scope.series }, knowledge: {}, qa: { model: result.scope.model, market: result.scope.market, country: result.scope.country }, issues: {} };
  const sections = Object.entries(result.sections).map(([key, section]) => {
    const canOpen = section.state !== 'needs_clarification' && !(result.scope.market === 'overseas' && ['config', 'qa'].includes(key));
    return `<section class="workspace-section"><div class="section-heading compact"><h3>${escapeHtml(titles[key] || key)}</h3>${canOpen ? `<a class="text-button" href="${escapeAttribute(buildHash(views[key], params[key]))}">进入详情</a>` : ''}</div>${section.message ? `<p class="${section.state === 'unavailable' ? 'search-source-error' : 'strategy-note'}">${escapeHtml(section.message)}</p>` : ''}${modelSectionContent(key, section, result.scope) || '<p class="empty-state compact">没有可展示的已确认内容。</p>'}</section>`;
  }).join('');
  const pending = result.pending_confirmation;
  const documents = pending.documents || [];
  const pendingCount = Object.values(pending).reduce((count, rows) => count + rows.length, 0);
  document.querySelector('#model-workspace-result').innerHTML = `<p class="workspace-scope"><strong>${escapeHtml(result.scope.model)}</strong> · ${escapeHtml(result.scope.market_label)} · ${escapeHtml(result.scope.country || '国家未选择')} · 检查 ${escapeHtml(formatDateTime(result.checked_at))}</p><div class="workspace-grid">${sections}</div><details class="workspace-section"><summary>范围或结论待确认：${pendingCount} 项</summary><p>这些资料尚不能作为该机型的适用结论。</p>${documents.map(documentCard).join('')}${pending.knowledge.length ? `<p>${pending.knowledge.length} 个知识条目未登记独立机型范围，可在知识条目页核对。</p>` : ''}${pending.questions.length ? `<p>${pending.questions.length} 个未回答问题待处理。</p>` : ''}${pending.product_states.length ? `<p>${pending.product_states.length} 条状态记录待审核。</p>` : ''}</details>`;
}

async function loadModelWorkspace() {
  const model = document.querySelector('#workspace-model').value.trim();
  if (!model) return;
  const requestId = (state.workspaceRequest || 0) + 1;
  state.workspaceRequest = requestId;
  const resultElement = document.querySelector('#model-workspace-result');
  resultElement.innerHTML = loadingMarkup('正在汇总机型资料…');
  const params = new URLSearchParams();
  for (const key of ['model', 'market', 'country', 'series']) params.set(key, document.querySelector(`#workspace-${key}`).value.trim());
  try {
    const result = await api(`/api/v1/workbench/model?${params}`);
    if (requestId !== state.workspaceRequest) return;
    renderModelWorkspace(result);
    syncLocation();
  } catch (error) {
    if (requestId === state.workspaceRequest) resultElement.innerHTML = `<p class="search-source-error">${escapeHtml(error.message)}</p>`;
  }
}

async function openDocumentEditor(mode, documentId = null, versionId = null, modelScope = '', market = '') {
  const editor = { mode, documentId, versionId };
  state.documentEditor = editor;
  const dialog = document.querySelector('#document-editor-dialog');
  document.querySelector('#document-editor-title').textContent = { historical: '补充历史资料', register: '登记新资料', append: '追加资料版本', review: '复核当前版本' }[mode];
  const fields = document.querySelector('#document-editor-fields');
  fields.innerHTML = loadingMarkup('正在读取可登记文件…');
  document.querySelector('#document-editor-error').textContent = '';
  dialog.showModal();
  if (mode === 'historical') {
    try {
      const catalog = await api('/api/v1/workbench/historical-documents/files');
      if (state.documentEditor !== editor || !dialog.open) return;
      fields.innerHTML = `<p>从已接入目录选择历史 PDF、技术 Excel 或其他资料，登记后可检索和定位原文。保留为未复核的历史参考。</p><label>查找文件<input id="historical-file-filter" type="search" placeholder="输入版本号或文件名"></label><label>历史文件<select name="file_token" required></select></label><label>资料名称<input name="title" required></label><label>版本标签<input name="version_label" placeholder="例如 1.50.0；跨版本 Excel 可填多版本"></label><label>适用机型<input name="model_scope" placeholder="以原文为准，无法确认时留空"></label><label>市场<select name="scope_market"><option value="">未登记</option><option value="domestic">国内</option><option value="overseas">海外</option></select></label><p>${catalog.total} 个可选文件${catalog.unavailable_roots ? ` · ${catalog.unavailable_roots} 个目录不可访问` : ''}。未列出的目录需先在本机配置的 source_roots 中接入。</p>`;
      const select = fields.querySelector('[name="file_token"]');
      const renderFiles = query => {
        const selected = select.value;
        select.innerHTML = '<option value="">选择历史文件</option>' + catalog.files.filter(file => (file.relative_name || file.name).toLocaleLowerCase().includes(query.toLocaleLowerCase())).map(file => `<option value="${escapeAttribute(file.file_token)}">${escapeHtml(file.relative_name || file.name)} · ${escapeHtml(file.root_label)}${file.registered ? ' · 已登记' : ''}</option>`).join('');
        if ([...select.options].some(option => option.value === selected)) select.value = selected;
      };
      renderFiles('');
      fields.querySelector('#historical-file-filter').addEventListener('input', event => renderFiles(event.target.value));
      select.addEventListener('change', () => {
        const file = catalog.files.find(item => item.file_token === select.value);
        if (file) fields.querySelector('[name="title"]').value = file.name;
      });
    } catch (error) { fields.innerHTML = `<p class="search-source-error">${escapeHtml(error.message)}</p>`; }
    return;
  }
  if (mode === 'review') {
    fields.innerHTML = `<label>适用机型<input name="model_scope" value="${escapeAttribute(modelScope)}" required placeholder="以资料原文为准，多个机型用顿号分隔"></label><label>市场<select name="scope_market" required><option value="">请选择</option><option value="domestic">国内</option><option value="overseas">海外</option></select></label><label>复核人<input name="reviewer" required></label><label>复核日期<input name="reviewed_at" type="date" required></label><label>复核依据<textarea name="basis" rows="3" required placeholder="记录原文位置及核对内容"></textarea></label><label class="checkbox-filter"><input name="confirmed" type="checkbox" required>已核对原文、版本和适用范围</label>`;
    fields.querySelector('[name="scope_market"]').value = market;
    const panel = document.createElement('section');
    panel.className = 'scope-suggestion';
    panel.innerHTML = loadingMarkup('正在智能匹配适用机型…');
    fields.prepend(panel);
    try {
      const suggestion = await api(`/api/v1/knowledge-hub/documents/${documentId}/scope-suggestion`);
      if (state.documentEditor !== editor || !dialog.open) return;
      if (suggestion.version_id !== versionId) throw new Error('当前版本已变化，请重新打开复核窗口。');
      const levels = { high: '高', medium: '中', low: '低', none: '无' };
      panel.innerHTML = `<h3>智能匹配建议 <span class="pill warning">可信度：${levels[suggestion.confidence] || '待确认'}</span></h3><p>${escapeHtml(suggestion.message)}</p>${suggestion.models.length ? `<p><strong>${escapeHtml(suggestion.models.join('、'))}</strong></p>` : ''}${suggestion.evidence.map(row => `<details><summary>${escapeHtml(row.locator)}${row.preview_id ? ' · 原文依据' : ''}</summary><p>${escapeHtml(row.excerpt)}</p>${row.preview_id ? `<button type="button" class="text-button" data-search-result-preview="${escapeAttribute(row.preview_id)}" data-search-result-locator="${escapeAttribute(row.locator)}">打开原文位置</button>` : ''}</details>`).join('')}`;
      if (suggestion.status === 'suggested' && suggestion.model_scope) {
        const scopeInput = fields.querySelector('[name="model_scope"]');
        const basisInput = fields.querySelector('[name="basis"]');
        if (!scopeInput.value.trim()) scopeInput.value = suggestion.model_scope;
        if (!basisInput.value.trim()) basisInput.value = suggestion.basis;
      }
    } catch (error) {
      if (state.documentEditor === editor && dialog.open) panel.innerHTML = `<p class="search-source-error">${escapeHtml(error.message)}</p>`;
    }
    return;
  }
  try {
    const catalog = await api('/api/v1/knowledge-hub/documents/files');
    const options = files => files.map(file => `<option value="${escapeAttribute(file.file_token)}">${escapeHtml(file.name)} · ${escapeHtml(file.root_label)}${file.registered ? ' · 已登记' : ''}</option>`).join('');
    fields.innerHTML = `${mode === 'register' ? '<label>资料名称<input name="title" required></label><label>资料类型<input name="doc_type" required placeholder="例如 白皮书、说明书"></label><label>适用机型<input name="model_scope" placeholder="无法确认时留空"></label><label>市场<select name="scope_market"><option value="">未登记</option><option value="domestic">国内</option><option value="overseas">海外</option></select></label>' : ''}<label>登记文件<select name="file_token" required><option value="">选择已接入目录中的文件</option>${options(catalog.files.filter(file => file.role !== 'extract_source'))}</select></label><label>Word 抽取源（可选）<select name="extract_source_token"><option value="">无独立抽取源</option>${options(catalog.files.filter(file => file.format === 'docx'))}</select></label><label>版本标签<input name="version_label" ${mode === 'append' ? 'required' : ''} placeholder="例如 1.14.80"></label><label>生效日期（可选）<input name="effective_date" type="date"></label><p>相同内容会复用已有登记；新版本保留历史并使相关旧答案待复核。</p>${catalog.unavailable_roots ? `<p class="search-source-error">${catalog.unavailable_roots} 个资料目录当前不可用。</p>` : ''}`;
  } catch (error) { fields.innerHTML = `<p class="search-source-error">${escapeHtml(error.message)}</p>`; }
}

document.querySelector('#model-workspace-form').addEventListener('submit', event => { event.preventDefault(); loadModelWorkspace(); });
document.querySelector('#workspace-market').addEventListener('change', () => { document.querySelector('#workspace-country').value = ''; });
document.querySelector('#register-historical-document').addEventListener('click', () => openDocumentEditor('historical').catch(error => showNotice(error.message)));
document.querySelector('#register-document').addEventListener('click', () => openDocumentEditor('register').catch(error => showNotice(error.message)));
document.querySelector('#document-editor-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.target.querySelector('[type="submit"]');
  button.disabled = true;
  const payload = Object.fromEntries(new FormData(event.target));
  if (!payload.extract_source_token) delete payload.extract_source_token;
  if (!payload.effective_date) delete payload.effective_date;
  payload.confirmed = event.target.querySelector('[name="confirmed"]')?.checked;
  const { mode, documentId, versionId } = state.documentEditor;
  const path = mode === 'historical' ? '/api/v1/workbench/historical-documents' : mode === 'register' ? '/api/v1/knowledge-hub/documents' : `/api/v1/knowledge-hub/documents/${documentId}/versions${mode === 'review' ? `/${versionId}/review` : ''}`;
  try {
    const result = await api(path, { method: 'POST', body: JSON.stringify(payload) });
    document.querySelector('#document-editor-dialog').close();
    if (mode === 'historical') {
      showNotice(result.duplicate ? '已复用既有资料，正在更新索引。' : '历史资料已登记，正在更新索引。');
      await refreshSearchIndex();
      return;
    }
    await loadKnowledgeDocuments();
    if (state.activeView === 'model') await loadModelWorkspace();
    showNotice(result.duplicate ? '内容已登记，已复用既有记录。' : '已保存资料记录。');
  } catch (error) { document.querySelector('#document-editor-error').textContent = error.message; }
  finally { button.disabled = false; }
});

document.addEventListener('click', event => {
  const matchedLocation = event.target.closest('[data-preview-locator]');
  if (matchedLocation && state.preview) openSearchPreview(state.preview.preview_id, matchedLocation.dataset.previewLocator, state.preview.query || '', state.preview.originalQuery || state.preview.query || '').catch(error => showNotice(error.message));
  const preview = event.target.closest('[data-search-result-preview]');
  if (preview && !preview.closest('#global-search-panel')) openSearchPreview(preview.dataset.searchResultPreview, preview.dataset.searchResultLocator || '', preview.dataset.searchResultQuery || '', preview.dataset.searchResultInputQuery || preview.dataset.searchResultQuery || '').catch(error => showNotice(error.message));
  const shortcut = event.target.closest('[data-personal-search]');
  if (shortcut) applySavedSearch(savedSearches()[Number(shortcut.dataset.personalSearch)]).catch(error => showNotice(error.message));
  const append = event.target.closest('[data-document-append]');
  if (append) openDocumentEditor('append', Number(append.dataset.documentAppend)).catch(error => showNotice(error.message));
  const review = event.target.closest('[data-document-review]');
  if (review) openDocumentEditor('review', Number(review.dataset.documentReview), Number(review.dataset.documentVersion), review.dataset.documentScope, review.dataset.documentMarket).catch(error => showNotice(error.message));
  if (event.target.closest('#copy-preview-reference') && state.preview) {
    const preview = state.preview;
    try {
      const citation = formatEvidenceCitation(preview, preview, window.location.href);
      copyEvidenceCitation(citation, document.querySelector('#search-preview-dialog'));
    } catch (error) { showNotice(error.message); }
  }
});

document.querySelector('#personal-index-toggle')?.addEventListener('click', async () => {
  try { state.personal = await api('/api/v1/workbench/personal', { method: 'PUT', body: JSON.stringify({ index_paused: !state.personal.index_paused }) }); renderPersonalWorkspace(); }
  catch (error) { showNotice(error.message); }
});
document.querySelector('#personal-backup')?.addEventListener('click', async event => {
  event.target.disabled = true;
  try { await api('/api/v1/workbench/backups', { method: 'POST', body: '{}' }); await loadPersonalWorkspace(); showNotice('已备份，并在副本中验证数据库完整性。'); }
  catch (error) { showNotice(error.message); }
  finally { event.target.disabled = false; }
});
document.querySelector('#personal-export')?.addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify({ schema_version: 1, saved_searches: savedSearches() }, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a'); link.href = url; link.download = '产品管理-常用入口.json'; link.click(); URL.revokeObjectURL(url);
});
document.querySelector('#personal-import')?.addEventListener('change', async event => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (file.size > 256000) throw new Error('设置文件过大，请选择导出的常用入口文件。');
    state.personal = await api('/api/v1/workbench/personal/restore', { method: 'POST', body: JSON.stringify(JSON.parse(await file.text())) });
    renderPersonalWorkspace(); renderSavedSearches(); showNotice('已恢复常用入口。');
  } catch (error) { showNotice(`恢复未完成：${error.message}`); }
  finally { event.target.value = ''; }
});

loadPersonalWorkspace().catch(error => {
  const container = document.querySelector('#personal-shortcuts');
  if (container) container.textContent = `个人工作入口暂时无法载入：${error.message}`;
});
