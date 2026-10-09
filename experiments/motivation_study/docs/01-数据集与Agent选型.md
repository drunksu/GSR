# 在线数据集与 Agent 选型（面向「执行顺序 → 成功率」的 OD flaky 实验）

> 依据：`开题报告 36cab7d…md`（3.1 研究内容 / 3.3 技术路线 / 6 已有基础）与 `GUI State Recovery …md` 的 TODO
> 本文件回答两个问题：**在哪跑**（在线数据集）、**用谁跑**（Agent）。
> 所有事实性数据都标注了来源链接；凡是"我推断"的都显式写了 `［推断］`。

---

## 0. 结论先行

### 推荐阵容（三平台 + 四档 Agent）

| 角色 | 选择 | 为什么是它 |
|---|---|---|
| **主实验平台**（因果实验） | **AndroidWorld** | 唯一同时满足：完全可控可复现、**执行顺序可任意重排**、内置 app 级快照作为"干净基线"、内置 5 个 agent 实现、零外部依赖成本、116 任务足以做分层抽样 |
| **在线实证平台**（生态效度） | **MobileBench-OL** | 1080 任务 / 80 个真实中国 App + 真机 uiautomator2；任务表里带 `reset_xpath` / `reset_query`（**人工/脚本 cleaner**）且框架有 `[reset] reset=true|false` 开关——直接把"cleaner 够不够用"变成自变量 |
| **上界对照**（负对照） | **WebArena**（Docker + DB 重置）/ **OSWorld**（VM 快照） | 重置最彻底的两种极端。在这两个平台上顺序效应**应当 ≈ 0**；如果也测出显著 ΔSR，说明效应来自噪声而非污染 |
| **机制速测沙盒**（阶段 0） | **OpenApps** | 纯 Python、单 CPU、全状态 YAML 可见可改 → 半天内可跑几千次"注污染/清污染"实验，用来先把检测/恢复方法和统计管道调通，不用等模拟器 |
| **可选第三平台** | **A3** | 100 任务 / 20 个 Google Play 真实在线 App，essential-state 过程化评测；但论文写的是 "will be publicly released"，**发布状态需确认**（见 §1.4） |
| **多 Agent 横向补充** | **AndroidLab** | 138 任务 / 9 App，XML 与 SoM 两种模态共享同一动作空间，9 个 agent 都有公开成绩；成功率仅 18%–33% → 天然落在"信号带"内 |

**Agent 四档**（细节见 §2）：

1. **中档主力（信号带内，做主要结论）**：T3A / M3A + GPT-4o 或 Gemini 2.5 Flash（AndroidWorld 内置 wrapper 即可跑）
2. **强 Agent（边界条件）**：Minitap（多 Agent 系统，AndroidWorld 100%）、Seed1.8-GUI / Gemini 3 Flash（≈97%）
3. **弱 Agent（对照）**：SeeAct + GPT-4V、`random_agent`（成功率下界）
4. **开源自部署（省钱、可并行）**：UI-TARS-1.5-7B、Qwen2.5-VL-7B、Mobile-Agent-v2（多 Agent 架构）

### 三条必须先知道的坑

