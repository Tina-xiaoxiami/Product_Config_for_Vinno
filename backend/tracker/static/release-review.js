/* Human Release Note reconciliation. Source text and automatic revisions stay intact. */
function releaseReviewPatch(content, operation, selected, replacement = '') {
  if (typeof content !== 'string' || typeof replacement !== 'string') throw Error('正文格式无效。');
  if (operation === 'append') {
    if (!replacement.trim()) throw Error('请填写要纳入的内容。');
    return { content: `${content.trimEnd()}\n\n${replacement.trim()}`, before: '', after: replacement.trim() };
  }
  if (!['replace', 'delete'].includes(operation)) throw Error('请选择有效操作。');
  if (!selected) throw Error('请先点击左侧正文段落，再选择替换或删除。');
  if (content.split(selected).length !== 2) throw Error('选中段落无法唯一定位，请重新选择或使用“编辑正文”。');
  if (operation === 'replace' && !replacement.trim()) throw Error('替换内容不能为空。');
  const after = operation === 'delete' ? '' : replacement.trim();
  return { content: content.replace(selected, () => after), before: selected, after };
}

function releaseReviewDecisions(context, row, action) {
  const previous = context.review.decisions || [];
  const remaining = previous.filter(item => item.id !== row.id);
  return action ? [...remaining, {id: row.id, action}] : remaining;
}

function releaseReviewLogMarkup(data, query) {
  const rows = data.change_log || [];
  const recorded = rows.filter(row => ['recognized', 'adopted'].includes(row.log_status));
  const ignored = rows.filter(row => row.log_status === 'ignored');
  const grouped = new Map();
  recorded.forEach(row => { const version = row.version || '未标注版本'; if (!grouped.has(version)) grouped.set(version, []); grouped.get(version).push(row); });
  const labels = {recognized: '系统识别', adopted: '已采纳', ignored: '已忽略'};
  return `<section class="release-feature-log" aria-label="版本更新记录"><header><h4>版本更新记录</h4><button type="button" class="text-button" data-release-review-history="log">记录处理历史</button></header><p class="release-review-hint">采纳记录不修改功能正文；撤销记录处理也不会回滚正文。</p>${recorded.length ? [...grouped].map(([version, entries]) => `<details class="release-feature-log-version"><summary>${escapeHtml(version)} <span>${entries.length} 条</span></summary>${entries.map(row => `<article><div class="release-feature-log-meta"><span>${escapeHtml(labels[row.log_status] || row.log_status)}</span>${row.review_action === 'include' ? '<span>曾关联正文修改</span>' : ''}</div><p>${escapeHtml(row.text || row.content || '')}</p><div class="release-review-change-actions">${row.log_status !== 'ignored' && row.id ? `<button type="button" class="text-button" data-release-review-include="${escapeAttribute(row.id)}">更新正文</button>` : ''}${row.review_action && row.id ? `<button type="button" class="text-button" data-release-review-undo="${escapeAttribute(row.id)}">撤销${row.log_status === 'ignored' ? '忽略' : '采纳'}</button>` : ''}${scenarioPreviewButton(row.source_id || row.preview_id, row.locator, query, '原文')}</div></article>`).join('')}</details>`).join('') : '<p class="release-review-empty">还没有已记录的版本更新。</p>'}${ignored.length ? `<details class="release-review-ignored"><summary>已忽略（${ignored.length}）</summary>${ignored.map(row => `<article><strong>${escapeHtml(row.version)}</strong><p>${escapeHtml(row.text || row.content || '')}</p><button type="button" class="text-button" data-release-review-undo="${escapeAttribute(row.id || '')}">撤销忽略</button>${scenarioPreviewButton(row.source_id || row.preview_id,row.locator,query,'原文')}</article>`).join('')}</details>` : ''}</section>`;
}

