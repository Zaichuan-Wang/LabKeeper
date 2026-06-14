function renderInventoryWorkbench(data) {
  const grid = data.grid || { rows: data.current.rows || 1, cols: data.current.cols || 3, capacity: 0 };
  const capacityText = grid.is_framed === false ? '无框架' : `框架 ${grid.rows}x${grid.cols}`;
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
    <div class="inventory-shell overview-shell">
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

function tileBody({ coord = '', name = '', sub = '' } = {}) {
  const parts = [];
  if (coord) parts.push(`<span class="coord">${esc(coord)}</span>`);
  if (name !== null && name !== undefined && String(name).trim() !== '') parts.push(`<b>${esc(name)}</b>`);
  if (sub !== null && sub !== undefined && String(sub).trim() !== '') parts.push(`<small>${esc(sub)}</small>`);
  return parts.join('');
}

function storageSummaryText(item) {
  return `空间 · ${item.total ?? 0} 件`;
}

function renderSpaceCell(item, coord = '', options = {}) {
  const tag = options.tag || 'button';
  const action = options.action || 'inventory-node';
  const kindAttr = options.kind ? ` data-kind="${esc(options.kind)}"` : '';
  const coordClass = coord ? ' has-coord' : ' no-coord';
  const dropAttrs = options.drop
    ? ` data-drop-node="${item.id}" data-drop-storage-parent="${item.id}"`
    : '';
  const dragAttrs = options.drag
    ? ` data-drag-type="storage-node" data-drag-id="${item.id}" draggable="${canManageLocation() ? 'true' : 'false'}"`
    : '';
  const typeAttr = tag === 'button' ? ' type="button"' : '';
  return `<${tag} class="frame-cell occupied item-space${coordClass}"${typeAttr} data-action="${esc(action)}" data-id="${item.id}"${kindAttr}${dropAttrs}${dragAttrs}>${tileBody({ coord, name: item.name, sub: storageSummaryText(item) })}</${tag}>`;
}

function renderInventoryCell(item, coord = '', options = {}) {
  const itemType = inventoryItemType(item);
  const tag = options.tag || 'button';
  const action = options.action === undefined ? 'inventory-item' : options.action;
  const kindAttr = options.kind ? ` data-kind="${esc(options.kind)}"` : '';
  const actionId = options.actionId ?? item.id;
  const activeClass = options.active ? ' active' : '';
  const coordClass = coord ? ' has-coord' : ' no-coord';
  const draggable = options.drag !== false && tag === 'button';
  const dragAttrs = draggable
    ? ` data-drag-type="${esc(itemType)}" data-drag-id="${item.id}" draggable="${canManageLocation() ? 'true' : 'false'}"`
    : '';
  const typeAttr = tag === 'button' ? ' type="button"' : '';
  const actionAttr = action === null || action === '' ? '' : ` data-action="${esc(action)}"`;
  return `<${tag} class="frame-cell occupied ${inventoryItemClass(itemType)}${coordClass}${activeClass}"${typeAttr}${actionAttr} data-type="${esc(itemType)}" data-id="${esc(actionId)}"${kindAttr}${dragAttrs}>${tileBody({ coord, name: inventoryDisplayName(item), sub: inventorySubtypeText(item) })}</${tag}>`;
}

function renderInventoryItemCard(r) {
  const itemType = inventoryItemType(r);
  const active = state.selectedItemType === itemType && Number(r.id) === Number(state.selectedItemId);
  return renderInventoryCell(r, '', { action: 'inventory-item', active });
}

function renderStorageOverviewCard(c) {
  return renderSpaceCell(c, '', { action: 'inventory-node', drop: true, drag: true });
}

function renderPickerStorageCard(c, kind) {
  return renderSpaceCell(c, '', { action: 'picker-node', kind });
}

function renderPickerInventoryCard(item) {
  return renderInventoryCell(item, '', { tag: 'div', action: null, drag: false });
}

function renderInventoryCenter(data) {
  const unplaced = data.grid?.is_framed === false ? '' : renderUnplacedInventory(data);
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
  return (data.direct_items || []).filter(item => !item.grid_cell).sort(compareUnplacedInventory);
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
    ? `<div class="tile-grid unplaced-tile-grid">${cards.join('')}</div>`
    : '<p class="muted compact-empty">无未归位库存</p>';
  const storageDrop = globalUnplaced
    ? ' data-drop-storage-parent="" data-drop-unplaced="1"'
    : ` data-drop-storage-parent="${data.current.id}"`;
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
    ? `<div class="tile-grid unplaced-tile-grid">${cards.join('')}</div>`
    : `<p class="muted compact-empty">${emptyText}</p>`;
  return `<section class="overview-section unplaced-section ${cards.length ? '' : 'is-empty'}"><div class="section-head"><h4>${sectionTitle}</h4></div>${body}</section>`;
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
  const byItemPosition = new Map((data.frame_items || []).map(item => [String(item.grid_cell || ''), item]));
  const cells = [];
  const capacity = visibleGridCapacity(grid, positionedChildren, data.frame_items || []);
  for (let index = 1; index <= capacity; index += 1) {
    const child = byPosition.get(index);
    const label = child?.grid_label || coordLabel(index, Number(grid.cols || 0));
    const item = child ? null : byItemPosition.get(label);
    const row = gridCellRow(index, Number(grid.cols || 1));
    const col = gridCellCol(index, Number(grid.cols || 1));
    cells.push(child
      ? renderSpaceCell(child, label, { action: 'inventory-node', drop: true, drag: true })
      : item
        ? renderFrameInventoryCell(item, label)
        : `<button class="frame-cell empty" type="button" data-action="position-actions" data-node-id="${data.current.id}" data-well="${esc(label)}" data-row="${row}" data-col="${col}" data-label="框架空位 ${esc(label)}" data-drop-node="${data.current.id}" data-drop-well="${esc(label)}" data-drop-storage-parent="${data.current.id}" data-drop-row="${row}" data-drop-col="${col}">${tileBody({ coord: label })}</button>`);
  }
  const used = positionedChildren.length + (data.frame_items || []).length;
  return `<section class="overview-section"><div class="section-head"><h4>空间框架</h4><div class="section-actions"><span>${used}/${capacity} 已使用</span>${frameActions}</div></div><div class="frame-grid" style="--cols:${grid.cols || 3}">${cells.join('')}</div></section>`;
}

function renderFrameInventoryCell(item, label) {
  return renderInventoryCell(item, label, { action: 'inventory-item' });
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
    const position = String(item.grid_cell || '');
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
  arrival: { container: 'arrivalStoragePicker', form: 'arrivalForm', nodeField: 'storage_node_id', positionField: 'grid_cell', title: '到货存放位置', label: '到货登记' },
  reagent: { container: 'reagentStoragePicker', form: 'reagentForm', nodeField: 'storage_node_id', positionField: 'grid_cell', title: '试剂存放位置', label: '试剂位置' },
  sample: { container: 'sampleStoragePicker', form: 'sampleForm', nodeField: 'storage_node_id', positionField: 'grid_cell', title: '临床标本存放位置', label: '标本位置' },
  sampleEdit: { container: 'sampleEditStoragePicker', form: 'sampleEditForm', nodeField: 'storage_node_id', positionField: 'grid_cell', title: '标本存放位置', label: '标本位置' },
  aliquot: { container: 'aliquotStoragePicker', form: 'aliquotForm', nodeField: 'storage_node_id', positionField: 'grid_cell', title: '分装存放位置', label: '分装位置' },
  movement: { container: 'movementStoragePicker', form: 'movementForm', nodeField: 'to_storage_node_id', positionField: 'grid_cell', title: '移动目标位置', label: '移动目标' },
};

function renderPickerCenter(data, kind) {
  if (isVirtualUnplacedNode(data.current)) {
    return renderPickerUnplacedSection(data, kind);
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
  const byItemPosition = new Map((data.frame_items || []).map(item => [String(item.grid_cell || ''), item]));
  const capacity = visibleGridCapacity(grid, positionedChildren, data.frame_items || []);
  const cells = [];
  for (let index = 1; index <= capacity; index += 1) {
    const child = byPosition.get(index);
    const label = child?.grid_label || coordLabel(index, Number(grid.cols || 0));
    const item = child ? null : byItemPosition.get(label);
    cells.push(child
      ? renderSpaceCell(child, label, { action: 'picker-node', kind })
      : item
        ? renderInventoryCell(item, label, { action: 'picker-occupied-well', kind, actionId: label, drag: false })
      : `<button class="frame-cell empty" type="button" data-action="picker-well" data-kind="${esc(kind)}" data-id="${esc(label)}">${tileBody({ coord: label })}</button>`);
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
