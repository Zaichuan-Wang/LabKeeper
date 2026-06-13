function setManualMode(mode = 'reagent') {
  const cleanMode = mode === 'sample' ? 'sample' : 'reagent';
  state.manualMode = cleanMode;
  document.querySelectorAll('[data-manual-mode]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.manualMode === cleanMode);
    btn.setAttribute('aria-selected', btn.dataset.manualMode === cleanMode ? 'true' : 'false');
  });
  document.querySelectorAll('[data-manual-panel]').forEach(panel => {
    panel.classList.toggle('active-manual-pane', panel.dataset.manualPanel === cleanMode);
  });
}

async function openReagentEditor(id) {
  activateView('inventory');
  setInventoryTab('manual', false);
  setManualMode('reagent');
  await loadManualEditor();
  await editReagent(id);
}

async function openSampleEditor(id) {
  activateView('inventory');
  setInventoryTab('manual', false);
  setManualMode('sample');
  await loadManualEditor();
  const data = await api(inventoryObjectDetailPath('sample', id));
  const item = data.item;
  const form = $('sampleEditForm');
  $('sampleEditTitle').textContent = `编辑标本：${item.code || item.id}`;
  setFormValues(form, item);
  fillPositionSelect(form.elements.position_in_box, item.storage_node_id, item.position_in_box || '');
  await loadLocationPicker('sampleEdit');
}

function inventoryObjectSelectPlaceholder(type, action) {
  const itemType = inventoryObjectType(type);
  if (action === 'move') return itemType === 'sample' ? '请选择已入库临床标本' : '请选择已入库试剂';
  return itemType === 'sample' ? '请选择已入库标本' : '请选择已入库试剂';
}

async function fetchSelectableInventoryObjects(type, { keyword = '', explicitId = null } = {}) {
  const itemType = inventoryObjectType(type);
  const purpose = state.inventoryTab === 'move' ? 'movement' : (state.inventoryTab === 'checkout' ? 'checkout' : 'form');
  const data = await searchInventoryObjects({ type: itemType, keyword, available: true, explicitId, limit: 120, purpose });
  return data.items || [];
}

function syncInventoryObjectSelect(select, items, selectedId, placeholder, itemType) {
  fillSelectObjects(select, items, {
    placeholder,
    label: item => inventoryObjectSelectLabel(item, itemType),
  });
  if (selectedId && optionExists(select, selectedId)) select.value = selectedId;
  else if (select) select.value = '';
  return select?.value || null;
}

async function loadMoveItems() {
  const form = $('movementForm');
  if (!form) return;
  if (state.moveItemType && optionExists(form.elements.item_type, state.moveItemType)) {
    form.elements.item_type.value = state.moveItemType;
  }
  const type = inventoryObjectType(form.elements.item_type.value || state.moveItemType);
  const keyword = form.elements.keyword.value.trim();
  state.moveItemType = type;
  state.moveItems = await fetchSelectableInventoryObjects(type, { keyword, explicitId: state.moveItemId });
  state.moveItemId = syncInventoryObjectSelect(
    form.elements.item_id,
    state.moveItems,
    state.moveItemId,
    inventoryObjectSelectPlaceholder(type, 'move'),
    type
  );
  renderMoveSummary();
}

async function openInventoryMover(itemType, id) {
  if (!canManageLocation()) return;
  state.moveItemType = itemType === 'sample' ? 'sample' : 'reagent';
  state.moveItemId = id;
  activateView('inventory');
  const form = $('movementForm');
  if (form) form.elements.keyword.value = '';
  setInventoryTab('move', false);
  await loadMovements();
}

async function openReagentMover(id) {
  await openInventoryMover('reagent', id);
}

async function loadMovements() {
  await loadStorageTree();
  await loadMoveItems();
  const form = $('movementForm');
  if (form) {
    form.elements.to_storage_node_id.value = state.moveTargetId || '';
    fillPositionSelect(form.elements.position_in_box, form.elements.to_storage_node_id.value, state.moveWell);
    if (state.moveWell) form.elements.position_in_box.value = state.moveWell;
  }
  renderMoveSummary();
  await loadLocationPicker('movement');
}

async function loadInventory() {
  await loadStorageTree();
  const query = new URLSearchParams({ node_id: state.selectedNodeId || '', well: state.selectedWell || '', item_type: state.selectedItemType || '', item_id: state.selectedItemId || '' });
  const data = await api(`/api/storage/visual?${query}`);
  state.selectedNodeId = data.current.id;
  setInventoryTab(state.inventoryTab, false);
  renderInventoryWorkbench(data);
  if (isVirtualUnplacedNode(data.current)) fillSpaceForm({}, 'new-root');
  else fillSpaceForm(data.current);
  $('inventoryOverviewCount').textContent = `${data.stats.total} 件`;
  await loadInventoryTab(state.inventoryTab);
}

function optionExists(select, value) {
  return Boolean(select && [...select.options].some(option => String(option.value) === String(value)));
}

function setSelectValueIfPresent(select, value) {
  if (value && optionExists(select, value)) select.value = value;
}

