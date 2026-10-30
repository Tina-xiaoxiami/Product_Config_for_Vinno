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

function releaseReviewWorkspaceMarkup(data, query) {
  const review = data.review || {};
  const pending = data.unresolved_changes || [];
  const groups = new Map();
  pending.forEach(row => { const version = row.version || '未标注版本'; if (!groups.has(version)) groups.set(version, []); groups.get(version).push(row); });
  const imageSlot = '<!-- release-review-illustrations -->';
  const documentMarkup = scenarioDocumentMarkup(data.content, data.applied_changes || [], imageSlot)
    .replace(/<(p|li)(?=[\s>])/g, '<$1 tabindex="0" data-release-review-paragraph')
    .replace(imageSlot, scenarioIllustrationsMarkup(data, query));
  return `<div class="feature-review-workspace">
    <div class="feature-review-main"><div class="release-review-toolbar"><div><strong>功能正文</strong><span>修订 ${Number(review.revision) || 0}</span></div><div><button type="button" class="ghost-button compact-button" data-release-review-edit${review.source_fingerprint ? '' : ' disabled'}>编辑正文</button><button type="button" class="text-button" data-release-review-history>修订历史</button></div></div>
      ${review.stale ? '<div class="release-review-warning" role="alert">来源已变化，旧修订暂未应用。<button type="button" class="text-button" data-release-review-history>查看旧稿</button></div>' : ''}
      <p class="release-review-selection-help" data-release-review-selection>点选正文段落后，可将右侧变更替换或补入正文。</p><p class="release-review-status" data-release-review-status role="status"></p>
      ${documentMarkup}</div>
    <aside class="feature-review-sidebar" aria-label="待人工核对的版本变更"><header><h4>待核对变更</h4><span>${pending.length} 条</span></header>
      ${pending.length ? [...groups].map(([version, rows]) => `<section class="release-review-version"><h5>${escapeHtml(version)}</h5>${rows.map(row => `<article class="release-review-change"><div class="release-review-source-text">${escapeHtml(row.text || row.content || '')}</div><div class="release-review-change-actions"><button type="button" class="ghost-button compact-button" data-release-review-include="${escapeAttribute(row.id || '')}"${row.id ? '' : ' disabled'}>纳入正文</button><button type="button" class="text-button" data-release-review-ignore="${escapeAttribute(row.id || '')}"${row.id ? '' : ' disabled'}>忽略</button>${scenarioPreviewButton(row.source_id || row.preview_id, row.locator, query, '原文')}</div>${row.reason ? `<details><summary>待核对原因</summary><p>${escapeHtml(row.reason)}</p></details>` : ''}</article>`).join('')}</section>`).join('') : '<p class="release-review-empty">当前没有待核对变更。</p>'}
      ${(data.resolved_changes || []).length ? `<details class="release-review-resolved"><summary>已处理（${data.resolved_changes.length}）</summary>${data.resolved_changes.map(row => `<article><strong>${escapeHtml(row.version)} · ${row.review_action === 'include' ? '已纳入' : '已忽略'}</strong><p>${escapeHtml(row.text || row.content || '')}</p>${scenarioPreviewButton(row.source_id || row.preview_id, row.locator, query, '原文')}</article>`).join('')}</details>` : ''}
    </aside></div>`;
}

