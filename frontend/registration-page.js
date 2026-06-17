function syncReagentStorageFields(form = $('reagentForm')) {
  if (!form) return;
  const isConsumed = form.elements.status.value === STATUS_CONSUMED || Number(form.elements.quantity.value || 0) <= 0;
  const storageField = form.elements.storage_node_id;
  const positionField = form.elements.grid_cell;
  const note = form.dataset.reagentFormMode === 'edit' ? $('reagentEditStorageState') : $('reagentStorageState');
  if (isConsumed) {
    storageField.value = '';
    positionField.innerHTML = '<option value="">位置将释放</option>';
  } else if (!positionField.options.length || positionField.options[0].textContent === '位置将释放') {
    fillPositionSelect(positionField, storageField.value);
  }
  storageField.disabled = isConsumed;
  positionField.disabled = isConsumed;
  form.classList.toggle('consumed-reagent', isConsumed);
  if (note) note.textContent = isConsumed ? '保存后释放存放位置，试剂记录和验证结果继续保留。' : '';
}

const ANTIBODY_FIELDS = ['target', 'conjugate', 'react_species', 'host_species', 'clone', 'isotype', 'aliases', 'raw_note'];
const ANTIBODY_CONJUGATE_HELP = '间接法未偶联一抗填 Unlabeled；二抗填实际标记，如 HRP、AF488。';

function isAntibodyCategory(value) {
  return /抗体|antibody/i.test(String(value || '').trim());
}

function applyAntibodyNamePrefix(value) {
  const text = String(value || '').trim();
  if (!text) return '';
  return /^抗|^anti[-\s]?/i.test(text) ? text : `抗${text}`;
}

function antibodyNameFromForm(form, { requireComplete = false } = {}) {
  const target = String(form?.elements.antibody_target?.value || '').trim();
  const conjugate = String(form?.elements.antibody_conjugate?.value || '').trim();
  if (!target || !conjugate) {
    if (requireComplete) throw new Error('抗体必须填写靶标和颜色');
    return '';
  }
  return `抗${target}-${conjugate}`;
}

function syncAntibodyNameField(form) {
  if (!form?.elements.name) return;
  const isAntibody = isAntibodyCategory(form.elements.category?.value);
  const nameInput = form.elements.name;
  nameInput.readOnly = isAntibody;
  nameInput.classList.toggle('readonly-field', isAntibody);
  nameInput.placeholder = isAntibody ? '由靶标和颜色自动生成' : '';
  nameInput.title = isAntibody ? '抗体名称固定为“抗靶标-颜色”' : '';
  if (isAntibody) nameInput.value = antibodyNameFromForm(form);
}

function syncAntibodySection(form) {
  if (!form) return;
  const section = form.querySelector('[data-antibody-section]');
  if (!section) return;
  const conjugateInput = form.elements.antibody_conjugate;
  if (conjugateInput) {
    conjugateInput.placeholder = 'APC / HRP / Unlabeled';
    conjugateInput.title = ANTIBODY_CONJUGATE_HELP;
  }
  let conjugateGuide = section.querySelector('[data-antibody-conjugate-guide]');
  if (!conjugateGuide) {
    conjugateGuide = document.createElement('p');
    conjugateGuide.className = 'form-note';
    conjugateGuide.dataset.antibodyConjugateGuide = '1';
    const metadataNote = section.querySelector('.form-note');
    if (metadataNote) metadataNote.insertAdjacentElement('beforebegin', conjugateGuide);
    else section.appendChild(conjugateGuide);
  }
  conjugateGuide.textContent = ANTIBODY_CONJUGATE_HELP;
  const show = isAntibodyCategory(form.elements.category?.value);
  section.classList.toggle('hidden', !show);
  section.querySelectorAll('input, textarea, select, button').forEach(input => {
    input.disabled = !show;
  });
  syncAntibodyNameField(form);
}

function clearAntibodyForm(form) {
  if (!form) return;
  ANTIBODY_FIELDS.forEach(field => {
    const input = form.elements[`antibody_${field}`];
    if (input) input.value = '';
  });
}

function setAntibodyFormValues(form, item = {}) {
  if (!form) return;
  ANTIBODY_FIELDS.forEach(field => {
    const input = form.elements[`antibody_${field}`];
    if (input) input.value = item?.[field] ?? '';
  });
  syncAntibodyNameField(form);
}

function normalizeOptionText(value) {
  return String(value || '').trim().toLowerCase().replace(/[\s_\-.,，。()（）]+/g, '');
}

function matchedExistingOption(value, options = []) {
  const text = normalizeOptionText(value);
  if (!text) return '';
  return options.find(option => normalizeOptionText(option) === text) || '';
}

function preferredOptionValue(value, options = [], { fallback = '' } = {}) {
  return matchedExistingOption(value, options) || String(value || '').trim() || fallback;
}

function ensureBrandSaveOptionRows() {
  ['orderForm', 'reagentForm', 'reagentEditForm'].forEach(formId => {
    const form = $(formId);
    const brandInput = form?.elements.brand;
    if (!form || !brandInput) return;
    if (!form.querySelector('[data-save-brand-option-row]')) {
      const row = document.createElement('label');
      row.className = 'check-row full hidden';
      row.setAttribute('data-save-brand-option-row', '');
      row.innerHTML = '<span>保存为常用公司<small>之后会出现在品牌/厂家候选中。</small></span><input name="save_brand_option" type="checkbox" />';
      brandInput.closest('label')?.insertAdjacentElement('afterend', row);
    }
    if (form.dataset.brandSaveOptionWired === '1') return;
    form.dataset.brandSaveOptionWired = '1';
    brandInput.addEventListener('input', () => syncBrandSaveOptionRow(form));
    brandInput.addEventListener('change', () => syncBrandSaveOptionRow(form));
    form.addEventListener('reset', () => setTimeout(() => syncBrandSaveOptionRow(form), 0));
  });
  syncAllBrandSaveOptionRows();
}

