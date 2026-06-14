# Dev Tools

`dev_tools` 只用于本机开发、演示和测试，不属于正式部署运行面。

- `demo.sqlite3` 是按需生成的 Demo 数据库，不纳入源码跟踪。
- `build_demo_db.py` 可按当前 `backend/db/schema.sql` 重建 `demo.sqlite3`。
- 载入 Demo 前自动生成的 `db/dev_backups/` 只用于本机回退测试数据，不能替代正式备份策略。

正式部署请保持：

```env
LABKEEPER_ENV=production
LABKEEPER_ENABLE_DEV_TOOLS=0
```

首次点击“载入 Demo 数据库”时会自动生成。也可以手动重建：

```bash
python dev_tools/build_demo_db.py
```
