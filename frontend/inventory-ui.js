function renderInventoryWorkbench(data) {
  const isBoxView = isBox(data.current);
  const grid = data.grid || { rows: data.current.rows || 1, cols: data.current.cols || 3, capacity: 0 };
  const capacityText = isBox(data.current) && data.stats.capacity
    ? `孔位 ${data.stats.occupied}/${data.stats.capacity}`
    : (grid.is_framed === false ? '无框架' : `框架 ${grid.rows}x${grid.cols}`);
  const statText = `下级 ${data.stats.children} · 直接 ${data.stats.direct} · 总计 ${data.stats.total} · ${capacityText}`;
  const isVirtualUnplaced = isVirtualUnplacedNode(data.current);
  const deleteAction = isAdmin() ? `<button class="danger" type="button" data-action="delete-current-space" data-id="${data.current.id}">删除当前</button>` : '';
  const maintenanceActions = isVirtualUnplaced || !canManageLocation()
    ? ''
    : `<details class="overview-quick-actions">
              <summary>空间维护</summary>
              <div class="overview-action-menu"><button class="ghost" type="button" data-action="edit-current-space" data-id="${data.current.id}">编辑当前</button><button class="ghost" type="button" data-action="new-child-space" data-id="${data.current.id}">新建下级</button><button class="ghost" type="button" data-action="new-root-space">新建空间</button>${deleteAction}</div>
            </details>`;
  $('inventoryWorkbench').innerHTML = `
    <div class="inventory-shell overview-shell ${isBoxView ? 'box-overview-shell' : ''}">
          <aside class="inventory-tree">${renderOverviewNavigation(data)}</aside>
      <main class="inventory-main">
        <div class="storage-hero compact-hero">
          <div><h3>${esc(data.current.name)}</h3>${metaLine(storageContext(data.current))}</div>
          <div class="overview-stat-line">${esc(statText)}</div>
          <div class="overview-hero-actions">
            ${maintenanceActions}
            <details class="overview-quick-actions">
              <summary>填入位置</summary>
              <div class="overview-action-menu"><button class="ghost" type="button" data-action="use-storage" data-id="arrival">到货</button><button class="ghost" type="button" data-action="use-storage" data-id="reagent">试剂</button><button class="ghost" type="button" data-action="use-storage" data-id="sample">标本</button><button class="ghost" type="button" data-action="use-storage" data-id="movement">移动目标</button></div>
            </details>
          </div>
        </div>
        <div class="inventory-canvas">${renderInventoryCenter(data)}</div>
      </main>
    </div>
  `;
}

function renderOverviewNavigation(data, options = {}) {
  const tree = data.tree || [];
  const currentId = String(data.current.id);
  const current = tree.find(node => String(node.id) === currentId) || data.current;
  const parentId = current.parent_id ? Number(current.parent_id) : null;
  const ancestors = [];
  let cursor = current;
  let guard = 0;
  while (cursor?.parent_id && guard < 20) {
    const parent = tree.find(node => Number(node.id) === Number(cursor.parent_id));
    if (!parent) break;
    ancestors.unshift(parent);
    cursor = parent;
    guard += 1;
  }
  const realTree = tree.filter(node => !isVirtualUnplacedNode(node));
  const virtualUnplaced = tree.find(isVirtualUnplacedNode);
  const rootNode = findOverviewRoot(realTree, current);
  const siblings = realTree.filter(node =>
    parentId
    && Number(node.parent_id || 0) === Number(parentId)
    && Number(node.id) !== Number(currentId)
  );
  const children = realTree.filter(node => Number(node.parent_id) === Number(currentId));
  const entryButtons = [
    rootNode ? overviewNodeButton({ ...rootNode, name: '全部空间' }, 0, options) : '',
    virtualUnplaced ? overviewNodeButton(virtualUnplaced, 0, options) : '',
  ].filter(Boolean).join('');
  const entryGroup = entryButtons ? `<div class="tree-group tree-group-entry"><h4>空间入口</h4>${entryButtons}</div>` : '';
  const pathButtons = ancestors.length
    ? `<div class="tree-group"><h4>上级路径</h4>${ancestors.map(node => overviewNodeButton(node, node.depth || 0, options)).join('')}</div>`
    : '';
  const siblingButtons = siblings.length
    ? `<div class="tree-group"><h4>同级空间</h4>${siblings.map(node => overviewNodeButton(node, 0, options)).join('')}</div>`
    : '';
  const childButtons = children.length
    ? `<div class="tree-group"><h4>下级空间</h4>${children.map(node => overviewNodeButton(node, 0, options)).join('')}</div>`
    : '';
  return `${childButtons}${pathButtons}${siblingButtons}${entryGroup}` || '<p class="muted">暂无空间导航</p>';
}

