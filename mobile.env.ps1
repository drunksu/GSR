# ============================================================================
#  MobileBench-OL 运行环境配置
#  用法（每个新开的终端里执行一次）：
#      . 'D:\projects\GUI state recovery\mobile.env.ps1'
#  或直接用配套脚本：
#      & 'D:\projects\GUI state recovery\run_mbl.ps1' -TaskFile data/order_canonical.csv -Output results/o1
#
#  ★ 这个文件不放在 git 仓库里（在仓库外的上一级目录），避免被误提交。
#     但请注意：写进文件的 key 仍是明文，别把本文件发给别人/上传。
# ============================================================================

$env:MBL_API_KEY = 'sk-ws-H.PIHIYHE.lnSR.MEUCIQC0sIGjFmTLj5RN2ZnhaGudioMy4ct5GIEgNXTgGDgZpAIgAm7XEpfGXDHGzqhkRYMhAzAV_aoAJqufpl4bDf4RilU'          
# ---------------------------------------------------------------- ② 模型与坐标约定（实测值，勿随意改）
# ---- 模型注册表：模型名 → 坐标约定 ----
# ⚠️ 这是整套流程最容易致命的参数：约定填错，所有点击会挤到左上角、任务全灭且看不出原因。
#    实测证据（合成图上放已知坐标的目标，看模型答什么）：
#      qwen3-vl-plus  答 <point>851 879</point>；归一化中心=(852,879)、像素中心=(920,2110)
#                     → 距归一化 1 px、距像素 1233 px  ⇒ **norm**
#      qwen-vl-max    两次答 y=1489 / 1490 —— **>1000，归一化不可能超 1000** ⇒ **pixel**
#      qwen-vl-plus   答 <point>641 y872</point>：距归一化 290 px、距像素 1269 px
#                     ⇒ 倾向 norm，但**未坐实**；用前请自己跑一次：
#                       experiments\scripts\mbl_coord_convention_check.py --model <模型> --repo <repo>
$MBL_MODELS = [ordered]@{
    # —— 主力梯队：Qwen3-VL 世代，全部 norm，定位精确（实测距目标 1–6 px）——
    'qwen3-vl-plus'              = 'norm'    # 已验证；已有 310 个任务的结果
    'qwen3-vl-plus-2025-12-19'   = 'norm'    # 日期快照版 → 可做"版本"消融
    'qwen3-vl-flash'             = 'norm'    # 同代 flash：更快更便宜、能力更弱 → 更适合落在信号带
    'qwen3-vl-flash-2026-01-22'  = 'norm'
    # —— 更新世代（2026，omni 系列；实测 norm 且精确）——
    'qwen3.8-omni-flash'         = 'norm'
    'qwen3.5-omni-plus'          = 'norm'
    'qwen3-omni-flash'           = 'norm'    # 未单独实测，按同族推断
    # —— 老世代：像素约定，且合成图上定位偏差 600+ px ——
    'qwen-vl-max'                = 'pixel'   # 已验证（y=1489/1490）
    'qwen-vl-plus'               = 'norm'    # 推测，未坐实
    'gui-plus'                   = 'pixel'   # 已验证（y=1304>1000），但定位可疑，需真机复验
    # —— 不适用 ——
    'qwen-vl-ocr'                = 'pixel'   # 纯 OCR，不是 agent
    'qwen3-vl-max'               = 'norm'    # 百炼上 404，留着以防以后上线
}

$env:MBL_MODEL       = 'qwen3-vl-plus'                  # 默认模型；用 run_mbl.ps1 -Model 覆盖
$env:MBL_COORD       = $MBL_MODELS[$env:MBL_MODEL]      # ★ 自动按注册表取，别手改
if (-not $env:MBL_COORD) {
    $env:MBL_COORD = ''
    Write-Host "[mobile.env] ⚠️  模型 $($env:MBL_MODEL) 不在注册表里 —— 请先跑坐标约定检测再手动设 MBL_COORD" -ForegroundColor Yellow
}
$env:MBL_API_LOG     = 'results/api_errors.jsonl'   # 接口失败落盘（防止抖动被误判成顺序效应）
$env:MBL_API_RETRIES = '2'               # 单次调用失败后的重试次数

# ---------------------------------------------------------------- ③ 任务集 / 设备 / 路径
$env:MBL_TASK_FILE = ''                  # 留空 = 用 --subset 的默认任务集
                                         # 要跑指定顺序就填：data/order_canonical.csv 等

# 自动定位仓库根目录（本文件所在目录）→ 换机器/换路径都不用改代码
$MBL_ROOT = $PSScriptRoot
$REPO     = "$MBL_ROOT\third_party\mobilebench-ol-main"
$PY       = "$MBL_ROOT\mobile\Scripts\python.exe"
$ADB      = "$MBL_ROOT\third_party\platform-tools\adb.exe"
$DEVICE   = 'GAGU8HGYW8JF9TIJ'   # ★ 换机器/换手机必须改这里（用 adb devices 查），注意别把空格带进来
$CONFIG   = 'config/interact_API_qwen3vl_base.conf'

$env:PATH = "$MBL_ROOT\third_party\platform-tools;$env:PATH"
$env:ADBUTILS_ADB_PATH  = $ADB
$env:PYTHONUTF8         = '1'
$env:PYTHONIOENCODING   = 'utf-8'

# ---------------------------------------------------------------- ④ 自检
Write-Host "[mobile.env] repo   = $REPO"
Write-Host "[mobile.env] device = $DEVICE"
Write-Host "[mobile.env] model  = $($env:MBL_MODEL)   coord=$($env:MBL_COORD)"
Write-Host "[mobile.env] tasks  = $(if ($env:MBL_TASK_FILE) { $env:MBL_TASK_FILE } else { '(由 --subset 决定)' })"
if (-not $env:MBL_API_KEY) {
    Write-Host "[mobile.env] ⚠️  MBL_API_KEY 为空 —— 请用编辑器打开本文件填上 $env:MBL_API_KEY 那一行" -ForegroundColor Yellow
} else {
    Write-Host "[mobile.env] key    = $($env:MBL_API_KEY.Substring(0,7))...（已设置）"
}