function syncBrandSaveOptionRow(form) {
  const row = form?.querySelector('[data-save-brand-option-row]');
  const input = form?.elements.save_brand_option;
  const brand = String(form?.elements.brand?.value || '').trim();
  if (!row || !input) return;
  const key = normalizeOptionText(brand);
  const isNewBrand = Boolean(key && !matchedExistingOption(brand, currentOptions('brands')));
  row.classList.toggle('hidden', !isNewBrand);
  input.disabled = !isNewBrand;
  if (!isNewBrand) {
    input.checked = false;
    input.dataset.brandOptionKey = '';
    return;
  }
  if (input.dataset.brandOptionKey !== key) {
    input.checked = false;
    input.dataset.brandOptionKey = key;
  }
}

function syncAllBrandSaveOptionRows() {
  ['orderForm', 'reagentForm', 'reagentEditForm'].forEach(formId => syncBrandSaveOptionRow($(formId)));
}

function applyReturnedOptions(result = {}) {
  if (!result?.options) return;
  state.options = result.options;
  fillDatalist($('brandOptions'), currentOptions('brands'));
  syncAllBrandSaveOptionRows();
  if (typeof fillSettingsForms === 'function') fillSettingsForms();
}

function setSelectFromExistingOptions(select, value, { fallback = '' } = {}) {
  if (!select) return '';
  const options = [...select.options].map(option => option.value).filter(Boolean);
  const matched = matchedExistingOption(value, options);
  const next = matched || (fallback && options.includes(fallback) ? fallback : '');
  if (next) select.value = next;
  return next;
}

function aiExtractPayload(form, text) {
  const context = form?.id === 'orderForm' ? 'order' : 'reagent';
  return {
    text,
    form_context: context,
    categories: currentOptions('categories'),
    brands: currentOptions('brands'),
    amount_units: currentOptions('amount_units'),
    antibody_conjugates: currentOptions('antibody_conjugates'),
    antibody_react_species: currentOptions('antibody_react_species'),
    antibody_host_species: currentOptions('antibody_host_species'),
    antibody_isotypes: currentOptions('antibody_isotypes'),
  };
}

function setNumericField(input, value) {
  if (!input || value === null || value === undefined || value === '') return;
  input.value = value;
}

async function warnExistingCatalogFromAi(form, catalogNo) {
  const catalog = String(catalogNo || '').trim();
  if (!catalog) return null;
  const params = new URLSearchParams({ catalog_no: catalog });
  const excludeId = String(form?.elements.id?.value || '').trim();
  if (excludeId) params.set('exclude_id', excludeId);
  const usage = await api(`/api/inventory/catalog-usage?${params}`);
  if (!usage.has_existing) return usage;
  const examples = (usage.items || []).slice(0, 3).map(item => `${item.code || item.id} ${item.name || ''}`.trim()).filter(Boolean).join('；');
  const message = `AI 返回的货号“${catalog}”已有 ${usage.count} 条记录${examples ? `：${examples}` : ''}，请核对是否重复登记。`;
  toast(message);
  return { ...usage, warning_message: message };
}

function openAiExtractDialog(form) {
  if (!form) return;
  const dialog = $('aiExtractDialog');
  const input = $('aiExtractInput');
  const status = $('aiExtractStatus');
  if (!dialog || !input) return;
  dialog.dataset.formId = form.id;
  input.value = '';
  if (status) status.textContent = '';
  dialog.classList.remove('hidden');
  dialog.setAttribute('aria-hidden', 'false');
  setTimeout(() => input.focus(), 0);
}

function closeAiExtractDialog() {
  const dialog = $('aiExtractDialog');
  const status = $('aiExtractStatus');
  if (!dialog) return;
  dialog.classList.add('hidden');
  dialog.setAttribute('aria-hidden', 'true');
  delete dialog.dataset.formId;
  if (status) status.textContent = '';
}

function applyReagentExtractionToForm(form, result = {}) {
  if (!form) return;
  const item = result.item || {};
  if (item.name && !isAntibodyCategory(item.category)) form.elements.name.value = item.name;
  const category = setSelectFromExistingOptions(form.elements.category, item.category, { fallback: currentOptions('categories').includes('其他') ? '其他' : '' });
  form.elements.brand.value = preferredOptionValue(item.brand, currentOptions('brands'));
  if (item.catalog_no) form.elements.catalog_no.value = item.catalog_no;
  setNumericField(form.elements.amount, item.amount);
  if (item.amount_unit) form.elements.amount_unit.value = preferredOptionValue(item.amount_unit, currentOptions('amount_units'));
  setNumericField(form.elements.quantity, item.quantity);
  setNumericField(form.elements.price, item.price);
  if (form.elements.reason && item.reason) form.elements.reason.value = item.reason;
  if (form.elements.note && item.note) form.elements.note.value = item.note;
  const shouldShowAntibody = result.is_antibody || category === '抗体';
  if (shouldShowAntibody && currentOptions('categories').includes('抗体')) {
    form.elements.category.value = '抗体';
    setAntibodyFormValues(form, result.antibody || {});
    form.dataset.antibodyAiSuggested = '1';
  }
  syncAntibodySection(form);
  syncAntibodyNameField(form);
  syncBrandSaveOptionRow(form);
  if (form.id === 'reagentForm') {
    syncReagentStorageFields(form);
    syncMultiRegisterFields(form);
  }
  const warnings = Array.isArray(result.warnings) ? result.warnings.filter(Boolean) : [];
  const confidence = Number(result.confidence || 0);
  const confidenceText = confidence > 0 ? `，置信度 ${Math.round(confidence * 100)}%` : '';
  toast(warnings.length ? `AI 已提取试剂信息${confidenceText}，已填入表单，请核对：${warnings[0]}` : `AI 已提取试剂信息${confidenceText}，已填入表单，保存前请核对`);
}

