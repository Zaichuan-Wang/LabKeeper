# 后端目录结构

LabKeeper 后端按职责分层：

```text
backend/
  server.py          FastAPI 入口和全局错误处理
  routers/           HTTP API 路由，只放请求/响应衔接
  services/          库存、储位、登录、备份等业务逻辑
  models/            Pydantic 请求模型和参数校验
  db/                SQLite 连接、建表和迁移
  core/              配置、权限、安全和通用工具
```

排查前端请求时，先按 URL 路径去 `routers/` 找入口，再顺着调用进入
`services/`。除非只是解析参数或检查权限，不要把大量数据库业务逻辑直接写在
router 里。

## SQLite 维护原则

默认目标是“低配置服务器也能稳”：少索引、少后台任务、少隐式重建。

- 新增索引前，先确认有稳定页面或接口会长期使用它；不要因为某个字段存在就建索引。
- 优先保留能服务常见路径的索引：位置、状态、更新时间、有效期、货号、分装来源、时间线。
- 大量清理后，文件体积需要通过 `python backend/server.py --compact` 才会真正缩小。
- `db/`、`data/`、`dev_tools/demo.sqlite3` 都是运行时或本机测试产物，不应写入源码仓库。