1. **别用顶端模型做主实验。** AndroidWorld 榜单上 Seed1.8-GUI、Gemini 3 Flash 已到 97.4%（[BenchmarkList 2026-08-26 快照](https://benchmarklist.com/benchmarks/androidworld/)），[Minitap](https://arxiv.org/abs/2602.07787) 甚至报了 100%。**成功率饱和 = 没有失败可供顺序去改变**，OD 效应会被天花板吃掉。必须选成功率落在 **0.2–0.8** 的 agent/任务组合。
2. **AndroidWorld 的官方执行顺序是任务名字典序，而且"乱序"要自己改代码。** `suite_utils.create_suite()` 最后一行就是 `Suite(sorted(suite.items()))`；而 `run.py --tasks` 传进去的顺序也会被重排。实验必须在 Suite(dict) 上重排 key（本仓库 `order_runner.py` 已实现）。
3. **字典序本身就会把同 App 任务排在一起**，等于自带污染；而**纯随机置换会把污染稀释掉**。所以"顺序执行 vs. 乱序执行"必须包含一个**对抗性顺序**（把写任务紧排在读任务之前），否则很容易得出"乱序没影响"的假阴性。本仓库 `order_adversarial()` 已实测：对抗序在 4 个日历读任务上构造出 3 个 writer→reader 紧邻，而字典序也有 2 个、shuffle(seed=0) 只有 1 个。

---

## 1. 在线数据集候选：逐个体检

对比矩阵（"可注入顺序"= 能否在不改被测系统的前提下任意重排任务执行次序）：

| 数据集 | 规模 | 环境 | 状态重置机制 | 可注入顺序 | 可关重置 | 代码/许可 | 成本 | 本实验用途 |
|---|---|---|---|---|---|---|---|---|
| **AndroidWorld** | 116 任务 / 20 App（参数化后百万级变体） | Android 模拟器（Pixel 6 / API 33） | **app 级快照恢复**：`TaskEval.initialize_task → _initialize_apps → app_snapshot.restore_snapshot` | ✅ 需自定义 runner（本仓库已提供） | ✅ monkey-patch 即可 | [google-research/android_world](https://github.com/google-research/android_world)，Apache-2.0，2026-09-09 仍在更新 | 1 台机器 + 模拟器 + API key | **主实验** |
| **MobileBench-OL** | 1080 任务 / 80 个中国 App；5 个子集（base / long-tail / long-horizon / gui-reasoning / noise-robust） | **真机**（uiautomator2 + ADB） | 任务 CSV 自带 `reset_xpath` / `reset_query`；框架 `[reset] reset=true|false` | ✅ 置换任务表行序 | ✅ `reset=false` 就是现成的污染条件 | [xiaomi-research/mobilebench-ol](https://github.com/xiaomi-research/mobilebench-ol)，代码 Apache-2.0 / 数据 CC BY-NC-SA 4.0 | 需 1 台真机（或稳定模拟器）+ 被评测 App 的账号 | **在线实证** |
| **A3 (Android Agent Arena)** | 100 任务 / 20 个 Google Play 真实在线 App | 真机 / 在线 App | toolkit 内含 reset 模块；评测用 MLLM-as-reward 的 essential-state | 文档未明示 | 未明示 | 论文（[arXiv:2501.01149](https://arxiv.org/abs/2501.01149)，[ACL Findings 2026](https://aclanthology.org/2026.findings-acl.184/)）称 "will be publicly released" | 真机 + 账号 + MLLM 评测 API | **可选第三平台**（先确认可得性） |
| **AndroidLab** | 138 任务 / 9 个预装 App + 94.3K 步指令数据 | AVD，离线、冻结时间与位置 | 离线镜像 + 重置 | ✅ 需改造 | 需改造 | [THUDM/Android-Lab](https://github.com/THUDM/Android-Lab)（ACL 2025） | 中 | **多 Agent 横向对比**补充 |
| **OSWorld** | 369 任务（Ubuntu/Win/macOS） | VirtualBox VM | 每任务独立 VM 快照，结束回滚 | 顺序可换，但快照重置极彻底 | 代价高 | 开源 | **高**（VM 重） | **负对照**（预期 ΔSR≈0） |
| **WebArena** | 812 任务 / 4 类自建站点 | Docker + 数据库 seed | 容器 + DB 重置 | ✅ | ✅ | 开源 | 中（单站 100GB+ 内存） | **机制对照**（可完全重置） |
| **OpenApps** | 6 个自建 App / 15 任务 / 8 变体 | **纯 Python、单 CPU、<10MB 内存** | YAML 即初始状态，初始化即重置，bit 级可复现 | ✅ | ✅ | [facebookresearch.github.io/OpenApps](https://facebookresearch.github.io/OpenApps/)（ICLR 2026，[arXiv:2511.20766](https://arxiv.org/abs/2511.20766)） | **极低** | **阶段 0 方法开发沙盒** |

### 1.1 AndroidWorld —— 主实验平台（推荐指数 ★★★★★）

**为什么主推它：**

- **规模够用且参数化**：116 个手写任务、20 个 App，随机参数化产生"数百万种"任务变体（[官方 README](https://github.com/google-research/android_world)）。做 30 任务 × 4 条件 × 40 重复的实验完全在能力范围内。
- **顺序可完全控制**：`Suite` 是 `dict` 子类，`_run_task_suite` 就是按 `suite.items()` 迭代 —— 重排 key 即重排执行顺序，**不需要修改任何被测代码**。
- **自带"干净基线"**：每个任务在 `initialize_task` 里对 `task.app_names` 声明的 App 做 `app_snapshot.restore_snapshot()`，`tear_down` 再做一次。这给了我们一个**真实的、可以审计的重置机制**——正好对应开题报告第 2.1 节说的"AndroidWorld 的 teardown 清理彻底性从未经过系统验证"。
- **工程友好**：轻量（2GB 内存 / 8GB 磁盘）、实验性 Docker 支持、`--checkpoint_dir` 断点续跑、`--tasks` 跑子集、`n_task_combinations` 控制参数组合数、`--task_random_seed` 可复现。

**已知污染入口（代码级证据，直接构成实验假设）：**

| # | 证据 | 后果 | 假设 |
|---|---|---|---|
| E1 | `task_eval.py`：`initialize_task()` 与 `tear_down()` 都只调用 `_initialize_apps()`，而它只遍历 `self.app_names` | **只有任务声明过的 App 会被恢复**；系统设置、剪贴板、共享文件系统（`/sdcard`）不在范围内 | **H3**：`SystemWifi*` / `SystemBrightness*` / `SystemCopyToClipboard` / `Files*` / `SaveCopyOfReceiptTaskEval` / `SimpleDrawProCreateDrawing` 是快照覆盖不到的污染源 |
| E2 | `suite_utils.py::_run_task()`：`try: … except: return _create_failed_result(...)` —— **异常路径不会执行 `tear_down()`** | 任何抛异常的任务都会把污染留给后续所有任务 | **H5**：失败/异常任务的"后遗症"比成功任务更严重（"错误路径下的清理缺失"） |
| E3 | `create_suite()` 末尾 `Suite(sorted(suite.items()))` | 字典序会把同 App 任务连续排布 → 默认顺序自带污染 | **H1/H2**：字典序 ≠ 干净序；"乱序"未必更差 |
| E4 | `env.interaction_cache = ""` 在 `initialize_task` 里被重置 | 作者已意识到"前序任务影响本次运行" | 支撑问题成立性 |
| E5 | `_allocate_step_budget()` = `10 × task.complexity`，与位置无关 | 步数预算不随顺序变化 → 排除"顺序改变了算力"这一混淆因素 | 设计清洁性 |

**落地要求**：Android Studio + AVD（Pixel 6, Tiramisu API 33, 名字 `AndroidWorldAvd`），模拟器需用 `-grpc 8554` 启动；`OPENAI_API_KEY` / `GCP_API_KEY` 之一。

### 1.2 MobileBench-OL —— 在线实证平台（推荐指数 ★★★★☆）

**它是唯一"把 cleaner 明写出来"的在线基准**，对我们极为关键：

- 任务 CSV 必填列：`task_identifier, goal, adb_home_page, golden_steps, key_nodes`，**可选列 `reset_xpath, reset_query`** —— 这就是开题报告里说的"Recent benchmarks 需要人工设计 cleaner"的实物证据。
- 配置里 `[reset] reset=<true|false>` 直接开关重置 → **`reset=false` 天然就是"无 cleaner"实验组**。
- 5 个子集里含 **`noise-robust`**（`repeat / unexecuted / delay / popup` 四类噪声顺序执行）→ 说明作者已在关心环境变异，但**没有关心任务间顺序污染**，这正是我们的空白。
- 统一 Agent 接口已支持：`uitars_1_5`、`gpt4o`、`m3a`、`t3a`、`qwen2_5vl`、`mobileagentv2` —— **多 Agent 维度开箱即用**（同 §2 阵容高度重合，代码可复用）。
- 已有 resume 机制（`result_list.txt` 缓存）与多轮重试（`retry_rounds`），跑长实验省心。

**代价**：需要真机（USB/Wi-Fi ADB）+ 中国 App 的登录态；数据 CC BY-NC-SA 4.0（**非商用**，学术用途 OK）；仓库 2026-04 后无提交，遇到 bug 得自己修。`［推断］` 80 个 App 中相当一部分需要登录，建议先跑 `base` 子集摸清可用比例。

### 1.3 负对照：WebArena / OSWorld（推荐指数 ★★★☆☆）

论文里最容易被审稿人问："你怎么知道 ΔSR 不是随机波动或 API 抖动？" 答案就是**在两个"理论上能完全重置"的平台上跑同一套顺序实验**：

- **WebArena**：Docker + 数据库 seed 重置，任务间状态可完全还原 → 预期 ΔSR ≈ 0、CTCI ≈ 0。
- **OSWorld**：每个任务独立 VM 快照，回滚最彻底 → 预期 ΔSR ≈ 0，但代价高、速度慢。

如果这两个平台也测出显著顺序效应，说明我们的指标或统计有问题（而不是发现了现象）。**这是花小钱买大保险的一步**，建议至少做 WebArena。

### 1.4 A3 —— 生态效度（推荐指数 ★★★☆☆，取决于可得性）

- 100 任务 / 20 个 Google Play 真实在线 App / 20 个类别；用 MLLM-as-reward 做 essential-state 过程化验证（[arXiv:2501.01149](https://arxiv.org/abs/2501.01149)，已发表于 ACL Findings 2026）。开题报告 6 节把它列为已有实验环境。
- **风险**：论文（含 2026 年 1 月的 v3）措辞仍是"complete A3 system … will be publicly released"，ACL Anthology 页面也没有 artifact 链接。`［需核实］` 动手前先确认 benchmark 与 toolkit 是否真的放出；若未放出，本课题的"在线"部分就落在 MobileBench-OL 上。
- 附带价值：A3 明确采用"**选型规避**"（只挑"支持可靠重置"的 App，排除即时通讯类）——这正是开题报告 2.3 节说的互补点，可以在论文里作为最强动机引用。

### 1.5 阶段 0 沙盒：OpenApps（推荐指数 ★★★★★，仅作方法开发）

- ICLR 2026，6 个纯 Python 自建 App（Calendar/Messenger/Maps/ToDo/Code/Shop），外观与内容全部抽成 **YAML**，一份 YAML = 一个变体；单实例 <10MB 内存、单 CPU 可跑；奖励用**全状态 ground truth**（`r = δ[s_t = s_target]`），论文跑了 >10000 次评测 × 7 个 agent。
- 对我们是"免费的实验室"：可以**人为注入污染**（改 YAML 初值 = 模拟前序任务残留）、**精确知道 ground truth**（哪一步写脏了哪个字段），半天内验证"检测模块能不能找全污染""指标算得对不对"。
- 局限：任务太简单（"加一条待办"级别），**不能**用它出论文主结论，只能说"方法在受控环境有效"。
- 另一个可用点：它的 **cross-variant / intra-app 方差**度量思路，和我们 CTCI/PASR 是同一家族，可作为指标章节的对照文献。

### 1.6 多 Agent 补充平台：AndroidLab（推荐指数 ★★★☆☆）

- 138 任务 / 9 个预装 App，AVD 离线、冻结时间与位置，**XML（文本）与 SoM（截图+标号）两种模态共享同一动作空间** → 跨模态、跨模型比较最公平。
- 公开成绩：GPT-4-1106 XML 31.16%、GPT-4o SoM 31.16%、Claude-3.5-Sonnet SoM 28.99%、Qwen2-VL-7B 微调后 18.12% → **都在 20–33% 的"信号带"内**，非常适合观测顺序效应。
- 局限：9 个 App、离线，生态效度不如 A3/MobileBench-OL。

---

## 2. Agent 选型

### 2.1 为什么"选哪个 Agent"比"选哪个数据集"更容易翻车

OD 效应的观测量是 **ΔSR = SR(乱序) − SR(规范序)**。它需要任务既有成功也有失败：

- Agent 太强（SR ≈ 1.0）→ 没有失败可供顺序改变，ΔSR 被天花板压成 0；
- Agent 太弱（SR ≈ 0.1）→ 失败主要来自能力不足，顺序效应淹没在噪声里（本仓库合成实验已复现：`seeact` 这类弱 agent 的 OD-flaky 检出数反而更少）。

所以**必须按成功率分层选 Agent**，并在正式实验前做一次"信号带筛选"（见 §3.3）。

### 2.2 Agent 对比矩阵

| Agent | 观测模态 | 底层模型 | AndroidWorld 报告 SR | 成本/延迟 | 可得性 | 本实验角色 |
|---|---|---|---|---|---|---|
| **T3A** | 文本 accessibility tree（+SoM） | GPT-4 / GPT-4o | 原始论文约 30–40%（`t3a_gpt4` 内置） | 中 | AndroidWorld 内置 | **主力**（信号带） |
| **M3A** | 多模态 + Set-of-Mark | GPT-4V / Gemini | 原始论文约 25–35%（`m3a_gpt4v` 内置） | 中 | AndroidWorld 内置 | **主力**（多模态对照） |
| **SeeAct** | 截图 + 元素标号 | GPT-4V | 偏好（论文中偏低） | 中 | AndroidWorld 内置 `seeact` | **弱对照** |
| `random_agent` | 无 | 无 | ≈0 | 0 | 内置 | 管道自测 / 下界 |
| **UI-TARS-1.5-7B** | 纯视觉 | 自研 7B | 中 | **本地 GPU，零 API 费** | [HF: ByteDance-Seed/UI-TARS-1.5-7B](https://huggingface.co/ByteDance-Seed/UI-TARS-1.5-7B)；MobileBench-OL 已适配 | **开源自部署主力** |
| **Qwen2.5-VL** | 视觉 | Qwen 系列 | 中 | 本地 GPU | HF 开源；MobileBench-OL 已适配 | 开源对照 |
| **Mobile-Agent-v2** | 视觉，**多 Agent 架构** | Qwen-VL 系 | 中 | 本地/API | [X-PLUG/MobileAgent](https://github.com/X-PLUG/MobileAgent) | **"多个 Agent"维度**（多 Agent 系统 vs 单 Agent） |
| **Minitap** | 多模态，**6 个专职子 Agent** | 闭源 API | **100%（116/116）** | 高 | [github.com/minitap-ai/mobile-use](https://github.com/minitap-ai/mobile-use) | **强上界 / 边界条件**（验证"越强越不敏感"） |
| **Gemini 3 Flash / Seed1.8-GUI** | 多模态 | 闭源 | 97.4%（榜单） | 中 | API | 饱和对照（预期 ΔSR≈0） |
| GUI-Owl-1.5 / Aguvis / AppVLM | 视觉 | 开源小模型 | 中 | 本地 | HF | 备选开源池 |

**推荐的最小可用阵容（4 个 agent，覆盖能力梯度与模态）**：
`t3a_gpt4`（文本+GPT-4o）、`m3a_gpt4v`（多模态+Gemini）、`seeact`（弱对照）、`uitars_1_5_7b`（开源自部署）。若算力允许再加 `mobileagentv2`（多 Agent 架构）与 `minitap_multi`（强上界）。

### 2.3 接新模型只需加一个 wrapper

AndroidWorld 的 `infer.py` 里只有 `GeminiGcpWrapper`（走 `google.generativeai`）与 `Gpt4Wrapper`（走 `chat/completions`，`temperature=0.0` 默认）。**换新模型的正确做法是新增一个 `LlmWrapper + MultimodalLlmWrapper` 子类**，而不是改现有类——这样官方基线结果仍可复现。`order_runner.py::_make_agent()` 支持 `--agents t3a_gpt4:gpt-4o` 这种 `名字:模型` 写法做临时覆盖。

`temperature=0.0` 很重要：agent 自身采样抖动越小，顺序效应越容易被干净地分离出来。**建议正式实验全程 temperature=0，并在效度威胁一节说明"真实部署是高温的，因此本文估计的是下界"。**

---

## 3. 任务与 task pair 的挑法

### 3.1 用官方标签分层，不要凭感觉挑

AndroidWorld 每个任务有 `difficulty`（easy/medium/hard）与 `tags`（`data_entry` / `data_edit` / `information_retrieval` / `multi_app` / `requires_setup` / `verification` …），官方 task list 可查：<https://google-research.github.io/android_world/task_list.html>（本仓库 `task_catalog.py` 已把 33 个推荐任务的 name/difficulty/tags/cluster 抄好）。

### 3.2 按"状态作用方向"构造 writer → reader 配对

这是构造对抗性顺序的基础。本仓库 `task_catalog.py` 已给出 33 个任务 / 7 个状态域，其中：

| 状态域 | writer | reader（victim 候选） | 快照是否覆盖 |
|---|---|---|---|
| Markor 笔记 | 创建 / 编辑 / 删除 / 移动 / 建目录（7 个） | —（Markor 无纯读任务） | 覆盖 |
| Pro Expense | 添加 / 删除 / 去重（6 个） | — | 覆盖 |
| Simple Calendar | 添加事件 / 删事件（3 个） | AnyEventsOnDate / EventsOnDate / NextEvent / EventsInTimeRange（4 个） | 覆盖 |
| Tasks | — | DueOnDate / HighPriorityTasks / DueNextWeek（3 个） | 覆盖 |
| Retro Music | 建播放列表 / 播放队列 / 导出（3 个） | — | 覆盖 |
| **系统** | Wifi / 亮度 / 剪贴板（3 个） | **任意后续任务** | **不覆盖** |
| **文件系统** | 移动 / 删除 / 复制 / 画图落盘（4 个） | **任意后续任务** | **不覆盖** |

**两个真实配对示例**（"某个任务因为执行顺序变化而失败"的教科书案例）：

1. `SimpleCalendarAddOneEvent`（在 X 日 h 时建事件） → `SimpleCalendarAnyEventsOnDate`（问 X 日有没有事件）。若前序任务的事件没被清掉，读任务会读到多余事件 → 答案错 → 判失败。
2. `MarkorCreateNote`（建笔记） → `MarkorDeleteNewestNote`（删最新笔记）。前序残留会改变"哪条是最新的"，**删除任务的目标对象直接变了**。

第 2 类尤其值得强调：**污染不只会让读任务错，还会让写任务作用在错误的对象上。**

### 3.3 正式实验前必须做的"信号带筛选"（半天工作量）

对候选任务 × 候选 agent，在 **official 条件、规范顺序**下各跑 10 次：

- SR ≥ 0.9 → 剔除（天花板）
- SR ≤ 0.1 → 剔除（地板）
- 保留 **0.2 ≤ SR ≤ 0.8** 的 (task, agent) 组合作为正式实验单元

这一步同时给出了 baseline 成功率，也是后续统计功效计算的输入。**不要跳过**：否则可能花两周跑完才发现所有任务都是 0% 或 100%。

---

## 4. 落地前提

| 项 | 要求 | 现状（本机 2026-09-18 检查） |
|---|---|---|
| Python | AndroidWorld 要求 ≥ 3.11 | 本机 3.10 → **需装 3.11+ 或 conda 环境** |
| Android SDK / AVD | Pixel 6 / API 33 / `AndroidWorldAvd`，模拟器需 `-grpc 8554` | 本机无 `adb`、无 `java` → **待装** |
| API Key | `OPENAI_API_KEY` 与/或 `GCP_API_KEY` | 未见配置 → 待补 |
| GPU（可选） | 自部署 UI-TARS-1.5-7B / Qwen2.5-VL-7B | 本机 `nvidia-smi` 不存在 → 只能走 API 或换机器 |
| 真机（MobileBench-OL） | Android 真机 + USB/Wi-Fi ADB + App 账号 | 待备 |
| 本仓库脚本 | 只需 Python 3.8+ 标准库（已用 3.10 实测通过） | ✅ 可直接跑 |

---

## 5. 参考资料

**基准与平台**
- [AndroidWorld: A Dynamic Benchmarking Environment for Autonomous Agents (arXiv:2405.14573)](https://arxiv.org/abs/2405.14573) ｜ [代码](https://github.com/google-research/android_world)（Apache-2.0）｜ [任务清单](https://google-research.github.io/android_world/task_list.html) ｜ [榜单快照](https://benchmarklist.com/benchmarks/androidworld/)
- [MobileBench-OL: A Comprehensive Chinese Benchmark for Evaluating Mobile GUI Agents in Real-World Environment (arXiv:2601.20335)](https://arxiv.org/abs/2601.20335) ｜ [代码](https://github.com/xiaomi-research/mobilebench-ol)
- [A3: Android Agent Arena (arXiv:2501.01149)](https://arxiv.org/abs/2501.01149) ｜ [ACL Findings 2026](https://aclanthology.org/2026.findings-acl.184/)
- [AndroidLab: Training and Systematic Benchmarking of Android Autonomous Agents (ACL 2025)](https://aclanthology.org/2025.acl-long.107/) ｜ [代码](https://github.com/THUDM/Android-Lab)
- [OSWorld (arXiv:2404.07972)](https://arxiv.org/abs/2404.07972) ｜ [WebArena (arXiv:2307.13854)](https://arxiv.org/abs/2307.13854)
- [OpenApps: Simulating Environment Variations to Measure UI-Agent Reliability (ICLR 2026, arXiv:2511.20766)](https://arxiv.org/abs/2511.20766)

**Agent**
- [Do Multi-Agents Dream of Electric Screens? (arXiv:2602.07787, Minitap)](https://arxiv.org/abs/2602.07787) ｜ [代码](https://github.com/minitap-ai/mobile-use)
- [UI-TARS-1.5-7B (HuggingFace)](https://huggingface.co/ByteDance-Seed/UI-TARS-1.5-7B) ｜ [Mobile-Agent (X-PLUG)](https://github.com/X-PLUG/MobileAgent)
- 开题报告 2.2 / 2.3 节所列状态恢复与 deep link 工作（Delm、APE、Stoat、RERAN、Barista、GUITAR）作为 Related Work，本实验不直接使用。

---

## 6. 一页速览（贴到汇报里用）

> **主实验**：AndroidWorld（33 任务子集） × 4 个 Agent × {规范序, 反向序, 随机置换, 对抗序} × {官方重置, 无重置, 无 teardown} × 10–40 重复。
> **在线验证**：MobileBench-OL `base` 子集，`reset=true` vs `reset=false`。
> **负对照**：WebArena（预期 ΔSR≈0）。
> **方法沙盒**：OpenApps（先调通检测/分析管道）。
> **核心指标**：ΔSR、OD-flaky 率、CTCI、PASR、polluter lift、DiD 交互项。
