# run_all_models.ps1 - Re-run inference for all 4 models sequentially with the
# updated prompt (unified entity-naming conventions), OVERWRITING existing ledgers.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File experiments\state_recovery\scripts\run_all_models.ps1
#
# Outputs (overwritten in place):
#   experiments\state_recovery\results\ledgers\base_canonical\*.json            (qwen3-vl-plus)
#   experiments\state_recovery\results\ledgers_flash\base_canonical\*.json      (qwen3.5-flash)
#   experiments\state_recovery\results\ledgers_deepseek_pro\base_canonical\*.json   (deepseek-v4-pro)
#   experiments\state_recovery\results\ledgers_deepseek_flash\base_canonical\*.json (deepseek-v4.1-flash)
#
# Log: experiments\state_recovery\results\rerun_all.log

$ErrorActionPreference = "Continue"
$env:PYTHONUNBUFFERED = "1"   # 让 infer 脚本的 print 实时写入日志，避免进程被杀时整批输出丢失

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$PyExe    = Join-Path $RepoRoot "mobile\Scripts\python.exe"
$Infer    = Join-Path $RepoRoot "experiments\state_recovery\scripts\infer_mutations.py"
$RunDir   = Join-Path $RepoRoot "third_party\mobilebench-ol-main\results\base_canonical"
$OutRoot  = Join-Path $RepoRoot "experiments\state_recovery\results"
$LogFile  = Join-Path $OutRoot "rerun_all.log"

if (-not (Test-Path $PyExe)) { Write-Host "[FATAL] python not found: $PyExe" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $Infer)) { Write-Host "[FATAL] infer script not found: $Infer" -ForegroundColor Red; exit 1 }

$Jobs = @(
    @{ Model = "qwen3-vl-plus";         OutDir = "ledgers"               },
    @{ Model = "qwen3.5-flash";         OutDir = "ledgers_flash"         },
    @{ Model = "deepseek-v4-pro";       OutDir = "ledgers_deepseek_pro"  },
    @{ Model = "deepseek-v4.1-flash";   OutDir = "ledgers_deepseek_flash" }
)

$startAll = Get-Date
"=== run_all_models started at $startAll ===" | Out-File -FilePath $LogFile -Encoding utf8

foreach ($j in $Jobs) {
    $out = Join-Path $OutRoot $j.OutDir
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] START  $($j.Model)  ->  $($j.OutDir)"
    Write-Host $line -ForegroundColor Cyan
    $line | Out-File -FilePath $LogFile -Append -Encoding utf8

    & $PyExe $Infer --run-dir $RunDir --all --model $j.Model --out-dir $out 2>&1 |
        ForEach-Object { "$_" } | Tee-Object -FilePath $LogFile -Append

    $code = $LASTEXITCODE
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] DONE   $($j.Model)  (exit=$code)"
    Write-Host $line -ForegroundColor $(if ($code -eq 0) {'Green'} else {'Yellow'})
    $line | Out-File -FilePath $LogFile -Append -Encoding utf8
}

$elapsed = (Get-Date) - $startAll
$line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ALL FINISHED. Total elapsed: $($elapsed.ToString('hh\:mm\:ss'))"
Write-Host $line -ForegroundColor Cyan
$line | Out-File -FilePath $LogFile -Append -Encoding utf8
