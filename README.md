# LabKeeper 实验室库存管理系统

LabKeeper 是一个给实验室、课题组或小型平台使用的库存管理系统。它用浏览器操作，不需要安装数据库服务器；数据保存在一个 SQLite 文件里，方便备份、搬迁和在低性能服务器上部署。

适合记录：

- 试剂、抗体、耗材、试剂盒
- 临床标本、冻存管、分装样本
- 冰箱、液氮罐、抽屉、冻存盒和盒内孔位
- 订购、到货、验证、入库、移动、出库和备份记录

系统界面和文档目前以中文为主。

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

1. 安装 Python 3.10 或更高版本。
2. 下载并解压项目，例如放到 `D:\LabKeeper`。
3. 在项目目录打开 PowerShell，安装依赖：

```powershell
pip install -r requirements.txt
```

4. 运行：

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
pip install -r requirements.txt
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
cp .env.example .env
```

至少修改这些项：

```env
LABKEEPER_ENV=production
LABKEEPER_ENABLE_DEV_TOOLS=0
LABKEEPER_API_SECRET=请换成随机长字符串
LABKEEPER_INITIAL_ADMIN_PASSWORD=请换成正式管理员密码
LABKEEPER_CORS_ORIGINS=http://服务器IP:5173
```

正式环境会关闭“测试管理员登录”和“载入 Demo 数据库”入口。

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

管理员可在系统的“管理员 > 数据库备份”里创建、下载和清理备份。

建议在这些操作前备份：

- 大批量导入 Excel
- 调整冰箱、盒子、孔位结构
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

建议先阅读其中的“日常使用流程”“库存空间”“管理员功能”和“常见问题”。

## 给维护人员

常用检查：

```bash
pytest tests/ -v
python -m compileall backend
LABKEEPER_ENV=test python backend/server.py --check
node --check frontend/app.js
```

普通 Python、CI 和服务器部署使用 `requirements.txt`；conda 用户可使用 `environment.yml`。

## 许可证

MIT License
