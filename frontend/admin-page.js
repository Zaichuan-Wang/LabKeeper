async function loadExcel() {
  const data = await api('/api/excel/tables');
  state.excelTables = data.items;
  $('excelTableCount').textContent = `可操作 ${data.count} 张底层表`;
  fillSelectObjects($('excelExportForm').elements.table, data.items, { placeholder: '全部表', valueKey: 'name', label: t => t.name });
  fillSelectObjects($('excelImportForm').elements.table, data.items, { placeholder: '请选择表', valueKey: 'name', label: t => t.name });
}

async function loadUsers() {
  const data = await api('/api/users');
  state.users = data.items;
  $('userCount').textContent = `${data.count} 个`;
  renderPagedTable('userTable', [
    { key: 'id', label: 'ID' }, { key: 'username', label: '用户名' }, { key: 'display_name', label: '显示名' }, { key: 'role', label: '角色', render: badge }, { key: 'permissions', label: '权限', render: (_, r) => userPermissionSummary(r) }, { key: 'is_active', label: '启用', render: v => v ? '是' : '否' }, { key: 'updated_at', label: '更新时间' }, { key: 'id', label: '操作', render: (_, r) => `${actionButton('编辑', 'edit-user', r.id)} ${actionButton('重置密码', 'reset-user-password', r.id, 'danger')}` }
  ], data.items, { pageSize: 20 });
}

async function loadDataHealth() {
  const data = await api('/api/admin/data-health');
  state.dataHealth = data;
  renderDataHealth(data);
}