async function extractReagentInfoForForm(form) {
  if (!form) return;
  const dialog = $('aiExtractDialog');
  const status = $('aiExtractStatus');
  const submitBtn = document.querySelector('[data-action="submit-ai-extract"]');
  const text = String($('aiExtractInput')?.value || '').trim();
  if (!String(text || '').trim()) {
    if (status) status.textContent = '请先输入试剂链接或描述。';
    return;
  }
  if (status) status.textContent = 'AI 正在提取，请稍等...';
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = '提取中...';
  }
  try {
    const result = await api('/api/reagents/ai-extract', {
      method: 'POST',
      body: JSON.stringify(aiExtractPayload(form, text)),
    });
    applyReagentExtractionToForm(form, result);
    const catalogWarning = await warnExistingCatalogFromAi(form, result.item?.catalog_no || form.elements.catalog_no?.value);
    if (status) {
      status.textContent = catalogWarning?.warning_message || `AI 已返回结果，已填入表单${result.source ? `（${result.source}）` : ''}。`;
    }
    form.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (!catalogWarning?.has_existing) setTimeout(closeAiExtractDialog, 600);
  } catch (error) {
    if (status) status.textContent = `AI 提取失败：${error.message || '请稍后重试'}`;
    throw error;
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = '开始提取';
    }
    if (dialog?.classList.contains('hidden')) {
      if (status) status.textContent = '';
    }
  }
}

async function loadAntibodyMetadataIntoForm(form) {
  if (!form || !isAntibodyCategory(form.elements.category?.value)) {
    clearAntibodyForm(form);
    if (form) {
      delete form.dataset.antibodyMetadataExists;
      delete form.dataset.antibodyMetadataCatalog;
    }
    syncAntibodySection(form);
    return null;
  }
  const catalogNo = String(form.elements.catalog_no?.value || '').trim();
  if (!catalogNo) {
    clearAntibodyForm(form);
    delete form.dataset.antibodyMetadataExists;
    delete form.dataset.antibodyMetadataCatalog;
    syncAntibodySection(form);
    return null;
  }
  const data = await api(`/api/antibody-metadata?catalog_no=${encodeURIComponent(catalogNo)}`);
  if (data.item) {
    setAntibodyFormValues(form, data.item);
    form.dataset.antibodyMetadataCatalog = catalogNo;
  } else if (form.dataset.antibodyMetadataExists === '1') {
    clearAntibodyForm(form);
    delete form.dataset.antibodyMetadataCatalog;
  }
  form.dataset.antibodyMetadataExists = data.item ? '1' : '0';
  syncAntibodySection(form);
  return data.item || null;
}

async function syncAntibodyCategoryOrCatalog(form) {
  syncAntibodySection(form);
  await loadAntibodyMetadataIntoForm(form);
}

function antibodyPayloadFromForm(form) {
  const payload = {};
  ANTIBODY_FIELDS.forEach(field => {
    payload[field] = String(form.elements[`antibody_${field}`]?.value || '').trim();
  });
  return payload;
}

function hasAntibodyPayload(payload = {}) {
  return ANTIBODY_FIELDS.some(field => String(payload[field] || '').trim());
}

async function saveAntibodyMetadataFromForm(form, catalogNo) {
  if (!form || !isAntibodyCategory(form.elements.category?.value)) return;
  const cleanCatalog = String(catalogNo || '').trim();
  const payload = antibodyPayloadFromForm(form);
  if (!cleanCatalog) throw new Error('填写抗体信息时必须填写货号');
  const existing = await api(`/api/antibody-metadata?catalog_no=${encodeURIComponent(cleanCatalog)}`);
  if (!existing.item && !hasAntibodyPayload(payload)) return;
  const path = `/api/antibody-metadata${existing.item ? `?catalog_no=${encodeURIComponent(cleanCatalog)}` : ''}`;
  await api(path, {
    method: existing.item ? 'PATCH' : 'POST',
    body: JSON.stringify(existing.item ? payload : { catalog_no: cleanCatalog, ...payload }),
  });
}

function generateAntibodyName(form) {
  if (!form) return;
  try {
    form.elements.name.value = antibodyNameFromForm(form, { requireComplete: true });
  } catch (err) {
    toast(err.message || '请先填写靶标和颜色');
    return;
  }
}

function stripAntibodyFields(data) {
  ANTIBODY_FIELDS
    .filter(field => !['target', 'conjugate'].includes(field))
    .forEach(field => { delete data[`antibody_${field}`]; });
}

function validateAntibodyMetadataForm(form, data, antibodyPayload) {
  if (isAntibodyCategory(data.category) && hasAntibodyPayload(antibodyPayload) && !String(data.catalog_no || '').trim()) {
    throw new Error('填写抗体信息时必须填写货号');
  }
}

async function submitOrder(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const data = formData(form);
  const antibodyPayload = antibodyPayloadFromForm(form);
  stripAntibodyFields(data);
  validateAntibodyMetadataForm(form, data, antibodyPayload);
  if (isAntibodyCategory(data.category)) {
    data.name = antibodyNameFromForm(form, { requireComplete: true });
  }
  if (!(await confirmCatalogNameConflict({ catalogNo: data.catalog_no, name: data.name }))) return;
  const result = await api('/api/orders', { method: 'POST', body: JSON.stringify(data) });
  applyReturnedOptions(result);
  if (isAntibodyCategory(data.category) && (hasAntibodyPayload(antibodyPayload) || form.dataset.antibodyMetadataExists === '1')) {
    await saveAntibodyMetadataFromForm(form, data.catalog_no);
  }
  resetForm(form);
  clearAntibodyForm(form);
  delete form.dataset.antibodyMetadataExists;
  setDefaultDropdownValues();
  syncBrandSaveOptionRow(form);
  toast('订购登记已保存');
  await loadRegistrationTab('orders');
}

