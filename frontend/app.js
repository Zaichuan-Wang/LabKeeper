function setLoggedIn(isLoggedIn) {
  $('loginView').classList.toggle('hidden', isLoggedIn);
  $('appView').classList.toggle('hidden', !isLoggedIn);
  $('userPanel').classList.toggle('hidden', !isLoggedIn);
  if (state.user) $('userName').textContent = `${state.user.display_name || state.user.username} · ${state.user.role}`;
  document.querySelectorAll('.admin-only').forEach(el => el.classList.toggle('hidden', !isLoggedIn || !isAdmin()));
  document.querySelectorAll('.inventory-manage-only').forEach(el => el.classList.toggle('hidden', !isLoggedIn || !canManageInventory()));
  document.querySelectorAll('.location-manage-only').forEach(el => el.classList.toggle('hidden', !isLoggedIn || !canManageLocation()));
  document.querySelectorAll('.inventory-search-only').forEach(el => el.classList.toggle('hidden', !isLoggedIn || !canSearchInventory()));
  const formAllowed = form => {
    if (!isLoggedIn) return false;
    if (form.id === 'loginForm') return true;
    if (form.closest('#admin')) return isAdmin();
    if (['reagentForm', 'sampleEditForm'].includes(form.id)) return canManageInventory();
    if (form.id === 'bulkForm') return canManageInventory();
    if (form.id === 'sampleForm') return state.registrationTab === 'samples' ? true : canManageInventory();
    if (form.id === 'aliquotForm') return canManageInventory();
    if (['nodeForm', 'movementForm'].includes(form.id)) return canManageLocation();
    return true;
  };
  document.querySelectorAll('form').forEach(form => {
    if (form.id === 'loginForm') return;
    const canWrite = formAllowed(form);
    form.querySelectorAll('button[type="submit"]').forEach(btn => { btn.disabled = !canWrite; });
  });
}

function logout(show = true) {
  if (state.token) void fetch(`${state.apiBase}/api/logout`, { method: 'POST', credentials: 'include' }).catch(() => {});
  state.token = '';
  state.user = null;
  localStorage.removeItem(SESSION_USER_KEY);
  setLoggedIn(false);
  if (show) toast('已退出登录');
}

async function acceptLogin(data, message) {
  state.token = 'cookie';
  state.user = data.user;
  localStorage.setItem(SESSION_USER_KEY, JSON.stringify(state.user));
  setLoggedIn(true);
  await loadOptions();
  switchView('dashboard');
  toast(message);
}

async function loginWithCredentials(credentials) {
  $('loginError').textContent = '';
  const data = await api('/api/login', { method: 'POST', body: JSON.stringify(credentials) });
  await acceptLogin(data, '登录成功');
}

async function loadRuntimeConfig() {
  try {
    const res = await fetch(`${state.apiBase}/api/runtime-config`, { credentials: 'include' });
    if (!res.ok) throw new Error(`runtime config ${res.status}`);
    state.runtime = await res.json();
  } catch (err) {
    state.runtime = { dev_tools_enabled: false, dev_admin_username: '', demo_database_available: false };
  }
  renderDevToolsPanel();
}

function renderDevToolsPanel() {
  const panel = $('devToolsPanel');
  if (!panel) return;
  const enabled = Boolean(state.runtime?.dev_tools_enabled);
  panel.classList.toggle('hidden', !enabled);
  if (!enabled) {
    panel.innerHTML = '';
    return;
  }
  panel.innerHTML = `
    <p class="form-note">开发工具已启用，仅用于本机测试。</p>
    <div class="dev-tools-actions">
      <button id="testAdminLoginBtn" class="ghost dev-login-shortcut" type="button">测试管理员登录</button>
      <button id="loadDemoDbBtn" class="ghost" type="button" >载入 Demo 数据库</button>
    </div>
  `;
  $('testAdminLoginBtn')?.addEventListener('click', guard(loginAsDevAdmin));
  $('loadDemoDbBtn')?.addEventListener('click', guard(loadDemoDatabase));
}

async function loginAsDevAdmin() {
  $('loginError').textContent = '';
  const data = await api('/api/dev/login', { method: 'POST', body: JSON.stringify({}) });
  await acceptLogin(data, '已用测试管理员登录');
}

async function loadDemoDatabase() {
  if (!confirm('载入 Demo 数据库会替换当前运行数据库，并先自动备份现有数据库。确定继续？')) return;
  if (!state.token || !state.user || !isAdmin()) await loginAsDevAdmin();
  const result = await api('/api/dev/load-demo-db', { method: 'POST', body: JSON.stringify({}) });
  toast(result.message || 'Demo 数据库已载入');
  await loginAsDevAdmin();
}

