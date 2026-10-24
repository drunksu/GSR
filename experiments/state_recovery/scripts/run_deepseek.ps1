# run_deepseek.ps1 — Run DeepSeek pro + flash inference sequentially on base_canonical.
#
# Usage (from repo root or anywhere):
#   powershell -ExecutionPolicy Bypass -File experiments\state_recovery\scripts\run_deepseek.ps1
#
# Outputs:
#   experiments\state_recovery\results\ledgers_deepseek_pro\base_canonical\*.json
#   experiments\state_recovery\results\ledgers_deepseek_flash\base_canonical\*.json

$ErrorActionPreference = "Continue"

# Resolve repo root from script location (script is at experiments/state_recovery/scripts/)
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$PyExe    = Join-Path $RepoRoot "mobile\Scripts\python.exe"
$Infer    = Join-Path $RepoRoot "experiments\state_recovery\scripts\infer_mutations.py"
$RunDir   = Join-Path $RepoRoot "third_party\mobilebench-ol-main\results\base_canonical"
$OutRoot  = Join-Path $RepoRoot "experiments\state_recovery\results"
$LogFile  = Join-Path $OutRoot "deepseek_run.log"

if (-not (Test-Path $PyExe)) {
    Write-Host "[FATAL] python not found: $PyExe" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $Infer)) {
    Write-Host "[FATAL] infer script not found: $Infer" -ForegroundColor Red
    exit 1
}

# (model, output subdir) pairs to run sequentially
$Jobs = @(
    @{ Model = "deepseek-v4-pro";      OutDir = "ledgers_deepseek_pro"   },
    @{ Model = "deepseek-v4.1-flash";  OutDir = "ledgers_deepseek_flash" }
)

function Run-One {
    param([string]$Model, [string]$OutDir)
    $out = Join-Path $OutRoot $OutDir
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] START  $Model  ->  $OutDir" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan

    & $PyExe $Infer --run-dir $RunDir --all --model $Model --out-dir $out 2>&1 |
        Tee-Object -FilePath $LogFile -Append

    $code = $LASTEXITCODE
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] DONE   $Model  (exit=$code)" -ForegroundColor $(if ($code -eq 0) {'Green'} else {'Yellow'})
    return $code
}

$startAll = Get-Date
"=== run_deepseek started at $startAll ===" | Out-File -FilePath $LogFile -Encoding utf8

foreach ($j in $Jobs) {
    Run-One -Model $j.Model -OutDir $j.OutDir | Out-Null
}

$elapsed = (Get-Date) - $startAll
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "All DeepSeek runs finished.  Total elapsed: $($elapsed.ToString('hh\:mm\:ss'))" -ForegroundColor Cyan
Write-Host "Log: $LogFile" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
