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
| `run_mbl.cmd` / `run_mbl.ps1` | 跑一轮：自检 → 写 manifest → 执行 → **自动转 `episodes.jsonl`** |
| `pilot.cmd` / `pilot.ps1` | **一条命令跑完两轮顺序 + 自动分析** |
| `run_repeats.cmd` | 把**同一份任务集跑 N 遍**，每遍独立 `-Output`（重复实验用，见 B10） |
| `sync.cmd` | 一键 `add → 校验有没有 results\ → commit → push`（见 C1） |
| `experiments/docs/` | 01 数据集与 Agent 选型、02 实验方案（2×2 析因 / 指标 / 样本量） |
| `experiments/scripts/` | 全部脚本（见下） |
| `third_party/mobilebench-ol-main/` | **已打补丁**的 MobileBench-OL（源码 + 全套 CSV + 顺序任务集 + reset 配置） |
| `third_party/mobilebench-ol-main/results/` | 运行产物。**小文件（episodes / manifest / trajectory / report）会入库**，只有截图与元素树被 `.gitignore` 排除 |

**脚本清单**（都在 `experiments/scripts/`）

| 脚本 | 用途 |
|---|---|
| `mbl_make_task_csv.py` | **生成顺序任务集**：子集 + canonical / reverse / shuffle(seed) |
| `mbl_traj_to_episodes.py` | 真机结果 → `episodes.jsonl`（分析器的输入）；含黑屏检测 |
| `analyze_order_effects.py` | **核心分析**：2×2 析因、ΔSR / CTCI / PASR / victim / polluter / DiD；报告带「§0 空表诊断」 |
| `mbl_apply_api_patch.py` | 给 MobileBench-OL 打补丁（幂等 / 自动备份 / `--revert`） |
| `mbl_api_probe.py` | 零依赖探测端点（模型可用性、`--scan`、`--dump-models`） |
| `mbl_coord_convention_check.py` | **判定模型坐标约定**（norm / pixel）—— 换模型必跑 |
| `mbl_app_checklist.py` | 生成"要装哪些 App"清单（可查设备已装情况） |
| `mbl_task_audit.py` | 任务集审计（编码 / 坏行 / App / Reset 标注 / reset 集重叠） |
| `mbl_purge_tasks.py` | 长跑后摘掉**设备问题**造成的假失败以便补跑（用 `--blank-failed-only`，见 B7） |
| `mbl_fix_condition_labels.py` | **修正 manifest / episodes 里写错的重置条件标签**（见坑 #13） |
| `mbl_find_actions.py` | **轨迹取证**：查"是哪个任务的哪一步改了什么" |
| `task_catalog.py` / `order_runner.py` / `make_sim_data.py` / `power_analysis.py` / `selftest.py` | AndroidWorld 那条链路（另一条路线，已验证）；`selftest.py` 同时守卫本仓库自己的坑（G1/G2） |

---

# ★★ 全量实验一键流程（**一个块，整块复制粘贴到 cmd**）

> **这一块就是"把所有实验跑完"的全部命令，自包含**：打开一个新的 cmd 窗口，把下面整块复制粘贴进去就开始跑，
> 不需要先做任何设置（路径按 `D:\GSR` 写死，设备序列号已填好）。
> 总机器时间 **≈ 28 小时**、**≈ 177 M tokens**、磁盘 **≈ 8 GB**。
>
> ### ⚠️ 动手前先确认这两件事（否则会"瞬间跑完"、什么都发生不了）
>
> **① 这个块是纯 ASCII 的 —— 千万不要往里加中文。**
> 实测（2026-09-25）：往 cmd **粘贴**的文本里只要有一个非 ASCII 字符，cmd 会用当前代码页（中文 Windows 是
> GBK）去解码 UTF-8 字节，多出来的半个字节会**吃掉下一行的开头**：
>
> ```
> D:\>jects\GUISTA~1              ← 本来是  set MBL=D:\projects\GUISTA~1
> D:\>thon.exe                    ← 本来是  set PY=%MBL%\mobile\Scripts\python.exe
> ```
>
> `set` 全部残废 → 变量全空 → 后面每条命令都在瞬间报"不是内部或外部命令"，**整块 28 小时的任务 1 秒跑完**。
> 更狠的是 `chcp 65001`：夹在粘贴流中间会让**后面整段输入被直接丢弃**。所以这一块里**既没有中文、也没有 `chcp`**。
>
> **② 块里第 15–20 行是 `[CHECK]` 自检** —— 跑完那几行**先看一眼输出**：
>
> ```
> [CHECK] MBL=[D:\GSR]
> [CHECK] PY=[D:\GSR\mobile\Scripts\python.exe]
> [CHECK] REPO=[D:\GSR\third_party\mobilebench-ol-main]
> ```
>
> 三行都必须**有值且路径正确**。如果看到空值或 `[FATAL]`，**停下来**，别让它继续跑 ——
> 块里那三条 `if not exist ... echo [FATAL]` 就是为此准备的。
>
> **想让中文输出不乱码**（可选）：在粘贴本块**之前**，先单独敲一行 `chcp 65001` 回车，再粘。
> 之所以要分开：`chcp` 夹在粘贴流里会截断后续输入（见上）。本块是纯 ASCII 的，所以先切代码页不会有副作用。
>
> ### 其余说明
>
> **中断了怎么办**：断电、接口抖动、手机掉线都不用怕 —— **把整块重新粘贴一遍就是续跑**。
> 每个运行目录都有自己的 `result_list.txt`，已完成的任务会被跳过，不会重复烧 token。
>
> ★ **中途有 12 次需要你在手机上手工操作**（第 4 段的重复实验，恢复 QQ 状态），块里用 `pause` 停下来等你。
>
> **想省时间/省 token**：每段开头都标了单独的成本，**按 `rem` 注释整段删掉**即可，段与段互不依赖。
> 最贵的是第 2 段的 `baseflash`（12.1 h / 81 M tokens）—— 删掉它仍然满足"§1 每个对比都有两个模型"。
>
> ⚠️ **不要把这一块存成 `.cmd` 文件**：循环变量要从 `%r` 改成 `%%r`。**直接粘贴到 cmd 窗口**。


