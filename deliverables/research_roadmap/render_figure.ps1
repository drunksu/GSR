# render_figure.ps1 — 把 research_figure.svg 渲染成可嵌入 PPT 的 PNG（无头 Chrome，无需联网）。
#
#   powershell -ExecutionPolicy Bypass -File render_figure.ps1
#
# 产物：
#   research_figure_1920x720.png           1×，白底，插入 PPT 第 5 页内容区（约 12.5in × 4.7in）
#   research_figure_3840x1440.png          2×，白底，投影/打印用
#   research_figure_3840x1440_transparent.png  2×，透明底，可直接叠在有底纹的版面上
$ErrorActionPreference = 'Continue'

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chrome)) {
    $chrome = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
}
if (-not (Test-Path $chrome)) { Write-Host "[FATAL] 未找到 Chrome/Edge" -ForegroundColor Red; exit 1 }

$jobs = @(
    @{ svg = "research_figure.svg";           out = "research_figure_1920x720.png";           scale = 1; trans = $false },
    @{ svg = "research_figure.svg";           out = "research_figure_3840x1440.png";          scale = 2; trans = $false },
    @{ svg = "research_figure_transparent.svg"; out = "research_figure_3840x1440_transparent.png"; scale = 2; trans = $true }
)

foreach ($j in $jobs) {
    $url = "file:///" + ($dir -replace '\\', '/') + "/" + $j.svg
    $extra = if ($j.trans) { "--default-background-color=00000000" } else { "" }
    & $chrome --headless=new --disable-gpu --no-sandbox --hide-scrollbars `
        --user-data-dir="$env:TEMP\cr_roadmap" $extra `
        --screenshot="$dir\$($j.out)" --window-size=1920,720 `
        --force-device-scale-factor=$($j.scale) $url 2>&1 | Out-Null
    if (Test-Path "$dir\$($j.out)") {
        Write-Host ("[OK] {0}  ({1:N0} bytes)" -f $j.out, (Get-Item "$dir\$($j.out)").Length) -ForegroundColor Green
    } else {
        Write-Host "[FATAL] 渲染失败: $($j.out)" -ForegroundColor Red
        exit 1
    }
}
