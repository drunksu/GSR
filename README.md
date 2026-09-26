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

---

## 现在要做什么（先看这一节）

有**两台**机器，分工不同：

| | 有手机的那台（仓库在 `D:\GSR`） | 分析机（本文档所在机器） |
|---|---|---|
| 干什么 | **跑实验**（全部 ≈ 28 h） | **只出报告**，不插手机 |
| 怎么做 | `git pull --rebase --autostash`，然后跑 **`D:\GSR\run_all.cmd`** —— 就这一条。中途 12 次 `pause` 时在手机上恢复 QQ 状态 | `git pull` → 跑 `analyze_order_effects.py`，见 **「二、分析机」** |
| 命令在哪 | **「一、有手机的那台机器」**（一条命令） | **「二、分析机」** |

**为什么是一条脚本、而不是让你粘贴一大堆命令**：粘贴大段命令有两个实测踩过的坑 ——
① 文本里只要有**一个非 ASCII 字符**，cmd 会用 GBK 解码 UTF-8 字节、**吃掉下一行的开头**，所有 `set` 残废；
② 在一条命令还在执行时把后面几十行灌进去，控制台会**原样回显但不执行**，看起来像"跑完了"其实什么都没发生。
（详见坑 #18。）`run_all.cmd` 是**纯 ASCII 文件**，这两类问题都不存在。它做的事和原来看起来一样，
内容可以直接打开核对。

**★ 唯一需要你手动做的**：第 4 步（重复实验）有 **12 次 `pause`**，每次要在手机上
退出 DND 群 / 删好友 `1098074562` / 取消置顶，做完回 cmd 按任意键。**人不在旁边它会一直停着。**

---

## 文档地图

| 章节 | 讲什么 | 谁需要看 |
|---|---|---|
| **一、有手机的那台机器** | **跑 `run_all.cmd` 一条命令**跑完全部实验（含出报告 + 上传） | ★ 有手机那台，**只看这个** |
| **二、分析机** | 拉取 → 校验标签 → 出三份报告 → 看判据 → 上传 | 分析机 |
| **A. 新机器部署** | 克隆 / 建 venv / adb / 装 App / 改设备序列号 | 换新机器时 |
| **B. 运行命令** | 每个脚本的单独用法：B1 唤醒 · B3 全量两顺序 · B4 reset 通道 · B5 换模型 · B6 造任务集 · B7 清洗 · B8 出报告 · B10 重复实验 | 想单独跑某一步时 |
| **C. 同步方式** | 上传 / 拉取 / 什么会入库什么不会 | 每轮跑完 |
| **D. 十八个必踩的坑** | 全是实测踩过的静默失效 | **出问题先查这里** |
| **E. 补丁** | 为什么这个仓库改了 benchmark 源码 | 想了解背景 |
| **F. 当前进度** | 已经跑出什么结果、还缺什么 | 想了解现状 |
| **G. 术语** | OD flaky / victim / polluter / CTCI / PASR / DiD | 看报告时 |


## 目录速查

| 路径 | 内容 |
|---|---|
| `mobile.env.ps1` | **环境配置**：API key、模型注册表（含坐标约定）、路径、设备序列号 |
| **`run_all.cmd`** | ★ **跑完全部实验的唯一入口**（一条命令，纯 ASCII，见「一、」） |
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
| `mbl_env.py` | 给直连 API 的脚本找 API key（不用手动 `set MBL_API_KEY`，见坑 #17） |
| `mbl_find_actions.py` | **轨迹取证**：查"是哪个任务的哪一步改了什么" |
| `task_catalog.py` / `order_runner.py` / `make_sim_data.py` / `power_analysis.py` / `selftest.py` | AndroidWorld 那条链路（另一条路线，已验证）；`selftest.py` 同时守卫本仓库自己的坑（G1/G2） |

---

# 一、有手机的那台机器：跑一条命令

## 就这样，一条命令

```cmd
D:\GSR\run_all.cmd
```

> 打开 cmd，敲（或粘贴）上面这一行，回车，然后就不用管了 —— **除了中途 12 次 `pause`**。
> 脚本会自己检查环境、跑完全部实验、出三份报告、最后 `git pull` + 上传。