```cmd
rem ===== GSR full experiment set (plus + flash). Re-paste = auto resume =====
rem ===== This block is deliberately 100% ASCII. Do NOT add Chinese to it:  =====
rem ===== non-ASCII bytes break cmd's pasted input and the next line loses   =====
rem ===== its head, which silently kills every "set" below (README pit #18). =====
cd /d D:\GSR
git pull --rebase --autostash
set MBL=D:\GSR
set PY=%MBL%\mobile\Scripts\python.exe
set S=%MBL%\experiments\scripts
set REPO=%MBL%\third_party\mobilebench-ol-main
set ADB=%MBL%\third_party\platform-tools\adb.exe
set DEV=GAGU8HGYW8JF9TIJ
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d %REPO%

rem ===== CHECK. If a [CHECK] line is empty/wrong or you see [FATAL], STOP. =====
echo [CHECK] MBL=[%MBL%]
echo [CHECK] PY=[%PY%]
echo [CHECK] REPO=[%REPO%]
if not exist "%MBL%\run_mbl.cmd" echo [FATAL] run_mbl.cmd missing under MBL -- STOP
if not exist "%PY%" echo [FATAL] venv python missing at PY -- STOP
if not exist "%REPO%\run.py" echo [FATAL] benchmark missing under REPO -- STOP

rem ===== 0. self-test + flash coord check + wake phone (5 min) =====
rem   coord check exit code 3 = "norm convention" = EXPECTED, not a failure
%PY% %S%\selftest.py
%ADB% devices
%PY% %S%\mbl_coord_convention_check.py --model qwen3-vl-flash --repo %REPO%
%ADB% -s %DEV% shell "svc power stayon true; input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; settings put system screen_off_timeout 1800000"

rem ===== 1. plus: backfill base_shuffle (2 tasks) + 65-task same-day 2x2 (6.1 h) =====
%MBL%\pilot.cmd -Tag base -TasksCanonical data\base_canonical.csv -TasksShuffle data\base_shuffle0.csv
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_base.conf  -TaskFile data\reset_canonical.csv -Output results\p1_none_can
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_canonical.csv -Output results\p1_off_can
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_base.conf  -TaskFile data\reset_shuffle0.csv  -Output results\p2_none_shf
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_shuffle0.csv  -Output results\p2_off_shf
%PY% %S%\mbl_purge_tasks.py --run-dir results\base_shuffle --blank-failed-only --dry-run

rem ===== 2. flash: 65-task 2x2 + 310x2 full scale (17.9 h) =====
%MBL%\run_mbl.cmd -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_base.conf  -TaskFile data\reset_canonical.csv -Output results\f_none_can
%MBL%\run_mbl.cmd -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_canonical.csv -Output results\f_off_can
%MBL%\run_mbl.cmd -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_base.conf  -TaskFile data\reset_shuffle0.csv  -Output results\f_none_shf
%MBL%\run_mbl.cmd -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_shuffle0.csv  -Output results\f_off_shf
%MBL%\pilot.cmd -Tag baseflash -Model qwen3-vl-flash -TasksCanonical data\base_canonical.csv -TasksShuffle data\base_shuffle0.csv

rem ===== 3. pilot12 with flash (0.9 h) =====
%MBL%\pilot.cmd -Tag pilot12flash -Model qwen3-vl-flash -TasksCanonical data\pilot12_canonical.csv -TasksShuffle data\pilot12_shuffle0.csv

rem ===== 4. repeat experiment, redone: 6 rounds x 2 orders x 2 models (3.7 h) =====
rem   At every pause, restore QQ state on the phone:
rem     (a) leave the group "DND5..." (the one added in that round)
rem     (b) delete friend 1098074562
rem     (c) unpin the chat with the contact, restore the chat history if deleted
for /l %r in (1,1,6) do (
  %MBL%\run_mbl.cmd -TaskFile data\qqset_canonical.csv -Output results\q2_A_%r
  echo.
  echo ==== round %r order A done. Restore QQ state on the phone, then press any key ====
  pause
  %MBL%\run_mbl.cmd -TaskFile data\qqset_reverse.csv -Output results\q2_B_%r
  echo.
  echo ==== round %r order B done. Restore QQ state again, then press any key ====
  pause
)
for /l %r in (1,1,6) do (
  %MBL%\run_mbl.cmd -Model qwen3-vl-flash -TaskFile data\qqset_canonical.csv -Output results\q2_Af_%r
  echo.
  echo ==== flash round %r order A done. Restore QQ state, then press any key ====
  pause
  %MBL%\run_mbl.cmd -Model qwen3-vl-flash -TaskFile data\qqset_reverse.csv -Output results\q2_Bf_%r
  echo.
  echo ==== flash round %r order B done. Restore QQ state again, then press any key ====
  pause
)

rem ===== 5. build all reports =====
%PY% %S%\analyze_order_effects.py --input results\p1_none_can results\p1_off_can results\p2_none_shf results\p2_off_shf results\f_none_can results\f_off_can results\f_none_shf results\f_off_shf --out results\twomodel_2x2 --official-condition official
%PY% %S%\analyze_order_effects.py --input results\base_canonical results\base_shuffle results\baseflash_canonical results\baseflash_shuffle --out results\scale_analysis --official-condition official
%PY% %S%\analyze_order_effects.py --input results\base_canonical results\base_shuffle results\reset_can results\reset_shf --out results\master_analysis --official-condition official
%PY% %S%\analyze_order_effects.py --input results\q2_A_1 results\q2_A_2 results\q2_A_3 results\q2_A_4 results\q2_A_5 results\q2_A_6 results\q2_B_1 results\q2_B_2 results\q2_B_3 results\q2_B_4 results\q2_B_5 results\q2_B_6 results\q2_Af_1 results\q2_Af_2 results\q2_Af_3 results\q2_Af_4 results\q2_Af_5 results\q2_Af_6 results\q2_Bf_1 results\q2_Bf_2 results\q2_Bf_3 results\q2_Bf_4 results\q2_Bf_5 results\q2_Bf_6 --out results\repeat_analysis --official-condition none
type results\twomodel_2x2\report.md
type results\scale_analysis\report.md
type results\repeat_analysis\report.md

rem ===== 6. upload =====
%MBL%\sync.cmd "results: full experiment set, plus and flash, 2x2 scale repeats"
```

**分段成本速查（想删哪段就删哪段，互不依赖）**

| 段 | 内容 | 机器时间 | tokens |
|---|---|---|---|
| 0 | 准备（自检 / 设备 / flash 坐标检测 / 唤醒） | 5 min | — |
| 1 | plus 补 `base_shuffle` 2 个 + 65 任务同日四格 | ≈ 6.1 h | ≈ 29 M |
| 2 | flash 65 任务四格 + flash 310×2 顺序 | ≈ 17.9 h | ≈ 119 M |
| 3 | `pilot12` 换 flash | ≈ 0.9 h | ≈ 6 M |
| 4 | 重复实验重做版（6 轮 × 2 顺序 × 2 模型，人工恢复） | ≈ 3.7 h | ≈ 25 M |
| 5–6 | 分析 + 上传 | 几分钟 | — |
| **合计** | | **≈ 28 h** | **≈ 177 M** |

**跑到什么程度算"所有实验都有两个模型"**

| 报告 | 需要的目录 | 每个对比的模型数 |
|---|---|---|
| §1 2×2（主结果） | `p1_* p2_* f_*` 共 8 格 | **2** ✅ |
| §2 规模（n≈310） | `base_* baseflash_*` | **2** ✅ |
| §2 小样本（n=65） | 同上 8 格 | **2** ✅ |
| §3 victim / §4 polluter | `q2_*`（＋`q2_*f`） | **2** ✅ |

---

# ★ 待跑清单 —— 照着从上往下粘贴

> 这一节是**操作手册**：还需要跑的所有命令，按顺序排好，每一阶段末尾都带**跑完之后的 Git 操作**。
> 命令都是 CMD。**同一阶段的命令放在同一个 cmd 窗口里跑**（`set` 的变量只在当前窗口有效）。
> 跑不动或想了解每个脚本的细节，再去看 B / C / D 节。

## 现状（2026-09-24 更新）：四格都填上了，但有两处要补

| 格 | 顺序 | 重置条件 | 状态 |
|---|---|---|---|
| A | canonical | `none`（不跑 cleaner） | ✅ 310/310（数据本体 09-20），SR 57.1% |
| B | shuffle | `none` | ⚠️ **308/310** —— 有 2 个被摘掉没补 ← **阶段 6.1** |
| C | canonical | `official`（跑 cleaner） | ✅ 65/65（09-23） |
| D | shuffle | `official` | ✅ 65/65（09-23） |

`results\master_analysis\report.md` 已经出结果，**C1（污染主效应）ΔSR = −0.138，CI [−0.277, −0.015] 显著**；
C2（顺序主效应）≈ 0 不显著 —— 与"cleaner 挡住了同 app 污染"的预期一致。

**但两件事要做**：

1. **阶段 6.1**：`base_shuffle` 补回 2 个任务（1 分钟）。
2. **阶段 6.2**：C1 的两侧不对等（`official` 是 09-23 的 65 任务块，`none` 是 09-20 的 310 任务序列里的 65 个），
   日期差与运行上下文差都混在里面 → 要四格一起重跑才是严格配对。

**阶段 3（重复实验）已跑完但没有信息量**：`qqset` 的 ΔSR 恒等于 `+0.000`、CI `[+0.000, +0.000]`。
原因不是工具坏了（6 次重复的 trajectory MD5 互不相同，确实跑了 48 次），而是：
① QQ 状态在 09-20 那轮就已经**饱和到固定点**（`qq_1` 那轮成功、现在 12/12 失败）；② **重复之间没有重置**，
A 序第 1 遍就定了固定点，B 序的起点因此和 A 一样，顺序这个自变量被自己消掉了。
**重跑同样的东西没用，要改设计**（换"重置便宜"的 writer 任务对，或做轮次级重置）。

每格重复次数仍 **全是 1**（阶段 3 的重复无效）、Agent 有 `qwen3-vl-plus` 与 `qwen3-vl-flash` 两个。

---

## 阶段 0 · 准备（约 5 分钟）

**换机器、或每开一个新的 cmd 窗口，都要重做 0.2。**

### 0.1 拉最新代码（本轮所有修复都在里面）

```cmd
cd /d D:\GSR
git stash
git pull
git stash pop
```

> 仓库不在 `D:\GSR` 就换成你的路径。`git stash` 是保护你未提交的本地改动，工作区干净时可以跳过。
> 若 `git pull` 报冲突，先 `git status` 看清楚是哪个文件，别强推。

### 0.2 设变量（每个新 cmd 窗口一次）

```cmd
set MBL=D:\GSR
set PY=%MBL%\mobile\Scripts\python.exe
set S=%MBL%\experiments\scripts
set REPO=%MBL%\third_party\mobilebench-ol-main
set ADB=%MBL%\third_party\platform-tools\adb.exe
cd /d %REPO%
```

### 0.3 自检 + 设备检查（**必须过，别跳**）

```cmd
%PY% %S%\selftest.py
%ADB% devices
```

要看到 `✅ 全部通过`（17 项）和一行 `device`。少一样就先修，别开长跑。

### 0.4 唤醒手机并设常亮（**每次长跑前必做**）

```cmd
%ADB% -s 你的序列号 shell "svc power stayon true; input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; settings put system screen_off_timeout 1800000"
```

序列号在 `mobile.env.ps1` 的 `$DEVICE` 里。熄屏 = 截图全黑 = 整轮变成"假失败"，与污染无关。

---

## 阶段 1 · 把「乱序 × 不跑 cleaner」格跑满（约 2.6 小时）★ 先做这个

**买到什么**：§2 的 ΔSR 从"26 个公共任务"变成 **n=310/侧**，CTCI / PASR 覆盖全量 —— 这是论文的主数字。

