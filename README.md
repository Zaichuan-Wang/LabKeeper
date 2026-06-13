# LabKeeper — 实验室库存管理系统

LabKeeper 是给生物实验室和课题组使用的轻量级库存管理系统。它可以在一台普通电脑上本地运行，也可以部署到实验室 Linux 服务器上，让组内成员通过浏览器一起使用。

适合管理：

- 试剂、抗体、耗材、试剂盒
- 临床标本、冻存管、分装样本
- 冰箱、液氮罐、抽屉、样本盒和盒内孔位
- 订购、到货、验证、入库、移动、出库和备份记录

系统不需要安装数据库服务器，数据保存在一个 SQLite 文件中，便于备份和迁移。

## 推荐使用流程

建议按这个顺序使用：

1. **先启动测试版**：不用配置正式密码，直接进入系统，点击“载入 Demo 数据库”，熟悉页面和流程。
2. **再部署正式使用版**：创建正式配置，关闭测试入口，设置自己的管理员密码，从空数据库开始记录真实库存。

不要把 Demo 数据库当作正式库存库继续使用。正式使用前，建议重新解压/克隆一份干净项目，或先备份并删除测试时生成的：

```text
db/lab_inventory.sqlite3
```

## 主要功能

- 记录试剂/耗材从订购、到货、验证、入库到出库的完整流程
- 记录临床标本和分装信息，不保存姓名、身份证号、电话等个人身份信息
- 用空间树和盒内孔位管理冰箱、液氮罐、抽屉、盒子等位置
- 支持 Excel 批量导入、批量编辑、批量移动和批量出库
- 支持管理员和普通用户权限
- 支持数据库备份、数据健康检查、操作审计和库存时间线
- 开发测试模式可一键载入 Demo 数据库，正式部署默认关闭测试入口

## 第一步：启动测试版，先熟悉系统

测试版适合第一次试用、培训同事、演示流程。测试版会显示“测试管理员登录”和“载入 Demo 数据库”。

### Windows 电脑测试版

适合一个人先试用，或在实验室电脑上本机管理库存。

#### 1. 准备 Python

电脑需要先安装 Python 3.10 或更高版本。推荐使用 Miniconda / Miniforge，但普通 Python 也可以。

#### 2. 下载项目

从 GitHub 下载本项目，解压到一个固定位置，例如：

```text
D:\LabKeeper
```

#### 3. 安装依赖

第一次使用前，在项目目录打开 PowerShell，运行：

```powershell
pip install -r requirements.txt
```

如果使用 conda，也可以运行：

```powershell
conda env create -f environment.yml
conda activate labkeeper
```

#### 4. 启动测试版

在项目文件夹中找到：

```text
start.ps1
```

右键点击 `start.ps1`，选择“使用 PowerShell 运行”。

如果系统提示脚本权限问题，可以打开 PowerShell 后进入项目目录运行：

```powershell
.\start.ps1
```

启动成功后，浏览器访问：

```text
http://127.0.0.1:5173
```

测试版默认账号：

```text
用户名：admin
密码：admin123
```

进入登录页后，可以直接点击：

```text
测试管理员登录
```

登录后如需查看演示数据，点击：

```text
载入 Demo 数据库
```

这样可以先体验订购、到货、入库、位置、批量处理、备份等功能。

#### 5. 停止系统

关闭启动时打开的 PowerShell 窗口即可。

### Linux 服务器测试版

如果想先在服务器上给几个人试用，也可以先不创建 `.env`，直接运行测试版：

```bash
git clone https://github.com/yourname/labkeeper.git
cd labkeeper
pip install -r requirements.txt
./start.sh --daemon
```

然后在同一内网访问：

```text
http://服务器IP:5173
```

测试完成后停止服务：

```bash
./start.sh --stop
```

## 第二步：部署正式使用版

正式使用版用于记录真实库存。正式版会关闭测试管理员登录和 Demo 数据库入口，并要求设置正式管理员密码。

### Windows 本机正式使用

