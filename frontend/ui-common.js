function badge(value) {
  const text = fmt(value);
  let cls = 'badge';
  if (['已过期', '不通过', STATUS_DISABLED, STATUS_CONSUMED, '取消'].includes(text)) cls += ' danger';
  if (['待验证', VALIDATION_UNVERIFIED, '待复核', STATUS_ORDERED, 'user'].includes(text)) cls += ' warn';
  return `<span class="${cls}">${esc(text)}</span>`;
}

function actionButton(label, action, id, cls = 'ghost') {
  return `<button class="${cls} mini-btn" type="button" data-action="${action}" data-id="${id}">${esc(label)}</button>`;
}

function inventoryActionButtons(item, type, options = {}) {
  const itemType = inventoryObjectType(type);
  if (!canViewInventoryType(itemType)) return '';
  const detailAction = options.detailAction ?? (itemType === 'sample' ? 'inventory-sample-detail' : 'inventory-row-detail');
  const editAction = options.editAction ?? (itemType === 'sample' ? 'sample-row-edit' : 'inventory-row-edit');
  const moveAction = options.moveAction ?? (itemType === 'sample' ? 'sample-row-move' : 'inventory-row-move');
  const checkoutAction = options.checkoutAction ?? (itemType === 'sample' ? 'sample-row-checkout' : 'inventory-row-checkout');
  const showDetail = options.detail !== false;
  const canMoveOrCheckout = inventoryObjectAvailable(item, itemType);
  return [
    showDetail ? actionButton('详情', detailAction, item.id) : '',
    editAction && canManageInventory() ? actionButton('编辑', editAction, item.id) : '',
    canMoveOrCheckout && canManageLocation() ? actionButton('移动', moveAction, item.id) : '',
    canMoveOrCheckout ? actionButton('出库', checkoutAction, item.id, 'danger') : '',
  ].filter(Boolean).join(' ');
}

function amountText(item) {
  if (!item || item.amount === null || item.amount === undefined || item.amount === '') return '-';
  return `${esc(item.amount)}${esc(item.amount_unit || '')}`;
}

function orderPriceText(value) {
  if (value === null || value === undefined || value === '') return '未填写';
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : String(value);
}

function isAntibodyDetailItem(item = {}) {
  const text = `${item.category || ''} ${item.name || ''}`;
  return /抗体|antibody|anti-/i.test(text);
}

function antibodyMetadataHasContent(metadata = {}) {
  return ['target', 'conjugate', 'react_species', 'host_species', 'clone', 'isotype', 'aliases', 'raw_note']
    .some(field => String(metadata?.[field] || '').trim());
}

function antibodyDetailField(label, value, cls = '') {
  return `<span${cls ? ` class="${cls}"` : ''}>${esc(label)}：${esc(value || '-')}</span>`;
}

function renderAntibodyMetadataBlock(data = {}) {
  const item = data.item || {};
  const metadata = data.antibody_metadata || item.antibody_metadata || null;
  if (!metadata && !isAntibodyDetailItem(item)) return '';
  let rows = [antibodyDetailField('抗体信息', '尚未填写', 'detail-full-row')];
  if (metadata && antibodyMetadataHasContent(metadata)) {
    rows = [
      antibodyDetailField('靶标/抗原', metadata.target),
      antibodyDetailField('荧光/标记', metadata.conjugate),
      antibodyDetailField('反应种属', metadata.react_species),
      antibodyDetailField('宿主种属', metadata.host_species),
      antibodyDetailField('克隆号', metadata.clone),
      antibodyDetailField('同型/亚型', metadata.isotype),
    ];
    if (metadata.aliases) rows.push(antibodyDetailField('别称', metadata.aliases, 'detail-full-row'));
    if (metadata.raw_note) rows.push(antibodyDetailField('抗体备注', metadata.raw_note, 'detail-full-row'));
  }
  return `<h4>抗体信息</h4><div class="detail-grid antibody-detail-grid">${rows.join('')}</div>`;
}