function syncInventoryFilterVisibility() {
  const selector = $('inventoryItemType');
  if (selector && state.inventoryItemTypeFilter && selector.value !== state.inventoryItemTypeFilter) {
    selector.value = state.inventoryItemTypeFilter;
  }
  const type = inventorySearchType(selector?.value || state.inventoryItemTypeFilter || 'all');
  state.inventoryItemTypeFilter = type;
  document.querySelectorAll('[data-filter-kind]').forEach(el => {
    el.classList.toggle('hidden', el.dataset.filterKind !== type);
  });
  const keyword = $('inventoryKeyword');
  if (keyword) {
    keyword.placeholder = type === 'all'
      ? '关键词：名称 / 编号 / 货号 / 样本号 / 盒号 / 孔位 / 空间路径'
      : (type === 'sample'
        ? '关键词：系统编号 / 样本号 / 样本类型 / 管号 / 位置 / 备注'
        : (type === 'space'
          ? '关键词：空间名称 / 盒号 / 位置码 / 空间路径'
          : '关键词：名称 / 编号 / 货号 / 品牌 / 位置'));
  }
}

function renderMoveSummary() {
  const form = $('movementForm');
  const summary = $('moveSummary');
  if (!form || !summary) return;
  const target = nodeById(state.moveTargetId);
  form.elements.to_storage_node_id.value = state.moveTargetId || '';
  if (state.moveItemType && optionExists(form.elements.item_type, state.moveItemType)) {
    form.elements.item_type.value = state.moveItemType;
  }
  if (state.moveItemId && optionExists(form.elements.item_id, state.moveItemId)) {
    form.elements.item_id.value = state.moveItemId;
  } else {
    state.moveItemId = form.elements.item_id.value || null;
  }
  fillPositionSelect(form.elements.position_in_box, state.moveTargetId, state.moveWell);
  const item = state.moveItems.find(r => Number(r.id) === Number(form.elements.item_id.value || state.moveItemId));
  const typeLabel = inventoryObjectTypeLabel(state.moveItemType);
  const targetPosition = target
    ? `${target.path || target.name}${state.moveWell ? ` / ${state.moveWell}` : ''}`
    : '未归位';
  summary.innerHTML = `
    <div><span>待移动</span><b>${esc(inventoryObjectName(item, state.moveItemType))}</b>${metaLine(`${typeLabel} · ${locationText(item?.storage_location)}`)}</div>
    <div><span>移动到</span><b>${esc(targetPosition)}</b>${metaLine(target ? (isBox(target) ? '盒内孔位可从下方选择' : '目标空间本身或下级空间') : '清空具体空间')}</div>
  `;
}

async function loadCheckoutItems() {
  const form = $('checkoutForm');
  if (!form) return;
  if (state.checkoutItemType && optionExists(form.elements.item_type, state.checkoutItemType)) {
    form.elements.item_type.value = state.checkoutItemType;
  }
  const type = inventoryObjectType(form.elements.item_type.value || state.checkoutItemType);
  const keyword = form.elements.keyword?.value.trim() || '';
  state.checkoutItemType = type;
  state.checkoutItems = await fetchSelectableInventoryObjects(type, { keyword, explicitId: state.checkoutItemId });
  state.checkoutItemId = syncInventoryObjectSelect(
    form.elements.item_id,
    state.checkoutItems,
    state.checkoutItemId,
    inventoryObjectSelectPlaceholder(type, 'checkout'),
    type
  );
  renderCheckoutSummary();
}

function renderCheckoutSummary() {
  const form = $('checkoutForm');
  const summary = $('checkoutSummary');
  if (!form || !summary) return;
  const itemId = form.elements.item_id.value || state.checkoutItemId;
  const item = state.checkoutItems.find(row => Number(row.id) === Number(itemId));
  const typeLabel = inventoryObjectTypeLabel(state.checkoutItemType);
  state.checkoutItemId = itemId || null;
  summary.innerHTML = `
    <div><span>出库对象</span><b>${esc(inventoryObjectName(item, state.checkoutItemType, '请选择出库对象'))}</b>${metaLine(typeLabel)}</div>
    <div><span>当前位置</span><b>${esc(locationText(item?.storage_location))}</b>${metaLine(item?.position_in_box ? `孔位 ${item.position_in_box}` : '出库后释放占用位置')}</div>
  `;
}

async function loadCheckouts() {
  await loadCheckoutItems();
}

function bulkDefaultHeaders(operation, itemType) {
  if (operation === 'checkout') return ['对象类型', '编号', '出库原因', '备注'];
  if (operation === 'move') return ['对象类型', '编号', '目标空间ID', '孔位', '原因', '备注'];
  if (operation === 'edit') return itemType === 'sample'
    ? ['对象类型', '编号', '样本号', '样本类型', '规格量', '规格单位', '状态', '入库日期', '存放空间ID', '孔位', '备注']
    : ['对象类型', '编号', '名称', '类型', '品牌', '货号', '规格量', '规格单位', '数量', '状态', '验证状态', '入库日期', '有效期', '存放空间ID', '孔位', '备注'];
  return itemType === 'sample'
    ? ['系统编号', '样本号', '样本类型', '规格量', '规格单位', '状态', '入库日期', '存放空间ID', '孔位', '备注']
    : ['编号', '名称', '类型', '品牌', '货号', '规格量', '规格单位', '数量', '状态', '验证状态', '入库日期', '有效期', '存放空间ID', '孔位', '备注'];
}

