# SSH 连不上时的服务器手动更新方案

适用场景：SSH 端口临时连不上，但还能通过云平台网页终端、VNC/控制台、服务器文件管理器、SFTP 面板或其他方式进入服务器。

当前部署约定：

```text
服务器项目目录：/home/deploy/lab
SSH 登录：ssh -p <SSH_PORT> deploy@your-server.example.com
后端本机端口：http://127.0.0.1:8000
nginx 公网端口：<PUBLIC_PORT>
公网入口：http://your-server.example.com:<PUBLIC_PORT>/
正式数据库：/home/deploy/lab/db/lab_inventory.sqlite3
```

核心原则：

- 更新代码前必须先备份正式库 `db/lab_inventory.sqlite3`。
- 部署包里不要放 `db/lab_inventory.sqlite3`，只放 `db/schema.sql`。
- 不要删除服务器上的 `.env`。
- 只改前后端代码时通常不需要改 nginx，nginx 会直接读取新的 `frontend/` 文件。
- 只改公网端口时改 nginx 的 `listen <PUBLIC_PORT>;`，不要改后端 `8000`。
- 当前测试阶段可以保留“测试管理员登录”；正式上线前按 README 删除 `DEV_LOGIN_SHORTCUT`。
- `dev_tools/` 只用于部署前临时测试、演示库生成或一次性导入；正式部署后不能依赖 `dev_tools/` 做日常维护。
- 数据库备份、数据健康检查、Excel 导入预检等上线后持续维护能力，应通过后端正式接口、管理员界面或服务器计划任务完成。

## 1. 本机制作干净部署包

不要直接用 `Compress-Archive` 打包整个项目，因为它可能带上运行数据库、日志、缓存，也可能让 Windows zip 路径在 Linux 上出现兼容问题。

在本机 PowerShell 运行：

```powershell
cd D:\lab\lab_position

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$pkg = "D:\lab\lab_position\lab_position_deploy_posix_$stamp.zip"
$script = "$env:TEMP\make_lab_deploy_zip_$stamp.py"

@'
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(r"D:\lab\lab_position")
out = root / "__PKG_NAME__"

include_dirs = ["backend", "frontend", "tests", "config"]
include_files = [
    "db/schema.sql",
    "README.md",
    "AGENTS.md",
    "SERVER_MANUAL_UPDATE.md",
    "requirements.txt",
    "environment.yml",
    "start.ps1",
    ".env.example",
]

with ZipFile(out, "w", ZIP_DEFLATED) as z:
    for d in include_dirs:
        base = root / d
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            parts = p.relative_to(root).parts
            if "__pycache__" in parts or p.suffix == ".pyc":
                continue
            z.write(p, "/".join(parts))

    for rel in include_files:
        p = root / rel
        if p.exists():
            z.write(p, rel.replace("\\", "/"))

print(out)
'@.Replace('__PKG_NAME__', (Split-Path $pkg -Leaf)) | Set-Content -LiteralPath $script -Encoding UTF8

C:\programs\miniforge\envs\codex\python.exe $script
Remove-Item -LiteralPath $script -Force
C:\programs\miniforge\envs\codex\python.exe -m zipfile -l $pkg
```

生成的文件类似：

```text
D:\lab\lab_position\lab_position_deploy_posix_20260611-180000.zip
```

确认 zip 里应该有：

```text
backend/...
frontend/...
tests/...
config/dropdown_options.json
db/schema.sql
README.md
AGENTS.md
SERVER_MANUAL_UPDATE.md
requirements.txt
environment.yml
start.ps1
.env.example
```

不应该有：

```text
db/lab_inventory.sqlite3
data/*.log
dev_tools/
__pycache__/
*.pyc
```

## 2. 上传部署包

通过云平台文件管理器、网页终端上传、SFTP 面板或其他可用方式，把 zip 上传到：

```text
/home/deploy/lab_position_deploy_latest.zip
```

如果只能上传到别的目录，例如 `/tmp/lab_position_deploy_latest.zip`，后面命令里的 zip 路径也要同步替换。

如果 SSH 可用，可以直接用 `scp` 上传：

```powershell
scp -P <SSH_PORT> D:\lab\lab_position\lab_position_deploy_posix_YYYYMMDD-HHMMSS.zip deploy@your-server.example.com:/home/deploy/lab_position_deploy_latest.zip
```

如果这次也要同步本机数据库，先在本机用 SQLite backup API 生成一致快照，再上传到服务器：

```powershell
scp -P <SSH_PORT> D:\lab\lab_position\lab_inventory_deploy_YYYYMMDD-HHMMSS.sqlite3 deploy@your-server.example.com:/home/deploy/lab_inventory_deploy_latest.sqlite3
```