function canUseInventoryTab(tab) {
  if (tab === 'details') return canSearchInventory();
  if (tab === 'manual' || tab === 'bulk') return canManageInventory();
  if (tab === 'move' || tab === 'spaces') return canManageLocation();
  return true;
}

function canUseRegistrationTab(tab) {
  if (tab === 'samples' || tab === 'aliquots') return canManageInventory();
  return true;
}

function setWorkbenchTab(scope, tab, shouldLoad = true) {
  if (scope === 'inventory' && !canUseInventoryTab(tab)) tab = 'overview';
  if (scope === 'registration' && !canUseRegistrationTab(tab)) tab = 'orders';
  if (scope === 'registration') state.registrationTab = tab;
  if (scope === 'inventory') state.inventoryTab = tab;
  if (scope === 'history') state.historyTab = tab;
  if (scope === 'admin') state.adminTab = tab;
  if (scope === 'expiration') state.expirationTab = tab;
  document.querySelectorAll(`.tab-btn[data-tab-scope="${scope}"], #${scope} .tab-btn:not([data-tab-scope])`).forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
    btn.setAttribute('aria-selected', btn.dataset.tab === tab ? 'true' : 'false');
  });
  document.querySelectorAll(`.workbench-tab[data-tab-scope="${scope}"], #${scope} .inventory-tab[data-tab-panel]`).forEach(panel => {
    panel.classList.toggle('active-tab', panel.dataset.tabPanel === tab);
  });
  if (shouldLoad && (state.view === scope || (scope === 'expiration' && state.view === 'dashboard'))) void loadWorkbenchTab(scope, tab);
}

function setInventoryTab(tab, shouldLoad = true) {
  setWorkbenchTab('inventory', tab, shouldLoad);
}

function setRegistrationTab(tab, shouldLoad = true) {
  setWorkbenchTab('registration', tab, shouldLoad);
}

async function loadWorkbenchTab(scope, tab) {
  if (scope === 'registration') return loadRegistrationTab(tab);
  if (scope === 'inventory') return loadInventoryTab(tab);
  if (scope === 'history') return loadHistoryTab(tab);
  if (scope === 'admin') return loadAdminTab(tab);
  if (scope === 'expiration') return loadExpiration();
}





async function loadAdmin() {
  if (!isAdmin()) return;
  setWorkbenchTab('admin', state.adminTab, false);
  await loadAdminTab(state.adminTab);
}

async function loadAdminTab(tab = state.adminTab) {
  setLoggedIn(Boolean(state.token && state.user));
  if (!isAdmin()) return;
  if (tab === 'users') await loadUsers();
  if (tab === 'settings') fillSettingsForms();
  if (tab === 'maintenance') {
    await loadDataHealth();
    await loadBackups();
    await loadExcel();
  }
}

async function loadDashboard() {
  const data = await api('/api/dashboard');
  const m = data.metrics;
  const metrics = [
    ['全部库存', m.total_inventory],
    ['试剂/耗材', m.total_reagents],
    ['临床标本', m.total_samples],
    ['未归位', m.unplaced_inventory],
    ['待验证/复核', m.todo_validations],
    [`${m.remind_days}天内到期`, m.upcoming],
  ];
  $('metricGrid').innerHTML = metrics.map(([label, value]) => `<div class="metric-card"><span>${label}</span><strong>${value}</strong></div>`).join('');
  $('categoryBars').innerHTML = data.category_breakdown.map(i => `<span class="badge">${esc(i.category)} · ${i.n}</span>`).join('') || '<p>暂无分类数据</p>';
  $('statusPills').innerHTML = data.status_breakdown.map(i => `<span class="badge">${esc(i.status)} · ${i.n}</span>`).join('') || '<p>暂无状态数据</p>';
  $('spacePills').innerHTML = [
    ['空间节点', m.storage_nodes],
    ['带框架空间', m.framed_spaces],
    ['无框架空间', m.unframed_spaces],
  ].map(([label, value]) => `<span class="badge">${label} · ${value}</span>`).join('');
  await loadExpiration();
}