function syncBulkFields() {
  const form = $('bulkForm');
  if (!form) return;
  const operationSelect = form.elements.operation;
  [...operationSelect.options].forEach(option => {
    if (['import', 'edit', 'move', 'checkout'].includes(option.value)) option.disabled = !canManageInventory();
  });
  if (operationSelect.selectedOptions[0]?.disabled) {
    operationSelect.value = [...operationSelect.options].find(option => !option.disabled)?.value || 'checkout';
  }
  const operation = operationSelect.value;
  $('bulkModeLabel')?.classList.toggle('hidden', operation !== 'import');
  $('bulkItemTypeLabel')?.classList.toggle('hidden', false);
  $('bulkCommitBtn').disabled = !(state.bulkPreview || []).some(row => row.status === 'ok');
}

async function loadBulk() {
  syncBulkFields();
}

function parseDelimitedRows(text, operation, itemType) {
  const lines = String(text || '').split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (!lines.length) return [];
  const splitLine = line => line.includes('\t') ? line.split('\t') : line.split(',');
  let headers = splitLine(lines[0]).map(item => item.trim());
  const defaults = bulkDefaultHeaders(operation, itemType);
  const firstHasHeader = headers.some(header => defaults.includes(header) || ['编号', '对象类型'].includes(header));
  const dataLines = firstHasHeader ? lines.slice(1) : lines;
  if (!firstHasHeader) headers = defaults.slice(0, Math.max(1, splitLine(lines[0]).length));
  return dataLines.map((line, index) => {
    const values = splitLine(line);
    const row = { _row_no: index + 2 };
    headers.forEach((header, colIndex) => { row[header] = (values[colIndex] || '').trim(); });
    return row;
  });
}

function currentBulkPayload(rows) {
  const form = $('bulkForm');
  const data = formData(form);
  delete data.excel_file;
  delete data.pasted_rows;
  return {
    operation: data.operation,
    item_type: data.item_type || 'reagent',
    mode: data.mode || 'upsert',
    rows,
  };
}

function bulkInputRows() {
  const form = $('bulkForm');
  const operation = form.elements.operation.value;
  const itemType = form.elements.item_type.value || 'reagent';
  const pasted = form.elements.pasted_rows.value.trim();
  return pasted ? parseDelimitedRows(pasted, operation, itemType) : (state.bulkRows || []);
}

function renderBulkPreview(result) {
  state.bulkPreview = result.items || [];
  $('bulkResultCount').textContent = `${result.valid || 0} 可提交 / ${result.invalid || 0} 有问题`;
  $('bulkSummary').innerHTML = `
    <div class="mini-rows">
      <div><span>总行数</span><span>${esc(result.total || 0)}</span></div>
      <div><span>可提交</span><span>${esc(result.valid || 0)}</span></div>
      <div><span>需处理</span><span>${esc(result.invalid || 0)}</span></div>
    </div>
  `;
  renderPagedTable('bulkPreviewTable', [
    { key: 'row_no', label: '行号' },
    { key: 'status', label: '状态', render: v => v === 'ok' ? badge('可提交') : badge('有问题') },
    { key: 'action', label: '处理' },
    { key: 'summary', label: '确认内容', render: v => esc(v || '-') },
    { key: 'errors', label: '提示', render: v => esc((v || []).join('；') || '-') },
    { key: 'source', label: '原始数据', render: v => esc(Object.entries(v || {}).filter(([key]) => key !== '_row_no').slice(0, 6).map(([key, value]) => `${key}:${value}`).join('；')) },
  ], state.bulkPreview, { pageSize: 12 });
  $('bulkCommitBtn').disabled = !state.bulkPreview.some(row => row.status === 'ok');
}

async function submitBulkPreview(e) {
  e.preventDefault();
  const rows = bulkInputRows();
  if (!rows.length) throw new Error('请先上传 Excel 或粘贴表格数据');
  const result = await api('/api/bulk/preview', { method: 'POST', body: JSON.stringify(currentBulkPayload(rows)) });
  renderBulkPreview(result);
  toast('预检查完成');
}

async function commitBulkRows() {
  const okRows = (state.bulkPreview || []).filter(row => row.status === 'ok').map(row => row.source);
  if (!okRows.length) throw new Error('没有可提交的行');
  if (!confirm(`确认提交 ${okRows.length} 行？\n提交前会再次检查，失败行不会写入。`)) return;
  const result = await api('/api/bulk/commit', { method: 'POST', body: JSON.stringify(currentBulkPayload(okRows)) });
  $('bulkResultCount').textContent = `${result.success} 成功 / ${result.failed} 失败`;
  renderPagedTable('bulkPreviewTable', [
    { key: 'row_no', label: '行号' },
    { key: 'status', label: '状态', render: v => v === 'ok' ? badge('成功') : badge('失败') },
    { key: 'action', label: '处理' },
    { key: 'errors', label: '提示', render: v => esc((v || []).join('；') || '-') },
  ], result.items || [], { pageSize: 12 });
  $('bulkCommitBtn').disabled = true;
  state.bulkPreview = [];
  state.bulkRows = [];
  toast('批量处理完成');
  await loadInventory();
}

async function loadBulkExcel() {
  const form = $('bulkForm');
  const file = form.elements.excel_file.files[0];
  if (!file) throw new Error('请选择 Excel 文件');
  const result = await api('/api/bulk/parse-excel', { method: 'POST', body: JSON.stringify({ data_url: await fileToDataUrl(file) }) });
  state.bulkRows = result.items || [];
  form.elements.pasted_rows.value = '';
  $('bulkResultCount').textContent = `已读取 ${result.count || 0} 行`;
  renderPagedTable('bulkPreviewTable', [
    { key: '_row_no', label: '行号' },
    { key: '_raw', label: '内容', render: (_, r) => esc(Object.entries(r).filter(([key]) => key !== '_row_no').slice(0, 8).map(([key, value]) => `${key}:${value}`).join('；')) },
  ], state.bulkRows, { pageSize: 12 });
  $('bulkCommitBtn').disabled = true;
  toast('Excel 已读取，请预检查');
}