### 1.1 跑（A 格 310 个会秒跳过，从第 27 个接着跑 B 格）

```cmd
%MBL%\pilot.cmd -Tag base -TasksCanonical data\base_canonical.csv -TasksShuffle data\base_shuffle0.csv
```

`pilot.cmd` 会自己唤醒手机、跑两轮、转格式、出报告。**中途断了不要紧，重跑同一条命令就续跑**（`result_list.txt` 是续跑缓存）。

### 1.2 清洗掉"设备问题"造成的假失败

```cmd
%PY% %S%\mbl_purge_tasks.py --run-dir results\base_shuffle --blank-failed-only --dry-run
```

先看 dry-run 的数字合不合理，再删掉 `--dry-run` 真跑一次，然后**重跑 1.1** 让它自动补跑被摘掉的任务。

> ⚠️ 必须用 `--blank-failed-only`，**不要用 `--blank-only`**：实测 310 条里有 20 个末帧偏暗，但其中 **12 个其实是成功的**（播放类任务成功后屏幕就熄了）。`--blank-only` 会把成功的也删掉、污染 SR。

### 1.3 出报告（**先读最上面那节「§0 空表诊断」**）

```cmd
%PY% %S%\analyze_order_effects.py --input results\base_canonical results\base_shuffle --out results\base_analysis --official-condition official
type results\base_analysis\report.md
```

§0 会逐表告诉你"为什么这张表是空的、实测值多少、要补什么"。**别对着空表猜"没有效应"。**

### 1.4 【Git】上传

```cmd
cd /d %MBL%
sync.cmd "results: base_shuffle 310/310"
```

`sync.cmd` 会 `add → 打印将要提交的文件 → 检查有没有 results\ → commit → push`。
**必须看到 `[OK] results\ files are staged.`**；如果是 `[WARN]`，说明结果没进暂存区，**别推**，先看坑 #9。

---

## 阶段 2 · 填上「跑 cleaner」的两个格（约 1.5 小时）

reset 通道**只能用带 `reset_query` / `reset_xpath` 两列的 CSV**，而 310 个任务里只有 65 个有（`data\reset_canonical.csv`）。所以 2×2 落在这 65 个任务的交集上 —— 分析器本来就只在公共任务上算，**不用手动筛**。

### 2.1 通道验证（2 个任务，约 3 分钟）

```cmd
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_smoke_2task.csv -Output results\reset_smoke
```

结尾要看到 `退出码: 0` 和 `episodes: 2 行`。这一步是验证 cleaner 通道本身通的。

### 2.2 C 格：规范序 + 跑 cleaner

```cmd
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_canonical.csv -Output results\reset_can
```

### 2.3 生成 D 格要用的乱序版（生成器会保留 reset_query / reset_xpath 两列）

```cmd
%PY% %S%\mbl_make_task_csv.py --repo %REPO% --source reset_canonical.csv --order shuffle --seed 0 --out reset_shuffle0.csv
```

### 2.4 D 格：乱序 + 跑 cleaner

```cmd
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_shuffle0.csv -Output results\reset_shf
```

> ⚠️ `-Output` **必须独立**：reset 集的 65 个 id 与主集完全重叠，共用目录会让框架把它们当成"已完成"整轮跳过（坑 #2）。

### 2.5 出 2×2 报告

```cmd
%PY% %S%\analyze_order_effects.py --input results\base_canonical results\base_shuffle results\reset_can results\reset_shf --out results\full_analysis --official-condition official
type results\full_analysis\report.md
```

跑到这里，**§1（2×2 析因 + DiD 交互项）和 §2b 应该终于有内容了**。

### 2.6 【Git】上传

```cmd
cd /d %MBL%
sync.cmd "results: reset 2x2 (canonical+shuffle x cleaner)"
```

同样确认 `[OK] results\ files are staged.`。

---

## 阶段 3 · 重复实验 —— 让 §3 victim / §4 polluter 有内容（约 50 分钟）★ 回答原始问题

单轮每格只有 1 个样本时，Fisher 双边 p **恒等于 1.0**、polluter 需要的前序支持度只有 1 —— 这两张表**必然为空**，和真实效应无关。**只有重复跑才能让它们有内容。**

子集已按现有证据**预注册**好了，不用你再挑（`data\qqset_canonical.csv` / `data\qqset_reverse.csv`，各 8 个任务）：

| 角色 | 任务 | 证据 |
|---|---|---|
| 写状态（polluter） | `qq_1` | 判"查看"，实际提交了 DND 群加群申请（答了验证问题"龙与地下城"） |
| 写状态 | `qq_4` | 添加好友 `1098074562`；作者自己标 `Reset=Need` |
| 读状态（victim 候选） | `qq_10` ~ `qq_14` | 规范序里**紧跟 `qq_1` 之后连续 5 个失败**（18/14/20/15/20 步，末帧亮度 238–243 **不是黑屏**） |
| 对照 | `qq_17` | 快速失败（3 步） |

### 3.1 A 序：writer 在前、reader 在后（污染可发生）

```cmd
%MBL%\run_repeats.cmd data\qqset_canonical.csv results\qqset_A 6
```

### 3.2 B 序：reader 先跑、writer 最后（污染来不及发生）

```cmd
%MBL%\run_repeats.cmd data\qqset_reverse.csv results\qqset_B 6
```

`run_repeats.cmd TASKFILE OUTPREFIX N` 把同一份任务集跑 N 遍，每遍写进**独立的 `-Output`**（`qqset_A_r1` … `_r6`）。共用目录会被 `result_list.txt` 整轮跳过 —— 这是必须分开的原因。

**为什么是 6 遍**：由多重比较负担算出来的（§0 会直接算给你），最理想分裂下 8 个任务需 6 遍、12 个需 6 遍、40 个需 7 遍、**310 个需 8 遍**。所以**减少预注册任务数**比无限加重复有效得多。

### 3.3 出报告（所有重复目录一起喂，顺序模式靠各目录自己的 manifest 区分）

```cmd
%PY% %S%\analyze_order_effects.py --input ^
  results\qqset_A_r1 results\qqset_A_r2 results\qqset_A_r3 results\qqset_A_r4 results\qqset_A_r5 results\qqset_A_r6 ^
  results\qqset_B_r1 results\qqset_B_r2 results\qqset_B_r3 results\qqset_B_r4 results\qqset_B_r5 results\qqset_B_r6 ^
  --out results\qqset_analysis --official-condition official
type results\qqset_analysis\report.md
```

**这一步的 §3 / §4 两张表就是"哪个任务因为执行顺序变化而失败"的答案。**

### 3.4 【Git】上传

```cmd
cd /d %MBL%
sync.cmd "results: qqset repeats 6x2 (victim/polluter)"
```

---

## 阶段 4 · 第二个 Agent（可选，约 50 分钟）

原始课题里有"**多个 Agent**"。同理在预注册子集上换 `qwen3-vl-flash`（同代更弱更便宜，**更容易落在 0.2–0.8 信号带**）。坐标约定会从 `mobile.env.ps1` 的注册表自动取，不用手动指定。

```cmd
%MBL%\run_repeats.cmd data\qqset_canonical.csv results\qqset_Af 6 -Model qwen3-vl-flash
%MBL%\run_repeats.cmd data\qqset_reverse.csv   results\qqset_Bf 6 -Model qwen3-vl-flash
```

出报告时把两个 Agent 的目录一起喂（分析器按 `agent` 字段分组）：

```cmd
%PY% %S%\analyze_order_effects.py --input ^
  results\qqset_A_r1 results\qqset_A_r2 results\qqset_A_r3 results\qqset_A_r4 results\qqset_A_r5 results\qqset_A_r6 ^
  results\qqset_B_r1 results\qqset_B_r2 results\qqset_B_r3 results\qqset_B_r4 results\qqset_B_r5 results\qqset_B_r6 ^
  results\qqset_Af_r1 results\qqset_Af_r2 results\qqset_Af_r3 results\qqset_Af_r4 results\qqset_Af_r5 results\qqset_Af_r6 ^
  results\qqset_Bf_r1 results\qqset_Bf_r2 results\qqset_Bf_r3 results\qqset_Bf_r4 results\qqset_Bf_r5 results\qqset_Bf_r6 ^
  --out results\qqset_multiagent_analysis --official-condition official
```

```cmd
cd /d %MBL%
sync.cmd "results: qqset second agent (qwen3-vl-flash)"
```

---

## 阶段 5 · 在**分析机**上汇总（不插手机的那台）

阶段 1–4 全部上传之后，在另一台机器上：

```cmd
cd /d D:\projects\GUI state recovery
git stash
git pull
git stash pop

set MBL=D:\projects\GUI state recovery
set PY=%MBL%\mobile\Scripts\python.exe
set S=%MBL%\experiments\scripts
set REPO=%MBL%\third_party\mobilebench-ol-main
cd /d %REPO%
```

### 5.1 先核验标签（防止再出现"轮次被标错条件"）

