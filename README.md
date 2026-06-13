# 实验室库存管理系统

这是一个用于课题组管理试剂、耗材、临床标本和存放空间的本地 Web 系统。前端是普通 HTML/CSS/JavaScript，后端是 Python 标准库 HTTP API，数据保存在 SQLite。

## 快速启动

在 Windows PowerShell 中运行：

```powershell
cd D:\lab\lab_position
.\start.ps1
```

启动后访问：

```text
http://127.0.0.1:5173
```

默认本机服务：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8000`
- 数据库：`db\lab_inventory.sqlite3`

如果需要手动启动：

```powershell
C:\programs\miniforge\envs\codex\python.exe backend\server.py --host 127.0.0.1 --port 8000
C:\programs\miniforge\envs\codex\python.exe -m http.server 5173 -d frontend
```

## 测试账号

默认初始化管理员账号：

```text
admin / admin123
```

当前测试阶段登录页保留了“测试管理员登录”按钮。正式上线前必须搜索 `DEV_LOGIN_SHORTCUT`，删除 `frontend\index.html` 中的按钮和 `frontend\app.js` 中的事件监听。

管理员新增用户和重置密码时，默认密码为：

```text
123456
```

## 常用检查

小改动后优先运行：

```powershell
node --check frontend\app.js
C:\programs\miniforge\envs\codex\python.exe -m py_compile backend\server.py backend\registration.py backend\movements.py backend\storage_api.py
C:\programs\miniforge\envs\codex\python.exe backend\server.py --check
```

`tests\smoke_test.py` 会删除并重建 `db\lab_inventory.sqlite3`，不要作为日常检查随手运行。只有改到后端核心流程、数据库迁移、导入导出、发布前检查，或明确需要完整冒烟测试时再运行，并先备份当前数据库。

## 目录说明

```text
backend\     后端 API、数据库迁移、权限、库存、空间和导入导出逻辑
frontend\    前端页面、样式和交互脚本
config\      下拉选项配置
db\          SQLite 数据库和 schema
data\        运行数据，例如验证图片
dev_tools\   部署前临时测试、演示库生成和一次性数据导入脚本；部署后不作为维护依赖
tests\       冒烟测试
```

`dev_tools\` 不是正式运行时能力入口。上线后需要持续使用的维护能力，例如数据库备份、数据健康检查、Excel 导入预检，应由后端正式模块和管理员界面提供，不应要求管理员运行 `dev_tools\` 下的脚本。

## 主要文档

- `USER_MANUAL.md`：给使用者看的操作说明。
- `SERVER_MANUAL_UPDATE.md`：服务器部署和更新说明。
- `AGENTS.md`：给 Codex/维护 agent 看的项目规则和本机约定。
- `FEATURE_REFINEMENT_PLAN.md`：历史功能规划，内容可能过时，改功能前以当前代码和 `AGENTS.md` 为准。

## 上线前提醒

- 创建 `.env`，设置随机 `LAB_POSITION_API_SECRET`。
- 登录后修改默认管理员密码。
- 删除 `DEV_LOGIN_SHORTCUT` 测试登录入口。
- 确认后端只监听内网或 `127.0.0.1`，由 nginx 等服务代理对外访问。
- 备份正式数据库后再做迁移、导入或完整 smoke。
