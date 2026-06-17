# LabKeeper 实验室库存管理系统 / Laboratory Inventory Management System

当前版本：v1.0.0

LabKeeper 是一个给实验室、课题组或小型平台使用的库存管理系统。它用浏览器操作，不需要安装数据库服务器；数据保存在一个 SQLite 文件里，方便备份、搬迁和在低性能服务器上部署。

系统会把订购、到货、移动和出库统一记进流转记录，便于追溯；未订购、未到货、未归位和已出库则用系统位置节点表示。

LabKeeper is a lightweight inventory management system for laboratories, research groups, and small core facilities. It runs in a browser, requires no database server, and stores data in a SQLite file for easy backup, migration, and deployment on low-resource servers.

说明：英文版仍在开发中，当前界面和文档以中文为主。

Note: The English version is still under development. The interface and documentation are currently maintained primarily in Chinese.

适合记录：

- 试剂、抗体、耗材、试剂盒
- 临床标本、冻存管、分装样本
- 冰箱、液氮罐、抽屉、带框架空间和格位/孔位
- 订购、到货、验证、入库、移动、出库和备份记录
- 抗体货号元信息，以及可选的 AI 辅助试剂信息提取

## 一句话理解

LabKeeper 可以理解成“实验室库存台账 + 存放位置图 + 操作记录”。它不会记录患者姓名、身份证号、电话等个人身份信息，只记录样本业务编号和库存信息。

## 在线试用

无需安装，可直接访问：

```text
http://sw2-dynamic.xiyoucloud.pro:20829/
```

试用环境只用于体验流程，不要录入真实敏感数据。

## 推荐使用顺序

1. 先用测试模式熟悉页面。
2. 确认流程后，再创建正式配置。
3. 正式使用前，从空数据库开始录入真实库存。

不要把 Demo 数据库当作正式库存库继续使用。如果测试时生成过数据，正式使用前请备份后删除：

```text
db/lab_inventory.sqlite3
```

再次启动后，系统会创建新的空库。

## 快速启动

### Windows 本机试用

1. 安装 Miniforge 或 Miniconda。项目推荐使用 Python 3.11。
2. 下载并解压项目，例如放到 `D:\LabKeeper`。
3. 在项目目录打开 PowerShell，创建并进入 conda 环境：

```powershell
conda env create -f environment.yml
conda activate labkeeper
```

如果已经创建过环境，更新依赖可运行：

```powershell
conda env update -f environment.yml --prune
conda activate labkeeper
```

没有 conda 时，也可以使用普通 Python 3.11：

```powershell
python -m pip install -r requirements.txt
```

4. 运行。脚本会优先使用名为 `labkeeper` 的 conda 环境：

```powershell
.\start.ps1
```

5. 浏览器访问：

```text
http://127.0.0.1:5173
```

测试模式默认账号：

```text
用户名：admin
密码：admin123
```

停止服务：

```powershell
.\start.ps1 -Stop
```

### Linux 服务器试用

```bash
git clone https://github.com/Zaichuan-Wang/LabKeeper.git
cd LabKeeper
conda env create -f environment.yml
conda activate labkeeper
./start.sh --daemon
```

没有 conda 时，可使用 Python 3.11 和 `requirements.txt` 安装依赖：

```bash
python3.11 -m pip install -r requirements.txt
./start.sh --daemon
```

同一内网访问：

```text
http://服务器IP:5173
```

停止服务：

```bash
./start.sh --stop
```

## 正式部署

正式使用前，复制配置模板：

```bash
cp -r config.example config
```

主要配置模板位于 `config.example/.env`。复制后请编辑 `config/.env`。

至少修改这些项：

```env
LABKEEPER_ENV=production
LABKEEPER_ENABLE_DEVTOOLS=0
LABKEEPER_API_SECRET=请换成随机长字符串
LABKEEPER_INITIAL_PASSWORD=请换成正式初始密码
LABKEEPER_CORS_ORIGINS=http://服务器IP:5173
```

开发排查时可在非 `production` 环境启用 `LABKEEPER_ENABLE_DEVTOOLS=1`。开发接口集中在 `dev_tools/api.py`，正式部署不需要这些入口时可以不带 `dev_tools/` 目录。

如需在订购或试剂入库页使用“AI 获取”按钮，可在 `config/.env` 中配置 `LABKEEPER_QWEN_API_KEY`。该功能只用于根据产品链接或文字生成待核对草稿，保存前仍需要人工确认。

### 推荐的服务器方式

长期多人使用时，推荐用 nginx 提供前端页面，并把 `/api/` 转发到后端：

```nginx
server {
    listen 5173;
    server_name _;

    root /home/your-user/LabKeeper/frontend;
    index index.html;

    client_max_body_size 20m;

    gzip on;
    gzip_min_length 1024;
    gzip_types text/plain text/css application/javascript application/json;

    location = /index.html {
        add_header Cache-Control "no-cache";
        try_files $uri =404;
    }

    location ~* \.(css|js)$ {
        expires 7d;
        add_header Cache-Control "public";
        try_files $uri =404;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

启动：

```bash
./start.sh --daemon --nginx
```

## 数据库和轻量化

主要数据库文件：

```text
db/lab_inventory.sqlite3
```

LabKeeper 默认采用轻量 SQLite 策略：

- 只保留位置、状态、有效期、货号、分装和时间线常用查询所需的索引。
- WAL 日志自动限制大小，减少低性能服务器上的磁盘压力。
- 几万条数据可直接使用；更大数据量建议先做真实搜索耗时测试，再决定是否专项优化。

### 压缩数据库

清理历史索引或大量删除数据后，SQLite 文件不会立刻变小。维护人员可在停用服务或低峰期运行：

```bash
python backend/server.py --compact
```

该命令会初始化数据库、清理旧索引，并执行 SQLite `VACUUM` 压缩。

## 备份

管理员可在系统的“系统管理 > 系统维护”里创建、下载和清理备份。

建议在这些操作前备份：

- 大批量导入 Excel
- 调整冰箱、空间、格位/孔位结构
- 系统升级
- 手动压缩数据库

网页端不提供“一键恢复”，避免误覆盖正式数据。恢复备份应由维护人员停服务后手动替换数据库文件，并删除旧的 `-wal`、`-shm` 文件后再检查系统。

## 文件夹说明

```text
backend/       后端 API、业务逻辑和 SQLite 初始化
frontend/      浏览器页面、样式和交互脚本
config/        下拉选项和备份策略配置
db/            运行时数据库和本地备份，不纳入源码
data/          日志、PID、验证图片等运行时数据
dev_tools/     本机测试和 Demo 数据库生成工具
tests/         自动化测试
```

`archive/`、`.pytest_cache/`、`__pycache__/`、旧的 smoke/demo 数据库都属于本地历史或缓存，不是正式运行所需内容。

## 给日常使用者

更多操作说明见：

```text
USER_MANUAL.md
```

建议先阅读其中的“日常使用流程”“库存空间”“选项配置”“系统管理”和“常见问题”。

## 给维护人员

常用检查：

```powershell
conda run -n labkeeper python -m pytest tests -v
conda run -n labkeeper python -m compileall backend
$env:LABKEEPER_ENV='test'; conda run -n labkeeper python backend/server.py --check
node --check frontend/app.js
```

推荐用 `environment.yml` 创建 `labkeeper` 环境，当前固定 Python 3.11。普通 Python、CI 或不使用 conda 的服务器部署仍可使用 `requirements.txt`。

## 许可证

MIT License