function releaseReviewWorkspaceMarkup(data, query) {
  const review = data.review || {};
  const pending = data.unresolved_changes || [];
  const groups = new Map();
  pending.forEach(row => { const version = row.version || '未标注版本'; if (!groups.has(version)) groups.set(version, []); groups.get(version).push(row); });
  const imageSlot = '<!-- release-review-illustrations -->';
  const documentMarkup = scenarioDocumentMarkup(data.content, [], imageSlot)
    .replace(/<(p|li)(?=[\s>])/g, '<$1 tabindex="0" data-release-review-paragraph')
    .replace(imageSlot, () => scenarioIllustrationsMarkup(data, query));
  return `<div class="feature-review-workspace">
    <div class="feature-review-main"><div class="release-review-toolbar"><div><strong>功能正文</strong><span>正文修订 ${Number(review.body_revision) || 0}</span></div><div><button type="button" class="ghost-button compact-button" data-release-review-edit${review.source_fingerprint ? '' : ' disabled'}>编辑正文</button><button type="button" class="text-button" data-release-review-history="body">正文修订历史</button></div></div>
      ${review.stale ? '<div class="release-review-warning" role="status">来源有更新；已保存正文与未变化记录的结论继续保留，变化条目需要重新核对。</div>' : ''}
      ${review.migration_notice ? `<p class="release-review-migration">${escapeHtml(review.migration_notice)}</p>` : ''}
      ${(review.stale_decisions || []).length ? `<details class="release-review-stale-decisions"><summary>来源变化待复核（${review.stale_decisions.length}）</summary><p>旧结论仍保留在处理历史中，未自动套用到变化后的记录。</p><button type="button" class="text-button" data-release-review-history="log">查看记录处理历史</button></details>` : ''}
      <p class="release-review-selection-help" data-release-review-selection>采纳右侧记录不会改正文；需要更新正文时，可先点选要替换的段落。</p><p class="release-review-status" data-release-review-status role="status"></p>
      <section class="release-feature-body" aria-label="功能正文内容">${documentMarkup}</section>${releaseReviewLogMarkup(data, query)}</div>
    <aside class="feature-review-sidebar" aria-label="待人工核对的版本变更"><header><h4>待核对变更</h4><span>${pending.length} 条</span></header><p class="release-review-sidebar-help">先采纳记录，按需更新正文。</p>
      ${pending.length ? [...groups].map(([version, rows]) => `<section class="release-review-version"><h5>${escapeHtml(version)}</h5>${rows.map(row => `<article class="release-review-change"><div class="release-review-source-text">${escapeHtml(row.text || row.content || '')}</div><div class="release-review-change-actions"><button type="button" class="primary-button compact-button" data-release-review-adopt="${escapeAttribute(row.id || '')}"${row.id ? '' : ' disabled'}>采纳记录</button><button type="button" class="text-button" data-release-review-include="${escapeAttribute(row.id || '')}"${row.id ? '' : ' disabled'}>更新正文</button><button type="button" class="text-button" data-release-review-ignore="${escapeAttribute(row.id || '')}"${row.id ? '' : ' disabled'}>忽略</button>${scenarioPreviewButton(row.source_id || row.preview_id, row.locator, query, '原文')}</div>${row.reason ? `<details><summary>待核对原因</summary><p>${escapeHtml(row.reason)}</p></details>` : ''}</article>`).join('')}</section>`).join('') : '<p class="release-review-empty">当前没有待核对变更。</p>'}
    </aside></div>`;
}

async function releaseReviewCommit(session, content, decisions, dependencies, bodyChange = null) {
  if (session.busy) return null;
  if (!dependencies.isCurrent()) { session.error = '查询范围已变化，请重新查询后操作。'; return null; }
  if (bodyChange && session.context.result?.content === content) { session.error = '正文没有变化，请使用“采纳记录”记录这条更新。'; return null; }
  session.busy = true; session.error = '';
  try {
    const context = session.context;
    const result = await dependencies.api(dependencies.path('/api/v1/workbench/scenario/review'), {method: 'PUT', body: JSON.stringify({
      q: context.query, target: context.target, revision: context.review.revision,
      source_fingerprint: context.review.source_fingerprint, content, decisions,
      ...(bodyChange ? {body_change: bodyChange} : {}),
    })});
    if (!dependencies.isCurrent()) { session.error = '查询范围已变化，未将旧查询结果覆盖当前页面。'; return null; }
    dependencies.accept(result);
    return result;
  } catch (error) {
    session.error = error.status === 409 ? '修订或来源已更新，请保留当前草稿并重新查询，未覆盖已有内容。' : `保存失败：${error.message}。草稿已保留，可重试。`;
    return null;
  } finally { session.busy = false; }
}

