PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    permissions TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reagents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE,
    source_code TEXT,
    aliquot_no INTEGER,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    brand TEXT,
    catalog_no TEXT,
    amount REAL,
    amount_unit TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL DEFAULT 0,
    price REAL,
    status TEXT NOT NULL DEFAULT '可用',
    storage_node_id INTEGER NOT NULL DEFAULT -3,
    grid_cell TEXT,
    entry_date TEXT,
    expiration_date TEXT,
    note TEXT,
    created_by INTEGER,
    updated_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (updated_by) REFERENCES users(id),
    FOREIGN KEY (storage_node_id) REFERENCES storage_nodes(id)
);

CREATE TABLE IF NOT EXISTS clinical_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    source_code TEXT,
    aliquot_no INTEGER,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '临床标本',
    amount REAL,
    amount_unit TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT '可用',
    storage_node_id INTEGER NOT NULL DEFAULT -3,
    grid_cell TEXT,
    entry_date TEXT,
    note TEXT,
    created_by INTEGER,
    updated_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (updated_by) REFERENCES users(id),
    FOREIGN KEY (storage_node_id) REFERENCES storage_nodes(id)
);

CREATE TABLE IF NOT EXISTS storage_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER,
    name TEXT NOT NULL,
    node_type TEXT NOT NULL DEFAULT 'space',
    space_type INTEGER NOT NULL DEFAULT 5,
    location_code TEXT,
    rows INTEGER,
    cols INTEGER,
    grid_row INTEGER,
    grid_col INTEGER,
    note TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    updated_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES storage_nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (updated_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog_no TEXT NOT NULL,
    validator_id INTEGER,
    validation_date TEXT NOT NULL,
    method TEXT,
    result TEXT NOT NULL,
    description TEXT,
    image_path TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (validator_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    item_type TEXT,
    item_id INTEGER,
    from_storage_node_id INTEGER,
    from_grid_cell TEXT,
    to_storage_node_id INTEGER,
    to_grid_cell TEXT,
    from_location_snapshot TEXT,
    to_location_snapshot TEXT NOT NULL,
    moved_by INTEGER,
    moved_at TEXT NOT NULL,
    reason TEXT,
    note TEXT,
    reverted_by_movement_id INTEGER,
    FOREIGN KEY (from_storage_node_id) REFERENCES storage_nodes(id),
    FOREIGN KEY (to_storage_node_id) REFERENCES storage_nodes(id),
    FOREIGN KEY (reverted_by_movement_id) REFERENCES movements(id),
    FOREIGN KEY (moved_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    target_table TEXT,
    target_id INTEGER,
    old_value TEXT,
    new_value TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