## 3. 服务器上备份旧版本

进入服务器控制台后运行：

```bash
cd /home/deploy
ts=$(date +%Y%m%d-%H%M%S)
mkdir -p /home/deploy/lab_deploy_backups

if [ -d /home/deploy/lab ]; then
  tar --exclude='lab/data/*.log' -czf /home/deploy/lab_deploy_backups/lab_code_${ts}.tar.gz -C /home/deploy lab
fi

if [ -f /home/deploy/lab/db/lab_inventory.sqlite3 ]; then
  cp /home/deploy/lab/db/lab_inventory.sqlite3 /home/deploy/lab_deploy_backups/lab_inventory_${ts}.sqlite3
fi

ls -lh /home/deploy/lab_deploy_backups | tail
```

看到类似下面两类文件，就说明备份完成：

```text
lab_code_YYYYMMDD-HHMMSS.tar.gz
lab_inventory_YYYYMMDD-HHMMSS.sqlite3
```

## 4. 解压并覆盖代码

这一步只覆盖代码、配置和 schema，不覆盖正式数据库。

```bash
cd /home/deploy
ts=$(date +%Y%m%d-%H%M%S)
stage=/home/deploy/lab_deploy_stage_${ts}
rm -rf "$stage"
mkdir -p "$stage"

unzip -q /home/deploy/lab_position_deploy_latest.zip -d "$stage"

cd /home/deploy/lab
rm -rf backend frontend tests config
mkdir -p backend frontend tests config db data

cp -a "$stage"/backend/. backend/
cp -a "$stage"/frontend/. frontend/
cp -a "$stage"/tests/. tests/
cp -a "$stage"/config/. config/
cp -a "$stage"/db/schema.sql db/schema.sql
cp -a "$stage"/README.md "$stage"/AGENTS.md "$stage"/SERVER_MANUAL_UPDATE.md \
  "$stage"/requirements.txt "$stage"/environment.yml "$stage"/start.ps1 "$stage"/.env.example ./

rm -rf "$stage"
```

确认正式库还在：

```bash
ls -lh /home/deploy/lab/db/lab_inventory.sqlite3
```

## 5. 更新依赖

当前后端运行使用 Python 标准库 HTTP 服务，额外依赖为 `openpyxl` 和 `Pillow`。`Pillow` 用于验证图片压缩，上传图片会统一压成 `.jpg` 并尽量控制在 1MB 以内。

```bash
cd /home/deploy/lab
/home/deploy/miniforge3/envs/lab_position/bin/python -m pip install -r requirements.txt
```

如果服务器使用 conda 环境文件，也可以按需同步：

```bash
conda env update -n lab_position -f environment.yml
```

## 6. 检查代码和数据库

```bash
cd /home/deploy/lab

/home/deploy/miniforge3/envs/lab_position/bin/python -m py_compile \
  backend/server.py backend/database.py backend/auth.py backend/reagents.py \
  backend/registration.py backend/movements.py \
  backend/clinical_samples.py backend/storage_api.py backend/storage_inventory.py \
  backend/admin.py backend/backup.py backend/data_health.py backend/inventory_timeline.py \
  backend/options_config.py backend/common.py backend/config.py backend/constants.py \
  backend/inventory_search.py backend/inventory_items.py backend/bulk_operations.py

/home/deploy/miniforge3/envs/lab_position/bin/python backend/server.py --check
```

`backend/server.py --check` 应返回类似：

```json
{"ok": true, "db": "/home/deploy/lab/db/lab_inventory.sqlite3", "users": 1, "reagents": 10, "clinical_samples": 20, "orders": 5}
```

如果这里报 SQLite 权限错误，检查数据库和目录归属：

```bash
ls -lh /home/deploy/lab/db
chown -R deploy:deploy /home/deploy/lab/db /home/deploy/lab/data
```

## 7. 重启后端

如果使用 systemd：

```bash
sudo systemctl restart lab-position-api
sudo systemctl status lab-position-api --no-pager
journalctl -u lab-position-api -n 80 --no-pager
```

如果是手动 `nohup` 启动，先停旧进程：

```bash
ps -ef | grep 'backend/server.py' | grep -v grep
kill <PID>
```

再启动：

```bash
cd /home/deploy/lab
nohup /home/deploy/miniforge3/envs/lab_position/bin/python backend/server.py --host 127.0.0.1 --port 8000 > data/backend.out.log 2> data/backend.err.log &
```

确认健康检查：

```bash
curl -s http://127.0.0.1:8000/api/health
```