```cmd
%PY% %S%\mbl_fix_condition_labels.py --run-dir results\base_canonical results\base_shuffle results\reset_can results\reset_shf --dry-run
```

### 5.2 出总报告

```cmd
%PY% %S%\analyze_order_effects.py --input ^
  results\base_canonical results\base_shuffle ^
  results\reset_can results\reset_shf ^
  --out results\master_analysis --official-condition official
type results\master_analysis\report.md
```

### 5.3 确认 §0 空表诊断已经空掉

报告顶部那节「§0 空表诊断」如果还在报"缺什么"，说明对应阶段还没跑完 —— **回去补，不要解释空表**。

### 5.4 【Git】

```cmd
cd /d %MBL%
sync.cmd "analysis: master report"
```

---

## 每阶段跑完的固定动作（速查）

| 步骤 | 命令 | 判据 |
|---|---|---|
| 1 看这轮是否正常结束 | （看 `run_mbl.cmd` 结尾） | `退出码: 0` + `episodes: N 行` |
| 2 清洗设备问题 | `mbl_purge_tasks.py --run-dir <目录> --blank-failed-only --dry-run` | 数字合理再真删，然后补跑 |
| 3 出报告 | `analyze_order_effects.py --input <各目录> --out <分析目录> --official-condition official` | **先读 §0** |
| 4 上传 | `sync.cmd "results: <这一轮>"` | **`[OK] results\ files are staged.`** |
| 5 分析机汇总 | `git pull` → 重新跑分析器 | §0 里不再有告警 |

> `⚠️ 没有生成 episodes.jsonl` = 这一轮一个任务都没完成，先查目录里的 `result_list.txt`，别急着分析。

---

## 阶段 6 · 补跑 + 同日对照（2026-09-24 决定要做）

### 6.1 补 `base_shuffle` 缺的 2 个任务（约 1 分钟）

`minimap_9`、`neteasemusic_26` 被 `mbl_purge_tasks.py --blank-failed-only` 摘掉了
（`result_list.txt` 里已经查不到它们），所以**重跑同一轮就会自动只补这 2 个**：

```cmd
%MBL%\pilot.cmd -Tag base -TasksCanonical data\base_canonical.csv -TasksShuffle data\base_shuffle0.csv
```

跑完 `results\base_shuffle\episodes.jsonl` 应该从 308 行变成 310 行。

```cmd
cd /d %MBL%
sync.cmd "results: backfill base_shuffle 310/310"
```

### 6.2 把 C1（污染主效应）做成真正的同日配对

**为什么要做。** 现在 C1 = −0.138（CI 不含 0，是目前唯一显著的结果），但它两侧并不对等：

| 侧 | 数据来源 | 什么时候跑的 | 运行上下文 |
|---|---|---|---|
| `official`（跑 cleaner） | `results\reset_can` | **09-23** | 65 任务独立成块 |
| `none`（不跑 cleaner） | `results\base_canonical` 里的那 65 个 | **09-20**（数据本体） | 嵌在 310 任务序列里 |

也就是说 −0.138 里同时混了 **① cleaner 开关 ② 日期差 3 天 ③ 运行上下文（310 块 vs 65 块）**。
要让它变成"同一份 CSV、同一天、只差 cleaner"的严格配对，必须四格一起重跑。

> ⚠️ **只补 `none` 那两格并不能消除这个混淆** —— 只是把"日期差 3 天"变成"2 天"，
> 上下文差消失了但日期差还在。下面给两个方案，按你要的严格程度选。

**方案 1（省钱，约 1.2 小时）**：只补 `none` 两格。

```cmd
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_base.conf -TaskFile data\reset_canonical.csv -Output results\none_can
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_base.conf -TaskFile data\reset_shuffle0.csv  -Output results\none_shf
```

**方案 2（严格，约 6.5 小时）**：四格一起重跑。按"同一份 CSV 的两种条件背靠背"成对执行，
让时间漂移在两格之间**摊平**，而不是全落到其中一格上。

```cmd
rem 第 1 对：规范序，只差 cleaner（约 3.5 h）
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_base.conf  -TaskFile data\reset_canonical.csv -Output results\p1_none_can
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_canonical.csv -Output results\p1_off_can

rem 第 2 对：乱序，只差 cleaner（约 3 h）
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_base.conf  -TaskFile data\reset_shuffle0.csv -Output results\p2_none_shf
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_shuffle0.csv -Output results\p2_off_shf
```

出**严格 2×2**报告（只喂新的四格，别把旧的 `reset_can`/`reset_shf` 混进来 ——
同一格混两个日期反而会把日期差带回来）：

```cmd
%PY% %S%\analyze_order_effects.py --input ^
  results\p1_none_can results\p1_off_can results\p2_none_shf results\p2_off_shf ^
  --out results\strict2x2_analysis --official-condition official
type results\strict2x2_analysis\report.md
```

**全量 §2（n≈310 的 ΔSR / CTCI / PASR）仍然用主分析**，因为它要的是样本量，不是配对严格性：

```cmd
%PY% %S%\analyze_order_effects.py --input results\base_canonical results\base_shuffle --out results\base_analysis --official-condition official
```

上传：

```cmd
cd /d %MBL%
sync.cmd "results: same-day 2x2 pairing"
```

> ℹ️ **`base_canonical` 的 manifest 时间戳不可信**：它的 `started_at/finished_at` 是
> 09-22 22:55 的**秒级跳过重跑**写进去的（310 个任务全部命中 `result_list.txt` 被跳过，3 秒结束），
> 而真正的 `trajectory.json` 是 **09-20** 那轮跑出来的。判断数据"什么时候产生的"要看 trajectory 的 mtime，
> 不要看 manifest。

---

## 阶段 7 · 补齐 `qwen3-vl-flash` 的模型覆盖（**要求：每个实验都有两个模型**）

### 7.1 现状：flash 只覆盖了 96 个 episode，还都在那个无效的 `qqset` 上

| 实验格 | 任务数 | `qwen3-vl-plus` | `qwen3-vl-flash` | 缺口 |
|---|---|---|---|---|
| `base_canonical` × `none` | 310 | ✅ 310 | ❌ | **310** |
| `base_shuffle` × `none` | 310 | ⚠️ 308 | ❌ | **310** |
| `reset_can` × `official` | 65 | ✅ 65 | ❌ | **65** |
| `reset_shf` × `official` | 65 | ✅ 65 | ❌ | **65** |
| `pilot12` | 12 | ✅ 24 | ❌ | （可选）24 |
| `qqset` | 8 | ✅ 96 | ✅ 96 | 0（但实验本身无效，见 F3） |

**flash 总缺口 = 750 episode。**

### 7.2 经济性（用同一批任务上两模型的实测值外推，不是估算）

同一批 8 个任务、各 96 episode 的实测对比：

| | `qwen3-vl-plus` | `qwen3-vl-flash` | flash/plus |
|---|---|---|---|
| 平均步数 | 7.5 | 8.6 | 1.14× |
| 单轮墙钟 | 81.6 s | **70.4 s** | **0.86×** |
| tokens/任务 | 106,888 | **130,842** | **1.22×** |

★ **反直觉但重要**：flash **更快**（墙钟省 14%），但**更贵**（tokens 多 22%）——
因为它步数更多，而每步的 prompt 里带着历史截图，token 随步数**超线性**增长。
所以"用 flash 省钱"是错的，它省的是墙钟不是 token。

**两个补齐方案：**

| 方案 | 内容 | episodes | 墙钟 | tokens | 买到的覆盖 |
|---|---|---|---|---|---|
| **B 小** | 只在 65 任务公共集上把 2×2 补成双模型 | 260 | **≈ 5.8 h** | ≈ 38 M | §1 四个对比 × 2 模型；§2 双模型 n=65 |
| **A 全** | 再补 base 310 × 2 顺序 | +620 | **≈ 12.1 h** | ≈ 81 M | 追加 §2 双模型 **n=310** |
| A = 小 + 全 | | 880 | **≈ 17.9 h** | ≈ 119 M | 全部双模型 |

（`reset` 侧因为 cleaner 每任务多跑一趟，flash 约 91 s/任务、163k tokens/任务；
`none` 侧约 70 s、131k tokens/任务。base 侧约 70 s、131k tokens/任务。磁盘：base 类约 9.45 MB/任务 → A 方案再占约 6 GB，D: 还有 72 GB。）

### 7.3 方案 B 的命令（**推荐先做这个**，约 5.8 小时）

四格背靠背成对跑，让时间漂移在两格之间摊平：

```cmd
rem 规范序：不跑 cleaner / 跑 cleaner
%MBL%\run_mbl.cmd -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_base.conf  -TaskFile data\reset_canonical.csv -Output results\f_none_can
%MBL%\run_mbl.cmd -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_canonical.csv -Output results\f_off_can

rem 乱序：不跑 cleaner / 跑 cleaner
%MBL%\run_mbl.cmd -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_base.conf  -TaskFile data\reset_shuffle0.csv -Output results\f_none_shf
%MBL%\run_mbl.cmd -Model qwen3-vl-flash -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_shuffle0.csv -Output results\f_off_shf
```