**为什么是一条脚本而不是让你粘贴一大堆命令**：往 cmd 里粘贴大段命令有两个实测踩过的坑 ——
① 文本里只要有**一个非 ASCII 字符**，cmd 会用 GBK 解码 UTF-8 字节、**吃掉下一行的开头**，`set` 全部残废；
② 在一条命令还在执行时把后面几十行灌进去，控制台会先**原样回显**它们但**不执行**，看起来像"跑完了其实什么都没发生"。
`run_all.cmd` 是**纯 ASCII 文件**（内容等于原来那一大块命令，循环变量已改成 `%%r`），**这两类问题都不存在**。
脚本内容可直接打开 `run_all.cmd` 核对。

> 想让控制台中文不乱码：先单独敲一行 `chcp 65001` 再跑脚本（可选，不影响实验）。

## 脚本会做什么

| 步 | 内容 | 机器时间 | tokens |
|---|---|---|---|
| 0 | 环境自检（`[CHECK]`/`[FATAL]`）+ flash 坐标检测 + 唤醒手机 | 5 min | — |
| 1 | plus：补 `base_shuffle` 缺的 2 个任务 + 65 任务同日四格 | ≈ 6.1 h | ≈ 29 M |
| 2 | flash：65 任务四格 + flash 310×2 顺序（全量） | ≈ 17.9 h | ≈ 119 M |
| 3 | `pilot12` 换 flash | ≈ 0.9 h | ≈ 6 M |
| 4 | 重复实验重做版：6 轮 × 2 顺序 × 2 模型（**12 次人工恢复 QQ 状态**） | ≈ 3.7 h | ≈ 25 M |
| 5 | 出三份报告（`type` 出来给你看） | 几分钟 | — |
| 6 | `git pull` + `sync.cmd` 上传 | — | — |
| 7 | 打印三条报告路径 | — | — |
| **合计** | | **≈ 28 h** | **≈ 177 M** |

## 三条铁律

1. **先 pull**：跑之前保证仓库是最新的（`cd /d D:\GSR` → `git pull --rebase --autostash`），
   否则脚本里引用的 `run_all.cmd` / `sync.cmd` / 任务集 CSV 可能不存在。
2. **中断了就直接重跑 `D:\GSR\run_all.cmd`** —— 每个运行目录有自己的 `result_list.txt`，
   已完成的任务会跳过，**不会重复烧 token**。断电、接口抖动、手机掉线都不怕。
3. **第 4 步那 12 次 `pause` 必须有人守着**：每次要在手机上做三件事 ——
   ① 退出这一轮加进去的那个 DND 群；② 删掉好友 `1098074562`；③ 取消和「绕堤沙」的聊天置顶、
   如果聊天记录被删了就随便发一条恢复。做完回 cmd 按任意键。
   **人不在旁边它就会一直停在那里。**

## 想省时间 / 省 token

`run_all.cmd` 里每一步都有 `echo ============ N. ...` 分隔和 `rem` 说明，**整段删掉即可**，段与段互不依赖。
最贵的是第 2 步里的 `baseflash`（310×2 顺序 = 12.1 h / 81 M tokens）——
**删掉它仍然满足"§1 每个对比都有两个模型"**（第 2 步剩下的四行 `f_*` 就是 65 任务的 flash 四格）。

## 跑完（或跑挂了）怎么办

**跑完**：脚本最后一条就是上传。直接把 `D:\GSR` 上最新的 commit 号发给我，我在这台机器上出报告。

**跑挂了**：把 cmd 窗口最后 30 行发我。特别注意这几种：
- 出现 `[FATAL]` → 环境问题，脚本已经停在实验之前，什么都没跑
- `退出码: 1` 而且上面有 `Connection error` → 接口抖动，**直接重跑脚本**即可续跑
- 卡在 `Press any key to continue` → 是第 4 步在等你恢复 QQ 状态

**跑到什么程度算"所有实验都有两个模型"**