async function downloadBulkTemplate() {
  const form = $('bulkForm');
  const params = new URLSearchParams({ operation: form.elements.operation.value, item_type: form.elements.item_type.value || 'reagent' });
  await downloadWithAuth(`/api/bulk/template?${params}`, '批量处理模板.xlsx');
}

async function downloadBulkCurrentInventory() {
  const form = $('bulkForm');
  const params = new URLSearchParams({ item_type: form.elements.item_type.value || 'all' });
  await downloadWithAuth(`/api/bulk/current-inventory?${params}`, '现有库存清单.xlsx');
}

async function downloadStorageMap() {
  await downloadWithAuth('/api/bulk/storage-map', '空间ID和层级位置对应表.xlsx');
}

async function openCheckout(itemType, id) {
  state.checkoutItemType = itemType === 'sample' ? 'sample' : 'reagent';
  state.checkoutItemId = id;
  activateView('inventory');
  setInventoryTab('checkout', false);
  await loadCheckouts();
}

async function submitCheckout(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const data = formData(form);
  const itemName = form.elements.item_id.selectedOptions[0]?.textContent || '当前库存';
  if (!confirm(`确认出库：${itemName}？\n出库后会释放当前位置，并写入流转记录。`)) return;
  await api('/api/checkouts', { method: 'POST', body: JSON.stringify(data) });
  form.elements.note.value = '';
  state.checkoutItemId = null;
  toast('出库已登记');
  await loadCheckouts();
  await loadInventory();
  if (state.registrationTab === 'samples') await loadSamples();
  if (state.inventoryTab === 'manual') await loadManualEditor();
}

async function loadInventoryTab(tab = state.inventoryTab) {
  setLoggedIn(Boolean(state.token && state.user));
  if (tab === 'details') await searchInventory();
  if (tab === 'manual') await loadManualEditor();
  if (tab === 'bulk') await loadBulk();
  if (tab === 'checkout') await loadCheckouts();
  if (tab === 'move' && canManageLocation()) await loadMovements();
}

async function loadManualEditor() {
  setManualMode(state.manualMode || 'reagent');
  await loadStorageTree();
  const reagentForm = $('reagentForm');
  if (reagentForm) {
    fillPositionSelect(reagentForm.elements.position_in_box, reagentForm.elements.storage_node_id.value, reagentForm.elements.position_in_box.value);
    syncReagentStorageFields(reagentForm);
    await loadLocationPicker('reagent');
  }
  const sampleForm = $('sampleEditForm');
  if (sampleForm) {
    fillPositionSelect(sampleForm.elements.position_in_box, sampleForm.elements.storage_node_id.value, sampleForm.elements.position_in_box.value);
    await loadLocationPicker('sampleEdit');
  }
}

async function loadLocationPicker(kind) {
  const cfg = pickerConfigs[kind];
  const container = cfg ? $(cfg.container) : null;
  const form = cfg ? $(cfg.form) : null;
  if (!cfg || !container || !form || !state.storageNodes.length) return;
  const draft = state.activeLocationPicker === kind ? state.locationPickerDraft : null;
  const nodeId = draft?.nodeId ?? (form.elements[cfg.nodeField].value || VIRTUAL_UNPLACED_NODE_ID);
  const well = draft?.well ?? (form.elements[cfg.positionField].value || '');
  if (kind === 'reagent' && form.classList.contains('consumed-reagent')) {
    container.innerHTML = '<p class="muted">已耗尽试剂保存后不占用存放位置。</p>';
    return;
  }
  const query = new URLSearchParams({ node_id: nodeId, well });
  const data = await api(`/api/storage/visual?${query}`);
  container.innerHTML = renderLocationPicker(data, kind, cfg.title);
  if (state.activeLocationPicker === kind) $('locationPickerDialog').innerHTML = renderLocationPickerDialog(data, kind, cfg.title);
}

async function openLocationPicker(kind) {
  const cfg = pickerConfigs[kind];
  const form = cfg ? $(cfg.form) : null;
  if (!cfg || !form) return;
  state.activeLocationPicker = kind;
  state.locationPickerDraft = {
    nodeId: form.elements[cfg.nodeField].value || VIRTUAL_UNPLACED_NODE_ID,
    well: form.elements[cfg.positionField].value || '',
  };
  const dialog = $('locationPickerDialog');
  dialog.classList.remove('hidden');
  await loadLocationPicker(kind);
}

async function closeLocationPicker() {
  const kind = state.activeLocationPicker;
  state.activeLocationPicker = null;
  state.locationPickerDraft = null;
  const dialog = $('locationPickerDialog');
  if (dialog) {
    dialog.classList.add('hidden');
    dialog.innerHTML = '';
  }
  if (kind) await loadLocationPicker(kind);
}

async function browsePickerNode(kind, nodeId) {
  if (state.activeLocationPicker !== kind) return;
  state.locationPickerDraft = {
    nodeId: isVirtualUnplacedId(nodeId) ? VIRTUAL_UNPLACED_NODE_ID : nodeId,
    well: '',
  };
  await loadLocationPicker(kind);
}