> `-Model qwen3-vl-flash` 会**自动**从 `mobile.env.ps1` 的注册表取坐标约定（`norm`），不用手填。
> 但换了机器先验一次更稳：
> ```cmd
> %PY% %S%\mbl_coord_convention_check.py --model qwen3-vl-flash --repo %REPO%
> ```

双模型 2×2 报告（四个 plus 格 + 四个 flash 格一起喂，分析器按 `agent` 分组）：

```cmd
%PY% %S%\analyze_order_effects.py --input ^
  results\p1_none_can results\p1_off_can results\p2_none_shf results\p2_off_shf ^
  results\f_none_can results\f_off_can results\f_none_shf results\f_off_shf ^
  --out results\twomodel_2x2 --official-condition official
type results\twomodel_2x2\report.md
```

（`p1_*`/`p2_*` 是阶段 6.2 方案 2 的 plus 同日四格；如果那一档还没跑，就换成现有的
`results\reset_can results\reset_shf results\none_can results\none_shf`。）

### 7.4 方案 A 追加的命令（约 12 小时，为了 §2 的 n=310 双模型）

```cmd
%MBL%\pilot.cmd -Tag baseflash -Model qwen3-vl-flash -TasksCanonical data\base_canonical.csv -TasksShuffle data\base_shuffle0.csv
```

产出 `results\baseflash_canonical`（310）与 `results\baseflash_shuffle`（310）。
`pilot.cmd` 会自己唤醒手机、跑两轮、转格式、出报告；中断后重跑同一条命令自动续跑。

### 7.5 上传

```cmd
cd /d %MBL%
sync.cmd "results: flash model coverage (two-model 2x2)"
```

### 7.6 到齐之后报告里应该出现什么

`§1` 的四个对比（C1/C2/C3/DiD）**每个都有两行**（`qwen3-vl-plus` 一行、`qwen3-vl-flash` 一行）；
`§2` 的双模型分组表两侧 `n` 相等。**如果 flash 的 C1 也显著为负、C2 ≈ 0，那"cleaner 挡住顺序效应"
这个结论就不是单模型的偶然，可以直接写进论文。**

> ⚠️ **`qwen3-vl-max` 不存在**（托管端 261 个模型里没有它），唯一可用的 "max" 是 `qwen-vl-max`，
> 且它是 **pixel** 坐标约定 —— 见 B5。

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

## 3) adb —— **已经随仓库提供，不用下载**

仓库里已包含 adb 运行必需的 3 个文件（`adb.exe` + `AdbWinApi.dll` + `AdbWinUsbApi.dll`，共 8.1 MB），
clone 完直接验证即可：

```cmd
third_party\platform-tools\adb.exe version
```

> **为什么随仓库提供**：Windows 自带 curl 走 schannel，下载时会先去**联网校验证书吊销状态**，
> 一旦连不上吊销服务器就直接失败（新机器上实测踩到）：
> ```
> curl: (35) schannel: next InitializeSecurityContext failed:
> CRYPT_E_REVOCATION_OFFLINE (0x80092013) - 由于吊销服务器已脱机，吊销功能无法检查吊销。
> ```

**若你手上是旧版本仓库（没有这 3 个文件）**，任选一种方式补上：

```cmd
rem 方式 1：跳过吊销检查（curl 8.x；更温和的写法是 --ssl-revoke-best-effort）
curl --ssl-no-revoke -L -o third_party\platform-tools.zip https://dl.google.com/android/repository/platform-tools-latest-windows.zip

rem 方式 2：换 PowerShell 下载（走 .NET，不做吊销检查）
powershell -Command "Invoke-WebRequest -Uri 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile 'third_party\platform-tools.zip'"

rem 方式 3：浏览器手动下载，放到 third_party\ 下

rem 然后解压 + 验证
tar -xf third_party\platform-tools.zip -C third_party
third_party\platform-tools\adb.exe version
```

> `tar` 是 Windows 10/11 自带的（`C:\Windows\System32\tar.exe`），不需要额外安装。

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

- 310 个任务 / 一种顺序：**实测 6.9 小时**、**31.6 M tokens**（平均 80.5 s、101,960 tokens/任务）

> ⏱️ **别再按"3 小时"做预算了**（这个数字早先是拍脑袋估的，实测差 2.4 倍）。
> 2026-09-24 用 `sum(episode.run_time_s)` 核过：`base_canonical` **6.93 h**、`base_shuffle` **6.54 h**，
> 与 `base_shuffle` 那次的真实墙钟（09-22 22:55 → 09-23 06:04 = 7.15 h，含跳过的规范序一轮）对得上。

- 报告自动生成在 `results\base_analysis\report.md`
- **中断不用怕**：结果按任务落盘，重跑同一条命令会自动续跑（已完成任务跳过）

## B4 reset 通道（跑 benchmark 自带的 cleaner）

```cmd
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_smoke_2task.csv -Output results\reset_smoke
%MBL%\run_mbl.cmd -ConfigFile config\interact_API_qwen3vl_reset.conf -TaskFile data\reset_canonical.csv -Output results\reset_r1
```

第一条是 2 个任务的通道验证（约 3 分钟），第二条是完整的 65 个任务。

> ⏱️ **实测耗时（2026-09-23）**：`reset_canonical` 65 个任务墙钟 **2 h 35 m**（10:21→12:56）、
> `reset_shuffle0` **2 h 19 m**（13:21→15:40）；折算到 agent 身上的净时间分别是 **1.91 h / 1.65 h**
> （106.0 s 与 91.4 s / 任务）。比一开始估的 40 分钟长得多 —— 因为 cleaner 是
> **同一个 GUI agent 去执行 `reset_query`**，每个任务等于多跑一趟。
> 反过来，65 个任务**不跑 cleaner**（base.conf）约 **1.2 h**（约 70 s/任务）。做时间预算时按这个量级算。

跑完 `run_mbl.cmd` 会**自动**在同目录生成 `episodes.jsonl`（转格式已内置，见坑 #10）。所以只有「用别的办法跑的轮次」才需要手动转：

```cmd
%PY% %S%\mbl_traj_to_episodes.py --run-dir results\reset_r1
```

⚠️ **reset 必须用独立的 `-Output`**：reset 集的 65 个 task_identifier 与主集**完全重叠**，共用目录会让主运行把它们当成"已完成"跳过。

## B5 换模型 / 多 Agent 对比

```cmd
rem 一条命令跑完两轮顺序（换模型）
%MBL%\pilot.cmd -Tag baseflash -Model qwen3-vl-flash -TasksCanonical data\base_canonical.csv -TasksShuffle data\base_shuffle0.csv

rem 或者只跑某一轮（换模型；重复实验用 run_repeats.cmd）
%MBL%\run_mbl.cmd -Model qwen3-vl-flash -TaskFile data\reset_canonical.csv -Output results\flash_none_can
```

**可用模型与坐标约定**（`mobile.env.ps1` 里的注册表；★ 约定填错 → 所有点击挤到左上角、任务全灭）

| 模型 | 约定 | 备注 |
|---|---|---|
| `qwen3-vl-plus` | **norm** | 主力，定位 1 px，已有 872 episode |
| `qwen3-vl-flash` | **norm** | 同代更弱更便宜 → 更容易落在 0.2–0.8 信号带，**推荐当第二个 Agent** |
| `qwen3-vl-plus-2025-12-19` | **norm** | 日期快照 → 可做版本消融 |
| `qwen3.8-omni-flash` / `qwen3.5-omni-plus` | **norm** | 更新世代，实测精确 |
| `qwen-vl-max` | **pixel** | **唯一可用的 "max"**；老世代，合成图定位偏 630 px |
| `gui-plus` | **pixel** | GUI 专用但定位最差（偏 890 px） |
| `qwen-vl-plus` | norm（推测） | 输出格式有点脏 |
| `qwen-vl-ocr` | pixel | 纯 OCR，**不是 agent**，只能当定位器用 |
| `qwen3-vl-max` / `qwen2.5-vl-7b/72b-instruct` | — | **不可用**（404 / 403） |

**2026-09-24 复核**：`mbl_api_probe.py --dump-models` 拿到托管端**全部 261 个模型**，其中 VL/omni/GUI 系列实测存在的是：

```
gui-plus, qwen-vl-max, qwen-vl-ocr[-2025-11-20|-latest], qwen-vl-plus,
qwen3-vl-flash[-2025-10-15|-2026-01-22], qwen3-vl-plus[-2025-09-23|-2025-12-19],
qwen3-omni-flash[-2025-09-15|-2025-12-01|-realtime], qwen3.5-omni-flash|plus[-2026-03-15|-realtime],
qwen3.8-omni-flash[-realtime], qwen-omni-turbo
```

★ **`qwen3-vl-max` 不在列表里**（两次确认：既 404、也不在这 261 个里）→ 所以"max 版"只能用老世代的
`qwen-vl-max`，而且它是 **pixel** 约定。想要"强模型对照"的话这一点要在论文里写清楚。

