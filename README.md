# GSR —— 面向 MobileBench-OL 的「执行顺序 → 成功率」实验工作台

> 课题：**面向移动 GUI 智能体评测的应用状态污染检测和恢复方法研究**（开题报告见 `开题报告 ….md`）
>
> 本仓库服务于其中一个具体实验：
> **OD Flaky tests 是否影响成功率？某个任务因为执行顺序变化而失败**
> - 顺序执行 vs. 乱序执行
> - 多个 Agent

**核心机制**：MobileBench-OL 的执行顺序 = **CSV 行序**（`load_tasks()` 用 `csv.DictReader` 顺序读、无排序无打乱）。
所以"打乱任务"= 生成同一批任务的另一份行序排列的 CSV —— 本仓库提供生成器。

**本文档所有命令都写成 CMD 版本**（Windows 命令提示符，可直接粘贴）。
两个入口 `run_mbl.cmd` / `pilot.cmd` 是 PowerShell 脚本的包装，环境变量会自动载入，cmd 里不需要事先 `set` 任何东西。
（想用 PowerShell 直接调也可以：`powershell -NoProfile -File run_mbl.ps1 -TaskFile ... `）

---

## 目录速查

| 路径 | 内容 |
|---|---|
| `mobile.env.ps1` | **环境配置**：API key、模型注册表（含坐标约定）、路径、设备序列号 |
| `run_mbl.cmd` / `run_mbl.ps1` | 跑一轮：自检 → 写 manifest → 执行 → 提示转格式 |
| `pilot.cmd` / `pilot.ps1` | **一条命令跑完两轮顺序 + 自动分析** |
| `experiments/docs/` | 01 数据集与 Agent 选型、02 实验方案（2×2 析因 / 指标 / 样本量） |
| `experiments/scripts/` | 全部脚本（见下） |
| `third_party/mobilebench-ol-main/` | **已打补丁**的 MobileBench-OL（源码 + 全套 CSV + 顺序任务集 + reset 配置） |
| `third_party/mobilebench-ol-main/results/` | 运行产物（**已被 .gitignore 排除**，体积 3 GB+） |

**脚本清单**（都在 `experiments/scripts/`）

| 脚本 | 用途 |
|---|---|
| `mbl_make_task_csv.py` | **生成顺序任务集**：子集 + canonical / reverse / shuffle(seed) |
| `mbl_traj_to_episodes.py` | 真机结果 → `episodes.jsonl`（分析器的输入）；含黑屏检测 |
| `analyze_order_effects.py` | **核心分析**：2×2 析因、ΔSR / CTCI / PASR / victim / polluter / DiD |
| `mbl_apply_api_patch.py` | 给 MobileBench-OL 打补丁（幂等 / 自动备份 / `--revert`） |
| `mbl_api_probe.py` | 零依赖探测端点（模型可用性、`--scan`、`--dump-models`） |
| `mbl_coord_convention_check.py` | **判定模型坐标约定**（norm / pixel）—— 换模型必跑 |
| `mbl_app_checklist.py` | 生成"要装哪些 App"清单（可查设备已装情况） |
| `mbl_task_audit.py` | 任务集审计（编码 / 坏行 / App / Reset 标注 / reset 集重叠） |
| `mbl_purge_tasks.py` | 长跑后摘掉"与实验无关的失败"（黑屏等）以便补跑 |
| `mbl_find_actions.py` | **轨迹取证**：查"是哪个任务的哪一步改了什么" |
| `task_catalog.py` / `order_runner.py` / `make_sim_data.py` / `power_analysis.py` / `selftest.py` | AndroidWorld 那条链路（另一条路线，已验证） |

---

# A. 新机器部署（6 步）

## 0) 前置
**Git** + **Python 3.10 或以上**（本仓库实测 3.10.7）。

```cmd
git --version
python --version
```

## 1) 克隆（路径随意 —— 脚本已改为自动定位）

```cmd
set MBL=D:\GSR
git clone https://github.com/drunksu/GSR.git %MBL%
cd /d %MBL%
```

> `cd /d` 在 cmd 里跨盘符切换必须加 `/d`。

## 2) 建虚拟环境（★ 名字必须叫 `mobile`，必须在仓库根目录）

```cmd
python -m venv mobile
mobile\Scripts\python.exe -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
mobile\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple uiautomator2 pillow opencv-python numpy openai defusedxml lxml requests
```

> 用清华镜像：`pypi.org` 官方源在国内网络下 TLS 握手会被中断（`SSLEOFError`）。
> cmd 里续行符是 `^`（不是 PowerShell 的反引号），一行写不下时才需要。

## 3) 装 adb（platform-tools）