function releaseReviewRestorePayload(context, kind, revision) {
  if (!['body', 'log'].includes(kind)) throw Error('修订类型无效。');
  return {q: context.query, target: context.target, kind, revision: context.review.revision,
    source_fingerprint: context.review.source_fingerprint, restore_revision: Number(revision)};
}

function releaseReviewDraftKey(context, kind, eventId = '') {
  return 'release-review-draft-v1:' + JSON.stringify([context.project, String(context.query).trim().toLocaleLowerCase(), context.target || '', kind, eventId]);
}

function releaseReviewDraftStore(storage) {
  const error = '本机草稿暂存不可用，请保留当前窗口或将正文复制备份。';
  return {
    read(context, kind, id = '') {
      try {
        const raw = storage.getItem(releaseReviewDraftKey(context, kind, id));
        if (!raw) return {draft: null, error: ''};
        const draft = JSON.parse(raw);
        if (!draft || typeof draft.text !== 'string' || draft.text.length > 100000 || typeof draft.selected !== 'string'
            || !['append', 'replace', 'delete'].includes(draft.operation) || typeof draft.source_fingerprint !== 'string'
            || (draft.reason !== undefined && (typeof draft.reason !== 'string' || draft.reason.length > 2000))) throw Error('invalid draft');
        return {draft, error: ''};
      } catch { return {draft: null, error}; }
    },
    write(context, kind, id, draft) {
      try { storage.setItem(releaseReviewDraftKey(context, kind, id), JSON.stringify(draft)); return {ok: true, error: ''}; }
      catch { return {ok: false, error}; }
    },
    clear(context, kind, id = '') {
      try { storage.removeItem(releaseReviewDraftKey(context, kind, id)); return {ok: true, error: ''}; }
      catch { return {ok: false, error}; }
    },
  };
}

function releaseReviewRecoverDraft(draft, context, selected = '') {
  const changedSource = draft.source_fingerprint !== context.review.source_fingerprint;
  const changedRevision = draft.revision !== context.review.revision;
  selected = selected || (changedSource ? '' : draft.selected);
  if (selected && context.result.content.split(selected).length !== 2) selected = '';
  return { ...draft, selected, warning: changedSource ? '已恢复旧来源草稿；旧段落锚点已清除，可暂存关闭后重新点选当前正文，再打开核对。'
    : changedRevision ? '已恢复草稿，但正文已有新修订，请核对后再保存。' : '已恢复本机尚未提交的草稿。' };
}

function releaseReviewLeaveGuard(active, options) {
  if (options.busy || active?.session.busy) { options.warn('正在保存人工核对，请等待完成后离开。'); return false; }
  if (!active) return true;
  if (active.dirty()) {
    if (!options.confirm('人工核对草稿尚未提交。保留本机草稿并离开吗？')) return false;
    if (!active.persist()) {
      options.warn('草稿暂存失败，离开后无法保证恢复。');
      if (!options.confirm('本机草稿暂存失败。确定放弃当前草稿并离开吗？')) return false;
      active.discard();
    }
  }
  active.dismiss();
  return true;
}