**加新模型**：先跑坐标检测（这两个诊断脚本走标准库直连 API、不经过 PowerShell，所以要自己 `set`；key 可从 `mobile.env.ps1` 里复制）：

```cmd
set MBL_API_KEY=sk-你的key
%PY% %S%\mbl_coord_convention_check.py --model 新模型名 --repo %REPO%
%PY% %S%\mbl_api_probe.py --scan 模型名1,模型名2      rem 批量试可用性
```

> ⚠️ 换模型**必须**先跑坐标检测再开长跑：约定填错的表现是"任务全灭但看不出原因"（见坑 #1）。

## B6 生成新的顺序任务集

```cmd
%PY% %S%\mbl_make_task_csv.py --repo %REPO% --order reverse --out base_reverse.csv
%PY% %S%\mbl_make_task_csv.py --repo %REPO% --order shuffle --seed 1 --out base_shuffle1.csv
%PY% %S%\mbl_make_task_csv.py --repo %REPO% --limit 30 --order shuffle --seed 0 --out sub30_shuffle0.csv
```

> `--out` 写成纯文件名时，输出落到 `%REPO%\data\` 下；文件名必须含 `shuffle<数字>` 才会被 manifest 识别为乱序并记录 seed。

## B7 长跑后的清洗与补跑

```cmd
rem 先干跑看看要摘哪些
%PY% %S%\mbl_purge_tasks.py --run-dir results\base_shuffle --blank-failed-only --dry-run
%PY% %S%\mbl_purge_tasks.py --run-dir results\base_shuffle --blank-failed-only
```

摘掉那些与顺序无关的失败（黑屏/熄屏这类**设备问题**）之后，重跑 B3 就会自动补跑它们。

> ⚠️ **用 `--blank-failed-only`，不要用 `--blank-only`。** 实测 `base_canonical` 的 310 条记录里，
> 末帧偏暗的有 20 个，但其中 **12 个其实是成功的** —— 播放类任务（网易云）成功之后屏幕就熄了，
> 即时通讯类成功之后也常常息屏。"末帧变暗"是**设备活动信号，不是失败原因**。
> `--blank-only` 会把这 12 个成功结果一起删掉、污染 SR；`--blank-failed-only`
> 只取「末帧暗 **且** 失败」的交集（实测 20 → 8）。

## B8 单独出报告

```cmd
%PY% %S%\analyze_order_effects.py --input results\base_canonical results\base_shuffle --out results\base_analysis --official-condition official
type results\base_analysis\report.md
```

> ⚠️ `--official-condition` 指的是**跑了 cleaner 的那个标签**（= `official`）。
> 没跑 cleaner 的轮次（base.conf，`reset=false`）标签是 `none`，属于"被削弱的重置"。
> 之前这里写的是 `none`，是配合一个 bug 写的（见坑 #13）—— 现在已改正。
> 报告最上面那节「§0 空表诊断」会告诉你还缺哪一格、缺几次重复，**先读它再读表**。

## B9 其他常用查看命令

```cmd
type results\base_canonical\result_list.txt
dir /b results\base_canonical | find /c /v ""
notepad results\base_analysis\report.md
```

## B10 重复实验（**让 §3 victim / §4 polluter 两张表有内容的前提**）

单轮每格只有 1 个样本时，Fisher 双边 p **恒等于 1.0**、polluter 需要的前序支持度也只有 1 —— 这两张表**必然为空**，和真实效应无关。要它们有内容就必须重复跑。

```cmd
rem 预注册的 8 个 QQ 任务子集（writer→reader 顺序，即规范序）
%MBL%\run_repeats.cmd data\qqset_canonical.csv results\qqset_A 6

rem 同一批任务的反向顺序（reader 先跑，writer 最后）
%MBL%\run_repeats.cmd data\qqset_reverse.csv results\qqset_B 6

rem 可选：第二个 Agent 跑同一套（多 Agent 维度）
%MBL%\run_repeats.cmd data\qqset_canonical.csv results\qqset_A 6 -Model qwen3-vl-flash
```

`run_repeats.cmd TASKFILE OUTPREFIX N [额外参数]` 会把同一份任务集跑 N 遍，每遍写进**独立的 `-Output`**（`OUTPREFIX_r1` … `OUTPREFIX_rN`）—— 共用目录会被 `result_list.txt` 当成"已完成"整轮跳过，这是必须分开的原因。

**重复次数怎么定**：不是拍脑袋，由多重比较负担决定（`§0 空表诊断` 会直接算给你）。在最理想的 0/n vs n/n 分裂下：

| 同时检验的任务数 | 需要的最少重复次数 |
|---|---|
| 6 个 | 5 |
| 8 个 | 6 |
| 12 个 | 6 |
| 40 个 | 7 |
| 310 个（全量） | 8 |

所以**减少预注册的任务数**比无限加重复更有效。代价参考：8 个任务 × 2 顺序 × 6 遍 ≈ 96 episode ≈ **50 分钟**。

出报告时把**所有重复目录一起**喂进去（顺序模式靠各目录自己的 `run_manifest.json` 区分，不用手动分组）：

```cmd
%PY% %S%\analyze_order_effects.py --input ^
  results\qqset_A_r1 results\qqset_A_r2 results\qqset_A_r3 results\qqset_A_r4 results\qqset_A_r5 results\qqset_A_r6 ^
  results\qqset_B_r1 results\qqset_B_r2 results\qqset_B_r3 results\qqset_B_r4 results\qqset_B_r5 results\qqset_B_r6 ^
  --out results\qqset_analysis --official-condition official