async function loadExpiration() {
  setWorkbenchTab('expiration', state.expirationTab || 'overdue', false);
  const days = $('expirationDays').value;
  $('expirationDaysText').textContent = `${days} 天`;
  const data = await api(`/api/expiration?days=${days}`);
  $('overdueCount').textContent = String(data.overdue.length);
  $('upcomingCount').textContent = String(data.upcoming.length);
  $('pendingOrderCount').textContent = String(data.pending_orders.length);
  $('unvalidatedAntibodyCount').textContent = String(data.unvalidated_antibodies.length);
  $('upcomingWindowText').textContent = `${data.remind_days} 天内`;
  const pendingColumns = [
    { key: 'name', label: '名称' },
    { key: 'category', label: '类型', render: badge },
    { key: 'brand', label: '品牌' },
    { key: 'catalog_no', label: '货号' },
    { key: 'quantity', label: '数量' },
    { key: 'arrival_status', label: '到货', render: badge },
    { key: 'updated_at', label: '更新时间' },
  ];
  const tables = {
    overdue: ['overdueTable', reagentColumns(false), data.overdue],
    upcoming: ['upcomingTable', reagentColumns(false), data.upcoming],
    pending: ['pendingOrderTable', pendingColumns, data.pending_orders],
    unvalidated: ['unvalidatedAntibodyTable', reagentColumns(false), data.unvalidated_antibodies],
  };
  const current = tables[state.expirationTab || 'overdue'] || tables.overdue;
  Object.values(tables).forEach(([tableId]) => {
    if (tableId !== current[0]) {
      const pager = $(`${tableId}Pager`);
      if (pager) pager.innerHTML = '';
    }
  });
  renderPagedTable(current[0], current[1], current[2], { pageSize: 12 });
}

async function confirmCatalogNameConflict({ catalogNo, name, excludeId = '' }) {
  const catalog = String(catalogNo || '').trim();
  const cleanName = String(name || '').trim();
  if (!catalog || !cleanName) return true;
  const params = new URLSearchParams({ catalog_no: catalog, name: cleanName });
  if (excludeId) params.set('exclude_id', excludeId);
  const result = await api(`/api/inventory/catalog-conflicts?${params}`);
  if (!result.has_conflict) return true;
  const examples = result.items.slice(0, 5).map(item => `- ${item.code || item.id}：${item.name}`).join('\n');
  return confirm(`货号“${catalog}”已有不同名称的试剂/耗材。\n验证记录按货号关联，继续保存可能把验证记录关联到不同名称。\n\n已有记录：\n${examples}\n\n确定继续？`);
}

async function loadCurrentView() {
  if (!state.token) return;
  try {
    if (!state.options) await loadOptions();
    const needsStorage = ['registration', 'inventory'].includes(state.view);
    if (needsStorage) await loadStorageTree();
    const loaders = { dashboard: loadDashboard, registration: loadRegistration, history: loadHistory, admin: loadAdmin, password: async () => {}, inventory: loadInventory };
    await loaders[state.view]?.();
    setLoggedIn(true);
  } catch (err) { toast(err.message); }
}

function switchView(view) {
  activateView(view);
  loadCurrentView();
}

function setDefaultDates() {
  document.querySelectorAll('input[type="date"]').forEach(input => {
    if (!input.value && ['entry_date', 'validation_date'].includes(input.name)) input.value = today();
  });
}

function applySidebarState(collapsed) {
  const shell = $('shell');
  const toggle = $('sidebarToggle');
  if (!shell || !toggle) return;
  shell.classList.toggle('sidebar-collapsed', collapsed);
  toggle.textContent = collapsed ? '›' : '‹';
  toggle.setAttribute('aria-label', collapsed ? '展开侧边栏' : '收起侧边栏');
  toggle.title = collapsed ? '展开侧边栏' : '收起侧边栏';
}

function initSidebarToggle() {
  const toggle = $('sidebarToggle');
  if (!toggle) return;
  applySidebarState(localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1');
  toggle.addEventListener('click', () => {
    const collapsed = !$('shell').classList.contains('sidebar-collapsed');
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? '1' : '0');
    applySidebarState(collapsed);
  });
}

function clampOverviewActionMenu(menu) {
  if (!menu) return;
  menu.style.transform = '';
  const margin = 12;
  const rect = menu.getBoundingClientRect();
  let x = 0;
  let y = 0;
  if (rect.right > window.innerWidth - margin) x = window.innerWidth - margin - rect.right;
  if (rect.left + x < margin) x += margin - (rect.left + x);
  if (rect.bottom > window.innerHeight - margin) y = window.innerHeight - margin - rect.bottom;
  if (rect.top + y < margin) y += margin - (rect.top + y);
  if (x || y) menu.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
}

function clampOpenOverviewMenus() {
  document.querySelectorAll('.overview-quick-actions[open] .overview-action-menu').forEach(clampOverviewActionMenu);
}

function wireLocationFields(kind, options = {}) {
  const cfg = pickerConfigs[kind];
  const form = cfg ? $(cfg.form) : null;
  if (!cfg || !form) return;
  const extraFields = options.extraFields || [];
  form.addEventListener('change', e => {
    options.onChange?.(e);
    const name = e.target.name;
    const shouldLoad = name === cfg.nodeField || name === cfg.positionField || extraFields.includes(name);
    if (!shouldLoad) return;
    if (name === cfg.nodeField) fillPositionSelect(form.elements[cfg.positionField], e.target.value);
    options.onBeforeLoad?.(e);
    void loadLocationPicker(kind);
  });
}