```cmd
curl -L -o third_party\platform-tools.zip https://dl.google.com/android/repository/platform-tools-latest-windows.zip
tar -xf third_party\platform-tools.zip -C third_party
third_party\platform-tools\adb.exe version
```

> `curl` 和 `tar` 都是 Windows 10/11 自带的（`C:\Windows\System32\curl.exe`、`tar.exe`），不需要额外安装。

## 4) 手机 + 改一行配置

```cmd
third_party\platform-tools\adb.exe devices
notepad mobile.env.ps1
```

`notepad` 打开后**只改 `$DEVICE` 那一行**（换成新手机的序列号）。API key 已经在仓库里，不用重填。

手机端要求：

- 开 **USB 调试**（国产机型还要开"USB 调试（安全设置）"）
- **系统语言中文**（成功条件是中文文案的 xpath）
- **充电时保持常亮**（见 B1；熄屏会造成整轮假失败）
- base 子集的 **12 个 App**：B站 / 网易云 / 番茄 / 拼多多 / QQ / 58同城 / 同花顺 / 今日头条 / 高德 / 百度 / 钉钉 / 美柚（**要登录**，很多任务依赖账号既有状态）

## 5) 自检（不插手机也能跑）

```cmd
run_mbl.cmd -TaskFile data\smoke_2task.csv -Output results\_selftest -DryRun
```

看到 `[run_mbl] 模型 = qwen3-vl-plus   坐标约定 = norm` 即环境就绪。

## 6) 开跑 → 见下面 B 节

---

# B. 运行命令

## B0 先设好这几个变量（每个新的 cmd 窗口跑一次）

```cmd
set MBL=D:\GSR
set PY=%MBL%\mobile\Scripts\python.exe
set S=%MBL%\experiments\scripts
set REPO=%MBL%\third_party\mobilebench-ol-main
set ADB=%MBL%\third_party\platform-tools\adb.exe
cd /d %REPO%
```

> ⚠️ **`set` 必须单独一行**。cmd 在**解析整行时**就展开 `%VAR%`，所以
> `set PY=x && %PY% y.py` 这种写法里 `%PY%` 会展开成**空值**（实测踩过）。
> ⚠️ `set VAR=值`：等号两边**不能有空格**，值**不要加引号**（引号会变成值的一部分）。
> ⚠️ `cd /d` 换盘符时必须加 `/d`。
> ⚠️ 若你的路径含空格，调用时加引号：`"%MBL%\run_mbl.cmd" ...`。

**为什么要 `cd` 到 `%REPO%`**：benchmark 用相对路径 `data\...` 解析任务集，输出目录 `results\...` 也落在 benchmark 目录下（与官方一致）。
`%PY%` / `%S%` / `%ADB%` 都是**绝对路径**，所以在哪个目录下都能用。

## B1 唤醒手机（**每次长跑前必做**）

```cmd
%ADB% -s 你的序列号 shell "svc power stayon true; input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; settings put system screen_off_timeout 1800000"
```

## B2 冒烟：2 个 B站任务（约 3 分钟）

```cmd
%MBL%\run_mbl.cmd -TaskFile data\smoke_2task.csv -Output results\smoke
```

## B3 全量两种顺序（一条命令跑完两轮 + 自动分析）

```cmd
%MBL%\pilot.cmd -Tag base -TasksCanonical data\base_canonical.csv -TasksShuffle data\base_shuffle0.csv
```

- 310 个任务 / 一种顺序约 **3 小时**、约 17 M tokens
- 报告自动生成在 `results\base_analysis\report.md`
- **中断不用怕**：结果按任务落盘，重跑同一条命令会自动续跑（已完成任务跳过）

## B4 reset 通道（跑 benchmark 自带的 cleaner）

```cmd
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_smoke_2task.csv -Output results\reset_smoke
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_canonical.csv -Output results\reset_r1
```

第一条是 2 个任务的通道验证（约 3 分钟），第二条是完整的 65 个任务（约 40 分钟）。

⚠️ **reset 必须用独立的 `-Output`**：reset 集的 65 个 task_identifier 与主集**完全重叠**，共用目录会让主运行把它们当成"已完成"跳过。

## B5 换模型 / 多 Agent 对比

```cmd
%MBL%\pilot.cmd -Tag baseflash -Model qwen3-vl-flash -TasksCanonical data\base_canonical.csv -TasksShuffle data\base_shuffle0.csv
```

**可用模型与坐标约定**（`mobile.env.ps1` 里的注册表；★ 约定填错 → 所有点击挤到左上角、任务全灭）