function renderDataHealth(data) {
  const summary = data.summary || {};
  $('dataHealthCheckedAt').textContent = summary.checked_at ? `检查时间：${summary.checked_at}` : '尚未检查';
  $('dataHealthSummary').innerHTML = [
    ['错误类问题', summary.errors || 0],
    ['警告类问题', summary.warnings || 0],
    ['检查项', (data.items || []).length],
  ].map(([label, value]) => `<div class="metric-card"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('');
  const items = data.items || [];
  const problemItems = items.filter(item => Number(item.count || 0) > 0);
  if (!problemItems.length) {
    $('dataHealthItems').innerHTML = '<div class="empty-state">未发现明显数据问题。</div>';
    return;
  }
  $('dataHealthItems').innerHTML = problemItems.map(item => renderHealthItem(item)).join('');
}

function renderHealthItem(item) {
  const examples = item.examples || [];
  const keys = healthExampleKeys(examples);
  const body = examples.length
    ? `<div class="table-wrap compact"><table>${renderTableHead(keys.map(key => ({ key, label: healthKeyLabel(key) })))}<tbody>${examples.map(row => `<tr>${keys.map(key => `<td>${esc(row[key])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`
    : '<p class="muted">暂无示例</p>';
  return `
    <article class="health-item ${item.severity === 'error' ? 'critical' : 'warm'}">
      <div class="section-head"><h4>${esc(item.label)}</h4><span>${badge(item.severity === 'error' ? '错误' : '警告')} ${esc(item.count)} 条</span></div>
      ${body}
    </article>
  `;
}

function healthExampleKeys(examples) {
  const priority = ['item_type', 'id', 'code', 'source_code', 'name', 'category', 'catalog_no', 'aliquot_no', 'storage_node_id', 'position_in_box', 'count', 'location', 'names', 'objects', 'message'];
  const existing = new Set(examples.flatMap(row => Object.keys(row || {})));
  return priority.filter(key => existing.has(key)).concat([...existing].filter(key => !priority.includes(key))).slice(0, 8);
}

function healthKeyLabel(key) {
  return ({
    item_type: '对象',
    id: 'ID',
    code: '编号',
    source_code: '来源编号',
    name: '名称/样本号',
    category: '类型',
    catalog_no: '货号',
    aliquot_no: '管号',
    storage_node_id: '空间ID',
    position_in_box: '孔位',
    count: '数量',
    location: '位置',
    names: '名称',
    objects: '对象',
    message: '提示',
  })[key] || key;
}

async function loadBackups() {
  const data = await api('/api/admin/backups');
  state.backups = data.items || [];
  state.backupSettings = data.settings || {};
  $('backupCount').textContent = `${data.count || 0} 个`;
  renderBackupSettings(state.backupSettings);
  renderPagedTable('backupTable', [
    { key: 'created_at', label: '创建时间' },
    { key: 'reason', label: '原因' },
    { key: 'filename', label: '文件名' },
    { key: 'size', label: '大小', render: humanFileSize },
    { key: 'integrity_check', label: '完整性', render: v => badge(v === 'ok' ? 'ok' : v) },
    {
      key: 'filename',
      label: '操作',
      render: v => `${actionButton('下载', 'download-backup', v)} ${actionButton('删除', 'delete-backup', v, 'danger')}`,
    },
  ], state.backups, { pageSize: 20 });
}

function renderBackupSettings(settings = {}) {
  const form = $('backupSettingsForm');
  if (!form) return;
  form.elements.enabled.checked = Boolean(settings.enabled);
  form.elements.interval_hours.value = settings.interval_hours || 24;
  form.elements.retention_days.value = settings.retention_days || 30;
  form.elements.cleanup_on_schedule.checked = settings.cleanup_on_schedule !== false;
  $('backupScheduleStatus').textContent = settings.enabled ? '已启用' : '未启用';
  $('backupSettingsMeta').innerHTML = [
    settings.next_run_at ? `下次备份：${esc(settings.next_run_at)}` : '下次备份：未安排',
    settings.last_success_at ? `最近成功：${esc(settings.last_success_at)}` : '最近成功：暂无',
    settings.last_error ? `最近错误：${esc(settings.last_error)}` : '',
  ].filter(Boolean).map(text => `<span>${text}</span>`).join('');
}

function humanFileSize(value) {
  const size = Number(value || 0);
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${size} B`;
}

function startNewUser() {
  resetForm($('userForm'));
  $('userFormTitle').textContent = '新增用户';
  $('userForm').elements.is_active.checked = true;
  $('userForm').elements.role.value = 'user';
  setUserPermissionValues(state.options?.default_user_permissions || {});
  syncUserPermissionFields();
}

function editUser(id) {
  const user = state.users.find(item => Number(item.id) === Number(id));
  if (!user) return;
  $('userFormTitle').textContent = `修改用户：${user.username}`;
  setFormValues($('userForm'), user);
  setUserPermissionValues(user.permissions || {});
  syncUserPermissionFields();
}

function setUserPermissionValues(permissions = {}) {
  const form = $('userForm');
  if (!form) return;
  form.elements.perm_inventory_manage.checked = Boolean(permissions['inventory.manage']);
  form.elements.perm_location_manage.checked = Boolean(permissions['location.manage']);
  form.elements.perm_inventory_search.checked = Boolean(permissions['inventory.search']);
}

function userPermissionPayload(form) {
  return {
    'inventory.manage': Boolean(form.elements.perm_inventory_manage.checked),
    'location.manage': Boolean(form.elements.perm_location_manage.checked),
    'inventory.search': Boolean(form.elements.perm_inventory_search.checked),
  };
}

function userPermissionSummary(user) {
  if (user.role === 'admin') return '<span class="badge">全部权限</span>';
  const labels = state.options?.permissions || {};
  const entries = Object.entries(user.permissions || {}).filter(([, enabled]) => enabled);
  return entries.length
    ? entries.map(([key]) => `<span class="badge">${esc(labels[key] || key)}</span>`).join(' ')
    : '<span class="muted">基础登记和出库</span>';
}

function syncUserPermissionFields() {
  const form = $('userForm');
  if (!form) return;
  const isAdminRole = form.elements.role.value === 'admin';
  $('userPermissionFields')?.classList.toggle('admin-permission-mode', isAdminRole);
  $('adminPermissionHint')?.classList.toggle('hidden', !isAdminRole);
  form.querySelectorAll('#userPermissionFields input[type="checkbox"]').forEach(input => {
    input.disabled = isAdminRole;
  });
}

const SETTINGS_GROUPS = [
  { key: 'categories', title: '试剂类型', scope: '试剂登记', note: '用于订购、入库和筛选。' },
  { key: 'brands', title: '品牌/厂家', scope: '试剂登记', note: '用于订购和新建试剂时快速选择常用品牌，也可以临时手动输入。' },
  { key: 'reagent_statuses', title: '试剂状态', scope: '库存状态', fixed: true, note: '系统固定状态，用于判断是否占位、是否到货和是否耗尽，不能删除或改名。' },
  { key: 'validation_statuses', title: '验证状态', scope: '验证登记', fixed: true, note: '系统固定状态，用于验证结果和待办统计，不能删除或改名。' },
  { key: 'validation_methods', title: '验证方法', scope: '验证登记', note: '用于记录实验验证方式。' },
  { key: 'sample_prefixes', title: '样本号前缀', scope: '临床标本', note: '用于登记时快速拼接样本号，例如 SMP；表单里可选择建议项，也可以临时手动输入。' },
  { key: 'sample_names', title: '样本类型', scope: '临床标本', note: '用于临床标本入库和筛选，例如血清、组织、灌洗液。' },
  { key: 'amount_units', title: '规格单位', scope: '试剂/标本', note: '用于规格量的常用单位，也可以在表单里临时手动输入。' },
  { key: 'sample_statuses', title: '标本状态', scope: '临床标本', fixed: true, note: '系统固定状态，用于判断标本是否占位和是否耗尽，不能删除或改名。' },
];

function fillSettingsForms() {
  if (!state.options) return;
  const container = $('settingsCards');
  if (!container) return;
  $('settingsGroupCount').textContent = `${SETTINGS_GROUPS.length} 组`;
  container.innerHTML = SETTINGS_GROUPS.map(group => {
    const values = state.options[group.key] || [];
    const fixed = Boolean(group.fixed);
    return `
      <article class="settings-card${fixed ? ' fixed-settings-card' : ''}" data-settings-key="${esc(group.key)}" data-settings-fixed="${fixed ? '1' : '0'}">
        <div class="settings-card-head">
          <div><h4>${esc(group.title)}</h4><span>${esc(group.scope)} · <b data-settings-count>${values.length}</b> 项${fixed ? ' · 系统固定' : ''}</span></div>
        </div>
        <p class="settings-note">${esc(group.note)}</p>
        <div class="settings-options">${values.map(value => renderSettingsChip(value, { fixed })).join('') || '<span class="settings-empty">暂无选项</span>'}</div>
        <div class="settings-add-row">
          <input data-settings-input="${esc(group.key)}" placeholder="${fixed ? '系统固定，不可新增' : '输入新选项'}" autocomplete="off" ${fixed ? 'disabled' : ''} />
          <button class="ghost" type="button" data-action="settings-add" data-id="${esc(group.key)}" ${fixed ? 'disabled' : ''}>添加</button>
        </div>
      </article>
    `;
  }).join('');
}

function renderSettingsChip(value, { fixed = false } = {}) {
  const remove = fixed ? '' : `<button type="button" data-action="settings-remove" data-id="${esc(value)}" aria-label="删除 ${esc(value)}">×</button>`;
  return `<span class="option-chip${fixed ? ' fixed-option-chip' : ''}" data-value="${esc(value)}"><span>${esc(value)}</span>${remove}</span>`;
}

function settingsValuesFor(card) {
  return [...card.querySelectorAll('.option-chip')].map(chip => chip.dataset.value).filter(Boolean);
}

function refreshSettingsCard(card) {
  const count = card.querySelector('[data-settings-count]');
  if (count) count.textContent = settingsValuesFor(card).length;
  const options = card.querySelector('.settings-options');
  if (options && !options.querySelector('.option-chip')) {
    options.innerHTML = '<span class="settings-empty">暂无选项</span>';
  }
}

function addSettingsOption(key) {
  const card = document.querySelector(`.settings-card[data-settings-key="${CSS.escape(key)}"]`);
  if (card?.dataset.settingsFixed === '1') return;
  const input = document.querySelector(`[data-settings-input="${CSS.escape(key)}"]`);
  const options = card?.querySelector('.settings-options');
  const value = input?.value.trim();
  if (!card || !input || !options || !value) return;
  const exists = settingsValuesFor(card).some(item => item === value);
  if (exists) {
    input.value = '';
    toast('这个选项已经存在');
    return;
  }
  const empty = options.querySelector('.settings-empty');
  if (empty) empty.remove();
  options.insertAdjacentHTML('beforeend', renderSettingsChip(value));
  input.value = '';
  refreshSettingsCard(card);
}

function removeSettingsOption(button) {
  const card = button.closest('.settings-card');
  const chip = button.closest('.option-chip');
  if (!card || !chip) return;
  if (card.dataset.settingsFixed === '1') return;
  chip.remove();
  refreshSettingsCard(card);
}

function settingsPayload() {
  return Object.fromEntries(SETTINGS_GROUPS.map(group => {
    const card = document.querySelector(`.settings-card[data-settings-key="${CSS.escape(group.key)}"]`);
    if (group.fixed) return [group.key, state.options[group.key] || []];
    return [group.key, card ? settingsValuesFor(card) : state.options[group.key] || []];
  }));
}

async function saveSettings() {
  const data = await api('/api/settings/dropdowns', { method: 'PATCH', body: JSON.stringify(settingsPayload()) });
  state.options = { ...state.options, ...data.item };
  await loadOptions();
  toast('下拉配置已保存');
}

async function submitExcelExport(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const data = formData(form);
  const params = new URLSearchParams({ mode: data.mode, limit: data.limit || '0' });
  if (data.table) params.set('table', data.table);
  await downloadWithAuth(`/api/excel/export?${params}`, `${data.table || 'all_tables'}_${data.mode}.xlsx`);
}

async function submitExcelImport(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const data = formData(form);
  const file = form.elements.excel_file.files[0];
  if (!file) throw new Error('请选择 Excel 文件');
  if (!confirm('确认执行高危数据库表导入？\n这个入口会直接写入底层数据库表，可能绕过库存业务检查。\n日常试剂/标本导入、编辑和出库请使用“库存空间 → 批量处理”。\n\n只有在迁移、备份恢复或管理员修复数据时才继续。')) return;
  data.data_url = await fileToDataUrl(file);
  delete data.excel_file;
  const result = await api('/api/excel/import', { method: 'POST', body: JSON.stringify(data) });
  const backupText = result.backup
    ? `<p class="form-note">写入前已自动备份：${esc(result.backup.filename)}，完整性：${esc(result.backup.integrity_check)}</p>`
    : '';
  $('excelImportResult').innerHTML = `${backupText}${miniRows(result.items, ['table', 'sheet', 'success', 'inserted', 'updated', 'failed'])}`;
  toast('导入完成');
  await loadExcel();
}

async function submitBackup(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const data = formData(form);
  const result = await api('/api/admin/backups', { method: 'POST', body: JSON.stringify(data) });
  $('backupCreateResult').innerHTML = miniRows([result.item], ['filename', 'reason', 'size', 'integrity_check', 'created_at']);
  toast('数据库备份已创建');
  await loadBackups();
}

async function submitBackupSettings(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const data = formData(form);
  data.interval_hours = Number(data.interval_hours || 24);
  data.retention_days = Number(data.retention_days || 30);
  const result = await api('/api/admin/backups/settings', { method: 'PATCH', body: JSON.stringify(data) });
  state.backupSettings = result.item;
  renderBackupSettings(result.item);
  toast('备份策略已保存');
}

async function submitBackupCleanup(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const data = formData(form);
  const days = Number(data.days || 30);
  if (!confirm(`确认删除 ${days} 天前的数据库备份？\n该操作只删除备份文件，不影响当前运行数据库，但删除后无法从这些文件恢复。`)) return;
  const result = await api('/api/admin/backups/cleanup', { method: 'POST', body: JSON.stringify({ days }) });
  $('backupCleanupResult').innerHTML = result.count
    ? `<p class="form-note">已删除 ${esc(result.count)} 个备份文件。</p>${miniRows(result.items, ['filename', 'created_at', 'size'])}`
    : '<p class="muted">没有符合条件的过期备份。</p>';
  toast(result.count ? `已清理 ${result.count} 个备份` : '没有过期备份需要清理');
  await loadBackups();
}

async function downloadBackup(filename) {
  if (!filename) return;
  await downloadWithAuth(`/api/admin/backups/${encodeURIComponent(filename)}/download`, filename);
}

async function deleteBackup(filename) {
  if (!filename) return;
  if (!confirm(`确认删除这个数据库备份？\n${filename}\n\n删除后无法从该文件恢复。`)) return;
  await api(`/api/admin/backups/${encodeURIComponent(filename)}`, { method: 'DELETE' });
  toast('备份文件已删除');
  await loadBackups();
}

async function submitUser(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const data = formData(form);
  data.permissions = userPermissionPayload(form);
  const id = data.id;
  delete data.id;
  delete data.perm_inventory_manage;
  delete data.perm_location_manage;
  delete data.perm_inventory_search;
  if (id) {
    delete data.username;
    await api(`/api/users/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
  } else {
    if (!data.username) throw new Error('新增用户需要用户名');
    data.password = '123456';
    delete data.is_active;
    await api('/api/users', { method: 'POST', body: JSON.stringify(data) });
  }
  toast('用户已保存');
  startNewUser();
  await loadUsers();
}

async function resetUserPassword(id) {
  const user = state.users.find(item => Number(item.id) === Number(id));
  const name = user ? `${user.display_name || user.username}（${user.username}）` : '该用户';
  if (!confirm(`确认重置 ${name} 的密码？\n重置后默认密码为 123456。`)) return;
  await api(`/api/users/${id}`, { method: 'PATCH', body: JSON.stringify({ password: '123456' }) });
  toast('密码已重置为 123456');
  await loadUsers();
}
