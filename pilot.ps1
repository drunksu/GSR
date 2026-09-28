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
#
# ⚠️ 这里是**重大 bug 的现场**（2026-09-27 发现，实际毁掉了一整轮 12 小时的实验）：
#    原来的写法是
#        $modelArgs = @(); if ($Model) { $modelArgs += @('-Model', $Model) } ...
#        & $RUN -TaskFile $tf -Output $od @modelArgs
#    PowerShell **数组 splat 里的 '-Model' 不会被当作参数名**，而是被当成**位置参数**，
#    于是整体右移一格：$Subset 收到 '-Model'、$ConfigFile 收到 'qwen3-vl-flash'。
#    最终发给 run.py 的命令行是
#        run.py --subset -Model --config qwen3-vl-flash
#    → argparse 立刻报错退出 → **每轮 1 秒结束、0 个 episode**，而且 manifest 里
#    agent 还是默认的 qwen3-vl-plus，看起来像"模型没生效"而不是"根本没跑"。
#    修法：**显式写参数名**。空字符串在 run_mbl.ps1 里是 falsy（`if ($Model)` 不成立），
#    所以没传的值直接给 '' 就好，不需要条件拼接。
foreach ($pair in @(@('A 规范序', $TasksCanonical, $outA), @('B 随机序', $TasksShuffle, $outB))) {
    $label, $tf, $od = $pair
    Step '2/3' "跑顺序 $label   ($tf -> $od)"
    if ($DryRun) {
        # -DryRun **真的调用** run_mbl.ps1 -DryRun（而不是只回显一行字）：
        # 只回显的话就看不出上面那种参数绑定错误 —— 正是这个漏洞让 bug 溜了过去。
        Write-Host "  & `"$RUN`" -TaskFile $tf -Output $od -Model '$Model' -Coord '$Coord' -Condition '$Condition' -DryRun"
        & $RUN -TaskFile $tf -Output $od -Model $Model -Coord $Coord -Condition $Condition -DryRun
    } else {
        & $RUN -TaskFile $tf -Output $od -Model $Model -Coord $Coord -Condition $Condition

        # 跑完核对 manifest：请求的模型必须真的生效，否则大声报错（别再静默了）
        $mp = Join-Path $REPO "$od/run_manifest.json"
        if (Test-Path $mp) {
            $m = Get-Content $mp -Raw -Encoding UTF8 | ConvertFrom-Json
            $want = if ($Model) { $Model } else { $env:MBL_MODEL }
            if ($m.agent -ne $want) {
                Write-Host "❌ 严重：manifest 里的 agent='$($m.agent)'，但请求的是 '$want'。" -ForegroundColor Red
                Write-Host "   → 这一轮的实验数据**不能用**。请检查参数是否被正确绑定。" -ForegroundColor Red
            } elseif ($m.config -notmatch '\.conf$') {
                Write-Host "❌ 严重：manifest 里的 config='$($m.config)' 不像配置文件路径。" -ForegroundColor Red
                Write-Host "   → 参数绑定错位（历史 bug：数组 splat 导致位置参数右移）。" -ForegroundColor Red
            } else {
                Write-Host "  ✓ manifest 核对通过：agent=$($m.agent)  config=$($m.config)" -ForegroundColor DarkGray
            }
        }
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
    Write-Host "  & python analyze_order_effects.py --input $outA/episodes.jsonl $outB/episodes.jsonl --out $analysis --official-condition official"
} else {
    & $PY "$S\analyze_order_effects.py" `
        --input "$outA/episodes.jsonl" "$outB/episodes.jsonl" `
        --out $analysis --official-condition official
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
