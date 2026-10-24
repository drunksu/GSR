# run_modalities.ps1 - 同一模型（qwen3-vl-plus）跑四种输入模态对照，
# 验证 UI 层级树 XML 与真机截图对推断准确率的影响。
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File experiments\state_recovery\scripts\run_modalities.ps1
#
# Outputs (独立目录，互不覆盖):
#   experiments\state_recovery\results\ledgers_mod_text\          (text)
#   experiments\state_recovery\results\ledgers_mod_xml\           (text+xml)
#   experiments\state_recovery\results\ledgers_mod_image\         (text+image)
#   experiments\state_recovery\results\ledgers_mod_xml_image\     (text+xml+image)
#
# Log: experiments\state_recovery\results\rerun_modalities.log

$ErrorActionPreference = "Continue"
$env:PYTHONUNBUFFERED = "1"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$PyExe    = Join-Path $RepoRoot "mobile\Scripts\python.exe"
$Infer    = Join-Path $RepoRoot "experiments\state_recovery\scripts\infer_mutations.py"
$RunDir   = Join-Path $RepoRoot "third_party\mobilebench-ol-main\results\base_canonical"
$OutRoot  = Join-Path $RepoRoot "experiments\state_recovery\results"
$LogFile  = Join-Path $OutRoot "rerun_modalities.log"
$Model    = "qwen3-vl-plus"

if (-not (Test-Path $PyExe)) { Write-Host "[FATAL] python not found: $PyExe" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $Infer)) { Write-Host "[FATAL] infer script not found: $Infer" -ForegroundColor Red; exit 1 }

$Jobs = @(
    @{ Modality = "text";            OutDir = "ledgers_mod_text"        },
    @{ Modality = "text_xml";        OutDir = "ledgers_mod_xml"         },
    @{ Modality = "text_image";      OutDir = "ledgers_mod_image"       },
    @{ Modality = "text_xml_image";  OutDir = "ledgers_mod_xml_image"   }
)

$startAll = Get-Date
"=== run_modalities started at $startAll (model=$Model) ===" | Out-File -FilePath $LogFile -Encoding utf8

foreach ($j in $Jobs) {
    $out = Join-Path $OutRoot $j.OutDir
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] START  modality=$($j.Modality)  ->  $($j.OutDir)"
    Write-Host $line -ForegroundColor Cyan
    $line | Out-File -FilePath $LogFile -Append -Encoding utf8

    & $PyExe $Infer --run-dir $RunDir --all --model $Model `
        --modality $j.Modality --out-dir $out 2>&1 |
        ForEach-Object { "$_" } | Tee-Object -FilePath $LogFile -Append

    $code = $LASTEXITCODE
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] DONE   modality=$($j.Modality)  (exit=$code)"
    Write-Host $line -ForegroundColor $(if ($code -eq 0) {'Green'} else {'Yellow'})
    $line | Out-File -FilePath $LogFile -Append -Encoding utf8
}

$elapsed = (Get-Date) - $startAll
$line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ALL FINISHED. Total elapsed: $($elapsed.ToString('hh\:mm\:ss'))"
Write-Host $line -ForegroundColor Cyan
$line | Out-File -FilePath $LogFile -Append -Encoding utf8
