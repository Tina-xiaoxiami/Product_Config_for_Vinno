/* Provider settings follow the guide application's separate private profiles. */
(() => {
  const controls = document.querySelector('.scenario-controls');
  if (!controls) return;
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'ghost-button compact-button'; button.textContent = 'API 设置';
  button.dataset.descriptionSettings = '';
  controls.append(button);
  const dialog = document.createElement('dialog');
  dialog.className = 'description-model-dialog';
  dialog.setAttribute('aria-label', '自动整理 API 设置');
  dialog.innerHTML = `<form id="description-model-form"><div class="dialog-heading"><h2>自动整理 API 设置</h2><button type="button" data-model-close aria-label="关闭">×</button></div>
    <p>分别保存 DeepSeek 和 OpenAI 配置，密钥只存本机、不回显。仅在首次整理或相关资料变化时调用。</p>
    <div class="description-model-fields">
      <label>服务商<select name="provider"><option value="deepseek">DeepSeek</option><option value="openai">OpenAI</option></select></label>
      <label>模型<input name="model" required maxlength="100" autocomplete="off" placeholder="填写官方模型标识"></label>
      <label>API 密钥<input name="api_key" type="password" maxlength="512" autocomplete="new-password" placeholder="留空保留已有密钥"></label>
      <label>每日 token 预算<input name="daily_tokens" type="number" min="0" max="10000000" step="1" required></label>
    </div><p data-model-key-status></p><p>预算含输入与输出，0 表示暂停模型调用。手工编辑不消耗模型 token。</p>
    <p data-model-status role="status"></p><div class="dialog-actions"><button type="button" class="ghost-button" data-model-close>关闭</button><button type="submit" class="primary-button">保存并使用</button></div></form>`;
  document.body.append(dialog);
  const form = dialog.querySelector('form');
  const fields = form.elements;
  const status = dialog.querySelector('[data-model-status]');
  let config = null, provider = '', saving = false, original = '';
  const drafts = new Map();
  const signature = () => JSON.stringify([fields.provider.value, fields.model.value, fields.api_key.value, fields.daily_tokens.value, [...drafts]]);
  const busy = value => { saving = value; [...fields].forEach(field => { field.disabled = value; }); };
  const show = selected => {
    provider = selected; fields.provider.value = selected;
    const draft = drafts.get(selected);
    fields.model.value = draft?.model ?? config.providers[selected].model;
    fields.api_key.value = draft?.key ?? '';
    dialog.querySelector('[data-model-key-status]').textContent = Object.values(config.providers).map(profile => `${profile.label}：${profile.configured ? '已配置' : '待配置'}`).join(' · ');
  };
  function close() {
    if (saving) return false;
    if ((signature() !== original || drafts.size) && !window.confirm('API 设置尚未保存，放弃本次修改吗？')) return false;
    fields.api_key.value = ''; drafts.clear(); dialog.close(); return true;
  }
  button.addEventListener('click', async () => {
    if (dialog.open) return;
    dialog.showModal(); status.textContent = '正在读取设置…'; busy(true);
    try {
      config = await api('/api/v1/workbench/model-settings');
      drafts.clear(); show(config.provider); fields.daily_tokens.value = config.daily_tokens;
      original = signature(); status.textContent = '';
    } catch (error) { status.textContent = `设置读取失败：${error.message}`; }
    finally { busy(false); if (!config) form.querySelector('[type="submit"]').disabled = true; }
  });
  fields.provider.addEventListener('change', () => {
    if (!config) return;
    if (fields.model.value !== config.providers[provider].model || fields.api_key.value) drafts.set(provider, {model: fields.model.value, key: fields.api_key.value});
    else drafts.delete(provider);
    show(fields.provider.value);
  });
  dialog.addEventListener('cancel', event => { if (!close()) event.preventDefault(); });
  dialog.querySelectorAll('[data-model-close]').forEach(control => control.addEventListener('click', close));
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (saving || !config) return;
    const payload = {provider, model: fields.model.value.trim(), api_key: fields.api_key.value.trim(), daily_tokens: Number(fields.daily_tokens.value)};
    busy(true); status.textContent = '正在保存…';
    try {
      config = await api('/api/v1/workbench/model-settings', {method: 'PUT', body: JSON.stringify(payload)});
      drafts.delete(provider); show(provider); original = signature();
      status.textContent = '已保存。重新查询功能说明后生效；已有手工修订会保留。';
    } catch (error) { status.textContent = `保存失败：${error.message}`; }
    finally { busy(false); }
  });
})();