function syncMultiRegisterFields(form) {
  if (!form) return;
  form.querySelectorAll('[data-multi-register-row]').forEach(row => {
    const input = row.querySelector('input[name="separate_items"]');
    const countField = form.elements[row.dataset.countField || 'quantity'];
    const count = Number(countField?.value || 1);
    const show = count > 1 && !form.elements.id?.value;
    row.classList.toggle('hidden', !show);
    if (input) input.disabled = !show;
  });
}

function inventoryColumns() {
  if (state.inventoryItemTypeFilter === 'all') return allInventoryColumns();
  if (state.inventoryItemTypeFilter === 'space') return spaceInventoryColumns();
  if (state.inventoryItemTypeFilter === 'sample') return sampleInventoryColumns();
  const columns = reagentColumns(false);
  columns.push({
    key: 'id',
    label: '操作',
    render: (_, r) => inventoryActionButtons(r, 'reagent'),
  });
  return columns;
}

function spaceInventoryColumns() {
  return [
    { key: 'code', label: '编号/位置码', render: v => esc(v || '-') },
    { key: 'name', label: '空间名称', render: (_, r) => esc(r.display_title || r.name || '-') },
    { key: 'display_subtitle', label: '类型', render: badge },
    { key: 'display_location', label: '空间路径', render: v => esc(locationText(v)) },
    {
      key: 'id',
      label: '操作',
      render: (_, r) => actionButton('打开空间', 'inventory-node', r.id),
    },
  ];
}

function allInventoryColumns() {
  return [
    { key: 'item_type', label: '对象', render: (_, r) => badge(inventoryObjectTypeLabel(r, 'reagent')) },
    { key: 'code', label: '编号/样本号', render: (_, r) => esc(inventoryObjectCode(r, r.item_type)) },
    { key: 'name', label: '名称/类型', render: (_, r) => esc(inventoryObjectName(r, r.item_type, '-')) },
    { key: 'category', label: '分类', render: (_, r) => badge(r.display_type || r.category || inventoryObjectTypeLabel(r, r.item_type)) },
    { key: 'quantity', label: '数量/规格', render: (_, r) => inventoryObjectType(r, r.item_type) === 'sample'
      ? amountText(r)
      : (r.item_type === 'space' ? '-' : esc(r.quantity)) },
    { key: 'price', label: '价格', render: (_, r) => r.item_type === 'reagent' ? esc(orderPriceText(r.price)) : '-' },
    { key: 'status', label: '状态', render: badge },
    { key: 'storage_location', label: '位置', render: v => esc(locationText(v)) },
    { key: 'updated_at', label: '更新时间' },
    {
      key: 'id',
      label: '操作',
      render: (_, r) => {
        if (r.item_type === 'space') return actionButton('打开空间', 'inventory-node', r.id);
        const type = inventoryObjectType(r, r.item_type);
        return inventoryActionButtons(r, type);
      },
    },
  ];
}

function sampleInventoryColumns() {
  const columns = sampleColumns(false);
  columns.push({
    key: 'id',
    label: '操作',
    render: (_, r) => inventoryActionButtons(r, 'sample'),
  });
  return columns;
}

function tableColumnLabel(column) {
  return String(column?.label || '');
}

function tableColumnKey(column) {
  return String(column?.key || '');
}

function tableColumnClass(column) {
  const label = tableColumnLabel(column);
  const key = tableColumnKey(column);
  const classes = [];
  if (label === '操作') classes.push('table-col-action');
  if (label !== '操作' && (label === 'ID' || key === 'id' || key === 'aliquot_no')) classes.push('table-col-id');
  if (['code', 'object_id', 'catalog_no'].includes(key) || /编号|样本号|货号/.test(label)) classes.push('table-col-code');
  if (/位置/.test(label) || key.includes('location')) classes.push('table-col-location');
  if (/时间|日期|有效期|更新时间/.test(label) || /(_at|_date|date)$/.test(key)) classes.push('table-col-date');
  return classes.join(' ');
}