function findOverviewRoot(realTree, current) {
  const pathIds = new Set();
  let cursor = current;
  let guard = 0;
  while (cursor && !isVirtualUnplacedNode(cursor) && guard < 50) {
    pathIds.add(Number(cursor.id));
    if (!cursor.parent_id) break;
    cursor = realTree.find(node => Number(node.id) === Number(cursor.parent_id));
    guard += 1;
  }
  const currentRoot = [...pathIds].map(id => realTree.find(node => Number(node.id) === id)).find(node => node && !node.parent_id);
  return currentRoot || realTree.find(node => !node.parent_id) || realTree[0];
}

function overviewNodeButton(node, depth = 0, options = {}) {
  const virtual = isVirtualUnplacedNode(node);
  const withDrop = options.drop !== false;
  const action = options.action || 'inventory-node';
  const kindAttr = options.kind ? ` data-kind="${esc(options.kind)}"` : '';
  const storageDrop = withDrop
    ? (virtual ? ' data-drop-storage-parent="" data-drop-unplaced="1"' : ` data-drop-storage-parent="${node.id}"`)
    : '';
  const dropNode = withDrop ? ` data-drop-node="${node.id}"` : '';
  const systemClass = virtual ? ' system-node' : '';
  const meta = virtual ? '' : storageParentName(node);
  return `<button class="tree-node ${node.selected ? 'active' : ''}${systemClass}" data-action="${esc(action)}" data-id="${node.id}"${kindAttr}${dropNode}${storageDrop} style="padding-left:${10 + depth * 12}px"><span><span class="tree-name">${esc(node.name)}</span>${metaLine(meta)}</span><span class="badge">${node.total_items ?? 0}</span></button>`;
}

function inventoryDisplayName(item) {
  if (!item) return '';
  if ((item.item_type || 'reagent') === 'sample') return inventoryObjectName(item, 'sample', '');
  return item.display_name || item.name || item.category || '试剂';
}

function inventoryItemType(item) {
  return (item?.item_type || 'reagent') === 'sample' ? 'sample' : 'reagent';
}

function inventoryTypeLabel(itemOrType) {
  const type = typeof itemOrType === 'string' ? itemOrType : inventoryItemType(itemOrType);
  return type === 'sample' ? '临床标本' : '试剂';
}

function inventorySubtypeText(item) {
  if (inventoryItemType(item) === 'sample') return item.category || '临床标本';
  return item.category || item.display_type || '试剂';
}

function inventoryItemClass(itemOrType) {
  const type = typeof itemOrType === 'string' ? itemOrType : inventoryItemType(itemOrType);
  return type === 'sample' ? 'item-sample' : 'item-reagent';
}

function hasValue(value) {
  return value !== null && value !== undefined && value !== '';
}

function inventoryMeasureText(item) {
  if (!item) return '';
  if (inventoryItemType(item) === 'sample') {
    return hasValue(item.amount) ? `${item.amount}${item.amount_unit || ''}` : '';
  }
  return hasValue(item.quantity) ? `${item.quantity}` : '';
}

function renderInventoryItemCard(r) {
  const itemType = inventoryItemType(r);
  const name = inventoryDisplayName(r);
  const active = state.selectedItemType === itemType && Number(r.id) === Number(state.selectedItemId);
  const canDrag = canManageLocation();
  const measureText = inventoryMeasureText(r);
  const measure = measureText ? ` · ${esc(measureText)}` : '';
  const position = r.position_in_box ? ` · ${esc(r.position_in_box)}` : '';
  return `<button class="reagent-card ${inventoryItemClass(itemType)} ${active ? 'active' : ''}" data-action="inventory-item" data-type="${esc(itemType)}" data-id="${r.id}" data-drag-type="${esc(itemType)}" data-drag-id="${r.id}" draggable="${canDrag ? 'true' : 'false'}"><b>${esc(name)}</b><span>${esc(inventorySubtypeText(r))}${measure}${position}</span></button>`;
}

