# GUI State Recovery

## Intro

<aside>
💡

Repairing flaky tests in GUI agent evaluation 

</aside>

- Background:
    - Long-standing SE problem: test isolation
        - Reliable testing assumes tests are *isolated and reproducible*
    - However, shared-state pollution leads to flaky tests~\cite{}
        - 解释 Shared-state pollution
        - Such tests *pass or fail nondeterministically* across repeated executions
        - 包括：order-dependent(OD) tests, non-idempotent-outcome(NIO) tests
        
        *→ Makes test outcomes misleading and difficult to reproduce*
        
    - Prior work detects *polluters* and synthesizes *cleaners*
- Motivation
    - The same problem re-emerges in online GUI-agent evaluation
        - Mobile GUI agent 应用场景广泛，可以 task automation, a11y, GUI testing
        - They are evaluated by executing natural-language tasks sequentially on real apps
            - 要么忽视了这个问题
            - 要么企图通过重启 App 重置状态（很多情况下行不通）
            - 要么依赖于人工写好的脚本作为 cleaner
    - However, unlike offline benchmarks, online evaluation mutates the application state
        - One task can silently alter the initial condition of subsequent tasks
        - Leads to Flaky tests
        - Motivation study 里加：task order changes → agent success rate changes by Δ%.
    - It undermines the evaluation validity
        - Motivation study的结果
- Challenge: automation is hard?
    - Real-world mobile apps are *black-boxed*
        - Simple restart cannot clear persistent server-side states
        - Full snapshot is unavailable for many real-world cloud-backed apps
    - Recent benchmarks~\cite{MobileBench-OL} requires manually designed cleaners
    - ~~Localization is hard (不能直接访问变量)~~
    - ~~Reparing is hard (不能直接修改变量，需要找逆操作)~~
- Method：
    - 推断每个test的后果，然后用 GUI Agent模拟用户进行逆操作
    - 检测：
        - Agent 推断任务后果
        - 对比任务前后首页以及关键页面的状态，哪些是任务执行带来的？
    - 恢复：
        - 生成自恢复的任务并执行
- 贡献
    - Problem formulation
    - Tool
    - Evaluation

## TODO

- 证明这个现象：路径不同 & 成功率不同
    - 调研现有online的任务集合 & 他们有没有关注到恢复这个问题：[http://notion.so/benchmark-36cab7d10cb780bab362fadd57435016](http://notion.so/benchmark-36cab7d10cb780bab362fadd57435016)
    - 对比1：执行任务A后执行任务B vs. 直接执行任务B，一成功一失败
    - 对比2：GUI Agent A 跑完评测后跑 GUI Agent B vs. GUI Agent B 直接跑评测（后者成功率变化了）
- 0915故事：[https://acn6tprabs5x.feishu.cn/wiki/KUPQwuremidg89kyzrDcLJHAnCf?from=from_copylink](https://acn6tprabs5x.feishu.cn/wiki/KUPQwuremidg89kyzrDcLJHAnCf?from=from_copylink)
- 做点实验：
    - OD Flaky tests: 是否影响成功率？某个任务因为执行顺序变化而失败
        - 顺序执行 vs. 乱序执行
        - 多个 Agent
    - 落地材料（2026-09-18，已跑通，见 `experiments/`）：
        - `experiments/docs/01-数据集与Agent选型.md`：在线数据集与 Agent 选型（AndroidWorld 主实验 / MobileBench-OL 在线实证 / WebArena 负对照 / OpenApps 沙盒 / AndroidLab、A3 备选），含 AndroidWorld 代码级污染证据，以及"顶端模型在 AndroidWorld 已饱和（97%+）不能用作主实验 Agent"的提醒
        - `experiments/docs/02-实验方案-顺序vs乱序.md`：2×2 析因方案（顺序 × 重置）、H1–H5 可证伪假设、ΔSR / OD-flaky 率 / CTCI / PASR / polluter lift / DiD 指标定义、样本量与算力预算、效度威胁
        - `experiments/README.md`：可执行工作台（`python selftest.py` 13 项自检全绿，无需模拟器与 API key）

## Related

- [*MobileBench-OL: A Comprehensive Chinese Benchmark for Evaluating Mobile GUI Agents in Real-World Environment*](https://arxiv.org/abs/2601.20335)
- Flaky tests:
    - Repairing Order-Dependent Flaky Tests via Test Generation
    - Dependent-Test-Aware Regression Testing Techniques
    - Preempting Flaky Tests via Non-Idempotent-Outcome Tests
    - NIODebugger: A Novel Approach to Repair Non-Idempotent-Outcome Tests with LLM-Based Agent
    - Evolution-Aware Detection of Order-Dependent Flaky Tests
    - Ranking Relevant Tests for Order-Dependent Flaky Tests
- 状态恢复：
    - Reliable testing: detecting state-polluting tests to prevent test dependency
    - LiveDroid: Identifying and Preserving Mobile App State in Volatile Runtime Environments
    - Enhancing GUI Exploration Coverage of Android Apps with Deep Link-Integrated Monkey
    - *Time-travel testing of Android apps*
    - Multiple-Entry Testing of Android Applications by Constructing Activity Launching Contexts
    - Sara: self-replay augmented record and replay for Android in industrial cases
- GUI Agent & Agent 评测：
    - [https://www.notion.so/benchmark-36cab7d10cb780bab362fadd57435016](https://www.notion.so/benchmark-36cab7d10cb780bab362fadd57435016)

[开题报告 (1)](https://app.notion.com/p/1-3deab7d10cb780049380d477fc7a1355?pvs=21)

- **ISSTA 2027 abstract 2027-01-08，full paper 2027-01-11**
- ICSME 2027 research paper 2027-03-05
- ICST full paper 2026-11-02 (CCF-C)
- ISSRE 2027
- ASE 2027