function wireEvents() {
  $('loginForm').addEventListener('submit', async e => { e.preventDefault(); try { await loginWithCredentials(formData(e.currentTarget)); } catch (err) { $('loginError').textContent = err.message; } });
  $('logoutBtn').addEventListener('click', () => logout(true));
  $('refreshBtn').addEventListener('click', loadCurrentView);
  document.querySelectorAll('.nav-item').forEach(btn => btn.addEventListener('click', () => switchView(btn.dataset.view)));
  document.querySelectorAll('.tab-btn[data-tab]').forEach(btn => btn.addEventListener('click', () => setWorkbenchTab(btn.dataset.tabScope || 'inventory', btn.dataset.tab)));
  document.querySelectorAll('[data-manual-mode]').forEach(btn => btn.addEventListener('click', () => setManualMode(btn.dataset.manualMode)));
  document.body.addEventListener('click', handleActions);
  $('locationPickerDialog')?.addEventListener('click', e => {
    if (e.target.id === 'locationPickerDialog') void closeLocationPicker();
  });
  document.body.addEventListener('toggle', e => {
    if (e.target.matches?.('.overview-quick-actions[open]')) requestAnimationFrame(clampOpenOverviewMenus);
  }, true);
  window.addEventListener('resize', clampOpenOverviewMenus);
  $('orderForm').addEventListener('submit', guard(async e => {
    e.preventDefault();
    const form = e.currentTarget;
    const data = formData(form);
    if (!(await confirmCatalogNameConflict({ catalogNo: data.catalog_no, name: data.name }))) return;
    await api('/api/orders', { method: 'POST', body: JSON.stringify(data) });
    resetForm(form);
    toast('订购登记已保存');
    await loadRegistrationTab('orders');
  }));
  $('repeatOrderSearch').addEventListener('input', () => {
    clearTimeout(window.__repeatOrderSearchTimer);
    window.__repeatOrderSearchTimer = setTimeout(() => { void loadRepeatOrderCandidates(); }, 250);
  });
  $('repeatOrderSelect').addEventListener('change', renderRepeatOrderSummary);
  wireLocationFields('arrival', {
    onChange: e => {
      if (e.target.name === 'order_id') renderArrivalSummary();
      if (e.target.name === 'arrival_quantity') syncMultiRegisterFields(e.currentTarget);
    },
  });
  $('arrivalForm').addEventListener('submit', guard(async e => {
    e.preventDefault();
    const form = e.currentTarget;
    const data = formData(form);
    const result = await api('/api/arrivals', { method: 'POST', body: JSON.stringify(data) });
    resetForm(form);
    setDefaultDates();
    setDefaultDropdownValues();
    syncMultiRegisterFields(form);
    toast(data.separate_items === false && Number(data.arrival_quantity || 1) > 1 ? `到货已保存为 1 条记录，数量 ${data.arrival_quantity}` : (result.count > 1 ? `已分别登记 ${result.count} 件到货` : '到货登记完成'));
    await loadRegistrationTab('arrivals');
  }));
  $('arrivalForm').elements.arrival_quantity.addEventListener('input', e => syncMultiRegisterFields(e.currentTarget.form));
  $('validationForm').elements.method.addEventListener('change', e => $('validationOtherLabel').classList.toggle('hidden', e.target.value !== '其他'));
  $('validationReagentSearch').addEventListener('input', () => {
    clearTimeout(window.__validationSearchTimer);
    window.__validationSearchTimer = setTimeout(() => { void loadReagentCache(); }, 250);
  });
  $('validationForm').elements.item_id.addEventListener('change', e => {
    const reagent = state.reagents.find(r => Number(r.id) === Number(e.target.value));
    if (reagent?.catalog_no) e.currentTarget.form.elements.catalog_no.value = reagent.catalog_no;
  });
  $('validationForm').addEventListener('submit', guard(submitValidation));
  $('newReagentBtn').addEventListener('click', () => void startNewReagent());
  wireLocationFields('reagent', {
    extraFields: ['status', 'quantity'],
    onBeforeLoad: e => {
      if (['status', 'quantity', 'storage_node_id', 'position_in_box'].includes(e.target.name)) syncReagentStorageFields(e.currentTarget);
      if (e.target.name === 'quantity') syncMultiRegisterFields(e.currentTarget);
    },
  });
  $('reagentForm').addEventListener('submit', guard(submitReagent));
  $('reagentForm').elements.quantity.addEventListener('input', e => {
    syncReagentStorageFields(e.currentTarget.form);
    syncMultiRegisterFields(e.currentTarget.form);
  });
  wireLocationFields('sampleEdit');
  $('sampleEditForm').addEventListener('submit', guard(submitSampleEdit));
  wireLocationFields('sample');
  $('sampleForm').elements.tube_count.addEventListener('input', e => syncMultiRegisterFields(e.currentTarget.form));
  $('sampleForm').addEventListener('submit', guard(submitSample));
  $('aliquotForm').addEventListener('change', async e => {
    if (e.target.name === 'item_type') {
      state.aliquotItemType = e.target.value;
      await loadAliquotCandidates();
    }
    if (e.target.name === 'source_item_id') renderAliquotSourceSummary();
  });
  wireLocationFields('aliquot');
  $('aliquotSourceSearch').addEventListener('input', () => {
    clearTimeout(window.__aliquotSearchTimer);
    window.__aliquotSearchTimer = setTimeout(() => { void loadAliquotCandidates(); }, 250);
  });
  $('aliquotForm').addEventListener('submit', guard(submitAliquot));
  $('excelExportForm').addEventListener('submit', guard(submitExcelExport));
  $('excelImportForm').addEventListener('submit', guard(submitExcelImport));
  $('backupForm')?.addEventListener('submit', guard(submitBackup));
  $('backupSettingsForm')?.addEventListener('submit', guard(submitBackupSettings));
  $('backupCleanupForm')?.addEventListener('submit', guard(submitBackupCleanup));
  $('movementForm').addEventListener('change', async e => {
    if (e.target.name === 'item_type') {
      state.moveItemType = e.target.value;
      state.moveItemId = null;
      await loadMoveItems();
    }
    if (e.target.name === 'item_id') {
      state.moveItemId = e.target.value;
      renderMoveSummary();
    }
    if (e.target.name === 'position_in_box') {
      state.moveWell = e.target.value;
      renderMoveSummary();
      await loadLocationPicker('movement');
    }
  });
  $('movementForm').elements.keyword.addEventListener('input', () => {
    clearTimeout(window.__moveKeywordTimer);
    window.__moveKeywordTimer = setTimeout(() => {
      state.moveItemId = null;
      void loadMoveItems();
    }, 250);
  });
  $('movementForm').addEventListener('submit', guard(submitMovement));
  $('bulkForm')?.addEventListener('change', e => {
    if (['operation', 'item_type', 'mode'].includes(e.target.name)) {
      state.bulkPreview = [];
      $('bulkCommitBtn').disabled = true;
      syncBulkFields();
    }
  });
  $('bulkForm')?.addEventListener('submit', guard(submitBulkPreview));
  $('bulkCommitBtn')?.addEventListener('click', guard(commitBulkRows));
  $('checkoutForm').addEventListener('change', guard(async e => {
    if (e.target.name === 'item_type') {
      state.checkoutItemType = e.target.value;
      state.checkoutItemId = null;
      await loadCheckouts();
    }
    if (e.target.name === 'item_id') {
      state.checkoutItemId = e.target.value;
      renderCheckoutSummary();
    }
  }));
  $('checkoutForm').elements.keyword.addEventListener('input', () => {
    clearTimeout(window.__checkoutKeywordTimer);
    window.__checkoutKeywordTimer = setTimeout(() => {
      state.checkoutItemId = null;
      void loadCheckoutItems();
    }, 250);
  });
  $('checkoutForm').addEventListener('submit', guard(submitCheckout));
  $('expirationDays').addEventListener('input', () => {
    $('expirationDaysText').textContent = `${$('expirationDays').value} 天`;
    ['overdueTable', 'upcomingTable', 'pendingOrderTable', 'unvalidatedAntibodyTable'].forEach(key => { state.tablePages[key] = 1; });
  });
  $('refreshExpiration').addEventListener('click', loadExpiration);
  $('newUserBtn').addEventListener('click', startNewUser);
  $('userForm').elements.role.addEventListener('change', syncUserPermissionFields);
  $('userForm').addEventListener('submit', guard(submitUser));
  $('passwordForm').addEventListener('submit', guard(submitPassword));
  $('settingsForm').addEventListener('submit', guard(async e => { e.preventDefault(); await saveSettings(); }));
  $('settingsForm').addEventListener('keydown', e => {
    if (e.key === 'Enter' && e.target.matches('[data-settings-input]')) {
      e.preventDefault();
      addSettingsOption(e.target.dataset.settingsInput);
    }
  });
  $('nodeForm').elements.node_type.addEventListener('change', e => {
    const form = $('nodeForm');
    const layout = defaultSpaceLayout(e.target.value);
    if (!form.elements.rows.value) form.elements.rows.value = layout.rows;
    if (!form.elements.cols.value) form.elements.cols.value = layout.cols;
    updateNodeDimensionLabels();
  });
  $('unframedSpaceBtn')?.addEventListener('click', setSpaceUnframed);
  $('deleteSpaceBtn')?.addEventListener('click', guard(async () => { await deleteCurrentSpace($('nodeForm').elements.id.value); }));
  $('nodeForm').addEventListener('submit', guard(submitSpace));
  $('inventoryItemType').addEventListener('change', () => {
    state.inventoryItemTypeFilter = $('inventoryItemType').value;
    state.tablePages.inventoryTable = 1;
    syncInventoryFilterVisibility();
    void searchInventory();
  });
  $('inventorySearchBtn').addEventListener('click', searchInventory);
  setupInventoryDragMove();
}

