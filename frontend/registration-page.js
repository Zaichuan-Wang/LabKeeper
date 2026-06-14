function syncReagentStorageFields(form = $('reagentForm')) {
  if (!form) return;
  const isConsumed = form.elements.status.value === STATUS_CONSUMED || Number(form.elements.quantity.value || 0) <= 0;
  const storageField = form.elements.storage_node_id;
  const positionField = form.elements.position_in_box;
  const note = $('reagentStorageState');
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
  const data = await api('/api/orders');
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
    { key: 'name', label: '名称' }, { key: 'category', label: '类型', render: badge }, { key: 'brand', label: '品牌' }, { key: 'catalog_no', label: '货号' }, { key: 'amount', label: '规格', render: (_, r) => amountText(r) }, { key: 'quantity', label: '数量' }, { key: 'price', label: '价格' }, { key: 'arrival_status', label: '到货', render: badge }, { key: 'requester_name', label: '登记人' }, { key: 'updated_at', label: '更新时间' }
  ], data.items, { pageSize: 20 });
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
    item.name || item.code || '试剂/耗材',
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

function renderRepeatOrderSummary() {
  const box = $('repeatOrderSummary');
  if (!box) return;
  const item = selectedRepeatOrderItem();
  box.innerHTML = item
    ? `<b>${esc(item.name || item.code || '试剂/耗材')}</b><span>${esc(item.category || '其他')} · ${esc(item.brand || '无品牌')} · ${esc(item.catalog_no || '无货号')} · ${amountText(item)}</span>`
    : '<span>选择已有试剂后，可带入名称、类型、品牌、货号和规格。</span>';
}

async function loadRepeatOrderCandidates() {
  const select = $('repeatOrderSelect');
  if (!select) return { items: [], count: 0 };
  const keyword = $('repeatOrderSearch')?.value.trim() || '';
  const data = await searchInventoryObjects({ type: 'reagent', keyword, available: false, limit: 80, purpose: 'form' });
  state.repeatOrderItems = uniqueRepeatOrderItems(data.items);
  fillSelectObjects(select, state.repeatOrderItems, { placeholder: '请选择已有试剂/耗材', label: repeatOrderLabel });
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
    toast('请选择已有试剂/耗材');
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
    price: '',
    reason: form.elements.reason.value || '再次订购',
  });
  setOrderCategory(form, item.category || '');
  form.elements.name.focus();
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
  fillPositionSelect(document.querySelector('#arrivalForm select[name="position_in_box"]'), document.querySelector('#arrivalForm select[name="storage_node_id"]').value);
  await loadLocationPicker('arrival');
}

async function loadArrivals() {
  return loadArrivalForm();
}

async function loadArrivalsHistory() {
  const data = await api('/api/arrivals');
  $('historyArrivalCount').textContent = `${data.count} 条`;
  renderPagedTable('historyArrivalTable', [
    { key: 'id', label: 'ID' }, { key: 'code', label: '编号' }, { key: 'name', label: '名称' }, { key: 'storage_location', label: '位置' }, { key: 'entry_date', label: '入库日期' }, { key: 'expiration_date', label: '有效期' }, { key: 'received_by_name', label: '登记人' }, { key: 'created_at', label: '时间' }
  ], data.items, { pageSize: 20 });
}

async function loadValidationForm() {
  await loadReagentCache();
}

async function loadValidations() {
  return loadValidationForm();
}

async function loadValidationsHistory() {
  const data = await api('/api/validations');
  $('historyValidationCount').textContent = `${data.count} 条`;
  renderPagedTable('historyValidationTable', [
    { key: 'code', label: '编号' }, { key: 'name', label: '名称' }, { key: 'catalog_no', label: '货号' }, { key: 'validation_date', label: '日期' }, { key: 'method', label: '方法' }, { key: 'result', label: '结果', render: badge }, { key: 'validator_name', label: '验证人' }, { key: 'image_path', label: '图片' }, { key: 'description', label: '说明' }
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
    { key: 'id', label: '操作', render: (_, r) => r.can_rollback && canManageLocation() ? actionButton('回滚', 'rollback-movement', r.id, 'danger') : '' },
    { key: 'object_id', label: '编号' },
    { key: 'from_location', label: '原位置', render: v => esc(locationText(v)) },
    { key: 'to_location', label: '新位置', render: v => esc(locationText(v)) },
    { key: 'moved_by_name', label: '登记人' },
    { key: 'moved_at', label: '时间' },
    { key: 'reason', label: '原因' },
    { key: 'note', label: '备注' },
  ], data.items, { pageSize: 20 });
}

