# experiments/ —— 「执行顺序 → 成功率」（OD flaky）实验工作台

> 📌 **部署、运行命令、同步方式、必踩的坑、当前进度 → 见仓库根目录 [`../README.md`](../README.md)**
> 本文件只说明"每个脚本干什么"与"已验证到哪一步"。

为开题报告（`面向移动GUI智能体评测的应用状态污染检测和恢复方法研究`）里那一项实验准备的可执行工作台：

> **做点实验：OD Flaky tests 是否影响成功率？某个任务因为执行顺序变化而失败**
> - 顺序执行 vs. 乱序执行
> - 多个 Agent

**两条技术路线**：

| 路线 | 平台 | 状态 |
|---|---|---|
| **MobileBench-OL（当前主线）** | 真机 + 12 个真实中国 App + 托管 API（qwen3-vl-plus） | ✅ 已跑通，规范序 310 任务完成 |
| AndroidWorld | 模拟器 + app 快照 | ✅ 代码与合成数据自检通过，真机路径未验证 |

---

## 目录结构

```
experiments/
├─ README.md                      ← 本文件（入口 + 复现命令 + 已验证/未验证清单）
├─ docs/
│  ├─ 01-数据集与Agent选型.md      ← 在哪跑（在线数据集）、用谁跑（Agent），含决策矩阵与代码级证据
│  └─ 02-实验方案-顺序vs乱序.md    ← 2×2 析因设计、假设、指标、样本量、预算、效度威胁
├─ data/
│  └─ pilot_tasks.txt             ← 试点用 6 个任务
├─ scripts/
│  ├─ task_catalog.py             ← 33 任务 / 7 状态域的推荐实验集（含 writer/reader 标注）
│  ├─ order_runner.py             ← 顺序 × 重置条件可控的调度器（AndroidWorld 后端 + dry-run）
│  ├─ analyze_order_effects.py    ← 2×2 析因分析：ΔSR / OD-flaky 率 / CTCI / PASR / polluter lift / DiD
│  ├─ make_sim_data.py            ← 生成带已知顺序效应的合成数据（管道自检用）
│  └─ power_analysis.py           ← 样本量计算
└─ results/                       ← 输出（plan / sim / analysis）
```

---

## 30 秒上手（不需要模拟器）

```powershell
cd experiments\scripts
$env:PYTHONUTF8=1

# 1) 看推荐任务集
python task_catalog.py

# 2) 生成执行计划（顺序 × 重置 × Agent × 重复）
python order_runner.py --backend dryrun --out-dir ..\results\plan

# 3) 生成"已知答案"的合成数据，验证分析管道
python make_sim_data.py --out ..\results\sim --repeats 12
python analyze_order_effects.py --input ..\results\sim\episodes.jsonl `
    --out ..\results\sim\analysis --check-against ..\results\sim\ground_truth.json

# 4) 算样本量
python power_analysis.py --p 0.6 --deltas 0.1,0.2,0.3,0.45

# 5) 一条命令跑完全部验证（13 项检查，约 9 s）
python selftest.py
```

需要 Python 3.8+，**只用标准库**（本机 Python 3.10 实测通过）。

---

## 真跑 AndroidWorld（需要模拟器 + API key）

```powershell
# 前置：AVD = Pixel 6 / Tiramisu API 33 / 名 AndroidWorldAvd
#       emulator -avd AndroidWorldAvd -no-snapshot -grpc 8554
#       pip install android_world 依赖，设置 OPENAI_API_KEY / GCP_API_KEY

python order_runner.py --backend androidworld `
  --agents t3a_gpt4 `
  --tasks-file ..\data\pilot_tasks.txt `
  --order-modes canonical,adversarial `
  --clean-modes official,none `
  --repeats 10 `
  --out-dir ..\results\pilot

