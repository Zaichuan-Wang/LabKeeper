"""开发工具路径测试。"""

import sqlite3

from services import dev_tools


def test_load_demo_database_generates_missing_demo(tmp_path, monkeypatch):
    from db import database
    from services import backup

    demo_path = tmp_path / "demo.sqlite3"
    db_path = tmp_path / "loaded.sqlite3"
    backup_settings_path = tmp_path / "backup_settings.json"

    monkeypatch.setattr(dev_tools.config, "ENABLE_DEV_TOOLS", True)
    monkeypatch.setattr(dev_tools.config, "DEMO_DB_PATH", demo_path)
    monkeypatch.setattr(dev_tools.config, "DB_PATH", db_path)
    monkeypatch.setattr(dev_tools.config, "BACKUP_SETTINGS_PATH", backup_settings_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(backup, "DB_PATH", db_path)
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(backup, "BACKUP_SETTINGS_PATH", backup_settings_path)
    monkeypatch.setattr(backup, "stop_scheduler", lambda: None)
    monkeypatch.setattr(backup, "start_scheduler", lambda: None)

    result = dev_tools.load_demo_database()

    assert result["ok"] is True
    assert result["message"] == "Demo 数据库已生成并载入"
    assert demo_path.exists()
    assert db_path.exists()
    assert result["stats"]["reagents"] > 0

    demo_path.unlink()


def test_load_demo_database_replaces_open_sqlite_file(tmp_path, monkeypatch):
    from db import database
    from services import backup
    from dev_tools.build_demo_db import build_demo_database

    demo_path = tmp_path / "demo.sqlite3"
    db_path = tmp_path / "loaded.sqlite3"
    backup_settings_path = tmp_path / "backup_settings.json"
    build_demo_database(demo_path)

    monkeypatch.setattr(dev_tools.config, "ENABLE_DEV_TOOLS", True)
    monkeypatch.setattr(dev_tools.config, "DEMO_DB_PATH", demo_path)
    monkeypatch.setattr(dev_tools.config, "DB_PATH", db_path)
    monkeypatch.setattr(dev_tools.config, "BACKUP_SETTINGS_PATH", backup_settings_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(backup, "DB_PATH", db_path)
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(backup, "BACKUP_SETTINGS_PATH", backup_settings_path)
    monkeypatch.setattr(backup, "stop_scheduler", lambda: None)
    monkeypatch.setattr(backup, "start_scheduler", lambda: None)

    database.init_db()
    open_conn = sqlite3.connect(db_path)
    try:
        result = dev_tools.load_demo_database()
    finally:
        open_conn.close()

    assert result["ok"] is True
    assert result["message"] == "Demo 数据库已载入"
    assert result["stats"]["reagents"] > 0


def test_demo_builder_writes_current_space_type_schema(tmp_path):
    from dev_tools.build_demo_db import build_demo_database

    demo_path = tmp_path / "demo.sqlite3"
    build_demo_database(demo_path)

    with sqlite3.connect(demo_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(storage_nodes)").fetchall()}
        space_types = {
            row[0]
            for row in conn.execute("SELECT DISTINCT space_type FROM storage_nodes ORDER BY space_type").fetchall()
        }

    assert "space_type" in columns
    assert space_types == {1, 2, 3, 4, 5}