function setupInventoryDragMove() {
  let draggingCard = null;
  const dragPayload = target => {
    const card = target?.closest?.('[data-drag-type][data-drag-id]');
    if (!card || !canManageLocation()) return null;
    return { item_type: card.dataset.dragType || 'reagent', item_id: card.dataset.dragId };
  };
  const dropTarget = target => target?.closest?.('[data-drop-node], [data-drop-storage-parent]');
  const clearDragState = () => {
    draggingCard?.classList.remove('dragging');
    draggingCard = null;
    document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
  };
  document.body.addEventListener('dragstart', e => {
    const payload = dragPayload(e.target);
    if (!payload || !e.dataTransfer) return;
    draggingCard = e.target.closest('[data-drag-type][data-drag-id]');
    draggingCard?.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('application/json', JSON.stringify(payload));
    e.dataTransfer.setData('text/plain', `${payload.item_type}:${payload.item_id}`);
  });
  document.body.addEventListener('dragend', clearDragState);
  document.body.addEventListener('dragover', e => {
    const target = dropTarget(e.target);
    if (!target || !canManageLocation()) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    target.classList.add('drag-over');
  });
  document.body.addEventListener('dragleave', e => {
    const target = dropTarget(e.target);
    if (target && !target.contains(e.relatedTarget)) target.classList.remove('drag-over');
  });
  document.body.addEventListener('drop', guard(async e => {
    const target = dropTarget(e.target);
    if (!target || !canManageLocation()) return;
    e.preventDefault();
    const raw = e.dataTransfer?.getData('application/json') || '';
    const payload = raw ? JSON.parse(raw) : null;
    clearDragState();
    if (!payload?.item_id) return;
    if (payload.item_type === 'storage-node') await moveStorageNodeByDrop(payload, target);
    else await moveInventoryByDrop(payload, target);
  }));
}