async function applyPickerNode(kind, nodeId) {
  const cfg = pickerConfigs[kind];
  const form = cfg ? $(cfg.form) : null;
  if (!cfg || !form) return;
  const selectedNodeId = isVirtualUnplacedId(nodeId) ? '' : nodeId;
  form.elements[cfg.nodeField].value = selectedNodeId;
  form.elements[cfg.positionField].value = '';
  fillPositionSelect(form.elements[cfg.positionField], selectedNodeId);
  if (kind === 'movement') {
    state.moveTargetId = selectedNodeId;
    state.moveWell = '';
    renderMoveSummary();
  }
  await closeLocationPicker();
}

async function setPickerWell(kind, well) {
  const cfg = pickerConfigs[kind];
  const form = cfg ? $(cfg.form) : null;
  if (!cfg || !form) return;
  const draftNodeId = state.activeLocationPicker === kind ? state.locationPickerDraft?.nodeId : '';
  const nodeId = isVirtualUnplacedId(draftNodeId) ? '' : (draftNodeId || form.elements[cfg.nodeField].value || '');
  if (!nodeId) return;
  form.elements[cfg.nodeField].value = nodeId;
  fillPositionSelect(form.elements[cfg.positionField], nodeId, well);
  form.elements[cfg.positionField].value = well;
  if (kind === 'movement') {
    state.moveTargetId = nodeId;
    state.moveWell = well;
    renderMoveSummary();
  }
  await closeLocationPicker();
}

function updateNodeDimensionLabels() {
  const form = $('nodeForm');
  if (!form) return;
  const type = form.elements.node_type.value;
  const boxLabel = $('boxSpecLabel');
  if (boxLabel) boxLabel.classList.toggle('hidden', type !== 'box');
  $('rowsLabel').textContent = type === 'box' ? '孔位行数' : '框架行数';
  $('colsLabel').textContent = type === 'box' ? '孔位列数' : '框架列数';
  form.elements.rows.min = '1';
  form.elements.cols.min = '1';
  form.elements.rows.max = type === 'box' ? '26' : '50';
  form.elements.cols.max = '50';
  const unframedButton = $('unframedSpaceBtn');
  if (unframedButton) unframedButton.classList.toggle('hidden', type === 'box');
  const help = $('spaceFrameHelp');
  if (help) {
    help.textContent = type === 'box'
      ? '盒子按孔位管理；1x1 表示一个孔位，不按无框架处理。'
      : '行和列都为 1 时，该空间按无框架处理；不显示行列框架。库存明细请到“明细查询”查看，盒内孔位仍在空间总览中显示。';
  }
}

function setSpaceUnframed() {
  const form = $('nodeForm');
  if (!form) return;
  if (form.elements.node_type.value === 'box') {
    toast('盒子按孔位管理，不设置为无框架');
    return;
  }
  form.elements.rows.value = 1;
  form.elements.cols.value = 1;
  updateNodeDimensionLabels();
  toast('已设为无框架');
}

async function startNewRootSpace() {
  activateView('inventory');
  setInventoryTab('spaces', false);
  await loadStorageTree();
  const root = rootStorageNode();
  fillSpaceForm({}, 'new-root', { parentId: root?.id || DEFAULT_ROOT_STORAGE_NODE_ID });
}

async function startNewChildSpace(parentId = state.selectedNodeId, gridRow = '', gridCol = '') {
  if (parentId) state.selectedNodeId = parentId;
  if (isVirtualUnplacedId(parentId)) {
    toast('未归位不是实际空间，请先选择真实空间');
    return;
  }
  activateView('inventory');
  setInventoryTab('spaces', false);
  await loadStorageTree();
  fillSpaceForm({}, 'new-child', { parentId, gridRow, gridCol });
}

async function openSpaceEditor(nodeId = state.selectedNodeId) {
  if (!nodeId) return;
  if (isVirtualUnplacedId(nodeId)) {
    toast('未归位不是实际空间，不能编辑');
    return;
  }
  state.selectedNodeId = nodeId;
  activateView('inventory');
  setInventoryTab('spaces', false);
  await loadStorageTree();
  const node = nodeById(nodeId);
  if (node) fillSpaceForm(node);
}

async function deleteCurrentSpace(nodeId = state.selectedNodeId) {
  if (!isAdmin()) {
    toast('只有管理员可以删除空间');
    return;
  }
  const formId = $('nodeForm')?.elements.id.value || '';
  const targetId = nodeId || state.selectedNodeId || formId;
  if (!targetId) {
    toast('请先选择要删除的空间');
    return;
  }
  await loadStorageTree();
  const node = nodeById(targetId);
  if (isVirtualUnplacedId(targetId)) {
    toast('未归位不是实际空间，不能删除');
    return;
  }
  const label = node?.path || node?.name || '当前空间';
  if (!confirm(`确认删除空间“${label}”？\n只有没有下级空间、没有库存的空间可以删除。`)) return;
  const data = await api(`/api/storage/nodes/${targetId}`, { method: 'DELETE' });
  state.selectedNodeId = data.next_node_id || '';
  state.selectedWell = '';
  state.selectedItemType = '';
  state.selectedItemId = null;
  toast('空间已删除');
  await loadStorageTree();
  await loadInventory();
}

async function startMoveIntoSpace(nodeId = state.selectedNodeId, well = '') {
  if (!canManageLocation()) {
    toast('当前账号没有位置维护权限');
    return;
  }
  state.moveTargetId = isVirtualUnplacedId(nodeId) ? '' : nodeId;
  state.moveWell = state.moveTargetId ? (well || '') : '';
  state.moveItemId = null;
  activateView('inventory');
  setInventoryTab('move', false);
  await loadMovements();
}