function renderStorageOverviewCard(c) {
  const dragAttrs = `data-drag-type="storage-node" data-drag-id="${c.id}" draggable="${canManageLocation() ? 'true' : 'false'}"`;
  const dropAttrs = isBox(c) ? '' : `data-drop-storage-parent="${c.id}"`;
  return `<button class="reagent-card item-space" data-action="inventory-node" data-id="${c.id}" data-drop-node="${c.id}" ${dropAttrs} ${dragAttrs}><b>${esc(c.name)}</b><span>空间 · ${c.total ?? 0}件</span></button>`;
}

function renderPickerStorageCard(c, kind) {
  return `<button class="reagent-card item-space" data-action="picker-node" data-kind="${esc(kind)}" data-id="${c.id}"><b>${esc(c.name)}</b><span>空间 · ${c.total ?? 0}件</span></button>`;
}

function renderPickerInventoryCard(item) {
  const name = inventoryDisplayName(item);
  const measureText = inventoryMeasureText(item);
  const measure = measureText ? ` · ${esc(measureText)}` : '';
  const position = item.position_in_box ? ` · ${esc(item.position_in_box)}` : '';
  return `<div class="reagent-card static-card ${inventoryItemClass(item)}"><b>${esc(name)}</b><span>${esc(inventorySubtypeText(item))}${measure}${position}</span></div>`;
}

function renderInventoryCenter(data) {
  const unplaced = data.grid?.is_framed === false ? '' : renderUnplacedInventory(data);
  if (isBox(data.current)) {
    return `${unplaced}<section class="overview-section"><div class="section-head well-section-head"><h4>盒内孔位</h4><div class="well-head-tools"><span>${data.stats.occupied}/${data.stats.capacity} 已占用</span>${renderWellLegend()}</div></div><div class="well-grid overview-well-grid" style="--cols:${data.current.cols || 9}">${data.wells.map(w => renderInventoryWellCell(w, data.current.id)).join('')}</div></section>`;
  }
  return `${unplaced}${renderContainerGrid(data)}`;
}

function stableText(value) {
  return String(value ?? '').trim().toLowerCase();
}

function compareText(a, b) {
  return stableText(a).localeCompare(stableText(b), 'zh-Hans-CN', { numeric: true, sensitivity: 'base' });
}

function compareBy(valuesA, valuesB) {
  const length = Math.max(valuesA.length, valuesB.length);
  for (let index = 0; index < length; index += 1) {
    const left = valuesA[index];
    const right = valuesB[index];
    if (typeof left === 'number' || typeof right === 'number') {
      const diff = Number(left || 0) - Number(right || 0);
      if (diff) return diff;
    } else {
      const diff = compareText(left, right);
      if (diff) return diff;
    }
  }
  return 0;
}

function compareUnplacedSpace(a, b) {
  return compareBy(
    [Number(a.sort_order || 0), a.name, a.location_code, Number(a.id || 0)],
    [Number(b.sort_order || 0), b.name, b.location_code, Number(b.id || 0)],
  );
}

function compareUnplacedInventory(a, b) {
  const typeOrder = { sample: 0, reagent: 1 };
  return compareBy(
    [typeOrder[inventoryItemType(a)] ?? 9, inventoryDisplayName(a), a.code, Number(a.id || 0)],
    [typeOrder[inventoryItemType(b)] ?? 9, inventoryDisplayName(b), b.code, Number(b.id || 0)],
  );
}

function unplacedInventoryItems(data) {
  return (data.direct_items || []).filter(item => !item.position_in_box).sort(compareUnplacedInventory);
}

function unplacedStorageChildren(data) {
  return (data.children || [])
    .filter(child => child.is_unplaced || !(child.grid_row && child.grid_col))
    .sort(compareUnplacedSpace);
}

function positionedStorageChildren(data) {
  return (data.children || []).filter(child => !child.is_unplaced && child.grid_row && child.grid_col);
}