## 8. 检查 nginx

只改代码通常不需要动 nginx。确认配置和重载：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

如果公网端口改变，只改 nginx 的 `listen <PUBLIC_PORT>;`，然后再次执行上面的检查和重载。

## 9. 浏览器验收

打开：

```text
http://your-server.example.com:<PUBLIC_PORT>/
http://your-server.example.com:<PUBLIC_PORT>/api/health
```

关键预期：

- 前端页面能打开。
- `/api/health` 返回 `{"ok": true, ...}`。
- 登录、首页、空间概览、流转记录、库存明细能正常加载。
- 管理员页面能打开“数据健康”和“数据库备份”。
- 库存详情能看到只读时间线。
- 空间维护菜单在手机端不会超出页面。
- 流转记录能看到移动、出库、回滚记录，回滚列不会异常过宽。
- 验证图片上传后能保存 `.jpg`，大小通常在 1MB 以内。
- `db/lab_inventory.sqlite3` 对运行用户可写。
- `.env` 中 `LAB_POSITION_API_SECRET` 已设置为随机长字符串。
- 正式上线后默认管理员密码已修改。

## 10. 回滚部署

如果新版本启动失败，可以先恢复代码包：

```bash
cd /home/deploy
mkdir -p /home/deploy/lab_restore
tar -xzf /home/deploy/lab_deploy_backups/lab_code_YYYYMMDD-HHMMSS.tar.gz -C /home/deploy/lab_restore
rm -rf /home/deploy/lab/backend /home/deploy/lab/frontend /home/deploy/lab/tests /home/deploy/lab/config
cp -a /home/deploy/lab_restore/lab/backend /home/deploy/lab/
cp -a /home/deploy/lab_restore/lab/frontend /home/deploy/lab/
cp -a /home/deploy/lab_restore/lab/tests /home/deploy/lab/
cp -a /home/deploy/lab_restore/lab/config /home/deploy/lab/
```

如果确认数据库也需要恢复：

```bash
sudo systemctl stop lab-position-api
ts=$(date +%Y%m%d-%H%M%S)
cp /home/deploy/lab/db/lab_inventory.sqlite3 /home/deploy/lab_deploy_backups/lab_inventory_before_restore_${ts}.sqlite3
cp /home/deploy/lab_deploy_backups/lab_inventory_YYYYMMDD-HHMMSS.sqlite3 /home/deploy/lab/db/lab_inventory.sqlite3
rm -f /home/deploy/lab/db/lab_inventory.sqlite3-wal /home/deploy/lab/db/lab_inventory.sqlite3-shm
```

恢复后重启后端并检查：

```bash
sudo systemctl restart lab-position-api
/home/deploy/miniforge3/envs/lab_position/bin/python /home/deploy/lab/backend/server.py --check
curl -s http://127.0.0.1:8000/api/health
```

## 11. 正式数据库备份和恢复

系统已提供正式后端备份能力：

```text
GET  /api/admin/backups
POST /api/admin/backups
POST /api/admin/backups/cleanup
GET  /api/admin/backups/settings
PATCH /api/admin/backups/settings
GET  /api/admin/backups/{filename}/download
DELETE /api/admin/backups/{filename}
```

管理员也可以在页面“管理员 > 数据库备份”中手动创建、下载、删除备份，设置定期备份间隔，并按指定天数清理过期备份。备份文件保存在：

```text
/home/deploy/lab/db/backups/
```

定期备份策略保存在：

```text
/home/deploy/lab/config/backup_settings.json
```

备份使用 SQLite backup API 创建一致快照，并运行 `PRAGMA integrity_check`。高危“数据库表导入”在正式写入前也会自动创建一次备份。

内置定期备份由后端进程启动时加载策略并执行，间隔按小时设置。也可以继续用服务器计划任务调用正式后端接口或同等 SQLite backup API 的运维命令生成快照；不要把 `dev_tools/` 作为上线后的长期维护入口。

删除和清理只会处理 `db/backups/` 中符合 `lab_inventory*.sqlite3` 命名规则的备份文件，不会删除当前运行库。

网页不提供一键恢复。恢复必须人工执行：

1. 通知用户暂停使用系统。
2. 停止后端服务。
3. 先把当前库再做一次应急备份。
4. 用选定备份替换 `db/lab_inventory.sqlite3`。
5. 删除同目录旧的 `lab_inventory.sqlite3-wal` 和 `lab_inventory.sqlite3-shm`。
6. 启动后端。
7. 运行 `backend/server.py --check`。
8. 打开页面抽查首页、空间概览、明细查询、流转记录、数据健康和详情时间线。
