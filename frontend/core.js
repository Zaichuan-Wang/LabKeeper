const SESSION_USER_KEY = 'labkeeper_user';
const SIDEBAR_COLLAPSED_KEY = 'labkeeper_sidebar_collapsed';
const STATUS_ORDERED = '已订购';
const STATUS_AVAILABLE = '可用';
const STATUS_DISABLED = '停用';
const STATUS_CONSUMED = '已耗尽';
const VALIDATION_UNVERIFIED = '未验证';
const PHYSICAL_INVENTORY_STATUSES = new Set([STATUS_AVAILABLE, STATUS_DISABLED]);

const state = {
  // ── 会话 ──
  apiBase: getApiBase(),
  token: localStorage.getItem(SESSION_USER_KEY) ? 'cookie' : '',
  user: readStoredUser(),
  runtime: { dev_tools_enabled: false, dev_admin_username: '', demo_database_available: false },
  options: null,
  view: 'dashboard',
  tablePages: {},
  // ── 空间与选中状态 ──
  storageNodes: [],
  selectedNodeId: null,
  selectedWell: '',
  selectedItemType: '',
  selectedItemId: null,
  // ── 库存筛选 ──
  inventoryItemTypeFilter: 'all',
  inventoryRows: [],
  // ── 移动 ──
  moveTargetId: null,
  moveItemType: 'reagent',
  moveItemId: null,
  moveWell: '',
  moveItems: [],
  // ── 出库 ──
  checkoutItems: [],
  checkoutItemType: 'reagent',
  checkoutItemId: null,
  // ── 批量 ──
  bulkRows: [],
  bulkPreview: [],
  // ── 登记 ──
  reagents: [],
  aliquotCandidates: [],
  aliquotItemType: 'sample',
  orders: [],
  repeatOrderItems: [],
  // ── 位置选择器 ──
  activeLocationPicker: null,
  locationPickerDraft: null,
  // ── 管理员 ──
  users: [],
  excelTables: [],
  // ── 选项卡 ──
  registrationTab: 'orders',
  inventoryTab: 'overview',
  historyTab: 'orders',
  adminTab: 'users',
  expirationTab: 'overdue',
  manualMode: 'reagent',
};

function getApiBase() {
  const { protocol, hostname, port } = window.location;
  if ((hostname === '127.0.0.1' || hostname === 'localhost') && port && port !== '8000') return `${protocol}//${hostname}:8000`;
  return '';
}

function readStoredUser() {
  try {
    return JSON.parse(localStorage.getItem(SESSION_USER_KEY) || 'null');
  } catch {
    localStorage.removeItem(SESSION_USER_KEY);
    return null;
  }
}

const $ = id => document.getElementById(id);
const fmt = value => value === null || value === undefined || value === '' ? '-' : value;
const esc = value => String(fmt(value)).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const locationText = value => (value === null || value === undefined || value === '' ? '未放置' : value);
const today = () => new Date().toISOString().slice(0, 10);
const isAdmin = () => state.user?.role === 'admin';
function can(permissionKey) {
  if (isAdmin()) return true;
  return Boolean(state.user?.permissions?.[permissionKey]);
}
const canManageInventory = () => can('inventory.manage');
const canManageLocation = () => can('location.manage');
const canSearchInventory = () => can('inventory.search');
const VIEW_TITLES = {
  dashboard: '工作台',
  registration: '登记入库',
  history: '流转记录',
  admin: '管理员',
  password: '账号密码',
  inventory: '库存空间',
};

function toast(message) {
  const el = $('toast');
  el.textContent = message;
  el.classList.remove('hidden');
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => el.classList.add('hidden'), 2800);
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const body = options.body;
  if (!(body instanceof FormData)) headers['Content-Type'] = headers['Content-Type'] || 'application/json';
  const res = await fetch(`${state.apiBase}${path}`, { ...options, headers, credentials: 'include' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401) logout(false);
    throw new Error(data.error || `请求失败：${res.status}`);
  }
  return data;
}