async function rollbackMovement(id) {
  if (!id) return;
  if (!confirm(`确认回滚移动记录 #${id}？\n系统会把对象移回原位置；如果原位置已被占用，会拒绝回滚。`)) return;
  await api(`/api/movements/${id}/rollback`, { method: 'POST' });
  toast('已回滚移动记录');
  await loadMovementsHistory();
  if (state.view === 'inventory') await loadInventory();
  if (state.view === 'dashboard') await loadDashboard();
}

async function startNewReagent(options = {}) {
  const refreshPicker = options?.refreshPicker !== false;
  if (typeof setManualMode === 'function') setManualMode('reagent');
  const form = $('reagentForm');
  resetForm(form);
  $('reagentFormTitle').textContent = '新建试剂/耗材';
  setDefaultDropdownValues();
  fillPositionSelect(form.elements.position_in_box, form.elements.storage_node_id.value);
  syncReagentStorageFields(form);
  syncMultiRegisterFields(form);
  if (refreshPicker) await loadLocationPicker('reagent');
  $('reagentDetail').innerHTML = '';
}

async function editReagent(id) {
  const data = await api(inventoryObjectDetailPath('reagent', id));
  const item = data.item;
  $('reagentFormTitle').textContent = `编辑试剂：${item.code || item.id}`;
  setFormValues($('reagentForm'), item);
  fillPositionSelect($('reagentForm').elements.position_in_box, item.storage_node_id, item.position_in_box || '');
  syncReagentStorageFields($('reagentForm'));
  syncMultiRegisterFields($('reagentForm'));
  await loadLocationPicker('reagent');
  renderReagentDetail(data);
}

function renderReagentDetail(data) {
  const item = data.item;
  const actionButtons = inventoryActionButtons(item, 'reagent', { detail: false, editAction: '' });
  const actions = actionButtons ? `<div class="detail-actions">${actionButtons}</div>` : '';
  const aliquotText = reagentAliquotText(item);
  $('reagentDetail').innerHTML = `
    ${actions}
    <h4>${esc(item.code || item.id)} · ${esc(item.name)}</h4>
    <div class="detail-grid"><span>来源：${esc(item.source_code || item.code || '-')}</span><span>货号：${esc(item.catalog_no || '-')}</span>${aliquotText ? `<span>管号：${esc(aliquotText)}</span>` : ''}<span>规格：${amountText(item)}</span><span>类型：${esc(item.category)}</span><span>状态：${esc(item.status)}</span><span>验证：${esc(item.validation_status)}</span><span>位置：${esc(locationText(item.storage_location))}</span></div>
    <h4>验证记录</h4>${miniRows(data.validations, ['catalog_no', 'validation_date', 'method', 'result', 'description'])}
    <h4>到货记录</h4>${miniRows(data.arrivals, ['entry_date', 'storage_location', 'expiration_date'])}
    <h4>移动记录</h4>${miniRows(data.movements, ['from_location', 'to_location', 'moved_at', 'reason'])}
  `;
}

async function loadSampleForm() {
  setDefaultDropdownValues();
  await loadStorageTree();
  fillPositionSelect(document.querySelector('#sampleForm select[name="position_in_box"]'), document.querySelector('#sampleForm select[name="storage_node_id"]').value);
  syncMultiRegisterFields($('sampleForm'));
  await loadLocationPicker('sample');
}

async function loadSamples() {
  return loadSampleForm();
}