function displayTableColumns(columns) {
  const actionIndex = columns.findIndex(column => tableColumnLabel(column) === '操作');
  if (actionIndex <= 1) return columns;
  return [columns[0], columns[actionIndex], ...columns.slice(1, actionIndex), ...columns.slice(actionIndex + 1)];
}

function renderTableHead(columns) {
  return `<thead><tr>${columns.map(column => `<th class="${tableColumnClass(column)}">${esc(tableColumnLabel(column))}</th>`).join('')}</tr></thead>`;
}

function sanitizeTableHtml(value) {
  const template = document.createElement('template');
  template.innerHTML = String(value ?? '');
  const allowedTags = new Set(['SPAN', 'BUTTON', 'B', 'SMALL', 'DIV']);
  const allowedAttrs = new Set(['class', 'type', 'disabled', 'title']);
  const cleanNode = node => {
    if (node.nodeType === Node.TEXT_NODE) return;
    if (node.nodeType !== Node.ELEMENT_NODE) {
      node.remove();
      return;
    }
    if (!allowedTags.has(node.tagName)) {
      node.replaceWith(...Array.from(node.childNodes));
      return;
    }
    Array.from(node.attributes).forEach(attr => {
      const name = attr.name.toLowerCase();
      const allowed = allowedAttrs.has(name) || name.startsWith('data-') || name.startsWith('aria-');
      if (!allowed || name.startsWith('on') || /javascript:/i.test(attr.value)) node.removeAttribute(attr.name);
    });
    Array.from(node.childNodes).forEach(cleanNode);
  };
  Array.from(template.content.childNodes).forEach(cleanNode);
  return template.innerHTML;
}

function renderTableCell(column, row) {
  const value = column.render ? column.render(row[column.key], row) : esc(row[column.key]);
  return `<td class="${tableColumnClass(column)}">${sanitizeTableHtml(value)}</td>`;
}

function renderTable(id, columns, rows) {
  const table = $(id);
  if (!table) return;
  const visibleColumns = displayTableColumns(columns);
  table.classList.toggle('has-actions', visibleColumns.some(column => tableColumnLabel(column) === '操作'));
  if (!rows || rows.length === 0) {
    table.innerHTML = `${renderTableHead(visibleColumns)}<tbody><tr><td colspan="${visibleColumns.length}">暂无数据</td></tr></tbody>`;
    return;
  }
  table.innerHTML = `${renderTableHead(visibleColumns)}<tbody>${rows.map(row => `<tr>${visibleColumns.map(column => renderTableCell(column, row)).join('')}</tr>`).join('')}</tbody>`;
}

function renderPagedTable(id, columns, rows, options = {}) {
  const pageSize = Number(options.pageSize || 20);
  const pageKey = options.pageKey || id;
  const total = Number(options.total ?? rows?.length ?? 0);
  const maxPage = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.min(Math.max(Number(options.page || state.tablePages[pageKey] || 1), 1), maxPage);
  state.tablePages[pageKey] = currentPage;
  const start = (currentPage - 1) * pageSize;
  const visibleRows = options.serverSide ? (rows || []) : (rows || []).slice(start, start + pageSize);
  renderTable(id, columns, visibleRows);
  const pager = $(`${id}Pager`);
  if (!pager) return;
  const from = total ? start + 1 : 0;
  const to = Math.min(start + pageSize, total);
  pager.innerHTML = `
    <span>${from}-${to} / ${total}</span>
    <button class="ghost mini-btn" type="button" data-action="table-page" data-table="${esc(pageKey)}" data-page="${currentPage - 1}" ${currentPage <= 1 ? 'disabled' : ''}>上一页</button>
    <button class="ghost mini-btn" type="button" data-action="table-page" data-table="${esc(pageKey)}" data-page="${currentPage + 1}" ${currentPage >= maxPage ? 'disabled' : ''}>下一页</button>
  `;
}