async function loadReagentCache() {
  const keyword = $('validationReagentSearch')?.value.trim() || '';
  const data = await searchInventoryObjects({ type: 'reagent', keyword, available: true, limit: 80, purpose: 'validation' });
  state.reagents = data.items;
  fillSelectObjects(document.querySelector('#validationForm select[name="item_id"]'), state.reagents, {
    placeholder: '可选：选择参考试剂',
    label: r => inventoryObjectSelectLabel(r, 'reagent'),
  });
  return data;
}



async function loadOrdersCache() {
  const data = await api('/api/orders?purpose=form');
  state.orders = data.items;
  const pending = state.orders.filter(o => Number(o.arrival_count || 0) === 0 && o.status !== STATUS_DISABLED);
  fillSelectObjects(document.querySelector('#arrivalForm select[name="order_id"]'), pending, { placeholder: '请选择未到货订单', label: o => `${o.id} | ${o.name} | ${o.category || '其他'} | 数量 ${o.quantity || 1}` });
  renderArrivalSummary();
  return data;
}

async function loadOrders() {
  setDefaultDropdownValues();
  await loadRepeatOrderCandidates();
}

async function loadOrdersHistory() {
  const data = await api('/api/orders');
  $('historyOrderCount').textContent = `${data.count} 条`;
  renderPagedTable('historyOrderTable', [
    { key: 'name', label: '名称' },
    { key: 'category', label: '类型', render: badge },
    { key: 'brand', label: '品牌' },
    { key: 'catalog_no', label: '货号' },
    { key: 'amount', label: '规格', render: (_, r) => amountText(r) },
    { key: 'quantity', label: '订购数量' },
    { key: 'price', label: '价格' },
    { key: 'arrival_status', label: '到货信息', render: (_, r) => renderOrderArrivalLedger(r) },
    { key: 'requester_name', label: '订购人' },
    { key: 'created_at', label: '订购时间' },
    { key: 'updated_at', label: '更新时间' },
  ], data.items, { pageSize: 20 });
}

function compactLedgerText(value) {
  const parts = String(value || '').split('、').map(part => part.trim()).filter(Boolean);
  return [...new Set(parts)].join('、');
}

function ledgerLine(label, value) {
  const text = compactLedgerText(value);
  return text ? `<small><b>${esc(label)}</b>${esc(text)}</small>` : '';
}

function renderOrderArrivalLedger(row = {}) {
  const hasArrival = Number(row.arrival_count || 0) > 0;
  const lines = hasArrival ? [
    ledgerLine('已到数量', row.arrived_quantity || row.arrival_count),
    ledgerLine('库存编号', row.arrival_codes),
    ledgerLine('位置', row.arrival_locations),
    ledgerLine('入库日期', row.arrival_entry_dates),
    ledgerLine('有效期', row.arrival_expiration_dates),
    ledgerLine('到货人', row.received_by_names),
  ].filter(Boolean).join('') : '<small>尚未登记到货</small>';
  return `<div class="ledger-cell">${badge(row.arrival_status || '未到货')}${lines}</div>`;
}

function repeatOrderKey(item) {
  return [
    item.name || '',
    item.category || '',
    item.brand || '',
    item.catalog_no || '',
    item.amount || '',
    item.amount_unit || '',
  ].map(value => String(value).trim().toLowerCase()).join('|');
}