如果只在自己电脑上正式记录库存，可以仍然使用 `start.ps1`，但需要先创建正式配置。

复制 `.env.example`，重命名为：

```text
.env
```

打开 `.env`，至少修改这些内容：

```env
LABKEEPER_ENV=production
LABKEEPER_ENABLE_DEV_TOOLS=0
LABKEEPER_API_SECRET=请换成随机长字符串
LABKEEPER_INITIAL_ADMIN_PASSWORD=请换成正式管理员密码
```

然后双击或右键运行 `start.ps1`，访问：

```text
http://127.0.0.1:5173
```

如果你之前载入过 Demo 数据库，不要直接把它当正式库使用。正式开始前请重新解压一份干净项目，或备份后删除：

```text
db/lab_inventory.sqlite3
```

再次启动后，系统会按 `.env` 中的正式管理员密码创建新库。

### Linux 服务器正式共享

适合课题组多人共用。部署后，大家在同一个内网中通过浏览器访问服务器地址。

#### 1. 上传项目并安装依赖

```bash
git clone https://github.com/yourname/labkeeper.git
cd labkeeper
pip install -r requirements.txt
```

也可以用 conda：

```bash
conda env create -f environment.yml
conda activate labkeeper
```

#### 2. 创建正式配置

复制配置模板：

```bash
cp .env.example .env
```

至少修改这些项目：

```env
LABKEEPER_ENV=production
LABKEEPER_ENABLE_DEV_TOOLS=0
LABKEEPER_API_SECRET=请换成随机长字符串
LABKEEPER_INITIAL_ADMIN_PASSWORD=请换成正式管理员密码
```

#### 3. 启动服务

```bash
./start.sh --daemon
```

默认端口：

- 前端页面：`5173`
- 后端接口：`8000`

同一内网成员访问：

```text
http://服务器IP:5173
```

例如服务器 IP 是 `192.168.1.20`，访问：

```text
http://192.168.1.20:5173
```

停止后台服务：

```bash
./start.sh --stop
```

更正式的长期部署建议使用 nginx 反向代理，并配合服务器防火墙、HTTPS 和定期备份。

## 数据和备份

主要运行数据在：

```text
db/lab_inventory.sqlite3
```

管理员可以在系统里的“管理员 > 数据库备份”中创建备份。进行批量导入、空间结构大调整或系统升级前，建议先备份数据库。

开发测试用的 Demo 数据库在：

```text
dev_tools/demo.sqlite3
```

`dev_tools` 只用于本机测试和演示，正式部署不要依赖其中的脚本或测试数据。

## 常见问题

### 页面打不开

确认启动窗口没有报错，并访问：

```text
http://127.0.0.1:5173
```

如果是服务器部署，请把 `127.0.0.1` 换成服务器 IP。

### 忘记管理员密码

如果是正式数据，请先备份数据库，再由维护人员处理。不要直接删除数据库文件。

### Windows 提示不能运行脚本

可以改为打开 PowerShell，进入项目目录后运行：

```powershell
.\start.ps1
```

如仍被系统策略拦截，需要由电脑管理员调整 PowerShell 执行策略。

## 给开发者

项目结构：

```text
backend/     后端 API 和业务逻辑
frontend/    前端页面、样式和交互脚本
config/      下拉选项配置
db/          SQLite schema
data/        运行时数据
dev_tools/   本机测试和 Demo 数据库
tests/       单元测试和冒烟测试
```

常用检查：

```bash
pytest tests/ -v
python -m py_compile backend/server.py backend/registration.py backend/movements.py backend/storage_api.py
LABKEEPER_ENV=test python backend/server.py --check
node --check frontend/app.js
```

`requirements.txt` 保留给普通 Python、CI 和服务器部署；`environment.yml` 给 conda 用户。

## 文档

| 文件 | 内容 |
|------|------|
| `USER_MANUAL.md` | 用户操作手册 |
| `dev_tools/README.md` | Demo 数据库和本机测试说明 |

## 许可证

MIT License
