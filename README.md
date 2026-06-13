# LabKeeper — 实验室库存管理系统

面向课题组（约 30 人规模）的本地 Web 库存管理平台，统一管理试剂、耗材、临床标本和存放空间。

- **前端**：原生 HTML/CSS/JavaScript，无打包器
- **后端**：Python FastAPI
- **数据库**：SQLite（单文件，易备份迁移）

## 功能概览

- 统一空间框架：冰箱、柜子、液氮罐、架子、抽屉、样本架、盒子，用行列网格统一管理
- 试剂/耗材全生命周期：订购 → 到货 → 验证 → 入库 → 移动 → 出库
- 临床标本：入库、分装、移动、出库，不记录个人身份信息
- 批量 Excel 导入导出、数据库备份与恢复
- 角色权限（管理员 / 普通用户）、操作审计、数据健康检查
- 验证图片上传压缩、库存时间线追溯、误操作回滚

## 快速启动

### 前置条件

- Python 3.10+（推荐使用 conda 环境）
- Node.js（仅用于前端语法检查，运行不依赖）

### Linux / macOS

```bash
git clone https://github.com/yourname/labkeeper.git
cd labkeeper

# 安装依赖
pip install -r requirements.txt

# 启动（默认端口：后端 8000，前端 5173）
./start.sh

# 自定义端口
./start.sh --api-port 9000 --frontend-port 8080

# 后台运行
./start.sh --daemon

# 停止后台服务
./start.sh --stop
```

### Windows

```powershell
git clone https://github.com/yourname/labkeeper.git
cd labkeeper

# 安装依赖
pip install -r requirements.txt

# 启动
.\start.ps1

# 自定义端口
.\start.ps1 -ApiPort 9000 -FrontendPort 8080
```

启动后访问 `http://127.0.0.1:5173`。

## 默认账号

首次启动会自动创建管理员账号和根空间节点：

```
用户名：admin
密码：admin123
```

**首次部署后请立即修改默认密码。**

测试阶段登录页保留了"测试管理员登录"按钮，正式上线前搜索 `DEV_LOGIN_SHORTCUT` 并删除对应代码。

## 配置

复制 `.env.example` 为 `.env`，按需修改：

```bash
cp .env.example .env
```

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LAB_POSITION_API_SECRET` | 签名密钥，**部署前必须修改** | `change-this-secret-...` |
| `LAB_POSITION_TOKEN_TTL_SECONDS` | 登录令牌有效期（秒） | `28800`（8 小时） |
| `EXPIRATION_REMIND_DAYS` | 即将到期提醒窗口（天） | `30` |
| `LAB_POSITION_CORS_ORIGINS` | CORS 允许的源，逗号分隔；留空允许所有 | 空 |

## 目录结构

```
backend/     后端 API 和业务逻辑
frontend/    前端页面、样式和交互脚本
config/      下拉选项配置
db/          SQLite schema
data/        运行时数据（验证图片、日志等）
tests/       单元测试和冒烟测试
```

## 测试

```bash
# 单元测试
pytest tests/ -v

# 后端语法检查
python -m py_compile backend/server.py backend/registration.py backend/movements.py backend/storage_api.py
python backend/server.py --check

# 前端语法检查（需要 Node.js）
node --check frontend/app.js
```

> `tests/smoke_test.py` 会删除并重建数据库，不要作为日常检查运行。

## 部署

参考 `SERVER_MANUAL_UPDATE.md` 中的服务器部署和更新说明。

基本流程：

1. 安装 Python 依赖：`pip install -r requirements.txt`
2. 创建 `.env` 并设置随机密钥
3. 启动后端：`python backend/server.py --host 0.0.0.0 --port 8000`
4. 用 nginx 反向代理前端静态文件和后端 API
5. 修改默认管理员密码

## 文档

| 文件 | 内容 |
|------|------|
| `USER_MANUAL.md` | 用户操作手册 |
| `SERVER_MANUAL_UPDATE.md` | 服务器部署和更新说明 |

## 许可证

MIT License