async function downloadWithAuth(path, filename = '') {
  const res = await fetch(`${state.apiBase}${path}`, { credentials: 'include' });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || `下载失败：${res.status}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function formData(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  form.querySelectorAll('input[type="checkbox"][name]').forEach(input => { data[input.name] = input.checked; });
  return data;
}

function setFormValues(form, values = {}) {
  if (!form) return;
  Object.entries(values).forEach(([key, value]) => {
    const input = form.elements[key];
    if (!input) return;
    if (input.type === 'checkbox') input.checked = Boolean(value);
    else input.value = value ?? '';
  });
}

function resetForm(form) {
  if (!form) return;
  form.reset();
  form.querySelectorAll('input[type="hidden"]').forEach(input => { input.value = ''; });
  form.querySelectorAll('[data-multi-register-row] input[type="checkbox"]').forEach(input => { input.checked = true; });
}

function activateView(view) {
  state.view = view;
  document.querySelectorAll('.nav-item').forEach(btn => btn.classList.toggle('active', btn.dataset.view === view));
  document.querySelectorAll('.view').forEach(el => el.classList.toggle('active-view', el.id === view));
  if ($('viewTitle')) $('viewTitle').textContent = VIEW_TITLES[view] || view;
}

function inventoryObjectType(itemOrType, fallback = 'reagent') {
  const raw = typeof itemOrType === 'string' ? itemOrType : itemOrType?.item_type;
  if (raw === 'space') return 'space';
  return raw === 'sample' ? 'sample' : fallback === 'sample' ? 'sample' : 'reagent';
}

function inventorySearchType(type = 'all') {
  return ['reagent', 'sample', 'space', 'all'].includes(type) ? type : 'all';
}

function inventoryObjectTypeLabel(itemOrType, fallback = 'reagent') {
  const raw = typeof itemOrType === 'string' ? itemOrType : itemOrType?.item_type;
  if (raw === 'space') return '空间';
  return inventoryObjectType(itemOrType, fallback) === 'sample' ? '临床标本' : '试剂/耗材';
}

function inventoryObjectListPath(type, params) {
  const query = params instanceof URLSearchParams ? params.toString() : String(params || '');
  const itemType = inventoryObjectType(type);
  const search = new URLSearchParams(query);
  search.set('type', itemType);
  search.set('purpose', search.get('purpose') || 'global');
  return `/api/inventory/search?${search.toString()}`;
}

function inventoryObjectDetailPath(type, id) {
  return `/api/inventory/items/${inventoryObjectType(type)}/${id}`;
}

function inventoryObjectCode(item, fallbackType = 'reagent') {
  if (!item) return '';
  return item.code || item.id;
}

function inventoryObjectName(item, fallbackType = 'reagent', emptyText = '请选择库存对象') {
  if (!item) return emptyText;
  if (item.item_type === 'space') return item.name || item.display_title || item.code || item.id;
  return item.name || item.display_name || item.code || item.id;
}

function sampleTubeText(item) {
  if (!item?.aliquot_no) return '';
  return item.aliquot_total ? `${item.aliquot_no}/${item.aliquot_total}` : String(item.aliquot_no);
}

function reagentAliquotText(item) {
  if (!item?.aliquot_no) return '';
  return item.aliquot_total ? `${item.aliquot_no}/${item.aliquot_total}` : String(item.aliquot_no);
}

function inventoryObjectSelectLabel(item, fallbackType = 'reagent') {
  const type = inventoryObjectType(item, fallbackType);
  if (type === 'sample') {
    const source = inventoryObjectCode(item, type);
    const category = item.category ? ` | ${item.category}` : '';
    return `${source} | ${item.name || '临床标本'}${category} | ${locationText(item.storage_location)}`;
  }
  const brand = item.brand ? ` | ${item.brand}` : '';
  const catalog = item.catalog_no ? ` | ${item.catalog_no}` : '';
  const source = item.source_code && item.source_code !== item.code ? ` | 来源 ${item.source_code}` : '';
  return `${inventoryObjectCode(item, type)} | ${item.name || '试剂'}${brand}${catalog}${source} | ${locationText(item.storage_location)}`;
}

function inventoryObjectAvailable(item, fallbackType = 'reagent') {
  if (!item) return false;
  return PHYSICAL_INVENTORY_STATUSES.has(item.status);
}

async function searchInventoryObjects({ type = 'all', keyword = '', available = false, limit = 80, explicitId = null, params = {}, purpose = 'form' } = {}) {
  const itemType = inventorySearchType(type);
  const query = new URLSearchParams({ type: itemType, limit: String(limit), purpose });
  if (keyword) query.set('keyword', keyword);
  if (available) query.set('available', '1');
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') query.set(key, value);
  });
  const data = await api(`/api/inventory/search?${query}`);
  let items = data.items || [];
  if (explicitId && itemType !== 'all' && !items.some(item => Number(item.id) === Number(explicitId))) {
    const detail = await api(inventoryObjectDetailPath(itemType, explicitId));
    const explicitItem = { ...detail.item, item_type: itemType };
    if (!available || inventoryObjectAvailable(explicitItem, itemType)) items = [explicitItem, ...items];
  }
  return { ...data, items, count: items.length };
}