function renderUnplacedInventory(data) {
  const items = unplacedInventoryItems(data);
  const spaces = unplacedStorageChildren(data);
  const cards = [...spaces.map(renderStorageOverviewCard), ...items.map(renderInventoryItemCard)];
  const globalUnplaced = isVirtualUnplacedNode(data.current);
  const body = cards.length
    ? `<div class="card-list compact-card-list">${cards.join('')}</div>`
    : '<p class="muted compact-empty">无未归位库存</p>';
  const storageDrop = globalUnplaced
    ? ' data-drop-storage-parent="" data-drop-unplaced="1"'
    : (isBox(data.current) ? '' : ` data-drop-storage-parent="${data.current.id}"`);
  const sectionTitle = globalUnplaced ? '未归位' : '未指定格位';
  return `<section class="overview-section unplaced-section ${cards.length ? '' : 'is-empty'}" data-drop-node="${data.current.id}"${storageDrop}><div class="section-head"><h4>${sectionTitle}</h4></div>${body}</section>`;
}

function renderPickerUnplacedSection(data, kind) {
  const items = unplacedInventoryItems(data);
  const spaces = unplacedStorageChildren(data);
  const cards = [...spaces.map(space => renderPickerStorageCard(space, kind)), ...items.map(renderPickerInventoryCard)];
  if (!cards.length && !isVirtualUnplacedNode(data.current)) return '';
  const sectionTitle = isVirtualUnplacedNode(data.current) ? '未归位' : '未指定格位';
  const emptyText = isVirtualUnplacedNode(data.current) ? '无未归位空间和库存' : '无未指定格位内容';
  const body = cards.length
    ? `<div class="card-list compact-card-list">${cards.join('')}</div>`
    : `<p class="muted compact-empty">${emptyText}</p>`;
  return `<section class="overview-section unplaced-section ${cards.length ? '' : 'is-empty'}"><div class="section-head"><h4>${sectionTitle}</h4></div>${body}</section>`;
}

function renderWellLegend() {
  return `<div class="well-legend" aria-label="孔位颜色说明"><span class="legend-item item-reagent"><i></i>试剂</span><span class="legend-item item-sample"><i></i>临床标本</span><span class="legend-item item-empty"><i></i>空孔位</span></div>`;
}

function renderInventoryWellCell(well, nodeId) {
  const dropAttrs = `data-drop-node="${nodeId}" data-drop-well="${esc(well.coord)}"`;
  const item = well.item;
  if (!item) {
    return renderWellCell(well, 'position-actions', `${dropAttrs} data-node-id="${nodeId}" data-well="${esc(well.coord)}" data-label="空孔位 ${esc(well.coord)}"`);
  }
  const itemType = inventoryItemType(item);
  const dragAttrs = `data-drag-type="${esc(itemType)}" data-drag-id="${item.id}" draggable="${canManageLocation() ? 'true' : 'false'}"`;
  return renderWellCell(well, 'inventory-well', `${dropAttrs} ${dragAttrs} data-type="${esc(itemType)}" data-item-id="${item.id}"`);
}

function renderWellCell(well, action, extraAttrs = '') {
  const item = well.item;
  const code = item ? inventoryDisplayName(item) : '';
  const itemType = item ? inventoryItemType(item) : '';
  const name = item && itemType === 'sample' ? (item.category || '') : '';
  const summary = itemType === 'reagent' ? compactReagentName(code) : code;
  const sample = item
    ? `<span class="sample"><span class="sample-code">${esc(summary)}</span>${name ? `<span class="sample-name">${esc(name)}</span>` : ''}</span>`
    : '<span class="sample empty-sample"></span>';
  const tooltipBelow = /^A\d+$/i.test(String(well.coord || '')) ? 'tooltip-below' : '';
  const label = item ? `${well.coord} ${inventoryTypeLabel(item)} ${code}` : `${well.coord} 空孔位`;
  const tooltip = renderWellTooltipText(well, item);
  const tooltipAttr = tooltip ? ` data-tooltip="${esc(tooltip)}"` : '';
  return `<button class="well ${well.occupied ? 'occupied' : ''} ${item ? inventoryItemClass(item) : ''} ${well.selected ? 'selected' : ''} ${tooltipBelow}" data-action="${action}" ${extraAttrs} data-id="${esc(well.coord)}" aria-label="${esc(label)}"${tooltipAttr}><span class="coord">${esc(well.coord)}</span>${sample}</button>`;
}

function compactReagentName(name) {
  const clean = String(name || '').trim();
  if (!clean) return '';
  return clean.replace(/^Anti[- ]human\s+/i, '').replace(/^Recombinant\s+human\s+/i, '');
}