if (typeof document !== 'undefined') {
  const reviewUI = { selected: null, busy: false, dialog: null, active: null };
  let storage;
  try { storage = window.sessionStorage; } catch { storage = null; }
  const draftStore = releaseReviewDraftStore(storage);
  window.requestReleaseReviewLeave = () => releaseReviewLeaveGuard(reviewUI.active, {busy: reviewUI.busy, confirm: text => window.confirm(text), warn: message});
  window.addEventListener('beforeunload', event => {
    const active = reviewUI.active;
    if (reviewUI.busy || active?.session.busy || active?.dirty()) {
      if (active?.dirty()) active.persist();
      event.preventDefault(); event.returnValue = '';
    }
  });
  function context() {
    const result = scenarioState.result;
    if (scenarioState.task !== 'feature' || !result?.review) throw Error('请先查询Release Note完整描述。');
    return {request: scenarioState.request, project: state.activeProjectId, result,
      query: document.querySelector('#scenario-query').value.trim(), target: document.querySelector('#scenario-target').value,
      review: { ...result.review, decisions: [...(result.review.decisions || [])] }};
  }
  function current(ctx) {
    return scenarioState.task === 'feature' && scenarioState.request === ctx.request && state.activeProjectId === ctx.project
      && scenarioState.result === ctx.result && document.querySelector('#scenario-query').value.trim() === ctx.query
      && document.querySelector('#scenario-target').value === ctx.target;
  }
  function accept(result, ctx) {
    scenarioState.result = result;
    reviewUI.selected = null;
    document.querySelector('#scenario-result').innerHTML = scenarioEvolutionMarkup(result, ctx.query);
  }
  function message(text) { const node = document.querySelector('[data-release-review-status]'); if (node) node.textContent = text; }
  function decisions(ctx, row, action) {
    return releaseReviewDecisions(ctx, row, action);
  }
  function dependencies(ctx) { return {api, path: projectPath, isCurrent: () => current(ctx), accept: result => accept(result, ctx)}; }
  function selectedText(ctx) { return reviewUI.selected && reviewUI.selected.request === ctx.request && reviewUI.selected.project === ctx.project && reviewUI.selected.result === ctx.result ? reviewUI.selected.text : ''; }
  function newDialog(title, html) {
    if (reviewUI.dialog?.open) return null;
    const dialog = document.createElement('dialog');
    dialog.className = 'release-review-dialog'; dialog.setAttribute('aria-label', title);
    dialog.innerHTML = `<div class="dialog-heading"><h2>${escapeHtml(title)}</h2><button type="button" class="ghost-button" data-review-close aria-label="关闭">×</button></div>${html}`;
    document.body.append(dialog); reviewUI.dialog = dialog;
    return dialog;
  }
  function bindDialog(dialog, session, dirty, hooks = {}) {
    function dismiss() {
      dialog.close(); dialog.remove(); reviewUI.dialog = null;
      if (reviewUI.active?.dialog === dialog) reviewUI.active = null;
    }
    function close() {
      if (session.busy || reviewUI.busy) return false;
      if (dirty() && !window.confirm('人工核对草稿尚未保存，放弃本次修改吗？')) return false;
      hooks.discard?.(); dismiss(); return true;
    }
    reviewUI.active = {dialog, session, dirty, persist: hooks.persist || (() => true), discard: hooks.discard || (() => {}), dismiss};
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    dialog.querySelectorAll('[data-review-close]').forEach(button => button.addEventListener('click', close));
    dialog.querySelector('[data-review-keep-close]')?.addEventListener('click', () => {
      if (session.busy || reviewUI.busy) return;
      if (hooks.persist?.()) dismiss();
    });
    dialog.showModal();
    return dismiss;
  }
  function busy(dialog, value) {
    dialog.querySelectorAll('button,input,select,textarea').forEach(control => {
      if (value) { control.dataset.reviewWasDisabled = String(control.disabled); control.disabled = true; }
      else { control.disabled = control.dataset.reviewWasDisabled === 'true'; delete control.dataset.reviewWasDisabled; }
    });
  }
  async function recordDecision(ctx, row, action) {
    if (reviewUI.busy) return;
    reviewUI.busy = true;
    const session = {context: ctx, busy: false, error: ''};
    try {
      const result = await releaseReviewCommit(session, ctx.result.content, decisions(ctx, row, action), dependencies(ctx));
      message(session.error || (result ? action === 'adopt' ? '已采纳至版本更新记录，功能正文未改动。' : action === 'ignore' ? '已忽略该记录，功能正文未改动。' : '已撤销记录处理，功能正文保持不变。' : ''));
    }
    finally { reviewUI.busy = false; }
  }
  function edit(ctx, row = null) {
    let selected = selectedText(ctx);
    const kind = row ? 'include' : 'edit';
    const eventId = row?.id || '';
    const restored = draftStore.read(ctx, kind, eventId);
    const initial = row ? String(row.text || row.content || '') : ctx.result.content;
    const dialog = newDialog(row ? '采纳记录并更新正文' : '编辑功能正文', `<form data-review-form>
      ${row ? `<label>处理方式<select data-review-operation><option value="append">追加到正文</option><option value="replace">替换选中段落</option><option value="delete">删除选中段落</option></select></label><p class="release-review-hint">替换或删除前，请先点选左侧正文段落。当前未选中时仍可追加。</p><label>选中段落<textarea rows="3" readonly data-review-before>${escapeHtml(selected)}</textarea></label>` : ''}
      <p class="release-review-hint">${row ? '本次保存会同时采纳这条更新记录，并新增一条正文修订。' : '这里只修改正文，不改变版本更新记录的采纳或忽略结论。'}</p><label>${row ? '更新后的内容' : '完整正文'}<textarea data-review-draft rows="12" maxlength="100000" required>${escapeHtml(initial)}</textarea></label>
      <label>修改原因（可选）<input data-review-reason maxlength="2000" placeholder="例如：更新测量方式说明"></label>
      ${row ? '<details open class="release-review-patch-preview"><summary>变更预览</summary><div data-review-preview></div></details>' : ''}
      <p data-review-dialog-status role="status"></p><div class="dialog-actions"><button type="button" class="ghost-button" data-review-close>放弃草稿</button><button type="button" class="ghost-button" data-review-keep-close>暂存并关闭</button><button type="submit" class="primary-button">确认并保存</button></div></form>`);
    if (!dialog) return;
    const session = {context: ctx, busy: false, error: ''};
    const draft = dialog.querySelector('[data-review-draft]');
    const operation = dialog.querySelector('[data-review-operation]');
    const status = dialog.querySelector('[data-review-dialog-status]');
    const reason = dialog.querySelector('[data-review-reason]');
    const storageStatus = document.createElement('p');
    storageStatus.className = 'release-review-draft-status'; storageStatus.setAttribute('role', 'status');
    draft.parentElement.after(storageStatus);
    let restoredDirty = false;
    if (restored.error) storageStatus.textContent = restored.error;
    if (restored.draft) {
      draft.value = restored.draft.text; reason.value = restored.draft.reason || ''; restoredDirty = true;
      if (operation) operation.value = restored.draft.operation;
      const recovered = releaseReviewRecoverDraft(restored.draft, ctx, selected);
      selected = recovered.selected;
      const before = dialog.querySelector('[data-review-before]'); if (before) before.value = selected;
      storageStatus.textContent = recovered.warning;
    }
    const persist = () => {
      const saved = draftStore.write(ctx, kind, eventId, {text: draft.value, operation: operation?.value || 'append', selected,
        source_fingerprint: ctx.review.source_fingerprint, revision: ctx.review.revision, reason: reason.value});
      storageStatus.textContent = saved.ok ? '草稿已暂存在本机；尚未提交修订。' : saved.error;
      return saved.ok;
    };
    const discard = () => {
      const cleared = draftStore.clear(ctx, kind, eventId);
      if (!cleared.ok) message('本机草稿未能清除；再次打开时请核对，避免误用旧稿。');
    };
    const preview = () => {
      if (!row) return;
      draft.required = operation.value !== 'delete';
      try {
        const patch = releaseReviewPatch(ctx.result.content, operation.value, selected, draft.value);
        dialog.querySelector('[data-review-preview]').innerHTML = `<div><strong>原内容</strong><p>${escapeHtml(patch.before || '（追加，不替换原文）')}</p></div><div><strong>更新为</strong><p>${escapeHtml(patch.after || '（删除该段落）')}</p></div>`;
      } catch (error) { dialog.querySelector('[data-review-preview]').textContent = error.message; }
    };
    draft.addEventListener('input', () => { persist(); preview(); });
    reason.addEventListener('input', persist);
    operation?.addEventListener('change', () => { persist(); preview(); }); preview();
    const dismiss = bindDialog(dialog, session, () => restoredDirty || draft.value !== initial || Boolean(reason.value) || Boolean(operation && operation.value !== 'append'), {persist, discard});
    dialog.querySelector('form').addEventListener('submit', async event => {
      event.preventDefault(); if (session.busy || reviewUI.busy) return;
      let content;
      try { content = row ? releaseReviewPatch(ctx.result.content, operation.value, selected, draft.value).content : draft.value; }
      catch (error) { status.textContent = error.message; return; }
      if (!content.trim()) { status.textContent = '正文不能为空。'; return; }
      persist();
      reviewUI.busy = true; busy(dialog, true); status.textContent = '正在保存…';
      try {
        const bodyChange = {operation: row ? operation.value : 'edit', reason: reason.value, ...(row ? {event_id: row.id} : {})};
        const result = await releaseReviewCommit(session, content, row ? decisions(ctx, row, 'include') : ctx.review.decisions, dependencies(ctx), bodyChange);
        if (result) { discard(); dismiss(); } else status.textContent = session.error;
      } finally { reviewUI.busy = false; if (dialog.isConnected) busy(dialog, false); }
    });
  }
  async function history(ctx, kind = 'body') {
    const bodyHistory = kind === 'body';
    const dialog = newDialog(bodyHistory ? '正文修订历史' : '版本记录处理历史', `<p class="release-review-hint">${bodyHistory ? '仅记录正文的实际修改；恢复正文不会撤销采纳或忽略结论。' : '仅记录采纳、忽略及撤销；恢复这些结论不会修改功能正文。'}</p><p data-review-dialog-status role="status">正在读取历史…</p><div data-review-history-list></div><div class="dialog-actions"><button type="button" class="ghost-button" data-review-close>关闭</button></div>`);
    if (!dialog) return;
    const session = {context: ctx, busy: false, error: ''};
    const dismiss = bindDialog(dialog, session, () => false);
    const status = dialog.querySelector('[data-review-dialog-status]');
    try {
      const data = await api(projectPath(`/api/v1/workbench/scenario/review-history?${new URLSearchParams({q: ctx.query, target: ctx.target, kind})}`));
      if (!dialog.isConnected) return;
      if (!current(ctx)) { status.textContent = '查询范围已变化，请关闭后重新查询。'; return; }
      status.textContent = '';
      const activeRevision = Number(ctx.review[bodyHistory ? 'body_revision' : 'log_revision']) || 0;
      const historyEvents = new Map((ctx.result.change_log || []).map(row => [row.id, row]));
      const actionLabels = {adopt:'采纳记录',include:'采纳并更新正文',ignore:'忽略'};
      dialog.querySelector('[data-review-history-list]').innerHTML = (data.history || []).map(item => {
        const revision = Number(item[bodyHistory ? 'body_revision' : 'log_revision']) || 0;
        const title = Number(item.revision) === 0 ? bodyHistory ? '初始功能正文' : '初始记录处理状态' : `${bodyHistory ? '正文修订' : '记录处理'} ${revision}`;
        const change = item.body_change || {};
        const content = bodyHistory ? `${change.source_version ? `<p class="release-review-history-meta">关联版本 ${escapeHtml(change.source_version)}</p>` : ''}${change.reason ? `<p>${escapeHtml(change.reason)}</p>` : ''}${change.before !== undefined && change.after !== undefined ? `<details><summary>查看修改前后</summary><div class="release-review-history-diff"><section><strong>修改前</strong><p>${escapeHtml(change.before)}</p></section><section><strong>修改后</strong><p>${escapeHtml(change.after)}</p></section></div></details>` : ''}<details><summary>查看完整正文</summary><div class="release-review-history-content">${escapeHtml(item.content)}</div></details>`
          : (item.decisions || []).map(decision => { const row=historyEvents.get(decision.id); return `<p>${escapeHtml(actionLabels[decision.action] || decision.action)} · ${escapeHtml(row?.version || '')} ${escapeHtml(row?.text || row?.content || '原来源记录')}</p>`; }).join('') || '<p>没有已采纳或忽略的记录。</p>';
        return `<article><header><strong>${escapeHtml(title)}</strong><span>${escapeHtml(item.created_at || '')}</span><button type="button" class="ghost-button compact-button" data-review-restore="${Number(item.revision)}"${item.restorable && revision !== activeRevision ? '' : ' disabled'}>${bodyHistory ? '恢复正文' : '恢复处理结论'}</button></header>${item.restorable ? '' : '<p class="release-review-warning">相关来源已变化，此记录仅供参考。</p>'}${content}</article>`;
      }).join('') || '<p>还没有修订。</p>';
      dialog.querySelectorAll('[data-review-restore]').forEach(button => button.addEventListener('click', async () => {
        if (session.busy || reviewUI.busy) return;
        if (!current(ctx)) { status.textContent = '查询范围已变化，请重新查询。'; return; }
        session.busy = true; reviewUI.busy = true; busy(dialog, true); status.textContent = '正在恢复…';
        try {
          const result = await api(projectPath('/api/v1/workbench/scenario/review/restore'), {method: 'POST', body: JSON.stringify(releaseReviewRestorePayload(ctx, kind, button.dataset.reviewRestore))});
          if (!current(ctx)) { status.textContent = '查询范围已变化，未覆盖当前页面。'; return; }
          accept(result, ctx); dismiss();
        } catch (error) { status.textContent = error.status === 409 ? '修订或来源已更新，请关闭历史并重新查询。' : `恢复失败：${error.message}`; }
        finally { session.busy = false; reviewUI.busy = false; if (dialog.isConnected) busy(dialog, false); }
      }));
    } catch (error) { if (dialog.isConnected) status.textContent = `历史读取失败：${error.message}`; }
  }
  function selectParagraph(node) {
    if (!node.closest('.feature-review-main .feature-document-section') || node.closest('.feature-image-section,.feature-image-gallery')) return;
    let ctx; try { ctx = context(); } catch { return; }
    const text = node.dataset.releaseReviewText || node.textContent;
    document.querySelectorAll('.release-review-selected').forEach(item => { item.classList.remove('release-review-selected'); item.removeAttribute('aria-current'); });
    node.classList.add('release-review-selected'); node.setAttribute('aria-current', 'true');
    reviewUI.selected = {request: ctx.request, project: ctx.project, result: ctx.result, text};
    const help = document.querySelector('[data-release-review-selection]');
    if (help) help.textContent = `已选中：${text.slice(0, 80)}${text.length > 80 ? '…' : ''}；可从右侧选择“更新正文”并替换此段。`;
  }
  document.addEventListener('keydown', event => {
    const paragraph = event.target.closest?.('[data-release-review-paragraph]');
    if (paragraph && ['Enter', ' '].includes(event.key)) { event.preventDefault(); selectParagraph(paragraph); }
  });
  document.addEventListener('click', event => {
    const paragraph = event.target.closest?.('[data-release-review-paragraph]');
    if (paragraph && !event.target.closest('button,a,input,textarea,select')) selectParagraph(paragraph);
    const button = event.target.closest?.('[data-release-review-edit],[data-release-review-adopt],[data-release-review-include],[data-release-review-ignore],[data-release-review-undo],[data-release-review-history]');
    if (!button || reviewUI.busy) return;
    try {
      const ctx = context();
      if (button.hasAttribute('data-release-review-history')) { history(ctx, button.dataset.releaseReviewHistory === 'log' ? 'log' : 'body'); return; }
      if (button.hasAttribute('data-release-review-edit')) { edit(ctx); return; }
      const id = button.dataset.releaseReviewAdopt || button.dataset.releaseReviewInclude || button.dataset.releaseReviewIgnore || button.dataset.releaseReviewUndo;
      const row = [...(ctx.result.unresolved_changes || []), ...(ctx.result.change_log || []), ...(ctx.result.resolved_changes || [])].find(item => item.id === id);
      if (!row) throw Error('待核记录已变化，请重新查询。');
      if (button.hasAttribute('data-release-review-adopt')) recordDecision(ctx, row, 'adopt');
      else if (button.hasAttribute('data-release-review-ignore')) recordDecision(ctx, row, 'ignore');
      else if (button.hasAttribute('data-release-review-undo')) recordDecision(ctx, row, null);
      else edit(ctx, row);
    } catch (error) { message(error.message); }
  });
}