function setFormStorageTarget(form, nodeField, positionField, nodeId, well = '') {
  if (!form) return;
  form.elements[nodeField].value = nodeId || '';
  fillPositionSelect(form.elements[positionField], nodeId, well);
  form.elements[positionField].value = well || '';
}

function closePositionActionMenu() {
  $('positionActionMenu')?.remove();
}

function closeInventoryDetailDialog() {
  $('inventoryDetailDialog')?.remove();
}

async function startNewSampleAt(nodeId = state.selectedNodeId, well = '') {
  if (!canManageInventory()) {
    toast('当前账号没有库存维护权限');
    return;
  }
  const targetNodeId = isVirtualUnplacedId(nodeId) ? '' : nodeId;
  state.selectedNodeId = nodeId;
  state.selectedWell = well || '';
  activateView('registration');
  setRegistrationTab('samples', false);
  await loadRegistrationTab('samples');
  const form = $('sampleForm');
  resetForm(form);
  setDefaultDropdownValues();
  setDefaultDates();
  setFormStorageTarget(form, 'storage_node_id', 'position_in_box', targetNodeId, targetNodeId ? well : '');
  await loadLocationPicker('sample');
  toast(targetNodeId ? (well ? `标本入库位置已填入：${well}` : '标本入库位置已填入') : '标本将登记为未归位');
}

async function startNewReagentAt(nodeId = state.selectedNodeId, well = '') {
  if (!canManageInventory()) {
    toast('当前账号没有库存维护权限');
    return;
  }
  const targetNodeId = isVirtualUnplacedId(nodeId) ? '' : nodeId;
  state.selectedNodeId = nodeId;
  state.selectedWell = well || '';
  activateView('inventory');
  setInventoryTab('manual', false);
  setManualMode('reagent');
  await loadManualEditor();
  await startNewReagent({ refreshPicker: false });
  const form = $('reagentForm');
  setFormStorageTarget(form, 'storage_node_id', 'position_in_box', targetNodeId, targetNodeId ? well : '');
  syncReagentStorageFields(form);
  await loadLocationPicker('reagent');
  toast(targetNodeId ? (well ? `试剂/耗材位置已填入：${well}` : '试剂/耗材位置已填入') : '试剂/耗材将登记为未归位');
}

function positionActionButtons({ nodeId, well = '', row = '', col = '', node }) {
  const isVirtualUnplaced = isVirtualUnplacedNode(node || nodeId);
  const childButton = canManageLocation() && row && col && !isBox(node) && !isVirtualUnplaced
    ? `<button class="ghost mini-btn" type="button" data-action="new-child-space" data-id="${nodeId}" data-row="${esc(row)}" data-col="${esc(col)}">新建下级空间</button>`
    : '';
  const createButtons = !canManageInventory()
    ? '<p class="muted">当前账号没有库存维护权限。</p>'
    : `<button class="primary mini-btn" type="button" data-action="new-sample-at" data-node-id="${nodeId}" data-well="${esc(well)}">新建标本</button><button class="ghost mini-btn" type="button" data-action="new-reagent-at" data-node-id="${nodeId}" data-well="${esc(well)}">新建试剂</button>`;
  const moveButton = canManageLocation()
    ? `<button class="ghost mini-btn" type="button" data-action="move-into-space" data-node-id="${nodeId}" data-well="${esc(well)}">移入库存</button>`
    : '';
  return [childButton, createButtons, moveButton].filter(Boolean).join('');
}

function placePositionActionMenu(menu, anchor) {
  const rect = anchor?.getBoundingClientRect?.();
  if (!rect) return;
  const margin = 10;
  menu.style.maxHeight = `${Math.max(160, window.innerHeight - margin * 2)}px`;
  menu.style.overflow = 'auto';
  const width = Math.min(menu.offsetWidth || 280, window.innerWidth - margin * 2);
  const left = Math.min(Math.max(rect.left, margin), window.innerWidth - width - margin);
  const below = rect.bottom + margin;
  const height = Math.min(menu.offsetHeight || 0, window.innerHeight - margin * 2);
  const top = below + height + margin <= window.innerHeight
    ? below
    : Math.max(margin, rect.top - height - margin);
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
}

function showPositionActions({ nodeId = state.selectedNodeId, well = '', row = '', col = '', label = '', anchor = null } = {}) {
  if (!nodeId) return;
  closePositionActionMenu();
  state.selectedNodeId = nodeId;
  state.selectedWell = well || '';
  state.selectedItemType = '';
  state.selectedItemId = null;
  const node = nodeById(nodeId);
  const nodeText = node ? nodeLabel(node) : '';
  const title = label || (well ? `空孔位 ${well}` : '当前空间');
  const location = well ? `${nodeText}；${well}` : nodeText;
  const menu = document.createElement('div');
  menu.id = 'positionActionMenu';
  menu.className = 'position-action-popover';
  menu.innerHTML = `
      <h4>${esc(title)}</h4>
      <p>${esc(location || '未选择空间')}</p>
      <div class="detail-actions position-actions">${positionActionButtons({ nodeId, well, row, col, node })}</div>
  `;
  document.body.appendChild(menu);
  placePositionActionMenu(menu, anchor);
}