function renderWellTooltipText(well, item) {
  if (!item) return '';
  const type = inventoryItemType(item);
  const measure = inventoryMeasureText(item);
  const rows = type === 'sample'
    ? [
        ['孔位', well.coord],
        ['类型', inventoryTypeLabel(type)],
        ['系统编号', item.code],
        ['样本号', item.name],
        ['样本类型', item.category],
        ['规格', measure],
        ['状态', item.status],
      ]
    : [
        ['孔位', well.coord],
        ['类型', inventoryTypeLabel(type)],
        ['名称', item.name || item.display_name],
        ['分类', item.category],
        ['数量', measure],
        ['状态', item.status],
        ['有效期', item.expiration_date],
      ];
  return [inventoryDisplayName(item), ...rows.filter(([, value]) => hasValue(value)).map(([label, value]) => `${label}：${value}`)].join('\n');
}

function renderContainerGrid(data) {
  const grid = data.grid || { rows: data.current.rows || 1, cols: data.current.cols || 3, capacity: 0 };
  const frameActions = renderFrameActions(data.current.id);
  if (grid.is_framed === false) {
    const children = data.children || [];
    const directItems = unplacedInventoryItems(data);
    const mixedCards = [...children.map(renderStorageOverviewCard), ...directItems.map(renderInventoryItemCard)].join('');
    const body = mixedCards
      ? `<div class="storage-cards compact mixed-inventory-grid">${mixedCards}</div>`
      : '<p class="muted">当前空间没有下级空间和直接库存。需要分区时，把行列数改为大于 1 后保存。</p>';
    const storageDrop = isVirtualUnplacedNode(data.current)
      ? ' data-drop-storage-parent="" data-drop-unplaced="1"'
      : ` data-drop-storage-parent="${data.current.id}"`;
    return `<section class="overview-section no-frame-section" data-drop-node="${data.current.id}"${storageDrop}><div class="section-head"><h4>空间与库存</h4><div class="section-actions"><span>下级 ${children.length} · 库存 ${directItems.length}</span>${frameActions}</div></div>${body}</section>`;
  }
  const positionedChildren = positionedStorageChildren(data);
  const byPosition = new Map(positionedChildren.map(child => [Number(child.grid_position), child]));
  const byItemPosition = new Map((data.frame_items || []).map(item => [String(item.position_in_box || ''), item]));
  const cells = [];
  const capacity = visibleGridCapacity(grid, positionedChildren, data.frame_items || []);
  for (let index = 1; index <= capacity; index += 1) {
    const child = byPosition.get(index);
    const label = child?.grid_label || coordLabel(index, Number(grid.cols || 0));
    const item = child ? null : byItemPosition.get(label);
    const row = gridCellRow(index, Number(grid.cols || 1));
    const col = gridCellCol(index, Number(grid.cols || 1));
    cells.push(child
      ? `<button class="frame-cell occupied item-space" data-action="inventory-node" data-id="${child.id}" data-drop-node="${child.id}" ${isBox(child) ? '' : `data-drop-storage-parent="${child.id}"`} data-drag-type="storage-node" data-drag-id="${child.id}" draggable="${canManageLocation() ? 'true' : 'false'}"><span class="coord">${esc(label)}</span><b>${esc(child.name)}</b><small>空间 · ${child.total || 0} 件</small></button>`
      : item
        ? renderFrameInventoryCell(item, label)
        : `<button class="frame-cell empty" type="button" data-action="position-actions" data-node-id="${data.current.id}" data-well="${esc(label)}" data-row="${row}" data-col="${col}" data-label="框架空位 ${esc(label)}" data-drop-node="${data.current.id}" data-drop-well="${esc(label)}" data-drop-storage-parent="${data.current.id}" data-drop-row="${row}" data-drop-col="${col}"><span class="coord">${esc(label)}</span><b>空位</b><small>拖入空间 / 样本 / 试剂</small></button>`);
  }
  const used = positionedChildren.length + (data.frame_items || []).length;
  return `<section class="overview-section"><div class="section-head"><h4>空间框架</h4><div class="section-actions"><span>${used}/${capacity} 已使用</span>${frameActions}</div></div><div class="frame-grid" style="--cols:${grid.cols || 3}">${cells.join('')}</div></section>`;
}

