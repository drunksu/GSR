# experiments/ —— 「执行顺序 → 成功率」（OD flaky）实验工作台

> 📌 **部署、运行命令、同步方式、必踩的坑、当前进度 → 见仓库根目录 [`../README.md`](../README.md)**
> 本文件只说明目录怎么划分、每个脚本干什么。

为曦源本科生自主项目课题（`面向移动GUI智能体评测的应用状态污染检测和恢复方法研究`）准备的可执行工作台。已完成的第一阶段动机研究见 [`../docs/motivation_study.md`](../docs/motivation_study.md)（中期答辩 2026-10-29）。

## 目录结构（按实验划分）

```
experiments/
├─ README.md                      ← 本文件（索引）
├─ selftest.py                    ← 不依赖真机 / API key 的回归自检（见下）
├─ common/                        ← 跨实验复用的 MobileBench-OL 设施
│  ├─ mbl_env.py                  ← API key 查找（环境变量 → mobile.env.ps1）
│  ├─ mbl_apply_api_patch.py      ← 给 benchmark 打托管 API 适配补丁（幂等）
│  ├─ mbl_api_probe.py            ← 新模型接入第一步：端点连通 / 延迟探测
│  ├─ mbl_coord_convention_check.py ← 新模型接入第二步：坐标约定（norm/pixel）实测
│  └─ mbl_app_checklist.py        ← 生成"要装哪些 App"的安装清单
├─ state_recovery/                ← 第二阶段：状态污染检测与恢复闭环
│  ├─ docs/                       ← design.md（设计日志）/ method.md（中文方法叙述）
│  ├─ eval/                       ← 人工金标 / AI 污染清单
│  ├─ scripts/                    ← run_pipeline.py（`--mode workflow|harness` 入口）等
│  └─ results/{pipeline,ledgers,recovery_tasks}/base_canonical_workflow/ ← workflow 版全量 310 任务
└─ motivation_study/              ← 第一阶段：动机研究（三个实验的支撑代码）
   ├─ docs/
   │  ├─ 01-数据集与Agent选型.md   ← 在哪跑（在线数据集）、用谁跑（Agent）
   │  └─ 02-实验方案-顺序vs乱序.md ← 2×2 析因设计、假设、指标、样本量、预算
   ├─ scripts/
   │  ├─ analyze_order_effects.py ← 全部报告的分析口径：ΔSR / CI / CTCI / PASR /
   │  │                             victim（Fisher+BH-FDR+bootstrap）/ polluter
   │  ├─ mbl_traj_to_episodes.py  ← 每轮跑完后把轨迹转成 episodes.jsonl
   │  ├─ mbl_make_task_csv.py     ← 从同一任务集生成 canonical/reverse/shuffle CSV
   │  ├─ mbl_purge_tasks.py       ← 摘掉黑屏 / 空白 episode（默认 dry-run）
   │  ├─ mbl_fix_condition_labels.py ← 回填 manifest 的 condition 标签
   │  ├─ mbl_find_actions.py      ← 轨迹取证：把失败任务前一步动作捞出来
   │  └─ mbl_task_audit.py        ← 任务集 CSV 体检（编码 / 坏行 / Reset 标签）
   └─ results/
      └─ app_checklist_base.md    ← 12 个主力 App 的安装/登录清单
```

**约定**：以后每开一个新实验，在 `experiments/` 下新建同名目录（内部 `scripts/`、`docs/`、`results/` 按需建）；与具体实验无关、换实验还会复用的 benchmark 设施放 `common/`。

## 自检

```powershell
mobile\Scripts\python.exe experiments\selftest.py
```

D/G/H 三组检查、约 1 秒、不需要模拟器或 API key：

- **D1–D3**：分析器统计函数的已知值回归（Fisher 精确检验、BH-FDR 单调性、bootstrap CI 覆盖真值）——这些函数是全部实验报告的口径；
- **G1–G2**：仓库编码守卫——含中文的根目录 `.ps1` 必须带 UTF-8 BOM，`.cmd/.bat` 必须纯 ASCII；
- **H1–H44**：状态恢复闭环的 schema / 接地 / 门控 / 动作契约 / Policy Engine / workflow-harness 对照断言。

## 支线

AndroidWorld（模拟器路线）的 4 个脚本（任务目录、顺序调度器、合成数据、样本量）真机路径从未验证，其代码与产物已从工作树移除；当时的研究记录保留在 [`motivation_study/docs/`](motivation_study/docs/)。

## 术语速查

| 术语 | 含义 |
|---|---|
| **OD flaky** | Order-Dependent flaky：结果依赖执行顺序的不稳定测试/任务 |
| **victim** | 因顺序变化而失败的任务 |
| **polluter** | 把状态弄脏、害得后续任务失败的前序任务 |
| **CTCI** | Cross-Task Contamination Index：顺序不确定性带来的成功率全幅 |
| **PASR** | Pollution-Aware Success Rate：最坏顺序下的期望成功率（可信下界） |
| **DiD** | Difference-in-Differences：顺序 × 重置的交互项 |
| **clean mode** | 重置强度档位：official / none |
| **order mode** | 执行顺序档位：canonical / reverse / shuffle |
