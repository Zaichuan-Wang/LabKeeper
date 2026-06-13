# Dev Tools

`dev_tools` 只用于本机开发、演示和测试，不属于正式部署运行面。

- `demo.sqlite3` 是可直接载入的 Demo 数据库。
- `build_demo_db.py` 可按当前 `db/schema.sql` 重建 `demo.sqlite3`。

正式部署请保持：

```env
LABKEEPER_ENV=production
LABKEEPER_ENABLE_DEV_TOOLS=0
```

重建 Demo 数据库：

```bash
python dev_tools/build_demo_db.py
```