function syncAliquotFields() {
  const form = $('aliquotForm');
  if (!form) return 'sample';
  const type = inventoryObjectType(form.elements.item_type.value || 'sample');
  form.elements.item_type.value = type;
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
  const box = $('aliquotSourceSummary');
  if (!box) return;
  const item = selectedAliquotSourceItem();
  if (!item) {
    box.innerHTML = '';
    return;
  }
  const code = inventoryObjectCode(item, item.item_type);
  const name = inventoryObjectName(item, item.item_type, '-');
  const position = locationText(item.storage_location);
  const wellText = item.position_in_box
    ? `来源孔位：${esc(item.position_in_box)}；带入后会以该孔位为起点寻找空位。`
    : '来源没有具体孔位；带入后会使用同一空间。';
  box.innerHTML = `
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

async function loadAliquotCandidates() {
  const type = syncAliquotFields();
  const keyword = $('aliquotSourceSearch')?.value.trim() || '';
  const data = await searchInventoryObjects({ type, keyword, available: true, limit: 80, purpose: 'aliquot' });
  state.aliquotCandidates = data.items;
  fillSelectObjects(document.querySelector('#aliquotForm select[name="source_item_id"]'), state.aliquotCandidates, {
    placeholder: type === 'sample' ? '请选择已有标本' : '请选择试剂/耗材',
    label: item => inventoryObjectSelectLabel(item, type),
  });
  renderAliquotSourceSummary();
  fillPositionSelect(document.querySelector('#aliquotForm select[name="position_in_box"]'), document.querySelector('#aliquotForm select[name="storage_node_id"]').value);
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
  const nodeId = item.storage_node_id ? String(item.storage_node_id) : '';
  const startPosition = nodeId ? String(item.position_in_box || '') : '';
  form.elements.storage_node_id.value = nodeId;
  fillPositionSelect(form.elements.position_in_box, nodeId, startPosition);
  form.elements.position_in_box.value = startPosition;
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
  const actionButtons = inventoryActionButtons(item, 'sample', { detail: false });
  const actions = actionButtons ? `<div class="detail-actions">${actionButtons}</div>` : '';
  detail.innerHTML = `
    ${actions}
    <h4>${esc(sourceText)} · ${esc(item.name)}</h4>
    <div class="detail-grid"><span>系统编号：${esc(sourceText)}</span><span>样本号：${esc(item.name || '-')}</span><span>样本类型：${esc(item.category || '-')}</span><span>管号：${esc(tubeText)}</span><span>状态：${esc(item.status)}</span><span>规格：${specText}</span><span>入库日期：${esc(item.entry_date)}</span><span>位置：${esc(locationText(item.storage_location))}</span></div>
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
  if (tab === 'samples') await loadSamples();
  if (tab === 'aliquots') await loadAliquotCandidates();
}

async function loadHistory() {
  setLoggedIn(Boolean(state.token && state.user));
  setWorkbenchTab('history', state.historyTab, false);
  await loadHistoryTab(state.historyTab);
}

async function loadHistoryTab(tab = state.historyTab) {
  if (tab === 'orders') await loadOrdersHistory();
  if (tab === 'arrivals') await loadArrivalsHistory();
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
  const reagent = state.reagents.find(r => Number(r.id) === Number(data.item_id));
  if (!data.catalog_no && reagent?.catalog_no) data.catalog_no = reagent.catalog_no;
  const file = form.elements.image_file.files[0];
  if (data.method === '其他' && data.method_other) data.method = data.method_other;
  if (file) {
    const uploaded = await api('/api/uploads/validation-image', { method: 'POST', body: JSON.stringify({ data_url: await fileToDataUrl(file), code: reagent?.code || data.catalog_no || 'catalog', method: data.method, validation_date: data.validation_date }) });
    data.image_path = uploaded.path;
  }
  delete data.item_id;
  delete data.method_other;
  delete data.image_file;
  await api('/api/validations', { method: 'POST', body: JSON.stringify(data) });
  resetForm(form);
  setDefaultDates();
  toast('验证记录已保存');
  await loadRegistrationTab('validations');
}

async function submitReagent(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const consumed = form.elements.status.value === STATUS_CONSUMED || Number(form.elements.quantity.value || 0) <= 0;
  if (consumed && form.elements.id.value && !confirm('确认把该试剂/耗材设为已耗尽？\n保存后会释放存放位置，但试剂和验证记录会继续保留。')) return;
  form.elements.storage_node_id.disabled = false;
  form.elements.position_in_box.disabled = false;
  const data = formData(form);
  if (consumed) {
    data.storage_node_id = '';
    data.position_in_box = '';
  }
  const id = data.id;
  delete data.id;
  if (id) delete data.separate_items;
  if (!(await confirmCatalogNameConflict({ catalogNo: data.catalog_no, name: data.name, excludeId: id }))) {
    syncReagentStorageFields(form);
    return;
  }
  try {
    const result = id
      ? await api(inventoryObjectDetailPath('reagent', id), { method: 'PATCH', body: JSON.stringify(data) })
      : await api('/api/inventory/items', { method: 'POST', body: JSON.stringify({ ...data, item_type: 'reagent' }) });
    toast(!id && data.separate_items === false && Number(data.quantity || 1) > 1 ? `试剂已保存为 1 条记录，数量 ${data.quantity}` : (result?.count > 1 ? `已分别登记 ${result.count} 件试剂/耗材` : '试剂已保存'));
    await startNewReagent();
    await loadManualEditor();
    if (state.inventoryTab === 'details') await searchInventory();
  } finally {
    syncReagentStorageFields(form);
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
  await loadRegistrationTab('aliquots');
}
