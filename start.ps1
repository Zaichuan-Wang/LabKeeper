param(
  [string]$PythonPath = "",
  [int]$ApiPort = 8000,
  [int]$FrontendPort = 5173,
  [switch]$Stop
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend\server.py"
$Frontend = Join-Path $Root "frontend"
$EnvFile = Join-Path $Root ".env"
$PidDir = Join-Path $Root "data\pids"

function Stop-LabKeeper {
  $stopped = 0
  $stoppedIds = @{}
  if (Test-Path $PidDir) {
    Get-ChildItem -Path $PidDir -Filter "*.pid" -ErrorAction SilentlyContinue | ForEach-Object {
      $name = $_.BaseName
      $pidText = (Get-Content -LiteralPath $_.FullName -ErrorAction SilentlyContinue | Select-Object -First 1)
      $processId = 0
      if ([int]::TryParse($pidText, [ref]$processId)) {
        $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($proc) {
          Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
          Write-Host "已停止 $name (PID $processId)"
          $stoppedIds[$processId] = $true
          $stopped += 1
        }
      }
      Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
    }
  }
  foreach ($port in @($ApiPort, $FrontendPort)) {
    $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($owner in $owners) {
      if ($stoppedIds.ContainsKey($owner)) { continue }
      $proc = Get-Process -Id $owner -ErrorAction SilentlyContinue
      if ($proc -and @("python", "python3", "pythonw").Contains($proc.ProcessName)) {
        Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
        Write-Host "已停止端口 $port 上的 $($proc.ProcessName) (PID $owner)"
        $stoppedIds[$owner] = $true
        $stopped += 1
      }
    }
  }
  if ($stopped -eq 0) {
    Write-Host "没有找到由 start.ps1 记录的运行服务。"
    Write-Host "如果服务仍在运行，请关闭“启动后端”和“启动前端”的 PowerShell 窗口，或手动结束占用端口 $ApiPort / $FrontendPort 的进程。"
  }
}

if ($Stop) {
  Stop-LabKeeper
  exit 0
}

if (-not (Test-Path $EnvFile) -and -not $env:LABKEEPER_ENV) {
  $env:LABKEEPER_ENV = "development"
  $env:LABKEEPER_ENABLE_DEV_TOOLS = "1"
}

# ── 自动查找 Python ──
if (-not $PythonPath) {
  # 1. 常见 conda 环境
  $CondaRoots = @(
    "$env:USERPROFILE\miniforge3\envs",
    "$env:USERPROFILE\miniconda3\envs",
    "$env:USERPROFILE\anaconda3\envs",
    "C:\programs\miniforge\envs",
    "C:\ProgramData\miniforge3\envs",
    "C:\ProgramData\miniconda3\envs"
  )
  $EnvNames = @("labkeeper", "lab_position", "codex")
  foreach ($root in $CondaRoots) {
    foreach ($name in $EnvNames) {
      $candidate = Join-Path $root "$name\python.exe"
      if (Test-Path $candidate) { $PythonPath = $candidate; break }
    }
    if ($PythonPath) { break }
  }
  # 2. 系统 PATH
  if (-not $PythonPath) {
    $found = Get-Command python -ErrorAction SilentlyContinue
    if ($found) { $PythonPath = $found.Source }
  }
  if (-not $PythonPath) {
    $found = Get-Command python3 -ErrorAction SilentlyContinue
    if ($found) { $PythonPath = $found.Source }
  }
}

if (-not $PythonPath -or -not (Test-Path $PythonPath)) {
  Write-Host "错误：找不到 Python。请用 -PythonPath 参数指定路径，例如：" -ForegroundColor Red
  Write-Host "  .\start.ps1 -PythonPath C:\path\to\python.exe"
  exit 1
}

Write-Host "Python:     $PythonPath"
Write-Host "后端端口:   $ApiPort"
Write-Host "前端端口:   $FrontendPort"
Write-Host "运行模式:   $($env:LABKEEPER_ENV)"
Write-Host ""

# ── 安装依赖（首次运行） ──
$Requirements = Join-Path $Root "requirements.txt"
if (Test-Path $Requirements) {
  $installed = & $PythonPath -c "import fastapi; print('ok')" 2>$null
  if ($installed -ne "ok") {
    Write-Host "首次运行，安装依赖..." -ForegroundColor Yellow
    & $PythonPath -m pip install -r $Requirements -q
  }
}

# ── 启动服务 ──
New-Item -ItemType Directory -Force -Path $PidDir | Out-Null

Write-Host "启动后端: http://127.0.0.1:$ApiPort"
$BackendProcess = Start-Process powershell -PassThru -ArgumentList @(
  "-NoExit", "-Command",
  "cd '$Root'; & '$PythonPath' '$Backend' --host 127.0.0.1 --port $ApiPort"
)
$BackendProcess.Id | Set-Content -LiteralPath (Join-Path $PidDir "backend.pid") -Encoding ASCII

Write-Host "启动前端: http://127.0.0.1:$FrontendPort"
$FrontendProcess = Start-Process powershell -PassThru -ArgumentList @(
  "-NoExit", "-Command",
  "cd '$Root'; & '$PythonPath' -m http.server $FrontendPort -d '$Frontend'"
)
$FrontendProcess.Id | Set-Content -LiteralPath (Join-Path $PidDir "frontend.pid") -Encoding ASCII

Write-Host ""
Write-Host "打开浏览器: http://127.0.0.1:$FrontendPort" -ForegroundColor Green
Write-Host "停止服务:   .\start.ps1 -Stop" -ForegroundColor Yellow
