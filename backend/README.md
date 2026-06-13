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