function renderFrameInventoryCell(item, label) {
  const itemType = inventoryItemType(item);
  const canDrag = canManageLocation();
  const name = inventoryDisplayName(item);
  const sub = inventorySubtypeText(item);
  return `<button class="frame-cell occupied ${inventoryItemClass(itemType)}" data-action="inventory-item" data-type="${esc(itemType)}" data-id="${item.id}" data-drag-type="${esc(itemType)}" data-drag-id="${item.id}" draggable="${canDrag ? 'true' : 'false'}"><span class="coord">${esc(label)}</span><b>${esc(name)}</b><small>${esc(sub)}</small></button>`;
}

function renderFrameActions(nodeId) {
  if (isVirtualUnplacedId(nodeId)) return '';
  const childButton = canManageLocation() ? `<button class="mini-btn ghost" type="button" data-action="new-child-space" data-id="${nodeId}">新建下级空间</button>` : '';
  const createButtons = canManageInventory() ? `<button class="mini-btn ghost" type="button" data-action="new-sample-at" data-node-id="${nodeId}">新建标本</button><button class="mini-btn ghost" type="button" data-action="new-reagent-at" data-node-id="${nodeId}">新建试剂</button>` : '';
  const moveButton = canManageLocation() ? `<button class="mini-btn ghost" type="button" data-action="move-into-space" data-id="${nodeId}">移入库存</button>` : '';
  return `${childButton}${createButtons}${moveButton}`;
}

function gridCellRow(index, cols) {
  return Math.floor((index - 1) / Math.max(cols, 1)) + 1;
}

function gridCellCol(index, cols) {
  return ((index - 1) % Math.max(cols, 1)) + 1;
}

function coordLabel(index, cols) {
  if (cols > 0) {
    const row = Math.floor((index - 1) / cols);
    const col = ((index - 1) % cols) + 1;
    return row < 26 ? `${String.fromCharCode(65 + row)}${col}` : String(index);
  }
  return String(index);
}

function visibleGridCapacity(grid, children, frameItems = []) {
  const childMax = children.reduce((max, child) => Math.max(max, Number(child.grid_position) || 0), 0);
  const itemMax = frameItems.reduce((max, item) => {
    const position = String(item.position_in_box || '');
    const match = position.match(/^([A-Z])(\d+)$/i);
    if (!match) return max;
    const row = match[1].toUpperCase().charCodeAt(0) - 64;
    const col = Number(match[2] || 0);
    return Math.max(max, grid_position_from_row_col(row, col, Number(grid.cols || 1)));
  }, 0);
  return Math.max(Number(grid.capacity || 0), children.length, childMax, itemMax, 1);
}

function grid_position_from_row_col(row, col, cols) {
  if (!row || !col || !cols) return 0;
  return (row - 1) * cols + col;
}

const pickerConfigs = {
  arrival: { container: 'arrivalStoragePicker', form: 'arrivalForm', nodeField: 'storage_node_id', positionField: 'position_in_box', title: '到货存放位置', label: '到货登记' },
  reagent: { container: 'reagentStoragePicker', form: 'reagentForm', nodeField: 'storage_node_id', positionField: 'position_in_box', title: '试剂存放位置', label: '试剂位置' },
  sample: { container: 'sampleStoragePicker', form: 'sampleForm', nodeField: 'storage_node_id', positionField: 'position_in_box', title: '临床标本存放位置', label: '标本位置' },
  sampleEdit: { container: 'sampleEditStoragePicker', form: 'sampleEditForm', nodeField: 'storage_node_id', positionField: 'position_in_box', title: '标本存放位置', label: '标本位置' },
  aliquot: { container: 'aliquotStoragePicker', form: 'aliquotForm', nodeField: 'storage_node_id', positionField: 'position_in_box', title: '分装存放位置', label: '分装位置' },
  movement: { container: 'movementStoragePicker', form: 'movementForm', nodeField: 'to_storage_node_id', positionField: 'position_in_box', title: '移动目标位置', label: '移动目标' },
};