```

> `--input` 传**目录**时只读该目录下的 `episodes.jsonl`（见坑 #15 的修复），所以可以直接传运行目录名，不必写全 `\episodes.jsonl`。

---

# C. 同步方式

## C1 上传自己的实验结果（**每轮跑完都要做**）

```cmd
cd /d "D:\projects\GUI state recovery"
git add -A
git commit -m "results: base_shuffle 310/310"
git push
```

`git add -A` 之后**先看一眼将要提交什么**，别盲推：

```cmd
git status --short
git diff --cached --stat
```

只要看到 `results\...\episodes.jsonl`、`run_manifest.json`、`trajectory.json`、`result_list.txt`、`*_analysis\report.md` 出现在列表里，就是对的。
**如果列表里一个 `results\` 都没有 → 停，先看坑 #9。**

## C2 拉取别人的结果

```cmd
cd /d "D:\projects\GUI state recovery"
git stash
git pull
git stash pop
```

`git stash` 只是为了保护你可能还在改的本地文件；工作区干净时可以跳过。

## C3 什么会同步、什么不会

| 会同步（约 3.2 MB） | 不会同步 |
|---|---|
| 代码、配置、文档 | `step_*.png` / `step_*.xml` / `*_som.png`（截图与元素树，3 GB+） |
| `results\*\episodes.jsonl`（每任务一行，判定+步数） | `mobile\`（venv，245 MB） |
| `results\*\run_manifest.json`（这个目录是哪种顺序/条件） | `third_party\platform-tools.zip` |
| `results\*\*\trajectory.json`、`api_metrics.jsonl`、`step_timing.jsonl`、`result_list.txt` | `paper\`（参考论文 PDF） |
| `results\*_analysis\report.md` 等分析产物 | `experiments\results\sim\`（合成数据，可重生成） |
| adb（`adb.exe` + 2 个 DLL，8.1 MB，见 A3） | |

---

# D. 十八个必踩的坑

| # | 坑 | 后果 / 对策 |
|---|---|---|
| 1 | **坐标约定** | 模型输出 0–1000 归一化坐标而代码当像素用 → 所有点击挤到左上角、**任务全灭且看不出原因**。对策：注册表 + `MBL_COORD`，换模型必跑检测 |
| 2 | **`-Output` 目录复用** | `result_list.txt` 是续跑缓存，重名会让任务**全部被跳过**。对策：每种顺序用独立目录 |
| 3 | **venv 必须叫 `mobile` 且在仓库根** | `mobile.env.ps1` 里 `$PY = "$MBL_ROOT\mobile\Scripts\python.exe"` |
| 4 | **手机熄屏** | 截图全黑 → 整轮变成"假失败"，与污染无关。对策：B1 唤醒 + 保持充电；分析前用 `mbl_purge_tasks.py --blank-only` 剔除 |
| 5 | **cmd 里写中文注释** | cmd.exe 用本地代码页（中文 Windows 是 GBK）读 `.bat/.cmd`，UTF-8 中文会被误读、`rem` 行断掉后被当成命令执行。**批处理文件一律纯 ASCII**（本仓库的 `.cmd` 已遵守；想写中文说明就写进 `.md`） |
| 6 | **cmd 里 `set` 与 `%VAR%` 写在同一行** | cmd 在**解析整行时**就展开 `%VAR%`，`set PY=x && %PY% y.py` 会让 `%PY%` 变成空值。**`set` 必须单独一行**（实测踩过） |
| 7 | **相对路径的基准目录** | `results\...` 是相对 benchmark 目录，`mobile\Scripts\...` 是相对仓库根 —— 混用会报"文件不存在"。对策：按 B0 设好绝对路径变量 |
| 8 | **Windows curl 下载失败（schannel 吊销检查）** | `curl: (35) ... CRYPT_E_REVOCATION_OFFLINE (0x80092013)` —— curl 走 schannel，联网查不到证书吊销状态就拒绝下载。对策：`curl --ssl-no-revoke ...`、或换 `Invoke-WebRequest`、或浏览器下载。（adb 已随仓库提供，正常情况下不需要下载） |
| 9 | **`.gitignore` 把 `results\` 全排掉 → 实验结果悄悄传不上去** | 实测踩过：另一台机器跑完 `git add -A; git commit -m "add report"; git push`，**看着一切正常**，但推上来的 commit 只改了 `mobile.env.ps1` 一个文件，310 个任务的日志全留在本地。原因就是 `.gitignore` 里的 `**/results/**`。对策：只排除 `step_*.png/xml/som/jpg`（当前 `.gitignore` 已如此），并且**推送前用 `git diff --cached --stat` 确认 `results\` 在列表里** |
| 10 | **`run_mbl.ps1` 把 benchmark 跑两遍、且从不转格式** | 实测踩过：脚本末尾**又调用了一次 `& $PY @runArgs`**，而上面那行提示写的是"转成分析格式 `mbl_traj_to_episodes.py`"。三个后果：① 白跑一遍全量扫描（长跑时好几分钟）；② 第一遍崩了第二遍会**悄悄续跑**，退出码没法解读；③ 最要命 —— `run_mbl.cmd` 跑完**根本没有 `episodes.jsonl`**，直接接 B8 会报"没有读到任何 episode"。已修，并在结尾打印 episodes 行数 |
| 11 | **含中文的 `.ps1` 丢了 UTF-8 BOM** | `run_mbl.cmd` 走的是 PowerShell **5.1**，它读**无 BOM** 的 `.ps1` 时按本地代码页 GBK 解码，轻则输出乱码、重则语法错误。实测踩过两次（编辑工具会把 BOM 吃掉）。对策：`selftest.py` 新增 **G1/G2 守卫**（含中文的 `.ps1` 必须有 BOM；`.cmd`/`.bat` 必须纯 ASCII），**改完 `.ps1` 就跑一次自检** |
| 12 | **用 `Get-Content \| Set-Content` 回写含中文的文件会双重编码** | 实测踩过（代价：整份 README 变乱码 + 被推上远端）：本环境的 `Get-Content -Raw` 不带 `-Encoding` 时按 **GBK** 解码 UTF-8 文件，`Set-Content -Encoding UTF8` 再写回 → 全文中文字符串变成 `鈥斺€?` 之类，同时被加上 BOM、换行符也被改写。对策：**不要用 cmdlet 回写要保留的文本**；用编辑工具改，或用 `[System.IO.File]::ReadAllText($p, [System.Text.UTF8Encoding]::new($false))` / `WriteAllText`（显式指定 UTF-8 无 BOM）。改完用 `git diff --stat` 核对：**行数不该出现"整文件重写"那种规模** |
| 13 | **`run_mbl.ps1` 的 reset 判定恒为真 → 所有轮次被标成 `official`** | 原代码 `((Get-Content $cfg \| Select-String '^reset=') -match 'true').Count -gt 0` **永远为真**：config 里实际写的是 `[reset=false]`（带方括号）→ `^reset=` 匹配不到 → 左边是 `$null` → `$null -match 'true'` 得到标量 `$false` → 而 **PowerShell 3+ 给标量也加了 `.Count`（恒为 1）** → `1 -gt 0` = `$true`。后果：用 `reset=false` 的 base.conf 跑出来的 6 个 manifest 全被写成 `reset=True / condition=official`，**把"没跑 cleaner"的轮次标成了官方重置**。拿这种标签做 2×2，两格合并成一格、**交互项静默消失**。已修（显式解析 `[reset=...]` 并跳过注释行），并用 `experiments\scripts\mbl_fix_condition_labels.py` 把已产生的 5 个目录标签改正 |
| 14 | **改完 `.ps1` 一定要重跑自检** | 坑 #11（BOM 被吃掉）、#13（PowerShell 标量 `.Count` 陷阱）都属于"看着没问题、结果全错"的类型。`%PY% %S%\selftest.py` 不依赖手机与 API key，15 项检查约 10 秒，是唯一能在长跑前挡住这类错误的关卡 |
| 15 | **`analyze_order_effects.py --input` 传目录会读进无关文件** | 原实现用 `os.walk` 收目录下**所有** `*.jsonl`，于是每个任务子目录里的 `api_metrics.jsonl` / `step_timing.jsonl`（完全不同的 schema）也被当成 episode 读入 → `KeyError: 'agent'`；若某些行恰好带同名字段，则会**静默**混进统计。而"传目录"恰恰是最自然的写法（B10 就是这么用的）。已修为**只认 `episodes.jsonl`**，找不到时给出明确报错 |
| 16 | **在新开的 cmd 里直接 `%PY% 某脚本.py` 会崩在中文输出上** | `run_mbl.cmd` / `pilot.cmd` 没问题（`mobile.env.ps1` 里设了 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`），但**直接调 python 就没有这两个变量**，Python 会用控制台默认代码页 GBK。实测踩过：`%PY% %S%\selftest.py` 在新 cmd 里 `UnicodeEncodeError: 'gbk' codec can't encode character '\u2705'` —— 因为它最后一行要打印 `✅ 全部通过`。**后果比崩掉更糟：看起来像"自检失败"，其实是输出编码问题。** 对策：① 块里已 `set PYTHONUTF8=1` + `set PYTHONIOENCODING=utf-8`；② `selftest.py` 自己也做了 `sys.stdout.reconfigure(encoding="utf-8")` 兜底 |
| 17 | **诊断脚本"未设置 MBL_API_KEY"** | `mbl_api_probe.py` / `mbl_coord_convention_check.py` 是纯标准库直连 API、**不经过 PowerShell**，所以读不到 `mobile.env.ps1` 里设的 key，在新 cmd 里直接跑会报 `❌ 未设置 MBL_API_KEY`。实测踩过（正好卡在一键流程的第 0 段）。已新增 `experiments/scripts/mbl_env.py`：**先看环境变量，找不到就自动去仓库根的 `mobile.env.ps1` 里解析** —— 不用再手动 `set`，也不用把密钥抄到第二个地方 |
| 18 | **往 cmd 粘贴的命令块里含非 ASCII 字符 → 整块静默失效** | ★ **最容易让人误判"环境坏了"的一个坑。** 实测复现（2026-09-25）：cmd 用**当前代码页**（中文 Windows = GBK）解码粘贴进来的 UTF-8 字节，多出的半个字节会**吃掉下一行的开头**：`set MBL=D:\projects\X` 变成 `jects\X` → 变量全空 → 后面每条命令瞬间报"不是内部或外部命令" → **一个 28 小时的实验块 1 秒钟"跑完"**。更严重的是 `chcp 65001`：夹在粘贴流中间会让**后面整段输入被直接丢弃**（实测整块只剩前两行）。<br>**对策**：① 要粘贴的块**保持纯 ASCII**（本仓库的「★★ 全量实验一键流程」块已改成纯 ASCII，且不含 `chcp`）；② 想显示中文，先**单独敲一行** `chcp 65001` 回车，**再**粘那个 ASCII 块；③ 块里放 `echo [CHECK]` 打印变量、并 `if not exist ... echo [FATAL]` 兜底，**粘贴后先看这几行** |

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

> 更新的时间点：**2026-09-24**。**要跑的命令见上面的「★ 待跑清单」。**

## F1 实验数据

### F1a 模型覆盖矩阵（⚠️ 主实验**只有 plus 一个模型**）

| 实验 | 任务数 | `qwen3-vl-plus` | `qwen3-vl-flash` | 两模型都跑？ |
|---|---|---|---|---|
| `base_canonical` × `none` | 310 | ✅ 310 | ❌ | ❌ |
| `base_shuffle` × `none` | 310 | ✅ 308 | ❌ | ❌ |
| `reset_can` × `official` | 65 | ✅ 65 | ❌ | ❌ |
| `reset_shf` × `official` | 65 | ✅ 65 | ❌ | ❌ |
| `pilot12` × 2 顺序 | 12 | ✅ 24 | ❌ | ❌ |
| `qqset` × 2 顺序 × 6 遍 | 8 | ✅ 96 | ✅ 96 | ✅ **唯一双模型，但它无效**（见 F3） |

按模型汇总：`qwen3-vl-plus` **872 episode**、`qwen3-vl-flash` **96 episode**。

**结论：主结果（2×2 的 C1/C2/C3/DiD 与 n=308 的 ΔSR/CTCI/PASR）目前无法回答"换个 Agent 还成不成立"。**
"多个 Agent"这个维度目前只落在那个无效的 `qqset` 上。

### F1b 各轮数据

| 项 | 状态 |
|---|---|
| `base_canonical`（格 A：规范序 × 不跑 cleaner，qwen3-vl-plus） | ✅ **310/310**，SR = 57.1%（177/310），数据本体跑于 **09-20**，**实测 6.93 h**（早期写的 2.85 h 是错的） |
| `base_shuffle`（格 B：乱序 × 不跑 cleaner） | ⚠️ **308/310** —— 09-20 崩溃后续跑完成于 09-23 06:04；`minimap_9`、`neteasemusic_26` 被 `--blank-failed-only` 摘掉未补 → **阶段 6.1** |
| `reset_can`（格 C：规范序 × 跑 cleaner） | ✅ 65/65，**09-23** 10:21→12:56（**2 h 35 m**，比预估的 40 m 长得多） |
| `reset_shf`（格 D：乱序 × 跑 cleaner） | ✅ 65/65，**09-23** 13:21→15:40（2 h 19 m） |
| `qqset` 重复（8 任务 × 2 顺序 × 6 遍，plus） | ⚠️ **跑了但没有信息量** —— ΔSR 恒等于 `+0.000`、CI `[+0.000, +0.000]`（见 F3） |
| `qqset` 重复（同上，qwen3-vl-flash） | ⚠️ ΔSR `+0.021`、CTCI `0.021` —— 只有 `qq_4` 一个任务有方差 |
| `pilot12`（12 任务 × 2 顺序） | ✅ ΔSR +0.083 [0.000, +0.250]、CTCI 0.083、PASR 0.583，1 个任务翻转（`bili_4`） |

### F1c 补 `qwen3-vl-flash` 要花多少（**用实测值外推**）

flash 实测：**70.4 s**、**130,842 tokens / 任务**（`none` 条件）；带 cleaner 约 **91 s**、**163k tokens / 任务**。

| 做法 | 内容 | episodes | 墙钟 | tokens |
|---|---|---|---|---|
| **B 小**（推荐先做） | 65 任务公共集 → 2 顺序 × 2 条件 | 260 | **≈ 5.8 h** | ≈ 38 M |
| **A 全** | 再补 base 310 × 2 顺序 | +620 | **≈ 12.1 h** | ≈ 81 M |
| A 合计 | | 880 | **≈ 17.9 h** | ≈ 119 M |

详细命令见「★ 待跑清单」**阶段 7**。★ 注意 **flash 比 plus 更快但更贵**（tokens 多 22%，
因为步数多、而每步 prompt 带历史截图 → token 随步数超线性增长），所以别指望用 flash 省 token。

推荐 **B 档**：这样 §1 的四个对比每个都有两个 agent，才能回答"结论是否依赖 Agent"。

## F2 分析结果（`results\master_analysis\report.md`）

**§1 主结果 2×2：**

| 对比 | SR(参照) | SR(处理) | ΔSR | 95% CI | 判读 |
|---|---|---|---|---|---|
| **C1 污染主效应**（不跑 cleaner vs 跑，都规范序） | 0.723 | 0.585 | **−0.138** | **[−0.277, −0.015]** | ✅ **显著** |
| C2 顺序主效应（跑 cleaner 下乱序 vs 规范序） | 0.723 | 0.708 | −0.015 | [−0.092, +0.062] | ❌ 不显著 |
| C3 组合（弱重置 + 乱序） | 0.719 | 0.641 | −0.078 | [−0.203, +0.047] | ❌ 不显著 |
| DiD 交互（C3−C1−C2） | — | — | +0.078 | [−0.047, +0.203] | 方向正确，未达显著 |

**§2 分组：**

| condition | n | 规范序 | 乱序 | ΔSR | CTCI | PASR |
|---|---|---|---|---|---|---|
| `none` | 308 | 0.571 | 0.594 | +0.023 [−0.019, +0.068] | 0.153 | 0.506 |
| `official` | 65 | 0.723 | 0.708 | −0.015 [−0.092, +0.062] | 0.108 | 0.662 |

**读法**：只要跑官方 cleaner，执行顺序几乎不影响成功率（C2 ≈ 0）；不跑 cleaner 时，仅状态污染本身就吃掉
**13.8 个百分点**（C1 显著）；PASR 从 0.506 提到 0.662。DiD 方向为正是预期的故事线，但还没到显著。

⚠️ **C1 的局限**：两侧并非严格配对（`official` 是 09-23 的 65 任务块；`none` 是 09-20 的 310 任务序列里的那 65 个），
日期差与运行上下文差都混在里面 → **阶段 6.2** 就是为了消除它。

**§3 victim / §4 polluter 仍为空表**：§0 诊断已明确说明门槛（重复次数 2 < 8），不是"没有效应"。

## F3 为什么阶段 3 的重复实验无效（重要）

`qqset` 的 plus 侧 **8 任务 × 6 遍 × 2 顺序 = 96 episode，结果两两完全相同**（0/8 个任务有方差）。
6 次重复的 `trajectory.json` **MD5 互不相同**，所以确实真跑了 48 次 —— 是**结果确定性**，不是缓存或没执行。

两个原因：

1. **设备状态已饱和。** 这 8 个 QQ 任务在 09-20 那轮已经跑过，状态被推到固定点：`qq_1`（找 DND 群组）
   当时**成功**（提交了加群申请），现在 **12/12 全失败**（群已加进去、界面路径变了）。
   其余 7 个是幂等的写/读（加好友、置顶、删聊天记录、看钱包），第一遍就到固定点。
2. **重复之间没有重置，顺序这个自变量被自己消掉了。** `run_repeats.cmd` 是先跑完 A 序 6 遍再跑 B 序 6 遍，
   A 序第 1 遍就定了固定点 → B 序的起点与 A 相同 → B 不再是"干净起点先跑 reader"的对照。
   **ΔSR 恒等于 0 是这个设计的必然结果。**

**结论：重跑同样的东西不会有用，必须改设计**（在**轮次之间做轮次级重置** → 见「★★ 全量实验一键流程」段 4 的重做版）。

### F3b 「用 `Reset=Need` 任务当 writer」这个思路**不成立**（实测否定）

原本打算用作者标注 `Reset=Need`（"会产生残留"）的任务当 polluter，配合它们现成的 `reset_query`
做轮次级重置。**用 `base_canonical` 的 310 条实测把这个前提否掉了**：

| 统计量 | 值 |
|---|---|
| 前序任务带 `Reset=Need`/`Search`/`Message` 标注的相邻对数 | 65 |
| 这些后继任务的失败率 | **26/65 = 0.400** |
| 全体基线失败率 | 0.429 |
| **lift** | **0.93**（比基线还略低） |

也就是说：**作者标的"有残留"，并不抬高紧邻后继任务的失败率。** 残留存在（`Reset` 列是证据），
但它大多**不破坏下一个任务**。→ **污染是任务特定的，不是 `Reset=Need` 的普遍性质**；
唯一坐实的耦合仍是 QQ 那条链（加群改变了聊天列表），而它的前序 `qq_1` 根本不在 reset 集里。

这条负结果本身有价值：它说明"状态污染检测"不能靠一个通用的"哪些任务会写脏"的清单来解决 ——
这正是课题要做**检测方法**而不是人工标注的理由。

## F4 已知的判定假阴性（这些任务永远不可能贡献 OD 信号）

| 任务 | 现象 |
|---|---|
| `qq_17`「查看我的 QQ 钱包」 | 12/12 判失败，但轨迹里 agent 明确 `terminate` 说"已查看，余额 0.00 元…支付功能暂停" → **xpath 不匹配这个 App 版本** |
| `baidubrowser_13/14/17` | 早前已怀疑同类问题（状态达到了但 xpath 规则不匹配） |

## F5 已修掉的静默 bug 与口径说明

| 项 | 说明 |
|---|---|
| 条件标签 | 2026-09-22 修掉：6 个 manifest 原被误标为 `reset=True / condition=official`（实际全是不跑 cleaner），已用 `mbl_fix_condition_labels.py` 改正为 `none`；该脚本 09-24 又修了**跨机器找不到 config**（manifest 里的 `repo` 指向 `D:\GSR\...`） |
| 净 SR 口径 | 310 条里 20 个末帧偏暗，但其中 **12 个是成功的** → 清洗必须用 `--blank-failed-only`（20 → 8），用 `--blank-only` 会删掉成功结果 |
| `base_canonical` 的 manifest 时间戳 | **不可信**：`started_at/finished_at` 是 09-22 那次秒级跳过重跑写进去的（3 秒结束），真实数据是 09-20 的 |
| 跨运行状态残留 | ✅ 铁证：规范序把百度浏览器切到夜间模式（末帧亮度 44.7），乱序那轮**首帧就是 34.4** |
| QQ 群/好友污染链 | ✅ 已定位：`qq_1`（"**查看**QQ搜索找DND群组"，判定**成功**）实际提交了加群申请（回答了验证问题"龙与地下城"）；`qq_4` 添加了好友。随后 `qq_10`~`qq_14` **连续 5 个失败**（18/14/20/15/20 步，末帧亮度 238–243 不是黑屏），推理里反复被那个群误导 |

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