| 模型 | 约定 | 备注 |
|---|---|---|
| `qwen3-vl-plus` | **norm** | 主力，定位 1 px，已有 310 个结果 |
| `qwen3-vl-flash` | **norm** | 同代更弱更便宜 → 更容易落在 0.2–0.8 信号带，**推荐当第二个 Agent** |
| `qwen3-vl-plus-2025-12-19` | **norm** | 日期快照 → 可做版本消融 |
| `qwen3.8-omni-flash` / `qwen3.5-omni-plus` | **norm** | 更新世代，实测精确 |
| `qwen-vl-max` | **pixel** | 老世代，合成图定位偏 630 px |
| `gui-plus` | **pixel** | GUI 专用但定位最差（偏 890 px） |
| `qwen-vl-plus` | norm（推测） | 输出格式有点脏 |
| `qwen3-vl-max` / `qwen2.5-vl-7b/72b-instruct` | — | **不可用**（404 / 403） |

**加新模型**：先跑坐标检测（这两个诊断脚本走标准库直连 API、不经过 PowerShell，所以要自己 `set`；key 可从 `mobile.env.ps1` 里复制）：

```cmd
set MBL_API_KEY=sk-你的key
%PY% %S%\mbl_coord_convention_check.py --model 新模型名 --repo %REPO%
```

## B6 生成新的顺序任务集

```cmd
%PY% %S%\mbl_make_task_csv.py --repo %REPO% --order reverse --out base_reverse.csv
%PY% %S%\mbl_make_task_csv.py --repo %REPO% --order shuffle --seed 1 --out base_shuffle1.csv
%PY% %S%\mbl_make_task_csv.py --repo %REPO% --limit 30 --order shuffle --seed 0 --out sub30_shuffle0.csv
```

