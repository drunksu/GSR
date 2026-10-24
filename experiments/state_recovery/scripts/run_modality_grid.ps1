# run_modality_grid.ps1 - 4 模型 x 4 模态全网格对照实验。
# 输出: results\ledgers_grid\{model}_{modality}\base_canonical\*.json
# 日志: results\rerun_modality_grid.log (归档，可能缓冲)
# 实时进度: Trae 后台任务的 output.log（无缓冲）
# 注意: 含空格路径必须用 & 调用运算符，不能用 Start-Process -ArgumentList 数组。

$ErrorActionPreference = "Continue"
$env:PYTHONUNBUFFERED = "1"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$PyExe    = Join-Path $RepoRoot "mobile\Scripts\python.exe"
$Infer    = Join-Path $RepoRoot "experiments\state_recovery\scripts\infer_mutations.py"
$RunDir   = Join-Path $RepoRoot "third_party\mobilebench-ol-main\results\base_canonical"
$OutRoot  = Join-Path $RepoRoot "experiments\state_recovery\results\ledgers_grid"
$LogFile  = Join-Path $RepoRoot "experiments\state_recovery\results\rerun_modality_grid.log"

# 仅保留有视觉能力的模型：qwen3-vl-plus、deepseek-v4.1-flash
# （qwen3.5-flash 是纯文本模型、deepseek-v4-pro 实测不处理图片，已移除）
$Models = @("qwen3-vl-plus", "deepseek-v4.1-flash")
$Modalities = @("text", "text_xml", "text_image", "text_xml_image")

if (-not (Test-Path $PyExe)) { Write-Host "[FATAL] python not found: $PyExe" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $Infer)) { Write-Host "[FATAL] infer script not found: $Infer" -ForegroundColor Red; exit 1 }

New-Item -ItemType Directory -Force -Path $OutRoot | Out-Null
$total = $Models.Count * $Modalities.Count
$idx = 0
$startAll = Get-Date
$header = "=== run_modality_grid started at $startAll ($total runs) ==="
$header | Out-File -FilePath $LogFile -Encoding utf8

foreach ($m in $Models) {
    foreach ($mod in $Modalities) {
        $idx++
        $tag = $m + "_" + $mod
        $out = Join-Path $OutRoot $tag
        $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        $line = "[$ts] START  [$idx/$total] model=$m modality=$mod -> $tag"
        Write-Host $line -ForegroundColor Cyan
        $line | Out-File -FilePath $LogFile -Append -Encoding utf8

        & $PyExe $Infer --run-dir $RunDir --all --model $m --modality $mod --out-dir $out --skip-existing 2>&1 |
            ForEach-Object { "$_" } | Tee-Object -FilePath $LogFile -Append

        $code = $LASTEXITCODE
        $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        $line = "[$ts] DONE   [$idx/$total] model=$m modality=$mod (exit=$code)"
        $color = "Yellow"
        if ($code -eq 0) { $color = "Green" }
        Write-Host $line -ForegroundColor $color
        $line | Out-File -FilePath $LogFile -Append -Encoding utf8
    }
}

$elapsed = (Get-Date) - $startAll
$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$line = "[$ts] ALL FINISHED. Total elapsed: " + $elapsed.ToString("hh\:mm\:ss")
Write-Host $line -ForegroundColor Cyan
$line | Out-File -FilePath $LogFile -Append -Encoding utf8