function inventoryDetailActions(item) {
  if (item.item_type === 'sample') {
    return `<div class="detail-actions">${canManageInventory() ? actionButton('编辑', 'sample-row-edit', item.id) : ''}${inventoryObjectAvailable(item, 'sample') && canManageLocation() ? actionButton('移动', 'sample-row-move', item.id) : ''}${inventoryObjectAvailable(item, 'sample') ? actionButton('出库', 'sample-row-checkout', item.id, 'danger') : ''}</div>`;
  }
  return inventoryObjectAvailable(item, 'reagent')
    ? `<div class="detail-actions">${canManageInventory() ? actionButton('编辑', 'inventory-row-edit', item.id) : ''}${canManageLocation() ? actionButton('移动', 'inventory-row-move', item.id) : ''}${actionButton('出库', 'inventory-row-checkout', item.id, 'danger')}</div>`
    : '';
}

async function loadInventoryTimeline(itemType, id) {
  const params = new URLSearchParams({ item_type: inventoryObjectType(itemType), id: String(id) });
  return api(`/api/inventory/timeline?${params}`);
}

function renderTimelineValidationDetails(details = {}) {
  const rows = [
    ['货号', details.catalog_no],
    ['验证日期', details.validation_date],
    ['方法', details.method],
    ['结果', details.result],
    ['验证人', details.validator],
    ['记录时间', details.created_at],
    ['说明', details.description],
    ['图片', details.image_path],
  ].filter(([, value]) => value !== null && value !== undefined && value !== '');
  if (!rows.length) return '';
  return `
    <details class="timeline-detail">
      <summary>验证详情</summary>
      <div class="timeline-detail-grid">
        ${rows.map(([label, value]) => `<span><b>${esc(label)}</b>${esc(value)}</span>`).join('')}
      </div>
    </details>
  `;
}

function renderInventoryTimeline(events = []) {
  if (!events.length) return '<p class="muted">暂无历史记录</p>';
  return `<div class="timeline-list">${events.map(event => `
    <div class="timeline-item">
      <div class="timeline-dot"></div>
      <div class="timeline-content">
        <div class="timeline-head"><b>${esc(event.title || '记录')}</b><span>${esc(event.time || '-')}</span></div>
        <p>${esc(event.summary || '')}</p>
        ${event.actor ? `<small>操作人：${esc(event.actor)}</small>` : ''}
        ${event.event_type === 'validation' ? renderTimelineValidationDetails(event.details || {}) : ''}
      </div>
    </div>
  `).join('')}</div>`;
}

function inventoryDetailBody(data, itemType, timeline = null) {
  const item = { ...data.item, item_type: itemType };
  const timelineBlock = `<h4>时间线</h4>${renderInventoryTimeline(timeline?.items || [])}`;
  if (itemType === 'sample') {
    const sourceText = item.code || '-';
    const tubeText = sampleTubeText(item) || '-';
    const specText = amountText(item);
    return `
      ${inventoryDetailActions(item)}
      <h4>${esc(sourceText)} · ${esc(item.name)}</h4>
      <div class="detail-grid"><span>系统编号：${esc(sourceText)}</span><span>样本号：${esc(item.name || '-')}</span><span>样本类型：${esc(item.category || '-')}</span><span>管号：${esc(tubeText)}</span><span>状态：${esc(item.status)}</span><span>规格：${specText}</span><span>入库日期：${esc(item.entry_date)}</span><span>位置：${esc(locationText(item.storage_location))}</span></div>
      ${timelineBlock}
    `;
  }
  const aliquotText = reagentAliquotText(item);
  return `
    ${inventoryDetailActions(item)}
    <h4>${esc(item.name)}</h4>
    <div class="detail-grid"><span>编号：${esc(item.code || item.id)}</span><span>来源：${esc(item.source_code || item.code || '-')}</span><span>货号：${esc(item.catalog_no || '-')}</span>${aliquotText ? `<span>管号：${esc(aliquotText)}</span>` : ''}<span>规格：${amountText(item)}</span><span>类型：${esc(item.category)}</span><span>状态：${esc(item.status)}</span><span>验证：${esc(item.validation_status)}</span><span>数量：${esc(item.quantity)}</span><span>位置：${esc(locationText(item.storage_location))}</span></div>
    ${timelineBlock}
  `;
}

async function showInventoryItemDetailDialog(itemType = 'reagent', id = '') {
  if (!id) return;
  closeInventoryDetailDialog();
  const cleanType = inventoryObjectType(itemType, 'reagent');
  const [data, timeline] = await Promise.all([
    api(inventoryObjectDetailPath(cleanType, id)),
    loadInventoryTimeline(cleanType, id),
  ]);
  const title = cleanType === 'sample'
    ? (data.item.code || '临床标本')
    : (data.item.code || data.item.name || '试剂/耗材');
  const dialog = document.createElement('div');
  dialog.id = 'inventoryDetailDialog';
  dialog.className = 'detail-dialog-backdrop';
  dialog.innerHTML = `
    <article class="detail-dialog" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="detail-dialog-head"><h3>${esc(title)}</h3><button class="ghost mini-btn" type="button" data-action="close-inventory-detail">关闭</button></div>
      <div class="detail-panel">${inventoryDetailBody(data, cleanType, timeline)}</div>
    </article>
  `;
  document.body.appendChild(dialog);
}