function renderPickerCenter(data, kind) {
  if (isVirtualUnplacedNode(data.current)) {
    return renderPickerUnplacedSection(data, kind);
  }
  if (data.wells.length) {
    const unplaced = renderPickerUnplacedSection(data, kind);
    const wells = `<section class="overview-section"><div class="section-head well-section-head"><h4>盒内孔位</h4><div class="well-head-tools"><span>${data.stats.occupied}/${data.stats.capacity} 已占用</span>${renderWellLegend()}</div></div><div class="well-grid" style="--cols:${data.current.cols || 9}">${data.wells.map(w => {
      const selectable = !w.occupied || w.selected;
      const action = selectable ? 'picker-well' : 'picker-occupied-well';
      const disabledAttr = selectable ? '' : ' aria-disabled="true"';
      return renderWellCell(w, action, `data-kind="${esc(kind)}"${disabledAttr}`);
    }).join('')}</div></section>`;
    return `${unplaced}${wells}`;
  }
  const grid = data.grid || { rows: data.current.rows || 1, cols: data.current.cols || 3, capacity: 0 };
  if (grid.is_framed === false) {
    const children = data.children || [];
    const directItems = unplacedInventoryItems(data);
    const mixedCards = [...children.map(child => renderPickerStorageCard(child, kind)), ...directItems.map(renderPickerInventoryCard)].join('');
    const body = mixedCards
      ? `<div class="storage-cards compact mixed-inventory-grid">${mixedCards}</div>`
      : '<p class="muted">当前空间没有下级空间和直接库存。可以点上方“使用当前空间”。</p>';
    return `<section class="overview-section no-frame-section"><div class="section-head"><h4>空间与库存</h4><div class="section-actions"><span>下级 ${children.length} · 库存 ${directItems.length}</span></div></div>${body}</section>`;
  }
  const unplaced = renderPickerUnplacedSection(data, kind);
  const positionedChildren = positionedStorageChildren(data);
  const byPosition = new Map(positionedChildren.map(child => [Number(child.grid_position), child]));
  const byItemPosition = new Map((data.frame_items || []).map(item => [String(item.position_in_box || ''), item]));
  const capacity = visibleGridCapacity(grid, positionedChildren, data.frame_items || []);
  const cells = [];
  for (let index = 1; index <= capacity; index += 1) {
    const child = byPosition.get(index);
    const label = child?.grid_label || coordLabel(index, Number(grid.cols || 0));
    const item = child ? null : byItemPosition.get(label);
    cells.push(child
      ? `<button class="frame-cell occupied item-space" data-action="picker-node" data-kind="${kind}" data-id="${child.id}"><span class="coord">${esc(label)}</span><b>${esc(child.name)}</b><small>空间 · ${child.total || 0} 件</small></button>`
      : item
        ? `<button class="frame-cell occupied ${inventoryItemClass(item)}" type="button" data-action="picker-occupied-well" data-kind="${esc(kind)}" data-id="${esc(label)}"><span class="coord">${esc(label)}</span><b>${esc(inventoryDisplayName(item))}</b><small>${esc(inventorySubtypeText(item))}</small></button>`
      : `<div class="frame-cell empty"><span class="coord">${esc(label)}</span><b>空位</b></div>`);
  }
  const used = positionedChildren.length + (data.frame_items || []).length;
  return `${unplaced}<section class="overview-section"><div class="section-head"><h4>空间框架</h4><div class="section-actions"><span>${used}/${capacity} 已使用</span></div></div><div class="frame-grid" style="--cols:${grid.cols || 3}">${cells.join('')}</div></section>`;
}

function renderLocationPicker(data, kind, title) {
  return `<div class="location-picker-row"><button class="ghost mini-btn" type="button" data-action="open-location-picker" data-kind="${esc(kind)}">选择位置</button></div>`;
}

function renderLocationPickerDialog(data, kind, title) {
  const selectedText = data.selected_well ? `${data.current.path}；${data.selected_well}` : data.current.path;
  return `
    <article class="detail-dialog location-dialog" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="detail-dialog-head"><h3>${esc(title)}</h3><button class="ghost mini-btn" type="button" data-action="close-location-picker">关闭</button></div>
      <div class="picker-head"><span>${esc(selectedText)}</span><button class="primary mini-btn" type="button" data-action="picker-current" data-kind="${kind}" data-id="${data.current.id}">使用当前空间</button></div>
      <div class="location-picker-grid inventory-shell">
        <aside class="location-tree inventory-tree">${renderOverviewNavigation(data, { action: 'picker-node', kind, drop: false })}</aside>
        <main class="location-canvas inventory-main">${renderPickerCenter(data, kind)}</main>
      </div>
    </article>
  `;
}
