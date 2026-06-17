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

## 配置文件

后端启动时会读取 `config/.env`，模板在 `config.example/.env`。正式部署时应从
`config.example/` 复制出 `config/`，再修改密钥、初始密码、CORS 和可选功能。

`LABKEEPER_ENABLE_DEVTOOLS` 只在非 `production` 环境生效。开发接口代码放在
`dev_tools/api.py`，正式部署不依赖这部分。

## 抗体信息和 AI 提取

抗体元信息保存在 `antibody_metadata` 表，以 `catalog_no` 为主键。同一货号的订购、
库存详情和编辑表单共用同一组靶标、标记、种属、克隆号和同型/亚型。

- `services/antibody_metadata.py` 负责按货号读写元信息。
- `services/antibody_naming.py` 负责抗体名称规则：`抗{靶标}-{标记}`。
- `/api/reagents/ai-extract` 是可选入口，只有配置 `LABKEEPER_QWEN_API_KEY` 后才可用于 Qwen 联网提取。
- 货号受控更正需要同步 `reagents`、`validations` 和 `antibody_metadata`。

## SQLite 维护原则

默认目标是“低配置服务器也能稳”：少索引、少后台任务、少隐式重建。

- 新增索引前，先确认有稳定页面或接口会长期使用它；不要因为某个字段存在就建索引。
- 优先保留能服务常见路径的索引：位置、状态、更新时间、有效期、货号、分装来源、时间线。
- 大量清理后，文件体积需要通过 `python backend/server.py --compact` 才会真正缩小。
- `db/`、`data/`、`dev_tools/demo.sqlite3` 都是运行时或本机测试产物，不应写入源码仓库；`data/.gitkeep` 只用于让 GitHub 部署时保留空目录。

## 订购、到货和流转

当前数据库不再保留独立的 `orders`、`arrivals` 业务表。

- `/api/orders` 和 `/api/arrivals` 仍是前端入口名，但数据写入 `reagents` 和 `movements`。
- 订购会创建 `status='已订购'`、`storage_node_id=-2` 的试剂记录，并写入 `reason='订购'` 的流转。
- 到货会把未到货试剂转为实际库存；未选择真实空间时写入 `storage_node_id=-3`，显示为“未归位”。
- 多件到货沿用分装/同源语义，通过 `source_code + aliquot_no` 关联。
- 临床标本不走订购和未到货状态，只在入库、移动、出库时写入流转。

系统位置节点固定为：`-1 未订购`、`-2 未到货`、`-3 未归位`、`-4 已出库`。真实存储空间必须使用正数 `storage_nodes.id`。