async function moveStorageNodeByDrop(payload, target) {
  if (!canManageLocation()) {
    toast('当前账号没有位置维护权限');
    return;
  }
  const targetNode = nodeById(target.dataset.dropNode);
  const toUnplaced = target.dataset.dropUnplaced === '1' || isVirtualUnplacedId(target.dataset.dropNode);
  const parentId = toUnplaced ? '' : (target.dataset.dropStorageParent || (targetNode ? target.dataset.dropNode : ''));
  if (!toUnplaced && !parentId) {
    toast('空间只能拖到框架空位、空间卡片或未归位');
    return;
  }
  if (parentId && Number(payload.item_id) === Number(parentId)) {
    toast('不能把空间拖到自己下面');
    return;
  }
  const hasGridTarget = Boolean(!toUnplaced && target.dataset.dropStorageParent && target.dataset.dropRow && target.dataset.dropCol);
  await api(`/api/storage/nodes/${payload.item_id}`, {
    method: 'PATCH',
    body: JSON.stringify({
      parent_id: parentId,
      grid_row: hasGridTarget ? target.dataset.dropRow : '',
      grid_col: hasGridTarget ? target.dataset.dropCol : '',
    }),
  });
  state.selectedNodeId = toUnplaced ? VIRTUAL_UNPLACED_NODE_ID : parentId;
  state.selectedWell = '';
  state.selectedItemType = '';
  state.selectedItemId = null;
  toast(hasGridTarget ? '空间框架位置已更新' : (toUnplaced ? '空间已移到未归位' : '空间已移动到目标空间下'));
  await loadInventory();
}