python analyze_order_effects.py --input ..\results\pilot --out ..\results\pilot\analysis
```

`order_runner.py` 做的关键一件事：AndroidWorld 的 `create_suite()` 结尾是
`Suite(sorted(suite.items()))`，**执行顺序被强制成字典序**；本模块在
`Suite(dict)` 上按计划重排 key，从而真正做到"乱序执行"。
重置强度则通过运行时 monkey-patch 调整（`app_snapshot.restore_snapshot` / `TaskEval.tear_down`），
**不修改被测系统的任何文件**。

---

## 已验证 / 未验证（诚实清单）

### ✅ 本机实测通过

| 项 | 证据 |
|---|---|
| 任务目录 | `task_catalog.py` → 33 任务 / 7 状态域 / 26 个在快照覆盖内、7 个在覆盖外 |
| 计划生成 | `order_runner.py --backend dryrun` → 42 runs / 1368 episodes（默认参数），0.06 s 出计划 |
| 顺序构造 | 对抗序在 4 个日历读任务上构造出 3 对同簇 writer→reader 紧邻；字典序 2 对；`shuffle(0)` 1 对 |
| 顺序不变式 | 5 种顺序模式 × 5 个 seed 均恰好是原任务集的排列（不丢任务、不重复）；修复了"reader 多于 writer 时丢任务"的 bug 并加了回归测试 |
| 统计正确性 | 对数域 Fisher 与原始大整数实现逐表比对 **6561 张表全部一致**；BH FDR 单调性、bootstrap CI 覆盖性均通过 |
| 分析管道 | 22 176 条合成 episode → 自检 **precision 0.95 / recall 0.63**（19 真 victim 检出、1 个边界误判） |
| 科学形态 | official 条件下 C2 ΔSR ∈ [−0.02, +0.02]、**4 个 agent 全 0 victim**（H2）；污染 + 对抗序 ΔSR −0.19~−0.30、OD-flaky 39–46%（H1） |
| 交互项 | DiD +0.060 ~ +0.116（4 个中 3 个 CI 不含 0）→ 顺序效应只在污染条件下被放大 |
| 样本量工具 | `power_analysis.py` 输出 ΔSR=0.2 → 97/组；0.30 → 42/组；0.45 → 17/组 |
| 一键复现 | `python selftest.py` → **13 项检查全绿**，约 9 s，无需模拟器/API key |

### ⚠️ 尚未验证（缺环境，不是缺代码）

| 项 | 缺什么 |
|---|---|
| `--backend androidworld` 真机路径 | 本机无 Android SDK / adb / AVD / API key；该分支代码按官方 API 编写，首次运行需按报错微调（可能点：`checkpointer_lib` 的引用方式、`create_suite` 的 `env` 参数版本差异） |
| `--verify-catalog` | 需要装有 `android_world` 才能把目录里的 `apps` 与 registry 的 `app_names` 对齐 |
| 任务目录里的 app 归属字符串 | 按官方 task list 人工抄写，**首次落地务必先跑 `--verify-catalog`** |

---

## 下一步（建议顺序）

**MobileBench-OL 主线**（命令见根目录 README 的 B 节）：

1. **续跑乱序**：`results/base_shuffle` 停在 26/310（接口断连崩的），重跑同一条命令自动续
2. **清洗 + 出报告**：`mbl_purge_tasks.py --blank-only` 摘掉黑屏 episode 后补跑，再跑分析器
3. **加第二个 Agent**：`qwen3-vl-flash`（同代更弱 → 更容易落在 0.2–0.8 信号带）
4. **补 reset 通道**：填上分析器 §1 的 C1/C3 与 DiD 交互项
5. **加重复**：同一顺序跑 ≥3 次，才能出 polluter 排名与 per-task 显著性
6. **可选**：实现对抗序（`adversarial`）与分块随机（`blocked`）—— 见根目录 README 术语表

**AndroidWorld 支线**（另一条路线，本机无模拟器故未验证）：

---

## 术语速查

| 术语 | 含义 |
|---|---|
| **OD flaky** | Order-Dependent flaky：结果依赖执行顺序的不稳定测试/任务 |
| **victim** | 因顺序变化而失败的任务 |
| **polluter** | 把状态弄脏、害得后续任务失败的前序任务 |
| **CTCI** | Cross-Task Contamination Index：顺序不确定性带来的成功率全幅 |
| **PASR** | Pollution-Aware Success Rate：最坏顺序下的期望成功率（可信下界） |
| **DiD** | Difference-in-Differences：顺序 × 重置的交互项 |
| **clean mode** | 重置强度档位：official / no_reset / no_teardown / none |
| **order mode** | 执行顺序档位：canonical / reverse / shuffle / adversarial |