> `--out` 写成纯文件名时，输出落到 `%REPO%\data\` 下；文件名必须含 `shuffle<数字>` 才会被 manifest 识别为乱序并记录 seed。

## B7 长跑后的清洗与补跑

```cmd
%PY% %S%\mbl_purge_tasks.py --run-dir results\base_shuffle --blank-only --dry-run
%PY% %S%\mbl_purge_tasks.py --run-dir results\base_shuffle --blank-only
```

摘掉那些与顺序无关的失败（黑屏等）之后，重跑 B3 就会自动补跑它们。

## B8 单独出报告

```cmd
%PY% %S%\analyze_order_effects.py --input results\base_canonical\episodes.jsonl results\base_shuffle\episodes.jsonl --out results\base_analysis --official-condition none
type results\base_analysis\report.md
```

## B9 其他常用查看命令

```cmd
type results\base_canonical\result_list.txt
dir /b results\base_canonical | find /c /v ""
notepad results\base_analysis\report.md
```

---

# C. 同步方式

```cmd
git add -A
git commit -m "描述"
git push
```

拉取：

```cmd
git pull
```

**已排除的内容**（见 `.gitignore`）：截图与元素树（3 GB+）、venv（245 MB）、platform-tools、参考论文 PDF、合成数据、各机器的运行结果。
只同步"代码 + 配置 + 文档"，约 **1.7 MB**。

---

# D. 七个必踩的坑

| # | 坑 | 后果 / 对策 |
|---|---|---|
| 1 | **坐标约定** | 模型输出 0–1000 归一化坐标而代码当像素用 → 所有点击挤到左上角、**任务全灭且看不出原因**。对策：注册表 + `MBL_COORD`，换模型必跑检测 |
| 2 | **`-Output` 目录复用** | `result_list.txt` 是续跑缓存，重名会让任务**全部被跳过**。对策：每种顺序用独立目录 |
| 3 | **venv 必须叫 `mobile` 且在仓库根** | `mobile.env.ps1` 里 `$PY = "$MBL_ROOT\mobile\Scripts\python.exe"` |
| 4 | **手机熄屏** | 截图全黑 → 整轮变成"假失败"，与污染无关。对策：B1 唤醒 + 保持充电；分析前用 `mbl_purge_tasks.py --blank-only` 剔除 |
| 5 | **cmd 里写中文注释** | cmd.exe 用本地代码页（中文 Windows 是 GBK）读 `.bat/.cmd`，UTF-8 中文会被误读、`rem` 行断掉后被当成命令执行。**批处理文件一律纯 ASCII**（本仓库的 `.cmd` 已遵守；想写中文说明就写进 `.md`） |
| 6 | **cmd 里 `set` 与 `%VAR%` 写在同一行** | cmd 在**解析整行时**就展开 `%VAR%`，`set PY=x && %PY% y.py` 会让 `%PY%` 变成空值。**`set` 必须单独一行**（实测踩过） |
| 7 | **相对路径的基准目录** | `results\...` 是相对 benchmark 目录，`mobile\Scripts\...` 是相对仓库根 —— 混用会报"文件不存在"。对策：按 B0 设好绝对路径变量 |

其他已修掉的两个静默失效：

- PowerShell 变量名大小写不敏感，参数 `$Config` 会和 `mobile.env.ps1` 里的 `$CONFIG` 撞成同一个变量被覆盖 → 已改名 `$ConfigFile`（保留 `-Config` 别名）。
- Git 换行符若被转成 CRLF，会让"按精确文本锚点打补丁"的脚本全部失配 → 已加 `.gitattributes` 统一 LF。

**cmd 里中文输出乱码时**：先执行 `chcp 65001`（本仓库的 `.cmd` 没有强制切换，以免影响你终端其他程序的输出）。

---

# E. 对 benchmark 打的补丁（为什么需要）

`mobilebench/utils/mbl_api_shim.py` 是新增模块；7 个文件共 50+ 处标记。全部幂等、自动备份、`--revert` 可回滚。

```cmd
%PY% %S%\mbl_apply_api_patch.py --repo third_party\mobilebench-ol-main --with-retry --coord-norm --task-file-env --metrics --resilient
```

| 补丁 | 解决什么 |
|---|---|
| **key / 模型名走环境变量** | 原代码 `api_key="123456"` 写死、用 `models.list().data[0].id` 猜模型名 → 托管 API 上会选中 `qwen-mt-uni`（翻译模型） |
| **API 错误日志 + 重试** | 原代码接口失败只 `print` 就返回 None → 静默变成 `invalid` action → **会被误判成顺序效应** |
| **坐标归一化换算 + 真实分辨率** | 见坑 #1；同时把写死的 `1080×2400` 换成真实截图尺寸 |
| **滑动用真实屏幕尺寸** | `adb_executor` 原写死 1080×2400（实测设备 1220×2712） |
| **`MBL_TASK_FILE`** | `get_task_file()` 只认 5 个内置 subset，且**没有任何 subset 指向 `*-reset.csv`** → 无法控制顺序、无法跑 reset |
| **每步时间戳 / API 延迟 / token** | 原 `trajectory.json` 完全没有时间与成本信息，无法区分"超时失败"与"污染失败" |
| **抗抖动** | 原 `run_with_reconnect` 的重连是**死代码**、`try_execute_task_with_retry` 的 try 被注释掉 → **一次接口抖动让整个长跑崩溃**（已实际发生：2026-09-20 04:03，310 个任务跑到第 25 个时进程死亡） |

---

# F. 当前进度（诚实记录）

| 项 | 状态 |
|---|---|
| `base_canonical`（规范序 310 任务，qwen3-vl-plus） | ✅ **310/310 完成，SR = 57.1%（177/310）**，用时 2.85 h |
| `base_shuffle`（乱序 310 任务） | ⚠️ **26/310** —— 2026-09-20 04:03 接口断连导致进程崩溃，需用 B3 续跑 |
| `pilot12`（12 任务 × 2 顺序） | ✅ 完成：ΔSR +0.083 [0.000, +0.250]、CTCI 0.154、PASR 0.385，1 个任务翻转（`bili_4`） |
| 冒烟（2 任务） | ✅ 1/2；坐标换算在真机上精确吻合（`378,756` → `461,2050` = 378/1000×1220, 756/1000×2712） |
| reset 通道 | ⏳ 配置与任务集已就绪，未跑 |
| 跨运行状态残留 | ✅ 已有铁证：规范序把百度浏览器切到夜间模式（末帧亮度 44.7），乱序那轮**首帧就是 34.4** —— 继承了下来 |
| QQ 群/好友污染链 | ✅ 已定位：`qq_1`（"**查看**QQ搜索找DND群组"，判定**成功**）实际提交了加群申请（回答了验证问题"龙与地下城"）；`qq_4` 添加了好友。随后 5 个 QQ 任务连续失败（平均 17 步），推理里反复被那个群误导 |

---

# G. 术语

| 术语 | 含义 |
|---|---|
| **OD flaky** | Order-Dependent flaky：结果依赖执行顺序的不稳定任务 |
| **victim** | 因顺序变化而失败的任务 |
| **polluter** | 把状态弄脏、害得后续任务失败的前序任务 |
| **ΔSR** | 乱序与规范序的成功率差（逐任务配对） |
| **CTCI** | Cross-Task Contamination Index：顺序不确定性带来的成功率全幅 |
| **PASR** | Pollution-Aware Success Rate：最坏顺序下的期望成功率（可信下界） |
| **DiD** | Difference-in-Differences：顺序 × 重置的交互项 |
| **condition** | 重置条件：`official`（跑了 cleaner）/ `none`（只重启 App） |
| **order_mode** | 顺序档位：`canonical` / `reverse` / `shuffle<seed>` / `adversarial`（adversarial 尚未实现） |
