# ============================================================================
#  run_mbl.ps1 —— 用 mobile 虚拟环境跑一次 MobileBench-OL
#
#  示例：
#    # 冒烟：2 个 B站任务
#    & 'D:\projects\GUI state recovery\run_mbl.ps1' -TaskFile data/smoke_2task.csv -Output results/smoke
#
#    # 顺序实验：规范序 / 随机序（★ 每种顺序必须换 Output 目录）
#    & ...\run_mbl.ps1 -TaskFile data/order_canonical.csv -Output results/canonical
#    & ...\run_mbl.ps1 -TaskFile data/order_shuffle0.csv  -Output results/shuffle0
#
#    # 只看命令不执行
#    & ...\run_mbl.ps1 -TaskFile data/smoke_2task.csv -Output results/x -DryRun
# ============================================================================
param(
    [string]$TaskFile = '',
    [string]$Output   = 'results/run1',
    [string]$Subset   = 'base',
    [Alias('Config')][string]$ConfigFile = '',
    [string]$Model    = '',
    [string]$Coord    = '',
    [string]$Condition = '',
    [switch]$DryRun
)

. "$PSScriptRoot\mobile.env.ps1"

# 模型切换：坐标约定从注册表自动取，避免"换了模型忘了改约定"这类致命错误
if ($Model) {
    if (-not $MBL_MODELS.Contains($Model)) {
        Write-Host "⚠️  $Model 不在模型注册表（$($MBL_MODELS.Keys -join ', ')）" -ForegroundColor Yellow
        if (-not $Coord) {
            throw "❌ 未知模型的坐标约定未知。先跑：experiments\scripts\mbl_coord_convention_check.py --model $Model --repo `"$REPO`"  然后用 -Coord norm|pixel 指定"
        }
    }
    $env:MBL_MODEL = $Model
    $env:MBL_COORD = if ($Coord) { $Coord } else { $MBL_MODELS[$Model] }
}
if ($Coord) { $env:MBL_COORD = $Coord }
Write-Host "[run_mbl] 模型 = $($env:MBL_MODEL)   坐标约定 = $($env:MBL_COORD)" -ForegroundColor Cyan

if (-not $env:MBL_API_KEY) { throw '❌ MBL_API_KEY 为空：请编辑 D:\projects\GUI state recovery\mobile.env.ps1 填上' }
if (-not (Test-Path $PY))  { throw "❌ 找不到 venv python: $PY" }
if (-not (Test-Path $ADB)) { throw "❌ 找不到 adb: $ADB" }
if ($TaskFile) { $env:MBL_TASK_FILE = $TaskFile }
# ⚠️ 参数不能叫 $Config：PowerShell 变量名大小写不敏感，会与 mobile.env.ps1 里的
#    $CONFIG 撞成同一个变量并被后者覆盖 → -Config 静默失效（已踩过一次）
if ($ConfigFile) { $CONFIG = $ConfigFile }

# 设备在线？（-DryRun 演练不需要手机）
if (-not $DryRun) {
    $devs = & $ADB devices | Select-String -Pattern 'device$'
    if (-not $devs) { throw '❌ 没有检测到已授权的设备，请检查 USB 连接与「USB 调试」授权' }
} else {
    Write-Host '[run_mbl] (-DryRun：跳过设备检查)' -ForegroundColor DarkGray
}

Set-Location $REPO

# 续跑缓存提醒：同一个 --output 再跑一次会跳过所有已完成任务
if (Test-Path "$Output/result_list.txt") {
    Write-Host "⚠️  $Output 已存在 result_list.txt —— 框架会续跑并跳过已完成任务。" -ForegroundColor Yellow
    Write-Host "    想完整重跑：换一个 -Output，或删掉该文件。" -ForegroundColor Yellow
}

$runArgs = @('run.py', '--mode', 'interact', '--config', $CONFIG, '--subset', $Subset, '--output', $Output)
Write-Host "TASK_FILE = $(if ($env:MBL_TASK_FILE) { $env:MBL_TASK_FILE } else { '(subset 默认)' })"
Write-Host "COMMAND   = $PY $($runArgs -join ' ')"
Write-Host ("-" * 70)

# ---------------------------------------------------------------------------
# 写 run_manifest.json：让 mbl_traj_to_episodes.py 知道"这是哪种顺序/哪种重置条件"
# 顺序模式从任务文件名推断；重置条件默认从 config 的 [reset] 读，
# 但可用 -Condition 手动覆盖（跑 reset 通道 + 主运行分两步时必需，
# 因为主运行用的 config 里 reset=false，标不出来 official 条件）。
# ---------------------------------------------------------------------------
$manifestPath = Join-Path $Output 'run_manifest.json'
New-Item -ItemType Directory -Force -Path $Output | Out-Null
$tf = $env:MBL_TASK_FILE
$orderMode = 'as-is'
if ($tf -match 'canonical') { $orderMode = 'canonical' }
elseif ($tf -match 'reverse') { $orderMode = 'reverse' }
elseif ($tf -match 'shuffle(\d+)') { $orderMode = 'shuffle' }
elseif ($tf -match 'adversarial') { $orderMode = 'adversarial' }
$seed = 0
if ($tf -match 'shuffle(\d+)') { $seed = [int]$Matches[1] }
$resetOn = ((Get-Content (Join-Path $REPO $CONFIG) | Select-String -Pattern '^reset=') -match 'true').Count -gt 0
$taskIds = @()
if ($tf -and (Test-Path (Join-Path $REPO $tf))) {
    $taskIds = (Import-Csv (Join-Path $REPO $tf) -Encoding UTF8 | ForEach-Object { $_.task_identifier })
}
$manifest = [ordered]@{
    run_id      = ($Output -replace '.*[\\/]', '')
    task_file   = $tf
    order_mode  = $orderMode
    order_seed  = $seed
    condition   = $(if ($Condition) { $Condition } elseif ($resetOn) { 'official' } else { 'none' })
    reset       = $resetOn
    agent       = $env:MBL_MODEL
    model       = $env:MBL_MODEL
    coord       = $env:MBL_COORD
    device      = $DEVICE
    config      = $CONFIG
    repo        = $REPO
    tasks       = $taskIds
    started_at  = (Get-Date).ToString('s')
    finished_at = $null
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content $manifestPath -Encoding UTF8
Write-Host "MANIFEST  = $manifestPath  (order_mode=$orderMode, condition=$($manifest.condition), tasks=$($taskIds.Count))"

if ($DryRun) { Write-Host '（-DryRun：未执行）'; return }

& $PY @runArgs
$code = $LASTEXITCODE
$manifest.finished_at = (Get-Date).ToString('s')
$manifest | ConvertTo-Json -Depth 4 | Set-Content $manifestPath -Encoding UTF8
Write-Host ("-" * 70)
Write-Host "退出码: $code"
if (Test-Path "$Output/result_list.txt") {
    Write-Host "结果: $(Get-Content "$Output/result_list.txt" -Raw)"
}
Write-Host "转成分析格式: & $PY 'D:\projects\GUI state recovery\experiments\scripts\mbl_traj_to_episodes.py' --run-dir '$Output'"
& $PY @runArgs
$code = $LASTEXITCODE
Write-Host ("-" * 70)
Write-Host "退出码: $code"
if (Test-Path "$Output/result_list.txt") {
    Write-Host "结果: $(Get-Content "$Output/result_list.txt" -Raw)"
}
