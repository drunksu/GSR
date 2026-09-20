# ============================================================================
#  pilot.ps1 —— 一条命令跑完"顺序 A vs 顺序 B"的完整流程
#
#      & 'D:\projects\GUI state recovery\pilot.ps1'
#
#  它会依次做：
#    ① 唤醒手机并设为常亮（防黑屏，val1 就是栽在这里）
#    ② 跑顺序 A（规范序）
#    ③ 跑顺序 B（随机序）
#    ④ 把两次结果转成 episodes.jsonl
#    ⑤ 做顺序效应分析（ΔSR / CTCI / PASR / victim / polluter）
#    ⑥ 打印报告路径与结论摘要
#
#  常用参数：
#    -Tag pilot12                输出目录前缀（默认 pilot12）
#    -TasksCanonical data/pilot12_canonical.csv
#    -TasksShuffle   data/pilot12_shuffle0.csv
#    -SkipWake                   跳过唤醒步骤
#    -DryRun                     只打印不执行
# ============================================================================
param(
    [string]$Tag = 'pilot12',
    [string]$TasksCanonical = 'data/pilot12_canonical.csv',
    [string]$TasksShuffle   = 'data/pilot12_shuffle0.csv',
    [string]$Model = '',
    [string]$Coord = '',
    [string]$Condition = '',
    [switch]$SkipWake,
    [switch]$DryRun
)

$ErrorActionPreference = 'Continue'
$MBL  = $PSScriptRoot
$RUN  = "$MBL\run_mbl.ps1"
. "$MBL\mobile.env.ps1"                       # 载入 key / 路径 / 设备

$S       = "$MBL\experiments\scripts"
$outA    = "results/${Tag}_canonical"
$outB    = "results/${Tag}_shuffle"
$analysis= "results/${Tag}_analysis"

function Step($n, $msg) { Write-Host ""; Write-Host "===== [$n] $msg =====" -ForegroundColor Cyan }

# ---------------------------------------------------------------- ① 唤醒手机
Step 1 '唤醒手机并设为常亮'
$wake = 'svc power stayon true; input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; settings put system screen_off_timeout 1800000'
if ($DryRun -or $SkipWake) {
    Write-Host "  (跳过) $ADB -s $DEVICE shell `"$wake`""
} else {
    & $ADB -s $DEVICE shell $wake | Out-Null
    Start-Sleep 2
    $focus = (& $ADB -s $DEVICE shell dumpsys window | Select-String 'mCurrentFocus')
    Write-Host "  当前焦点: $focus"
    if ("$focus" -match 'Keyguard|StatusBar') {
        Write-Host '  ⚠️  检测到锁屏！请手动解锁手机后再重跑本脚本，否则截图会全黑、整轮变假失败。' -ForegroundColor Red
        if (-not $DryRun) { return }
    }
}

# ---------------------------------------------------------------- ②③ 跑两种顺序
foreach ($pair in @(@('A 规范序', $TasksCanonical, $outA), @('B 随机序', $TasksShuffle, $outB))) {
    $label, $tf, $od = $pair
    Step '2/3' "跑顺序 $label   ($tf -> $od)"
    $modelArgs = @()
    if ($Model) { $modelArgs += @('-Model', $Model) }
    if ($Coord) { $modelArgs += @('-Coord', $Coord) }
    if ($Condition) { $modelArgs += @('-Condition', $Condition) }
    if ($DryRun) {
        Write-Host "  & `"$RUN`" -TaskFile $tf -Output $od $($modelArgs -join ' ')"
    } else {
        & $RUN -TaskFile $tf -Output $od @modelArgs
        $rl = Join-Path $REPO "$od/result_list.txt"
        if (Test-Path $rl) { Write-Host "  结果: $(Get-Content $rl -Raw)" }
    }
}

# ---------------------------------------------------------------- ④ 转格式
Step 4 '转成分析格式 episodes.jsonl'
foreach ($od in @($outA, $outB)) {
    if ($DryRun) { Write-Host "  & python mbl_traj_to_episodes.py --run-dir $od" }
    else { & $PY "$S\mbl_traj_to_episodes.py" --run-dir $od }
}

# ---------------------------------------------------------------- ⑤ 分析
Step 5 '顺序效应分析'
if ($DryRun) {
    Write-Host "  & python analyze_order_effects.py --input $outA/episodes.jsonl $outB/episodes.jsonl --out $analysis --official-condition none"
} else {
    & $PY "$S\analyze_order_effects.py" `
        --input "$outA/episodes.jsonl" "$outB/episodes.jsonl" `
        --out $analysis --official-condition none
}

# ---------------------------------------------------------------- ⑥ 摘要
Step 6 '完成'
if ($DryRun) { Write-Host '（-DryRun：什么都没执行）'; return }
$report = Join-Path $REPO "$analysis/report.md"
Write-Host "  报告: $report"
if (Test-Path $report) {
    Write-Host ''
    Get-Content $report -Encoding UTF8 | Select-Object -Skip 9 -First 14 | ForEach-Object { "  $_" }
    Write-Host ''
    Write-Host "  打开报告: notepad `"$report`""
}