async function releaseReviewCommit(session, content, decisions, dependencies) {
  if (session.busy) return null;
  if (!dependencies.isCurrent()) { session.error = '查询范围已变化，请重新查询后操作。'; return null; }
  session.busy = true; session.error = '';
  try {
    const context = session.context;
    const result = await dependencies.api(dependencies.path('/api/v1/workbench/scenario/review'), {method: 'PUT', body: JSON.stringify({
      q: context.query, target: context.target, revision: context.review.revision,
      source_fingerprint: context.review.source_fingerprint, content, decisions,
    })});
    if (!dependencies.isCurrent()) { session.error = '查询范围已变化，未将旧查询结果覆盖当前页面。'; return null; }
    dependencies.accept(result);
    return result;
  } catch (error) {
    session.error = error.status === 409 ? '修订或来源已更新，请保留当前草稿并重新查询，未覆盖已有内容。' : `保存失败：${error.message}。草稿已保留，可重试。`;
    return null;
  } finally { session.busy = false; }
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
            || !['append', 'replace', 'delete'].includes(draft.operation) || typeof draft.source_fingerprint !== 'string') throw Error('invalid draft');
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
    const previous = ctx.review.stale ? [] : ctx.review.decisions;
    return [...previous.filter(item => item.id !== row.id), {id: row.id, action}];
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
  async function ignore(ctx, row) {
    if (reviewUI.busy) return;
    reviewUI.busy = true;
    const session = {context: ctx, busy: false, error: ''};
    try { await releaseReviewCommit(session, ctx.result.content, decisions(ctx, row, 'ignore'), dependencies(ctx)); message(session.error); }
    finally { reviewUI.busy = false; }
  }
  function edit(ctx, row = null) {
    let selected = selectedText(ctx);
    const kind = row ? 'include' : 'edit';
    const eventId = row?.id || '';
    const restored = draftStore.read(ctx, kind, eventId);
    const initial = row ? String(row.text || row.content || '') : ctx.result.content;
    const dialog = newDialog(row ? '将变更纳入正文' : '编辑功能正文', `<form data-review-form>
      ${row ? `<label>处理方式<select data-review-operation><option value="append">追加到正文</option><option value="replace">替换选中段落</option><option value="delete">删除选中段落</option></select></label><p class="release-review-hint">替换或删除前，请先点选左侧正文段落。当前未选中时仍可追加。</p><label>选中段落<textarea rows="3" readonly data-review-before>${escapeHtml(selected)}</textarea></label>` : ''}
      <label>${row ? '纳入的内容' : '完整正文'}<textarea data-review-draft rows="12" maxlength="100000" required>${escapeHtml(initial)}</textarea></label>
      ${row ? '<details open class="release-review-patch-preview"><summary>变更预览</summary><div data-review-preview></div></details>' : ''}
      <p data-review-dialog-status role="status"></p><div class="dialog-actions"><button type="button" class="ghost-button" data-review-close>放弃草稿</button><button type="button" class="ghost-button" data-review-keep-close>暂存并关闭</button><button type="submit" class="primary-button">确认并保存</button></div></form>`);
    if (!dialog) return;
    const session = {context: ctx, busy: false, error: ''};
    const draft = dialog.querySelector('[data-review-draft]');
    const operation = dialog.querySelector('[data-review-operation]');
    const status = dialog.querySelector('[data-review-dialog-status]');
    const storageStatus = document.createElement('p');
    storageStatus.className = 'release-review-draft-status'; storageStatus.setAttribute('role', 'status');
    draft.parentElement.after(storageStatus);
    let restoredDirty = false;
    if (restored.error) storageStatus.textContent = restored.error;
    if (restored.draft) {
      draft.value = restored.draft.text; restoredDirty = true;
      if (operation) operation.value = restored.draft.operation;
      const recovered = releaseReviewRecoverDraft(restored.draft, ctx, selected);
      selected = recovered.selected;
      const before = dialog.querySelector('[data-review-before]'); if (before) before.value = selected;
      storageStatus.textContent = recovered.warning;
    }
    const persist = () => {
      const saved = draftStore.write(ctx, kind, eventId, {text: draft.value, operation: operation?.value || 'append', selected,
        source_fingerprint: ctx.review.source_fingerprint, revision: ctx.review.revision});
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
    operation?.addEventListener('change', () => { persist(); preview(); }); preview();
    const dismiss = bindDialog(dialog, session, () => restoredDirty || draft.value !== initial || Boolean(operation && operation.value !== 'append'), {persist, discard});
    dialog.querySelector('form').addEventListener('submit', async event => {
      event.preventDefault(); if (session.busy || reviewUI.busy) return;
      let content;
      try { content = row ? releaseReviewPatch(ctx.result.content, operation.value, selected, draft.value).content : draft.value; }
      catch (error) { status.textContent = error.message; return; }
      if (!content.trim()) { status.textContent = '正文不能为空。'; return; }
      persist();
      reviewUI.busy = true; busy(dialog, true); status.textContent = '正在保存…';
      try {
        const result = await releaseReviewCommit(session, content, row ? decisions(ctx, row, 'include') : (ctx.review.stale ? [] : ctx.review.decisions), dependencies(ctx));
        if (result) { discard(); dismiss(); } else status.textContent = session.error;
      } finally { reviewUI.busy = false; if (dialog.isConnected) busy(dialog, false); }
    });
  }
  async function history(ctx) {
    const dialog = newDialog('人工修订历史', '<p data-review-dialog-status role="status">正在读取修订历史…</p><div data-review-history-list></div><div class="dialog-actions"><button type="button" class="ghost-button" data-review-close>关闭</button></div>');
    if (!dialog) return;
    const session = {context: ctx, busy: false, error: ''};
    const dismiss = bindDialog(dialog, session, () => false);
    const status = dialog.querySelector('[data-review-dialog-status]');
    try {
      const data = await api(projectPath(`/api/v1/workbench/scenario/review-history?${new URLSearchParams({q: ctx.query, target: ctx.target})}`));
      if (!dialog.isConnected) return;
      if (!current(ctx)) { status.textContent = '查询范围已变化，请关闭后重新查询。'; return; }
      status.textContent = '';
      dialog.querySelector('[data-review-history-list]').innerHTML = (data.history || []).map(item => `<article><header><strong>${Number(item.revision) === 0 ? '自动演进原稿' : `修订 ${Number(item.revision)}`}</strong><span>${escapeHtml(item.created_at || '')}</span><button type="button" class="ghost-button compact-button" data-review-restore="${Number(item.revision)}"${item.restorable && Number(item.revision) !== Number(ctx.review.revision) ? '' : ' disabled'}>恢复为新修订</button></header>${item.restorable ? '' : '<p class="release-review-warning">来源已变化，该旧稿仅供参考。</p>'}<div class="release-review-history-content">${escapeHtml(item.content)}</div></article>`).join('') || '<p>还没有人工修订。</p>';
      dialog.querySelectorAll('[data-review-restore]').forEach(button => button.addEventListener('click', async () => {
        if (session.busy || reviewUI.busy) return;
        if (!current(ctx)) { status.textContent = '查询范围已变化，请重新查询。'; return; }
        session.busy = true; reviewUI.busy = true; busy(dialog, true); status.textContent = '正在恢复…';
        try {
          const result = await api(projectPath('/api/v1/workbench/scenario/review/restore'), {method: 'POST', body: JSON.stringify({q: ctx.query, target: ctx.target, revision: ctx.review.revision, source_fingerprint: ctx.review.source_fingerprint, restore_revision: Number(button.dataset.reviewRestore)})});
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
    if (help) help.textContent = `已选中：${text.slice(0, 80)}${text.length > 80 ? '…' : ''}；可从右侧纳入变更并替换此段。`;
  }
  document.addEventListener('keydown', event => {
    const paragraph = event.target.closest?.('[data-release-review-paragraph]');
    if (paragraph && ['Enter', ' '].includes(event.key)) { event.preventDefault(); selectParagraph(paragraph); }
  });
  document.addEventListener('click', event => {
    const paragraph = event.target.closest?.('[data-release-review-paragraph]');
    if (paragraph && !event.target.closest('button,a,input,textarea,select')) selectParagraph(paragraph);
    const button = event.target.closest?.('[data-release-review-edit],[data-release-review-include],[data-release-review-ignore],[data-release-review-history]');
    if (!button || reviewUI.busy) return;
    try {
      const ctx = context();
      if (button.hasAttribute('data-release-review-history')) { history(ctx); return; }
      if (button.hasAttribute('data-release-review-edit')) { edit(ctx); return; }
      const id = button.dataset.releaseReviewInclude || button.dataset.releaseReviewIgnore;
      const row = (ctx.result.unresolved_changes || []).find(item => item.id === id);
      if (!row) throw Error('待核记录已变化，请重新查询。');
      if (button.hasAttribute('data-release-review-ignore')) ignore(ctx, row); else edit(ctx, row);
    } catch (error) { message(error.message); }
  });
}