function applySelectedStorage(target) {
  const nodeId = isVirtualUnplacedId(state.selectedNodeId) ? '' : (state.selectedNodeId || '');
  const well = state.selectedWell || '';
  const config = pickerConfigs[target];
  if (!config) return;
  const form = $(config.form);
  if (!form) return;
  if (target === 'reagent' && form.classList.contains('consumed-reagent')) {
    toast('已耗尽试剂不再占用位置');
    return;
  }
  form.elements[config.nodeField].value = nodeId;
  fillPositionSelect(form.elements[config.positionField], nodeId, nodeId ? well : '');
  form.elements[config.positionField].value = nodeId ? well : '';
  if (target === 'reagent') syncReagentStorageFields(form);
  if (target === 'movement') {
    state.moveTargetId = nodeId;
    state.moveWell = nodeId ? well : '';
    renderMoveSummary();
  }
  void loadLocationPicker(target);
  toast(nodeId ? `${config.label}已填入当前选中位置` : `${config.label}已设为未归位`);
}

function defaultSpaceLayout(nodeType) {
  if (nodeType === 'box') return { rows: 9, cols: 9 };
  return { rows: 1, cols: 1 };
}

function defaultChildType(parent) {
  if (!parent) return 'space';
  return parent.node_type === 'space' ? 'space' : 'box';
}

function fillSpaceForm(current, mode = 'edit', options = {}) {
  const form = $('nodeForm');
  resetForm(form);
  const deleteButton = $('deleteSpaceBtn');
  if (mode === 'new-root' || mode === 'new-child') {
    deleteButton?.classList.add('hidden');
    let parentId = mode === 'new-root'
      ? (options.parentId || rootStorageNode()?.id || DEFAULT_ROOT_STORAGE_NODE_ID)
      : (options.parentId || state.selectedNodeId || '');
    let parent = nodeById(parentId);
    if (parent?.node_type === 'box') {
      parentId = parent.parent_id || '';
      parent = nodeById(parentId);
      toast('盒子是末端空间，已切换到它的父级下新建');
    }
    const nodeType = defaultChildType(parent);
    const layout = defaultSpaceLayout(nodeType);
    $('spaceFormTitle').textContent = mode === 'new-root' ? '新建空间' : '新建下级空间';
    form.elements.parent_id.value = parentId;
    form.elements.node_type.value = nodeType;
    form.elements.name.value = mode === 'new-root' ? '新空间' : (nodeType === 'box' ? '新盒子' : '新空间');
    form.elements.rows.value = layout.rows;
    form.elements.cols.value = layout.cols;
    form.elements.grid_row.value = options.gridRow || '';
    form.elements.grid_col.value = options.gridCol || '';
    if (options.gridRow && options.gridCol) {
      $('spaceFormTitle').textContent += `（${options.gridRow}行${options.gridCol}列）`;
    }
    updateNodeDimensionLabels();
    return;
  }
  $('spaceFormTitle').textContent = `编辑空间：${current.name}`;
  setFormValues(form, current);
  deleteButton?.classList.toggle('hidden', !current?.id || !isAdmin());
  updateNodeDimensionLabels();
}

async function searchInventory() {
  syncInventoryFilterVisibility();
  if (!canSearchInventory()) {
    $('inventoryFilterCount').textContent = '无权限';
    renderTable('inventoryTable', [{ key: 'message', label: '提示' }], [{ message: '当前账号没有明细搜索权限' }]);
    return;
  }
  const type = inventorySearchType(state.inventoryItemTypeFilter);
  const params = new URLSearchParams({
    keyword: $('inventoryKeyword').value.trim(),
    storage_node_id: $('inventoryStorageNode').value,
    include_descendants: $('inventoryIncludeDescendants').checked ? '1' : '0',
    limit: '500',
  });
  if (type === 'sample') {
    params.set('category', $('inventorySampleType').value);
    params.set('status', $('inventorySampleStatus').value);
  } else if (type === 'reagent') {
    params.set('category', $('inventoryCategory').value);
    params.set('status', $('inventoryStatus').value);
    params.set('validation_status', $('inventoryValidationStatus').value);
  }
  params.set('purpose', 'global');
  if (type === 'all' || type === 'space') params.set('type', type);
  const data = type === 'all' || type === 'space'
    ? await api(`/api/inventory/search?${params}`)
    : await api(inventoryObjectListPath(type, params));
  state.inventoryRows = data.items;
  $('inventoryFilterCount').textContent = `${data.count} 条`;
  renderPagedTable('inventoryTable', inventoryColumns(), data.items, { pageSize: 20 });
}

async function submitMovement(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const data = formData(form);
  data.item_type = data.item_type || state.moveItemType || 'reagent';
  data.item_id = data.item_id || state.moveItemId;
  data.to_storage_node_id = data.to_storage_node_id || state.moveTargetId || '';
  data.position_in_box = data.to_storage_node_id ? (data.position_in_box || state.moveWell || '') : '';
  await api('/api/movements', { method: 'POST', body: JSON.stringify(data) });
  form.elements.note.value = '';
  state.moveItemId = null;
  state.moveWell = '';
  toast('移动完成');
  await loadInventory();
  if (state.inventoryItemTypeFilter === 'sample' || state.inventoryTab === 'details') await searchInventory();
}

async function submitSpace(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const data = formData(form);
  const id = data.id;
  delete data.id;
  if (!data.parent_id) delete data.parent_id;
  if (id) await api(`/api/storage/nodes/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
  else await api('/api/storage/nodes', { method: 'POST', body: JSON.stringify(data) });
  toast('空间已保存');
  await loadInventory();
}