| 报告 | 需要的目录 | 每个对比的模型数 |
|---|---|---|
| §1 2×2（主结果） | `p1_* p2_* f_*` 共 8 格 | **2** ✅ |
| §2 规模（n≈310） | `base_* baseflash_*` | **2** ✅ |
| §2 小样本（n=65） | 同上 8 格 | **2** ✅ |
| §3 victim / §4 polluter | `q2_*`（＋`q2_*f`） | **2** ✅ |

---

# 二、分析机（不插手机的那台）

那台跑完并把块尾的 `sync.cmd` 跑掉之后，在**这台**机器上做下面的操作。

```cmd
cd /d D:\projects\GUI state recovery
git pull --rebase --autostash

set MBL=D:\projects\GUI state recovery
set PY=%MBL%\mobile\Scripts\python.exe
set S=%MBL%\experiments\scripts
set REPO=%MBL%\third_party\mobilebench-ol-main
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d %REPO%

rem step 1. verify the condition/order/agent labels before trusting anything
%PY% %S%\mbl_fix_condition_labels.py --run-dir results\p1_none_can results\p1_off_can results\f_none_can results\baseflash_canonical --dry-run

rem step 2. verify flash really is the norm convention before comparing
%PY% %S%\mbl_coord_convention_check.py --model qwen3-vl-flash --repo %REPO%

rem step 3. rebuild every report from all episode files
%PY% %S%\analyze_order_effects.py --input results\p1_none_can results\p1_off_can results\p2_none_shf results\p2_off_shf results\f_none_can results\f_off_can results\f_none_shf results\f_off_shf --out results\twomodel_2x2 --official-condition official
%PY% %S%\analyze_order_effects.py --input results\base_canonical results\base_shuffle results\baseflash_canonical results\baseflash_shuffle --out results\scale_analysis --official-condition official
%PY% %S%\analyze_order_effects.py --input results\q2_A_1 results\q2_A_2 results\q2_A_3 results\q2_A_4 results\q2_A_5 results\q2_A_6 results\q2_B_1 results\q2_B_2 results\q2_B_3 results\q2_B_4 results\q2_B_5 results\q2_B_6 results\q2_Af_1 results\q2_Af_2 results\q2_Af_3 results\q2_Af_4 results\q2_Af_5 results\q2_Af_6 results\q2_Bf_1 results\q2_Bf_2 results\q2_Bf_3 results\q2_Bf_4 results\q2_Bf_5 results\q2_Bf_6 --out results\repeat_analysis --official-condition none

rem step 4. read the reports. ALWAYS read the first section (empty-table
rem   diagnostics) before the tables: it states, per table, why it is empty
rem   and what to add. An empty table means "threshold not reached",
rem   NOT "no effect".
type results\twomodel_2x2\report.md
type results\scale_analysis\report.md
type results\repeat_analysis\report.md

rem step 5. upload the regenerated reports
%MBL%\sync.cmd "analysis: two-model 2x2 + scale + repeats"
```

**看报告的判据**

| 看到什么 | 说明 |
|---|---|
| §1 里每个对比**两行**（plus 一行 + flash 一行） | 多 Agent 维度齐了 |
| §1 的 `C1 污染主效应` CI 不含 0 | 状态污染确实吃掉了成功率 |
| §1 的 `C2 顺序主效应` ≈ 0 且不显著 | 与"cleaner 挡住了同 app 污染"一致 |
| §3 / §4 非空 | 逐任务的 victim / polluter 终于可识别（重复实验起了作用） |
| §0 空表诊断里还有条目 | 对应那段实验还没跑完 → 回去补，**不要解释空表** |

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

**若你手上是旧版本仓库（没有这 3 个文件）**，任选一种方式补上（下面三个 `rem` 分别对应：跳过吊销检查 / 换 PowerShell 下载 / 浏览器手动下载）：