function uniqueRepeatOrderItems(items = []) {
  const seen = new Set();
  return items.filter(item => {
    const key = repeatOrderKey(item);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function repeatOrderLabel(item) {
  const parts = [
    item.name || item.code || '试剂',
    item.brand || '',
    item.catalog_no || '',
    amountText(item) === '-' ? '' : amountText(item),
  ].filter(Boolean);
  return parts.join(' | ');
}

function selectedRepeatOrderItem() {
  const select = $('repeatOrderSelect');
  return state.repeatOrderItems.find(item => Number(item.id) === Number(select?.value));
}

function repeatOrderPrice(item = {}) {
  return item.price ?? '';
}

function renderRepeatOrderSummary() {
  const summaryBox = $('repeatOrderSummary');
  if (!summaryBox) return;
  const item = selectedRepeatOrderItem();
  summaryBox.innerHTML = item
    ? `<b>${esc(item.name || item.code || '试剂')}</b><span>${esc(item.category || '其他')} · ${esc(item.brand || '无品牌')} · ${esc(item.catalog_no || '无货号')} · ${amountText(item)} · 价格 ${orderPriceText(repeatOrderPrice(item))}</span>`
    : '<span>选择已有试剂后，可带入名称、类型、品牌、货号、规格和价格。</span>';
}

async function loadRepeatOrderCandidates() {
  const select = $('repeatOrderSelect');
  if (!select) return { items: [], count: 0 };
  const keyword = $('repeatOrderSearch')?.value.trim() || '';
  const data = await searchInventoryObjects({ type: 'reagent', keyword, available: false, limit: 80, purpose: 'form' });
  state.repeatOrderItems = uniqueRepeatOrderItems(data.items);
  fillSelectObjects(select, state.repeatOrderItems, { placeholder: '请选择已有试剂', label: repeatOrderLabel });
  renderRepeatOrderSummary();
  return { ...data, items: state.repeatOrderItems, count: state.repeatOrderItems.length };
}

function setOrderCategory(form, category) {
  const select = form.elements.category;
  const value = category || '';
  if (value && ![...select.options].some(option => option.value === value)) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  }
  select.value = value;
}

function fillOrderFromRepeatItem() {
  const item = selectedRepeatOrderItem();
  if (!item) {
    toast('请选择已有试剂');
    return;
  }
  const form = $('orderForm');
  setFormValues(form, {
    name: item.name || '',
    brand: item.brand || '',
    catalog_no: item.catalog_no || '',
    amount: item.amount ?? '',
    amount_unit: item.amount_unit || '',
    quantity: 1,
    price: repeatOrderPrice(item),
    reason: form.elements.reason.value || '再次订购',
  });
  setOrderCategory(form, item.category || '');
  syncAntibodySection(form);
  syncBrandSaveOptionRow(form);
  void loadAntibodyMetadataIntoForm(form);
  if (!isAntibodyCategory(form.elements.category?.value)) form.elements.name.focus();
  toast('已带入订购登记');
}

async function startRepeatOrderFromItem(item = {}) {
  if (!item?.id) return;
  activateView('registration');
  setRegistrationTab('orders', false);
  await loadRegistrationTab('orders');
  const form = $('orderForm');
  setFormValues(form, {
    name: item.name || '',
    brand: item.brand || '',
    catalog_no: item.catalog_no || '',
    amount: item.amount ?? '',
    amount_unit: item.amount_unit || '',
    quantity: 1,
    price: repeatOrderPrice(item),
    reason: '再次订购',
  });
  setOrderCategory(form, item.category || '');
  syncAntibodySection(form);
  syncBrandSaveOptionRow(form);
  await loadAntibodyMetadataIntoForm(form);
  $('repeatOrderSearch').value = item.catalog_no || item.name || '';
  renderRepeatOrderSummary();
  if (!isAntibodyCategory(form.elements.category?.value)) form.elements.name.focus();
  toast('已带入订购登记');
}

function renderArrivalSummary() {
  const form = $('arrivalForm');
  if (!form) return;
  const order = state.orders.find(o => Number(o.id) === Number(form.elements.order_id.value));
  if (order && form.elements.arrival_quantity) {
    const orderChanged = form.dataset.orderId !== String(order.id);
    if (orderChanged || !form.elements.arrival_quantity.value) {
      form.elements.arrival_quantity.value = Math.max(1, Math.floor(Number(order.quantity || 1)));
    }
    form.dataset.orderId = String(order.id);
  }
  $('arrivalOrderSummary').innerHTML = order ? `<b>${esc(order.name)}</b><span>${esc(order.category || '其他')} · ${esc(order.brand || '无品牌')} · ${esc(order.catalog_no || '无货号')} · ${amountText(order)} · 数量 ${esc(order.quantity)}</span>` : '<span>选择订购登记后会显示订购摘要。</span>';
  syncMultiRegisterFields(form);
}

async function loadArrivalForm() {
  await loadOrdersCache();
  await loadStorageTree();
  fillPositionSelect(document.querySelector('#arrivalForm select[name="grid_cell"]'), document.querySelector('#arrivalForm select[name="storage_node_id"]').value);
  await loadLocationPicker('arrival');
}

async function loadArrivals() {
  return loadArrivalForm();
}

async function loadValidationForm() {
  await loadReagentCache();
}

async function loadValidations() {
  return loadValidationForm();
}

async function loadValidationsHistory() {
  const data = await api('/api/validations');
  state.validations = data.items;
  $('historyValidationCount').textContent = `${data.count} 条`;
  renderPagedTable('historyValidationTable', [
    { key: 'code', label: '编号' }, { key: 'name', label: '名称' }, { key: 'catalog_no', label: '货号' }, { key: 'validation_date', label: '日期' }, { key: 'method', label: '方法' }, { key: 'result', label: '结果', render: badge }, { key: 'validator_name', label: '验证人' }, { key: 'image_path', label: '图片' }, { key: 'description', label: '说明' },
  ], data.items, { pageSize: 20 });
}

async function loadCheckoutsHistory() {
  const data = await api('/api/checkouts');
  $('historyCheckoutCount').textContent = `${data.count} 条`;
  renderPagedTable('historyCheckoutTable', [
    { key: 'object_type', label: '类型' },
    { key: 'object_id', label: '编号' },
    { key: 'from_location', label: '原位置', render: v => esc(locationText(v)) },
    { key: 'moved_by_name', label: '登记人' },
    { key: 'moved_at', label: '时间' },
    { key: 'reason', label: '原因' },
    { key: 'note', label: '备注' },
  ], data.items, { pageSize: 20 });
}

async function loadMovementsHistory() {
  const data = await api('/api/movements');
  $('historyMovementCount').textContent = `${data.count} 条`;
  renderPagedTable('historyMovementTable', [
    { key: 'object_type', label: '类型' },
    { key: 'object_id', label: '编号' },
    { key: 'from_location', label: '原位置', render: v => esc(locationText(v)) },
    { key: 'to_location', label: '新位置', render: v => esc(locationText(v)) },
    { key: 'moved_by_name', label: '登记人' },
    { key: 'moved_at', label: '时间' },
    { key: 'reason', label: '原因' },
    { key: 'note', label: '备注' },
  ], data.items, { pageSize: 20 });
}

async function startNewReagent(options = {}) {
  const refreshPicker = options?.refreshPicker !== false;
  const form = $('reagentForm');
  resetForm(form);
  clearAntibodyForm(form);
  delete form.dataset.antibodyMetadataExists;
  $('reagentFormTitle').textContent = '试剂入库';
  $('reagentCodePreview').textContent = '保存后由系统自动生成';
  setDefaultDropdownValues();
  syncAntibodySection(form);
  syncBrandSaveOptionRow(form);
  fillPositionSelect(form.elements.grid_cell, form.elements.storage_node_id.value);
  syncReagentStorageFields(form);
  syncMultiRegisterFields(form);
  if (refreshPicker) await loadLocationPicker('reagent');
}

function resetReagentEditForm() {
  const form = $('reagentEditForm');
  if (!form) return;
  resetForm(form);
  clearAntibodyForm(form);
  delete form.dataset.antibodyMetadataExists;
  $('reagentEditTitle').textContent = '编辑试剂';
  $('reagentEditCodePreview').textContent = '请先选择已有试剂';
  $('reagentEditDetail').innerHTML = '<p class="muted">从空间总览或明细查询选择试剂后，在这里维护已有库存信息。</p>';
  syncAntibodySection(form);
  syncBrandSaveOptionRow(form);
  fillPositionSelect(form.elements.grid_cell, form.elements.storage_node_id.value);
  syncReagentStorageFields(form);
}

async function editReagent(id) {
  const [data, timeline] = await Promise.all([
    api(inventoryObjectDetailPath('reagent', id)),
    loadInventoryTimeline('reagent', id),
  ]);
  const item = data.item;
  const form = $('reagentEditForm');
  $('reagentEditTitle').textContent = `编辑试剂：${item.code || item.id}`;
  $('reagentEditCodePreview').textContent = item.code || `ID ${item.id}`;
  setFormValues(form, item);
  syncAntibodySection(form);
  syncBrandSaveOptionRow(form);
  await loadAntibodyMetadataIntoForm(form);
  fillPositionSelect(form.elements.grid_cell, item.storage_node_id, item.grid_cell || '');
  syncReagentStorageFields(form);
  await loadLocationPicker('reagentEdit');
  await renderReagentDetail(data, timeline);
}

async function renderReagentDetail(data, timeline = null) {
  const target = $('reagentEditDetail');
  if (!target) return;
  const item = data.item;
  const actionButtons = inventoryActionButtons(item, 'reagent', { detail: false, editAction: '' });
  const actions = actionButtons ? `<div class="detail-actions">${actionButtons}</div>` : '';
  const aliquotText = reagentAliquotText(item);
  const orderEvents = await loadOrderHistoryEvents(item.catalog_no || '');
  target.innerHTML = `
    ${actions}
    <h4>${esc(item.code || item.id)} · ${esc(item.name)}</h4>
    <div class="detail-grid"><span>来源：${esc(item.source_code || item.code || '-')}</span><span>货号：${esc(item.catalog_no || '-')}</span>${aliquotText ? `<span>管号：${esc(aliquotText)}</span>` : ''}<span>规格：${amountText(item)}</span><span>价格：${esc(orderPriceText(item.price))}</span><span>类型：${esc(item.category)}</span><span>状态：${esc(item.status)}</span><span>验证：${esc(item.validation_status)}</span><span>位置：${esc(locationText(item.storage_location))}</span><span>备注：${esc(item.note || '-')}</span></div>
    ${renderAntibodyMetadataBlock(data)}
    <div class="detail-timeline-stack">
      ${detailTimelineModule('时间线', timeline?.items || [], { open: true, actions: timelineEventActions })}
      ${detailTimelineModule('历史订购', orderEvents, { open: false })}
      ${detailTimelineModule('验证记录', validationDetailEvents(data.validations || []), { open: false, count: (data.validations || []).length, actions: validationEventActions })}
    </div>
  `;
}

async function loadSampleForm() {
  setDefaultDropdownValues();
  await loadStorageTree();
  fillPositionSelect(document.querySelector('#sampleForm select[name="grid_cell"]'), document.querySelector('#sampleForm select[name="storage_node_id"]').value);
  syncMultiRegisterFields($('sampleForm'));
  await loadLocationPicker('sample');
}

async function loadSamples() {
  return loadSampleForm();
}

function syncAliquotFields() {
  const form = $('aliquotForm');
  if (!form) return 'sample';
  if (state.aliquotItemType && optionExists(form.elements.item_type, state.aliquotItemType)) {
    form.elements.item_type.value = state.aliquotItemType;
  }
  syncInventoryTypeSelect(form.elements.item_type);
  const type = firstVisibleInventoryType(form.elements.item_type.value || 'sample');
  form.elements.item_type.value = type;
  state.aliquotItemType = type;
  document.querySelectorAll('[data-aliquot-reagent-field]').forEach(el => el.classList.toggle('hidden', type !== 'reagent'));
  const search = $('aliquotSourceSearch');
  if (search) search.placeholder = type === 'sample'
    ? '系统编号 / 样本号 / 样本类型 / 位置'
    : '名称 / 编号 / 货号 / 品牌 / 位置';
  return type;
}

function selectedAliquotSourceItem() {
  const form = $('aliquotForm');
  if (!form) return null;
  return state.aliquotCandidates.find(item => Number(item.id) === Number(form.elements.source_item_id.value)) || null;
}

function renderAliquotSourceSummary() {
  const summaryBox = $('aliquotSourceSummary');
  if (!summaryBox) return;
  const item = selectedAliquotSourceItem();
  if (!item) {
    summaryBox.innerHTML = '';
    return;
  }
  const code = inventoryObjectCode(item, item.item_type);
  const name = inventoryObjectName(item, item.item_type, '-');
  const position = locationText(item.storage_location);
  const wellText = item.grid_cell
    ? `来源孔位：${esc(item.grid_cell)}；带入后会以该孔位为起点寻找空位。`
    : '来源没有具体孔位；带入后会使用同一空间。';
  summaryBox.innerHTML = `
    <div class="source-location-head">
      <b>${esc(code)} · ${esc(name)}</b>
      <button class="ghost mini-btn" type="button" data-action="aliquot-use-source-location">带入来源位置</button>
    </div>
    <div class="source-location-meta">
      <span>当前位置：${esc(position)}</span>
      <span>${item.storage_node_id ? wellText : '来源当前未归位；带入后新分装也会暂存为未归位。'}</span>
    </div>
  `;
}

async function loadAliquotCandidates({ explicitId = null } = {}) {
  const type = syncAliquotFields();
  if (!canViewInventoryType(type)) {
    state.aliquotCandidates = [];
    fillSelectObjects(document.querySelector('#aliquotForm select[name="source_item_id"]'), [], { placeholder: '当前账号没有可查看的来源库存' });
    renderAliquotSourceSummary();
    return { items: [], count: 0 };
  }
  const keyword = $('aliquotSourceSearch')?.value.trim() || '';
  const data = await searchInventoryObjects({ type, keyword, available: true, explicitId, limit: 80, purpose: 'aliquot' });
  state.aliquotCandidates = data.items;
  fillSelectObjects(document.querySelector('#aliquotForm select[name="source_item_id"]'), state.aliquotCandidates, {
    placeholder: type === 'sample' ? '请选择已有标本' : '请选择试剂',
    label: item => inventoryObjectSelectLabel(item, type),
  });
  if (explicitId && optionExists(document.querySelector('#aliquotForm select[name="source_item_id"]'), explicitId)) {
    document.querySelector('#aliquotForm select[name="source_item_id"]').value = explicitId;
  }
  renderAliquotSourceSummary();
  fillPositionSelect(document.querySelector('#aliquotForm select[name="grid_cell"]'), document.querySelector('#aliquotForm select[name="storage_node_id"]').value);
  await loadLocationPicker('aliquot');
  return data;
}

async function useAliquotSourceLocation() {
  const form = $('aliquotForm');
  const item = selectedAliquotSourceItem();
  if (!form || !item) {
    toast('请先选择来源库存');
    return;
  }
  const nodeId = isRealStorageNodeId(item.storage_node_id) ? String(item.storage_node_id) : '';
  const startPosition = nodeId ? String(item.grid_cell || '') : '';
  form.elements.storage_node_id.value = nodeId;
  fillPositionSelect(form.elements.grid_cell, nodeId, startPosition);
  form.elements.grid_cell.value = startPosition;
  await loadLocationPicker('aliquot');
  toast(nodeId ? '已带入来源位置，可按需改到其他空位' : '已设为未归位');
}

function renderSampleDetail(data) {
  const detail = $('sampleDetail') || $('inventoryDetail');
  if (!detail) return;
  const item = data.item;
  const specText = amountText(item);
  const sourceText = item.code || '-';
  const tubeText = sampleTubeText(item) || '-';
  const aliquotAction = canManageInventory() && canViewSamples() && inventoryObjectAvailable(item, 'sample')
    ? actionButton('分装', 'sample-row-aliquot', item.id)
    : '';
  const actionButtons = [inventoryActionButtons(item, 'sample', { detail: false }), aliquotAction].filter(Boolean).join(' ');
  const actions = actionButtons ? `<div class="detail-actions">${actionButtons}</div>` : '';
  detail.innerHTML = `
    ${actions}
    <h4>${esc(sourceText)} · ${esc(item.name)}</h4>
    <div class="detail-grid"><span>系统编号：${esc(sourceText)}</span><span>样本号：${esc(item.name || '-')}</span><span>样本类型：${esc(item.category || '-')}</span><span>管号：${esc(tubeText)}</span><span>状态：${esc(item.status)}</span><span>规格：${specText}</span><span>入库日期：${esc(item.entry_date)}</span><span>位置：${esc(locationText(item.storage_location))}</span><span>备注：${esc(item.note || '-')}</span></div>
  `;
}

function sampleNameFromEntry(data) {
  const prefix = String(data.code_prefix || '').trim();
  const sampleNumber = String(data.sample_number || '').trim();
  const sampleName = prefix && sampleNumber ? `${prefix}${sampleNumber}` : (prefix || sampleNumber);
  if (!sampleName) throw new Error('样本号不能为空');
  return sampleName;
}

async function loadRegistrationTab(tab = state.registrationTab) {
  setLoggedIn(Boolean(state.token && state.user));
  if (tab === 'orders') await loadOrders();
  if (tab === 'arrivals') await loadArrivals();
  if (tab === 'validations') await loadValidations();
  if (tab === 'reagents') {
    const form = $('reagentForm');
    if (!form.elements.id.value) await startNewReagent();
    else {
      syncAntibodySection(form);
      fillPositionSelect(form.elements.grid_cell, form.elements.storage_node_id.value, form.elements.grid_cell.value);
      syncReagentStorageFields(form);
      await loadLocationPicker('reagent');
    }
  }
  if (tab === 'samples') await loadSamples();
}

async function loadHistory() {
  setLoggedIn(Boolean(state.token && state.user));
  setWorkbenchTab('history', state.historyTab, false);
  await loadHistoryTab(state.historyTab);
}

async function loadHistoryTab(tab = state.historyTab) {
  if (tab === 'orders') await loadOrdersHistory();
  if (tab === 'validations') await loadValidationsHistory();
  if (tab === 'checkouts') await loadCheckoutsHistory();
  if (tab === 'movements') await loadMovementsHistory();
}

async function loadRegistration() {
  setRegistrationTab(state.registrationTab, false);
  await loadRegistrationTab(state.registrationTab);
}

async function submitValidation(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const data = formData(form);
  const id = data.id;
  const reagent = state.reagents.find(r => Number(r.id) === Number(data.item_id));
  if (!data.catalog_no && reagent?.catalog_no) data.catalog_no = reagent.catalog_no;
  const file = form.elements.image_file.files[0];
  if (data.method === '其他' && data.method_other) data.method = data.method_other;
  if (file) {
    const uploaded = await api('/api/uploads/validation-image', { method: 'POST', body: JSON.stringify({ data_url: await fileToDataUrl(file), code: reagent?.code || data.catalog_no || 'catalog', method: data.method, validation_date: data.validation_date }) });
    data.image_path = uploaded.path;
  } else if (id) {
    data.image_path = form.dataset.imagePath || '';
  }
  delete data.id;
  delete data.item_id;
  delete data.method_other;
  delete data.image_file;
  await api(id ? `/api/validations/${id}` : '/api/validations', { method: id ? 'PATCH' : 'POST', body: JSON.stringify(data) });
  resetValidationForm();
  toast(id ? '验证记录已更新' : '验证记录已保存');
  await loadRegistrationTab('validations');
  if (state.historyTab === 'validations') await loadValidationsHistory();
}

function canEditValidation(item) {
  return isAdmin() || Number(item?.validator_id) === Number(state.user?.id);
}

async function editValidation(id) {
  const data = state.validations.find(item => Number(item.id) === Number(id)) || (await api('/api/validations')).items.find(item => Number(item.id) === Number(id));
  if (!data) throw new Error('验证记录不存在');
  if (!canEditValidation(data)) throw new Error('只能编辑自己登记的验证记录');
  activateView('registration');
  setRegistrationTab('validations', false);
  await loadValidationForm();
  const form = $('validationForm');
  const method = String(data.method || '');
  const methodInOptions = [...form.elements.method.options].some(option => option.value === method);
  setFormValues(form, {
    id: data.id,
    catalog_no: data.catalog_no,
    validation_date: data.validation_date,
    method: methodInOptions ? method : '其他',
    method_other: methodInOptions ? '' : method,
    result: data.result,
    description: data.description,
  });
  form.dataset.imagePath = data.image_path || '';
  $('validationFormTitle').textContent = '编辑验证记录';
  $('validationFormHint').textContent = `记录 #${data.id} · ${data.validator_name || '验证人'}`;
  $('cancelValidationEditBtn')?.classList.remove('hidden');
  $('validationOtherLabel').classList.toggle('hidden', form.elements.method.value !== '其他');
  form.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function resetValidationForm() {
  const form = $('validationForm');
  if (!form) return;
  resetForm(form);
  delete form.dataset.imagePath;
  setDefaultDates();
  $('validationFormTitle').textContent = '验证登记';
  $('validationFormHint').textContent = '按货号记录验证结果';
  $('cancelValidationEditBtn')?.classList.add('hidden');
  $('validationOtherLabel').classList.add('hidden');
}

async function submitReagent(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const consumed = form.elements.status.value === STATUS_CONSUMED || Number(form.elements.quantity.value || 0) <= 0;
  if (consumed && form.elements.id.value && !confirm('确认把该试剂设为已耗尽？\n保存后会释放存放位置，但试剂和验证记录会继续保留。')) return;
  form.elements.storage_node_id.disabled = false;
  form.elements.grid_cell.disabled = false;
  const data = formData(form);
  const antibodyPayload = antibodyPayloadFromForm(form);
  stripAntibodyFields(data);
  try {
    validateAntibodyMetadataForm(form, data, antibodyPayload);
  } catch (err) {
    syncReagentStorageFields(form);
    throw err;
  }
  if (isAntibodyCategory(data.category)) {
    data.name = antibodyNameFromForm(form, { requireComplete: true });
  }
  if (consumed) {
    data.storage_node_id = '';
    data.grid_cell = '';
  }
  const id = data.id;
  delete data.id;
  delete data.code;
  if (!id && form.dataset.reagentFormMode === 'edit') {
    syncReagentStorageFields(form);
    throw new Error('请先从空间总览或库存明细中选择一个试剂进行编辑');
  }
  if (id) delete data.separate_items;
  if (!(await confirmCatalogNameConflict({ catalogNo: data.catalog_no, name: data.name, excludeId: id }))) {
    syncReagentStorageFields(form);
    return;
  }
  try {
    const result = id
      ? await api(inventoryObjectDetailPath('reagent', id), { method: 'PATCH', body: JSON.stringify(data) })
      : await api('/api/inventory/items', { method: 'POST', body: JSON.stringify({ ...data, item_type: 'reagent' }) });
    applyReturnedOptions(result);
    if (isAntibodyCategory(data.category) && (hasAntibodyPayload(antibodyPayload) || form.dataset.antibodyMetadataExists === '1')) {
      await saveAntibodyMetadataFromForm(form, data.catalog_no);
    }
    toast(!id && data.separate_items === false && Number(data.quantity || 1) > 1 ? `试剂已保存为 1 条记录，数量 ${data.quantity}` : (result?.count > 1 ? `已分别登记 ${result.count} 件试剂` : '试剂已保存'));
    if (id) {
      await editReagent(id);
    } else {
      await startNewReagent();
      await loadRegistrationTab('reagents');
    }
    if (state.inventoryTab === 'details') await searchInventory();
    if (state.view === 'inventory') await loadInventory();
  } finally {
    syncReagentStorageFields(form);
    syncBrandSaveOptionRow(form);
  }
}

async function submitSampleEdit(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const data = formData(form);
  const id = data.id;
  if (!id) throw new Error('请先从空间总览或库存明细中选择一个临床标本进行编辑');
  delete data.id;
  await api(inventoryObjectDetailPath('sample', id), { method: 'PATCH', body: JSON.stringify(data) });
  toast('临床标本已保存');
  await loadManualEditor();
  if (state.inventoryTab === 'details' || state.inventoryItemTypeFilter === 'sample') await searchInventory();
}

async function submitSample(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const data = formData(form);
  data.name = sampleNameFromEntry(data);
  data.quantity = 1;
  delete data.code_prefix;
  delete data.sample_number;
  const result = await api('/api/inventory/items', { method: 'POST', body: JSON.stringify({ ...data, item_type: 'sample' }) });
  resetForm(form);
  form.elements.tube_count.value = 1;
  setDefaultDates();
  setDefaultDropdownValues();
  syncMultiRegisterFields(form);
  toast(data.separate_items === false && Number(data.tube_count || 1) > 1 ? `临床标本已保存为 1 条记录，数量 ${data.tube_count}` : (result.count > 1 ? `${result.count} 支冻存管已入库` : '临床标本已入库'));
  await loadRegistrationTab('samples');
}

async function submitAliquot(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const result = await api('/api/aliquots', { method: 'POST', body: JSON.stringify(formData(form)) });
  form.elements.tube_count.value = 1;
  form.elements.quantity.value = '';
  form.elements.note.value = '';
  renderAliquotSourceSummary();
  toast(result.count > 1 ? `已新增 ${result.count} 支分装` : '分装已新增');
  await loadInventoryTab('aliquots');
  if (state.view === 'inventory') await loadInventory();
}
