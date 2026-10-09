# backup/androidworld/ — AndroidWorld 模拟器支线（未验证）

归档时间 2026-10-09。动机研究全程在真机 MobileBench-OL 上完成；这条模拟器路线只走到
"代码 + 合成数据自检通过"，真机（模拟器）路径从未在本机验证。归档不删除，以后要做
快照重置路线时可以捡起来。

## 归档内容

| 文件 | 作用 |
|---|---|
| `task_catalog.py` | 33 任务 / 7 状态域的推荐实验集（含 writer/reader 标注） |
| `order_runner.py` | 顺序 × 重置条件可控的调度器（AndroidWorld 后端 + dry-run） |
| `make_sim_data.py` | 生成带已知顺序效应的合成数据（管道自检用）；依赖同目录前两个脚本 |
| `power_analysis.py` | 样本量计算（纯函数，`selftest` 不再守它，用前自测） |
| `pilot_tasks.txt` | 试点 6 个任务清单（来自原 `experiments/data/`） |
| `plan/` | dry-run 生成的执行计划（plan.json / schedule.csv / 命令脚本） |
| `sim/` | 合成数据与分析产物，**9 MB，git 未跟踪**；用 `make_sim_data.py` 可重新生成 |

`analyze_order_effects.py` 没有归档——它是动机研究的分析口径，仍在
`experiments/motivation_study/scripts/`；这几个脚本原本与它同目录，现在跨目录调用时
请显式 `--input/--out`，或把分析器路径写全。

## 30 秒上手（不需要模拟器）

```powershell
cd backup\androidworld
$env:PYTHONUTF8=1

python task_catalog.py
python order_runner.py --backend dryrun --out-dir .\plan
python make_sim_data.py --out .\sim --repeats 12
python ..\..\experiments\motivation_study\scripts\analyze_order_effects.py `
    --input .\sim\episodes.jsonl --out .\sim\analysis `
    --check-against .\sim\ground_truth.json
python power_analysis.py --p 0.6 --deltas 0.1,0.2,0.3,0.45
```

需要 Python 3.8+，**只用标准库**。

## 真跑 AndroidWorld（需要模拟器 + API key，从未在本机验证）

```powershell
# 前置：AVD = Pixel 6 / Tiramisu API 33 / 名 AndroidWorldAvd
#       emulator -avd AndroidWorldAvd -no-snapshot -grpc 8554
#       pip install android_world 依赖，设置 OPENAI_API_KEY / GCP_API_KEY

python order_runner.py --backend androidworld `
  --agents t3a_gpt4 `
  --tasks-file .\pilot_tasks.txt `
  --order-modes canonical,adversarial `
  --clean-modes official,none `
  --repeats 10 `
  --out-dir .\pilot

python ..\..\experiments\motivation_study\scripts\analyze_order_effects.py `
  --input .\pilot --out .\pilot\analysis
```

`order_runner.py` 做的关键一件事：AndroidWorld 的 `create_suite()` 结尾是
`Suite(sorted(suite.items()))`，**执行顺序被强制成字典序**；本模块在
`Suite(dict)` 上按计划重排 key，从而真正做到"乱序执行"。
重置强度则通过运行时 monkey-patch 调整（`app_snapshot.restore_snapshot` / `TaskEval.tear_down`），
**不修改被测系统的任何文件**。

## 当年已验证 / 未验证（诚实清单）

### 本机实测通过（归档时）

| 项 | 证据 |
|---|---|
| 任务目录 | 33 任务 / 7 状态域 / 26 个在快照覆盖内、7 个在覆盖外 |
| 计划生成 | `--backend dryrun` → 42 runs / 1368 episodes（默认参数），0.06 s 出计划 |
| 顺序构造 | 对抗序在 4 个日历读任务上构造出 3 对同簇 writer→reader 紧邻；字典序 2 对；`shuffle(0)` 1 对 |
| 顺序不变式 | 5 种顺序模式 × 5 个 seed 均恰好是原任务集的排列；修复过"reader 多于 writer 时丢任务"的 bug（回归测试随 selftest 精简已移除，改动前请自查） |
| 统计正确性 | 对数域 Fisher 与原始大整数实现逐表比对 6561 张表全部一致（这些检查现由 `experiments/selftest.py` D 组继续守） |
| 分析管道 | 22176 条合成 episode → precision 0.95 / recall 0.63 |
| 科学形态 | official 条件下 C2 ΔSR ∈ [−0.02, +0.02]、4 个 agent 全 0 victim（H2）；污染 + 对抗序 ΔSR −0.19~−0.30、OD-flaky 39–46%（H1） |
| 交互项 | DiD +0.060 ~ +0.116（4 个中 3 个 CI 不含 0）→ 顺序效应只在污染条件下被放大 |
| 样本量工具 | ΔSR=0.2 → 97/组；0.30 → 42/组；0.45 → 17/组 |

### 尚未验证（缺环境，不是缺代码）

| 项 | 缺什么 |
|---|---|
| `--backend androidworld` 真机路径 | 本机无 Android SDK / adb / AVD / API key；首次运行需按报错微调（可能点：`checkpointer_lib` 的引用方式、`create_suite` 的 `env` 参数版本差异） |
| `--verify-catalog` | 需要装有 `android_world` 才能把目录里的 `apps` 与 registry 的 `app_names` 对齐 |
| 任务目录里的 app 归属字符串 | 按官方 task list 人工抄写，**首次落地务必先跑 `--verify-catalog`** |