async function moveInventoryByDrop(payload, target) {
  if (!canManageLocation()) {
    toast('当前账号没有位置维护权限');
    return;
  }
  const toUnplaced = target.dataset.dropUnplaced === '1' || isVirtualUnplacedId(target.dataset.dropNode);
  if (target.dataset.dropStorageParent && !target.dataset.dropNode && !toUnplaced) {
    toast('库存请拖到具体空间、格位或未归位区');
    return;
  }
  const nodeId = target.dataset.dropNode;
  if (!nodeId && !toUnplaced) return;
  const well = toUnplaced ? '' : (target.dataset.dropWell || '');
  const result = await api('/api/movements', {
    method: 'POST',
    body: JSON.stringify({
      item_type: payload.item_type === 'sample' ? 'sample' : 'reagent',
      item_id: payload.item_id,
      to_storage_node_id: toUnplaced ? '' : nodeId,
      position_in_box: well,
      reason: '拖拽移动',
    }),
  });
  state.selectedNodeId = toUnplaced ? VIRTUAL_UNPLACED_NODE_ID : nodeId;
  state.selectedWell = well;
  state.selectedItemType = payload.item_type === 'sample' ? 'sample' : 'reagent';
  state.selectedItemId = payload.item_id;
  toast(result?.item?.unchanged ? '位置未变化，未新增移动记录' : (well ? `已移动到格位 ${well}` : '已移动到未归位区'));
  await loadInventory();
}

function guard(fn) {
  return async event => {
    try {
      await fn(event);
    } catch (err) {
      toast(err.message || String(err));
    }
  };
}

async function handleActions(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) {
    if (!e.target.closest('#positionActionMenu')) closePositionActionMenu?.();
    if (e.target.id === 'inventoryDetailDialog') closeInventoryDetailDialog?.();
    return;
  }
  e.preventDefault();
  const action = btn.dataset.action;
  const id = btn.dataset.id;
  const fromPositionMenu = btn.closest('#positionActionMenu');
  const fromInventoryDetail = btn.closest('#inventoryDetailDialog');
  if (fromPositionMenu && action !== 'position-actions') closePositionActionMenu?.();
  if (fromInventoryDetail && action !== 'close-inventory-detail') closeInventoryDetailDialog?.();
  if (await handleDetailActions(action, id)) return;
  if (await handleInventoryActions(action, id, btn)) return;
  if (await handleSpaceActions(action, id, btn)) return;
  if (await handlePickerActions(action, id, btn)) return;
  if (await handleAdminActions(action, id, btn)) return;
  await handleRegistrationActions(action, id);
}

async function handleDetailActions(action, id) {
  if (action === 'edit-reagent') {
    await editReagent(id);
    return true;
  }
  if (action === 'detail-reagent') {
    renderReagentDetail(await api(inventoryObjectDetailPath('reagent', id)));
    return true;
  }
  if (action === 'detail-sample') {
    renderSampleDetail(await api(inventoryObjectDetailPath('sample', id)));
    return true;
  }
  return false;
}

async function handleInventoryActions(action, id, btn) {
  if (action === 'inventory-row-detail') {
    state.selectedItemType = 'reagent';
    state.selectedItemId = id;
    state.selectedWell = '';
    await showInventoryItemDetailDialog('reagent', id);
    return true;
  }
  if (action === 'inventory-sample-detail') {
    state.selectedItemType = 'sample';
    state.selectedItemId = id;
    state.selectedWell = '';
    await showInventoryItemDetailDialog('sample', id);
    return true;
  }
  if (action === 'inventory-row-edit') { await openReagentEditor(id); return true; }
  if (action === 'sample-row-edit') { await openSampleEditor(id); return true; }
  if (action === 'inventory-row-move') { await openReagentMover(id); return true; }
  if (action === 'sample-row-move') { await openInventoryMover('sample', id); return true; }
  if (action === 'inventory-row-checkout') { await openCheckout('reagent', id); return true; }
  if (action === 'sample-row-checkout') { await openCheckout('sample', id); return true; }
  if (action === 'bulk-download-template') { await downloadBulkTemplate(); return true; }
  if (action === 'bulk-download-current') { await downloadBulkCurrentInventory(); return true; }
  if (action === 'bulk-download-storage-map') { await downloadStorageMap(); return true; }
  if (action === 'bulk-load-excel') { await loadBulkExcel(); return true; }
  if (action === 'inventory-node') {
    state.selectedNodeId = id;
    state.selectedWell = '';
    state.selectedItemType = '';
    state.selectedItemId = null;
    await loadInventory();
    return true;
  }
  if (action === 'inventory-reagent') {
    state.selectedItemType = 'reagent';
    state.selectedItemId = id;
    state.selectedWell = '';
    await loadInventory();
    return true;
  }
  if (action === 'inventory-item') {
    state.selectedItemType = btn.dataset.type || 'reagent';
    state.selectedItemId = id;
    state.selectedWell = '';
    await showInventoryItemDetailDialog(state.selectedItemType, id);
    return true;
  }
  if (action === 'close-inventory-detail') {
    closeInventoryDetailDialog?.();
    return true;
  }
  if (action === 'table-page') {
    state.tablePages[btn.dataset.table] = Number(btn.dataset.page || 1);
    await refreshPagedTable(btn.dataset.table);
    return true;
  }
  return false;
}