```cmd
rem option 1: skip the revocation check (curl 8.x); gentler variant is --ssl-revoke-best-effort
curl --ssl-no-revoke -L -o third_party\platform-tools.zip https://dl.google.com/android/repository/platform-tools-latest-windows.zip

rem option 2: download with PowerShell (.NET, no revocation check)
powershell -Command "Invoke-WebRequest -Uri 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile 'third_party\platform-tools.zip'"

rem option 3: download in a browser and drop it into third_party\

rem then unzip and verify
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

序列号就是 `mobile.env.ps1` 里的 `$DEVICE`（当前设备是 `GAGU8HGYW8JF9TIJ`）：

```cmd
%ADB% -s GAGU8HGYW8JF9TIJ shell "svc power stayon true; input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; settings put system screen_off_timeout 1800000"
```

> `pilot.cmd` 会自己唤醒，用 `run_mbl.cmd` 时才需要手动跑这一条。

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
rem run both order passes with another model
%MBL%\pilot.cmd -Tag baseflash -Model qwen3-vl-flash -TasksCanonical data\base_canonical.csv -TasksShuffle data\base_shuffle0.csv

rem or just one pass (for repeats use run_repeats.cmd)
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

**加新模型**：先跑坐标检测。`--model` 用真实模型名替换下面的 `MODEL_NAME`；
**不需要 `set MBL_API_KEY`** —— 脚本会用 `experiments/scripts/mbl_env.py` 自动去仓库根的 `mobile.env.ps1` 里读 key。

```cmd
%PY% %S%\mbl_coord_convention_check.py --model MODEL_NAME --repo %REPO%
%PY% %S%\mbl_api_probe.py --scan MODEL_NAME,ANOTHER_MODEL_NAME
```

> ⚠️ 换模型**必须**先跑坐标检测再开长跑：约定填错的表现是"任务全灭但看不出原因"（见坑 #1）。
> 退出码 **3 = 判定 norm**（需要换算）、**0 = 判定 pixel** —— 都是正常结论，不是失败。

## B6 生成新的顺序任务集

```cmd
%PY% %S%\mbl_make_task_csv.py --repo %REPO% --order reverse --out base_reverse.csv
%PY% %S%\mbl_make_task_csv.py --repo %REPO% --order shuffle --seed 1 --out base_shuffle1.csv
%PY% %S%\mbl_make_task_csv.py --repo %REPO% --limit 30 --order shuffle --seed 0 --out sub30_shuffle0.csv
```

> `--out` 写成纯文件名时，输出落到 `%REPO%\data\` 下；文件名必须含 `shuffle<数字>` 才会被 manifest 识别为乱序并记录 seed。

## B7 长跑后的清洗与补跑

```cmd
rem dry run first to see what would be dropped
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
rem pre-registered 8-task QQ subset, writer-before-reader order
%MBL%\run_repeats.cmd data\qqset_canonical.csv results\qqset_A 6

rem same tasks in reverse order (readers first, writers last)
%MBL%\run_repeats.cmd data\qqset_reverse.csv results\qqset_B 6

rem optional: same set with the second agent
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
| 18 | **手工往 cmd 粘贴大段命令 → 整块静默失效（两个独立原因）** | ★ **最容易让人误判"环境坏了"的坑，实测踩过两次。**<br>**原因 A（非 ASCII）**：cmd 用**当前代码页**（中文 Windows = GBK）解码粘贴进来的 UTF-8 字节，多出的半个字节会**吃掉下一行的开头** —— `set MBL=D:\projects\X` 变成 `jects\X` → 变量全空 → 后面每条命令瞬间报"不是内部或外部命令" → **28 小时的实验块 1 秒"跑完"**。更狠的是 `chcp 65001` 夹在粘贴流中间时，**后面整段输入被直接丢弃**（实测只剩前两行）。<br>**原因 B（输入缓冲）**：在一条命令（如 `adb shell`、`selftest.py`）**还在执行时**把后面几十行灌进去，控制台会先把它们**原样回显**（特征是**没有 `D:\...>` 提示符前缀**），cmd 要等当前命令结束才回到提示符去读 —— 看起来像"跑完了"，实际一条都没执行。<br>**对策（釜底抽薪）**：不要手工粘贴，**把命令写进一个纯 ASCII 的 `.cmd` 文件，跑那个文件** —— 见「一、」的 `run_all.cmd`。若必须粘贴：① 块保持纯 ASCII；② 先单独敲 `chcp 65001` 回车再粘；③ **等上一条命令跑完、提示符回来再粘下一段**；④ 块里放 `echo [CHECK]` 打印变量 + `if not exist ... echo [FATAL]` 兜底，粘完先看这几行 |

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