function fillSelect(select, values, placeholder = '') {
  if (!select) return;
  const current = select.value;
  select.innerHTML = placeholder ? `<option value="">${placeholder}</option>` : '';
  values.forEach(value => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
  if ([...select.options].some(o => o.value === current)) select.value = current;
}

function fillSelectObjects(select, items, { placeholder = '', valueKey = 'id', label = item => item.name } = {}) {
  if (!select) return;
  const current = select.value;
  select.innerHTML = placeholder ? `<option value="">${placeholder}</option>` : '';
  items.forEach(item => {
    const option = document.createElement('option');
    option.value = item[valueKey];
    option.textContent = label(item);
    select.appendChild(option);
  });
  if ([...select.options].some(o => o.value === current)) select.value = current;
}

function fillDatalist(list, values) {
  if (!list) return;
  list.innerHTML = '';
  values.forEach(value => {
    const option = document.createElement('option');
    option.value = value;
    list.appendChild(option);
  });
}

function nodeLabel(node) { return node.path || node.name; }

function nodeById(id) { return state.storageNodes.find(node => Number(node.id) === Number(id)); }

const DEFAULT_ROOT_STORAGE_NODE_ID = '1';
const VIRTUAL_UNPLACED_NODE_ID = '-3';
const VIRTUAL_FAVORITES_NODE_ID = '-5';

function isVirtualUnplacedId(id) { return String(id || '') === VIRTUAL_UNPLACED_NODE_ID; }
function isVirtualFavoritesId(id) { return String(id || '') === VIRTUAL_FAVORITES_NODE_ID; }
function isVirtualOverviewId(id) { return isVirtualUnplacedId(id) || isVirtualFavoritesId(id); }

function isRealStorageNodeId(id) {
  return Number.isFinite(Number(id)) && Number(id) > 0;
}

function isSystemStorageNode(nodeOrId) {
  if (typeof nodeOrId === 'object') return !isRealStorageNodeId(nodeOrId?.id) || nodeOrId?.node_type === 'system';
  return !isRealStorageNodeId(nodeOrId);
}

function isVirtualUnplacedNode(nodeOrId) {
  if (typeof nodeOrId === 'object') return Boolean(nodeOrId?.is_virtual_unplaced) || isVirtualUnplacedId(nodeOrId?.id);
  return isVirtualUnplacedId(nodeOrId);
}

function isVirtualFavoritesNode(nodeOrId) {
  if (typeof nodeOrId === 'object') return Boolean(nodeOrId?.is_virtual_favorites) || isVirtualFavoritesId(nodeOrId?.id);
  return isVirtualFavoritesId(nodeOrId);
}

function isVirtualOverviewNode(nodeOrId) {
  return isVirtualUnplacedNode(nodeOrId) || isVirtualFavoritesNode(nodeOrId);
}

function selectableStorageNodes() {
  return state.storageNodes.filter(node => !isSystemStorageNode(node));
}

function parentStorageNodes() { return selectableStorageNodes(); }

function rootStorageNode() {
  return nodeById(DEFAULT_ROOT_STORAGE_NODE_ID)
    || state.storageNodes.find(node => node.parent_id === null || node.parent_id === undefined)
    || state.storageNodes[0];
}

function currentOptions(key) { return state.options?.[key] || []; }

function currentSpaceTypes() {
  return normalizeSpaceTypeLabels(currentOptions('space_types'));
}

function normalizeSpaceTypeLabels(values = []) {
  const defaults = ['盒子', '冰箱', '液氮罐', '架子', '其他'];
  if (!Array.isArray(values) || values.length === 0) return defaults;
  const source = values;
  const result = [];
  for (let index = 0; index < 4; index += 1) {
    const value = String(index < source.length ? source[index] : defaults[index]).trim();
    result.push(value && value !== '其他' ? value : '');
  }
  return result.concat('其他');
}

function spaceTypeText(node) {
  const code = Math.max(1, Math.min(5, Number(node?.space_type || 5)));
  return currentSpaceTypes()[code - 1] || (code < 5 ? `类型 ${code}` : '其他');
}

function spaceTypeOptions() {
  return currentSpaceTypes()
    .map((label, index) => ({ value: String(index + 1), label }))
    .filter(item => item.value === '5' || item.label);
}

function isUnframedNode(node) {
  return Boolean(node && (isSystemStorageNode(node) || (Number(node.rows || 1) === 1 && Number(node.cols || 1) === 1)));
}

function storageContext(node) {
  if (!node?.path) return '';
  const parts = String(node.path).split(' / ');
  if (parts[parts.length - 1] === node.name) parts.pop();
  return parts.join(' / ');
}

function storageParentName(node) {
  if (!node?.path) return '';
  const parts = String(node.path).split(' / ');
  if (parts.length <= 1) return '';
  return parts[parts.length - 2] || '';
}

function metaLine(text) {
  return text ? `<span class="tree-meta">${esc(text)}</span>` : '';
}

function coordList(rows, cols) {
  const items = [];
  for (let r = 0; r < rows; r += 1) {
    const row = String.fromCharCode('A'.charCodeAt(0) + r);
    for (let c = 1; c <= cols; c += 1) items.push(`${row}${c}`);
  }
  return items;
}

function positionOptionsForNode(node) {
  if (!node || isUnframedNode(node)) return [];
  return coordList(Number(node.rows || 1), Number(node.cols || 1));
}

function fillPositionSelect(select, nodeId, current = '') {
  if (!select) return;
  if (!select.options) {
    select.value = current || '';
    return;
  }
  if (!isRealStorageNodeId(nodeId)) {
    select.innerHTML = '<option value="">无</option>';
    select.value = '';
    return;
  }
  const node = nodeById(nodeId);
  const coords = positionOptionsForNode(node);
  select.innerHTML = '<option value="">无</option>';
  coords.forEach(coord => {
    const option = document.createElement('option');
    option.value = coord;
    option.textContent = coord;
    select.appendChild(option);
  });
  if (current && [...select.options].some(o => o.value === current)) select.value = current;
}

async function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function loadOptions() {
  state.options = await api('/api/options');
  fillSelect($('reagentCategory'), currentOptions('categories'), '全部类型');
  fillSelect($('reagentStatus'), currentOptions('reagent_statuses'), '全部状态');
  fillSelect($('reagentValidationStatus'), currentOptions('validation_statuses'), '全部验证');
  fillSelect($('inventoryCategory'), currentOptions('categories'), '全部类型');
  fillSelect($('inventoryStatus'), currentOptions('reagent_statuses'), '全部状态');
  fillSelect($('inventoryValidationStatus'), currentOptions('validation_statuses'), '全部验证');
  fillSelect($('inventorySampleType'), currentOptions('sample_names'), '全部样本类型');
  fillSelect($('inventorySampleStatus'), currentOptions('sample_statuses'), '全部状态');
  document.querySelectorAll('select[name="category"]').forEach(sel => fillSelect(sel, currentOptions('categories'), sel.closest('#orderForm') ? '请选择' : ''));
  document.querySelectorAll('select[name="status"]').forEach(sel => {
    if (!sel.closest('#sampleForm') && !sel.closest('#sampleEditForm')) fillSelect(sel, currentOptions('reagent_statuses'));
  });
  document.querySelectorAll('#sampleForm select[name="status"], #sampleEditForm select[name="status"]').forEach(sel => fillSelect(sel, currentOptions('sample_statuses')));
  document.querySelectorAll('#sampleForm select[name="category"], #sampleEditForm select[name="category"]').forEach(sel => fillSelect(sel, currentOptions('sample_names')));
  document.querySelectorAll('select[name="result"]').forEach(sel => fillSelect(sel, currentOptions('validation_statuses')));
  document.querySelectorAll('select[name="method"]').forEach(sel => fillSelect(sel, currentOptions('validation_methods')));
  document.querySelectorAll('#nodeForm select[name="space_type"]').forEach(sel => {
    fillSelectObjects(sel, spaceTypeOptions(), { valueKey: 'value', label: item => item.label });
  });
  document.querySelectorAll('input[name="brand"]').forEach(input => input.setAttribute('list', 'brandOptions'));
  fillDatalist($('brandOptions'), currentOptions('brands'));
  fillDatalist($('samplePrefixOptions'), currentOptions('sample_prefixes'));
  fillDatalist($('amountUnitOptions'), currentOptions('amount_units'));
  fillDatalist($('antibodyConjugateOptions'), currentOptions('antibody_conjugates'));
  fillDatalist($('antibodyReactSpeciesOptions'), currentOptions('antibody_react_species'));
  fillDatalist($('antibodyHostSpeciesOptions'), currentOptions('antibody_host_species'));
  fillDatalist($('antibodyIsotypeOptions'), currentOptions('antibody_isotypes'));
  document.querySelectorAll('select[name="role"]').forEach(sel => fillSelectObjects(
    sel,
    Object.entries(state.options.roles || {}).map(([value, label]) => ({ value, label })),
    { valueKey: 'value', label: item => item.label }
  ));
  setDefaultDropdownValues();
  syncUserPermissionFields?.();
  fillSettingsForms();
  if (typeof syncAllBrandSaveOptionRows === 'function') syncAllBrandSaveOptionRows();
}

function setDefaultDropdownValues() {
  const reagentForm = $('reagentForm');
  if (reagentForm && !reagentForm.elements.id.value) {
    reagentForm.elements.category.value = currentOptions('categories').includes('其他') ? '其他' : currentOptions('categories')[0] || '';
    reagentForm.elements.status.value = currentOptions('reagent_statuses').includes(STATUS_AVAILABLE) ? STATUS_AVAILABLE : currentOptions('reagent_statuses')[0] || '';
    if (reagentForm.elements.separate_items) reagentForm.elements.separate_items.checked = true;
    if (typeof syncAntibodySection === 'function') syncAntibodySection(reagentForm);
  }
  const reagentEditForm = $('reagentEditForm');
  if (reagentEditForm && !reagentEditForm.elements.id.value) {
    reagentEditForm.elements.category.value ||= currentOptions('categories').includes('其他') ? '其他' : currentOptions('categories')[0] || '';
    reagentEditForm.elements.status.value ||= currentOptions('reagent_statuses').includes(STATUS_AVAILABLE) ? STATUS_AVAILABLE : currentOptions('reagent_statuses')[0] || '';
    if (typeof syncAntibodySection === 'function') syncAntibodySection(reagentEditForm);
  }
  const orderForm = $('orderForm');
  if (orderForm) {
    if (!orderForm.elements.quantity.value) orderForm.elements.quantity.value = 1;
    if (typeof syncAntibodySection === 'function') syncAntibodySection(orderForm);
  }
  const sampleForm = $('sampleForm');
  if (sampleForm) {
    sampleForm.elements.tube_count.value ||= 1;
    if (sampleForm.elements.separate_items) sampleForm.elements.separate_items.checked = true;
    sampleForm.elements.code_prefix.value ||= currentOptions('sample_prefixes')[0] || '';
    sampleForm.elements.category.value ||= currentOptions('sample_names')[0] || '';
    sampleForm.elements.status.value ||= currentOptions('sample_statuses').includes(STATUS_AVAILABLE) ? STATUS_AVAILABLE : currentOptions('sample_statuses')[0] || '';
  }
  const sampleEditForm = $('sampleEditForm');
  if (sampleEditForm && !sampleEditForm.elements.id.value) {
    sampleEditForm.elements.category.value ||= currentOptions('sample_names')[0] || '';
    sampleEditForm.elements.status.value ||= currentOptions('sample_statuses').includes(STATUS_AVAILABLE) ? STATUS_AVAILABLE : currentOptions('sample_statuses')[0] || '';
  }
  const aliquotForm = $('aliquotForm');
  if (aliquotForm) aliquotForm.elements.tube_count.value ||= 1;
  const nodeForm = $('nodeForm');
  if (nodeForm && !nodeForm.elements.id.value && nodeForm.elements.space_type) {
    nodeForm.elements.space_type.value = '5';
  }
  document.querySelectorAll('form').forEach(syncMultiRegisterFields);
}

function ensureSpaceTypeSelectValue(select, value) {
  if (!select) return;
  const code = String(Math.max(1, Math.min(5, Number(value || 5))));
  if ([...select.options].some(option => option.value === code)) {
    select.value = code;
    return;
  }
  const option = document.createElement('option');
  option.value = code;
  option.textContent = `${spaceTypeText({ space_type: code })}（已隐藏）`;
  option.hidden = true;
  select.appendChild(option);
  select.value = code;
}

async function loadStorageTree() {
  const data = await api('/api/storage/tree');
  state.storageNodes = data.items;
  const normalNodes = parentStorageNodes();
  const rootNode = rootStorageNode();
  if (!state.selectedNodeId && rootNode) state.selectedNodeId = rootNode.id;
  document.querySelectorAll('select[name="storage_node_id"]').forEach(sel => {
    fillSelectObjects(sel, selectableStorageNodes(), { placeholder: '未归位', label: nodeLabel });
  });
  document.querySelectorAll('#inventoryStorageNode').forEach(sel => {
    fillSelectObjects(sel, selectableStorageNodes(), { placeholder: '全部空间', label: nodeLabel });
  });
  document.querySelectorAll('#nodeForm select[name="parent_id"]').forEach(sel => {
    fillSelectObjects(sel, normalNodes, { placeholder: '未归位', label: nodeLabel });
  });
  return data;
}

function reagentColumns(showActions = false) {
  const columns = [
    { key: 'code', label: '编号' },
    { key: 'name', label: '名称' },
    { key: 'category', label: '类型', render: badge },
    { key: 'brand', label: '品牌' },
    { key: 'catalog_no', label: '货号' },
    { key: 'quantity', label: '数量', render: v => esc(v) },
    { key: 'price', label: '价格', render: v => esc(orderPriceText(v)) },
    { key: 'status', label: '状态', render: badge },
    { key: 'validation_status', label: '验证', render: badge },
    { key: 'storage_location', label: '位置', render: v => esc(locationText(v)) },
    { key: 'expiration_date', label: '有效期' },
  ];
  if (showActions) columns.push({
    key: 'id',
    label: '操作',
    render: (_, r) => inventoryActionButtons(r, 'reagent', {
      detailAction: 'detail-reagent',
      editAction: 'edit-reagent',
    }),
  });
  return columns;
}

function sampleColumns(showActions = false) {
  const columns = [
    { key: 'code', label: '系统编号', render: v => esc(v || '-') },
    { key: 'name', label: '样本号', render: v => esc(v || '-') },
    { key: 'category', label: '样本类型', render: badge },
    { key: 'amount', label: '规格', render: (_, r) => amountText(r) },
    { key: 'status', label: '状态', render: badge },
    { key: 'storage_location', label: '位置', render: v => esc(locationText(v)) },
    { key: 'entry_date', label: '入库日期' },
  ];
  if (showActions) columns.push({
    key: 'id',
    label: '操作',
    render: (_, r) => inventoryActionButtons(r, 'sample', { detailAction: 'detail-sample' }),
  });
  return columns;
}

function miniRows(rows, keys) {
  if (!rows || !rows.length) return '<p class="muted">暂无记录</p>';
  return `<div class="mini-rows">${rows.map(row => `<div>${keys.map(k => `<span>${esc(row[k])}</span>`).join('')}</div>`).join('')}</div>`;
}