async function refreshPagedTable(tableKey = '') {
  if (tableKey.startsWith('history')) return loadHistoryTab(state.historyTab);
  if (tableKey === 'inventoryTable') return searchInventory();
  if (tableKey === 'bulkPreviewTable') return renderPagedTable('bulkPreviewTable', [
    { key: 'row_no', label: '行号' },
    { key: 'status', label: '状态', render: v => v === 'ok' ? badge('可提交') : badge('有问题') },
    { key: 'action', label: '处理' },
    { key: 'summary', label: '确认内容', render: v => esc(v || '-') },
    { key: 'errors', label: '提示', render: v => esc((v || []).join('；') || '-') },
    { key: 'source', label: '原始数据', render: v => esc(Object.entries(v || {}).filter(([key]) => key !== '_row_no').slice(0, 6).map(([key, value]) => `${key}:${value}`).join('；')) },
  ], state.bulkPreview || [], { pageSize: 12 });
  if (tableKey === 'userTable') return loadUsers();
  if (['overdueTable', 'upcomingTable', 'pendingOrderTable', 'unvalidatedAntibodyTable'].includes(tableKey)) return loadExpiration();
}

async function handleSpaceActions(action, id, btn) {
  const nodeId = btn.dataset.nodeId || id;
  const well = btn.dataset.well || '';
  if (action === 'new-root-space') { await startNewRootSpace(); return true; }
  if (action === 'new-child-space') { await startNewChildSpace(id, btn.dataset.row || '', btn.dataset.col || ''); return true; }
  if (action === 'edit-current-space') { await openSpaceEditor(id); return true; }
  if (action === 'delete-current-space') { await deleteCurrentSpace(id); return true; }
  if (action === 'position-actions') {
    showPositionActions({
      nodeId,
      well,
      row: btn.dataset.row || '',
      col: btn.dataset.col || '',
      label: btn.dataset.label || '',
      anchor: btn,
    });
    return true;
  }
  if (action === 'new-sample-at') { await startNewSampleAt(nodeId, well); return true; }
  if (action === 'new-reagent-at') { await startNewReagentAt(nodeId, well); return true; }
  if (action === 'move-into-space') { await startMoveIntoSpace(nodeId, well); return true; }
  return false;
}

async function handlePickerActions(action, id, btn) {
  const actions = {
    'open-location-picker': () => openLocationPicker(btn.dataset.kind),
    'close-location-picker': () => closeLocationPicker(),
    'use-storage': () => applySelectedStorage(id),
    'picker-node': () => browsePickerNode(btn.dataset.kind, id),
    'picker-current': () => applyPickerNode(btn.dataset.kind, id),
    'picker-well': () => setPickerWell(btn.dataset.kind, id),
    'picker-occupied-well': () => toast('该格位已占用，请选择空格位'),
  };
  const handler = actions[action];
  if (!handler) return false;
  await handler();
  return true;
}

async function handleAdminActions(action, id, btn) {
  const actions = {
    'edit-user': () => editUser(id),
    'reset-user-password': () => resetUserPassword(id),
    'settings-add': () => addSettingsOption(id),
    'settings-remove': () => removeSettingsOption(btn),
    'download-backup': () => downloadBackup(id),
    'delete-backup': () => deleteBackup(id),
  };
  const handler = actions[action];
  if (!handler) return false;
  await handler();
  return true;
}

async function handleRegistrationActions(action, id) {
  const actions = {
    'repeat-order-fill': () => fillOrderFromRepeatItem(),
    'aliquot-use-source-location': () => useAliquotSourceLocation(),
    'rollback-movement': () => rollbackMovement(id),
  };
  const handler = actions[action];
  if (!handler) return false;
  await handler();
  return true;
}

async function submitPassword(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const data = formData(form);
  if (data.new_password !== data.new_password2) throw new Error('两次输入的新密码不一致');
  await api('/api/me/password', { method: 'PATCH', body: JSON.stringify(data) });
  resetForm(form);
  toast('密码已更新');
}

async function boot() {
  initSidebarToggle();
  await loadRuntimeConfig();
  wireEvents();
  setDefaultDates();
  setLoggedIn(Boolean(state.token && state.user));
  if (state.token && state.user) {
    await loadOptions();
    await loadCurrentView();
  }
}

boot();
