# State Recovery — Method Design (v0.3, 2026-10-10；阶段 A 推断定稿)

> 曦源项目第二阶段：在动机研究（[docs/motivation_study.md](../../../docs/motivation_study.md)）
> 证实"任务间状态污染真实存在、且任务特异性明显"之后，本阶段**正式尝试恢复方法**。
> 中期答辩 2026-10-29；本版决策见文末「决策记录」。
>
> 可读版方法说明（中文）：[method.md](method.md)。

## 1. 问题定义

MobileBench-OL 顺序执行任务时，前序任务在**设备端与服务端**留下的状态会改变后续任务的
成功率。官方 cleaner 是人工写的 `reset_query`，由同一个 GUI agent 执行，**只生成目标、
不验证、失败无声**——而且 310 个任务里只有 65 个有 cleaner。

我们要做的是一个**自动状态恢复闭环**：在任务执行后，从任务描述与执行轨迹推断发生了
哪些持久化状态变更，生成一个恢复任务目标，交由执行器恢复，并验证终态。

```
任务轨迹 ──► ①推断 污染清单 ──► ②生成 恢复任务 ──► ③执行 + 验证 ──► 门控决策
 (goal/thought/action/screenshot)      (恢复目标+前置检查+终态断言)   (GUI agent)      恢复完成 / 挂起人工
```

**第一原则（继承 AGENT.md）**：科学实验代码，宁可大声报错不可静默失效。恢复动作本身
也是设备操作，错误恢复 = 新污染。因此：**生成可以自由，执行必须受控**——恢复目标由
LLM 自由生成，但执行前后都有断言，任何不确定都走硬门控挂起，绝不猜测性操作。

## 2. 输入数据（已核实）

每条真机轨迹 `trajectory.json` 包含：

| 字段 | 内容 | 恢复方法中的用途 |
|---|---|---|
| `task_goal` | 中文任务描述 | 推断意图 |
| `history_response` | 每步完整 `Thought: … Action: …` | **意图与实体的主要来源**（如"搜索框输入 DND"、"已添加"） |
| `history_action` | 结构化动作：click 坐标、type 原文 | **实体的接地来源**（好友号、群名、搜索词都是逐字输入的） |
| `history_image_path` | 逐步截图（仅跑实验的机器本地有） | 阶段 B 起加入，判定 toggle 是否实际生效、元素当前状态 |
| `success` / episodes.jsonl | 判定结果、末帧亮度等 | **不能当作"有无变更"的依据**（见下） |

关键事实（动机研究取证）：

- `qq_1`（搜索 DND 群，s3_A_1）判失败，但输入了 4 个搜索词，搜索历史已被污染；
- `qq_4`（加好友 1098074562）轨迹里系统显示"已添加"——好友/请求仍在，状态只是饱和；
- `baidubrowser_14`（设置夜间模式）**判失败但设置实际生效**（末帧亮度 44.7，且乱序轮
  首帧亮度 34.4 证明跨轮残留）。

⇒ **推断必须独立于 success 判定**：`success=false` 不代表没有持久化变更。

## 3. 模块①：推断 —— 污染清单（Contamination List）

输出是**结构化污染清单**（不是自由文本），schema 版本化（`contamination-list/v0.1`）：

```json
{
  "schema": "contamination-list/v0.1",
  "task_id": "qq_4",
  "run_id": "base_canonical",
  "task_goal": "打开QQ添加1098074562为好友",
  "judged_success": true,
  "mutations": [
    {
      "id": "m1",
      "type": "relationship_request",
      "app": "QQ",
      "entity": {"kind": "friend", "name": "绕堤沙", "identifier": "1098074562"},
      "direction": "request_sent",
      "evidence_steps": [4, 5],
      "evidence_quote": "搜索结果已显示目标用户绕堤沙(1098074562)，状态显示为已添加",
      "confidence": 0.9,
      "attribution": "this_task",
      "carried_over_from_task": null
    }
  ],
  "search_terms": []
}
```

### 3.1 变更类型 taxonomy（v0.1，来自动机研究实际观测，可扩）

| `type` | 典型 |
|---|---|
| `settings_toggle` | 夜间/深色/关怀/长辈/备孕模式、无痕、阅读模式 |
| `relationship_request` | 加好友（请求） |
| `membership_change` | 加群/退群 |
| `content_lifecycle` | 笔记、日程、帖子、收藏 |
| `message_send` | 发消息、emoji |
| `social_reaction` | 关注、点赞、收藏 |
| `session_state` | 播放、导航、页面栈 |
| `search_history` | 搜索框输入残留 |
| `login_session` | 登录态变更 |
| `other` | 兜底，必须低置信度 + 引原文 |

每条变更必须带 `evidence_steps` 与 `evidence_quote`（Thought/Action 原文），
`confidence < τ(=0.7)` 的条目**禁止**自主恢复，直接进门控。

### 3.2 稳定性约束

1. **证据接地**：实体只允许来自轨迹原文（type 原文、Thought 中引用的界面文本），
   不允许推断模型编造标识符；
2. **空清单合法**：导航/浏览类任务应输出 `mutations: []`
   （清单为空即无需恢复；防过度触发是评测指标之一）；
3. **schema 强校验**：解析失败、枚举越界、缺证据字段 → 该条作废并报错，不静默。
   校验未过时把具体错误回灌模型**修正一次**（只修格式、不猜内容），仍失败才报错；
   `search_terms` 与 search_history 条目做跨字段一致性校验。

### 3.3 前序污染清单链式归因（稳定性机制，v0.3 定稿：模型判本任务，代码管结转）

批量顺序执行时，推断按 `episodes.jsonl` 的 position 顺序进行，每条任务的输入除自身
轨迹外，还附带**上一条任务污染清单中仍开放的全部残留**，每条变更必须给 `attribution`：

| 取值 | 含义 |
|---|---|
| `this_task` | 本任务新造成 |
| `carried_over` | 前序已登记、本任务只是看到/沿用（`carried_over_from_task` 取**最早来源任务**，即传递闭包起点） |
| `preexisting` | 存在但分不清先后（如进页时按钮已"已关注"） |

v0.2 曾让模型手工抄录 carried 条目，实测三类不稳定：看不到的残留直接漏登（qq_10 之后
DND 丢失）、Thought 里看到旧词就改标 this_task（qq_12）、温度 0 下修复轮无效。v0.3
把清单合并改为**确定性代码后处理**（`merge_carried()`），模型只负责判断本任务：

- **结转义务代码化**：前序污染清单每条持久化残留，若当前清单无同键条目，原样抄为
  carried_over（零输入任务也不丢），搜索词取并集；门控在合并后重算；
- **旧词误标改判**：搜索词在前序词表中、本任务却没有搜索框 type 动作 → 自动由
  this_task 改判 carried_over（qq_12 的误标即如此纠正）；
- **门控沿链保持**：carried 的不可逆/不确定残留继续占 GATE_HALT（q2 链 qq_11/12/17
  都正确挂着 qq_10 已发消息的门控），下游不能当无事发生；
- **链断裂保护**：某条推断失败时，后续任务不传前序（宁可 preexisting，不假装知道）。

另有两道确定性清洗（v0.3，全部在 schema 校验之外、以轨迹事实为准）：

- **搜索历史规范化** `canonicalize_search()`：一词一条 mutation，空实体名用词回填
  （否则空名搜索条目去重键塌缩，会把不同词互相吞掉，s3 链上实测到）；
- **搜索词双向接地**（`audit_grounding.py`）：搜索框（Thought 处于搜索语境的 type
  动作）输入过的词必须登记；登记的词没有搜索框 type 支撑（答题框文本"龙与地下城"、
  界面文案拼贴"dnd跑团"）先回灌修复，仍不过则代码确定性剔除并留痕 `_warnings`。

实测（q2_A_1 全链 8 任务 + s3_A_1 全链 4 任务）：开放残留跨链零丢失（q2 链尾
6 条：3 条搜索词 + 已发消息 + 置顶 + 已删聊天记录），两处不可逆门控沿链传递到链尾；
零输入的 qq_11/qq_12 不产生本任务新条目，前序 carried 残留仍在清单中占门控。

实现：[`scripts/mutation_taxonomy.py`](../scripts/mutation_taxonomy.py)（枚举 + 校验 +
门控）、[`scripts/audit_grounding.py`](../scripts/audit_grounding.py)
（双向接地 + 确定性清洗）、[`scripts/infer_mutations.py`](../scripts/infer_mutations.py)
（读轨迹 → 组 prompt → qwen3-vl-plus(temperature=0) → 解析/规范化/双向接地（含一次
修复）→ 确定性结转 → 写污染清单；`--all` 按 episodes 顺序自动链式推断）。

## 4. 模块②：生成 —— 恢复任务（Recovery Task）

生成器**自由撰写**恢复目标（这是方法的研究贡献点之一），但必须同时产出前置检查与
终态断言，且只能引用污染清单中有证据的实体：

```json
{
  "mutation_id": "m1",
  "recovery_goal": "打开QQ联系人，删除好友绕堤沙（QQ号1098074562），若显示等待验证则取消好友申请",
  "precondition": {
    "target": "好友/申请状态",
    "check_instruction": "进入该用户资料页或好友申请列表，判断当前是好友、申请待通过、还是无关系",
    "clean_if_state": "无关系 → 视为已恢复（no-op）"
  },
  "expected_end_state": {
    "kind": "vlm_judge",
    "question": "资料页是否显示加好友按钮（即当前已非好友），且没有待通过的好友申请？",
    "expected": "yes"
  },
  "idempotent": true,
  "risk_level": "medium",
  "max_steps": 15
}
```

设计要点：

- **前置检查保证幂等**：多轮实验重复恢复时，状态已干净就 no-op 成功，不做任何动作；
- **终态断言由生成器自己写、执行后由独立 VLM 判定**（不能让执行者自评）；
- **模板逆操作不作为主路径**，仅作为阶段 A/B 离线评测的 oracle 基线（自由生成 vs
  确定性模板的对照表是中期实验结果之一）；
- `risk_level=high`（如 `counterparty`/`irreversible`）的恢复任务不允许自主执行，
  只生成、不执行，进入人工门控。

实现（2026-10-10，离线版定稿）：
[`scripts/recovery_task.py`](../scripts/recovery_task.py)（恢复任务 schema v0.1 +
强校验：mutation_id 必须对应 this_task 变更、恢复目标必须逐字含 App/实体名/硬标识、
risk_level 与可逆性类别强制一致、断言必须是含实体名的 yes/no 问句、人工条目的
gate_reason 必须照抄门控）、[`scripts/generate_tasks.py`](../scripts/generate_tasks.py)
（污染清单 → prompt → qwen3-vl-plus(T=0) → 校验 → 一次修复 → 落盘）、
[`scripts/score_tasks.py`](../scripts/score_tasks.py)（批量复核与覆盖率统计）。

**触发口径（与负责人确认）：逐任务触发**——只为每条污染清单里 attribution=this_task
的变更产出处置；carried_over/preexisting 不重复生成。门控项产出**可读人工挂起清单**
（title / gate_reason / 中文原因 / 具体人工操作建议），中期演示即此清单，真机暂停
留到阶段 B。

## 5. 模块③：执行 + 验证（硬门控状态机）

复用 `run_mbl` 管线，把恢复任务的 `recovery_goal` 当普通任务跑，但包一层状态机：

```
PRECHECK ──已干净──► NOOP_OK（记日志，0 动作）
   │有残留
   ▼
EXECUTE ──异常/超步──► GATE_HALT（挂起，等人工）
   ▼
VERIFY（独立 VLM 按 expected_end_state 判定）
   ├─ yes ───────────► RECOVERED
   └─ no ─► RETRY（最多 1 次）─► VERIFY ─no─► GATE_HALT
推断 confidence<τ / risk=high / irreversible ─────────► GATE_HALT（不执行）
```

- 每个状态迁移与恢复任务自己的轨迹（含验证截图）全部落盘到
  `results/<run>/recovery/<task>/`，供审计"恢复动作有没有制造新污染"；
- 恢复完成后统一回 Home；恢复过程中输入的搜索词等新副作用，由对恢复轨迹再过一遍
  模块①来检测（恢复者自审计）；
- 执行器中期固定用 **qwen3-vl-plus**（不与任务执行模型混用，避免 flash 弱点污染
  条件；以后做执行器消融）；
- 门控挂起比照动机研究 QQ 每轮 `pause` 的人工恢复流程，**人工干预率是核心指标**。

## 6. 评测设计

### 阶段 A（离线，不要手机，10/09 起）

- 金标集 [`eval/golden_labels.json`](../eval/golden_labels.json)：**310 个 case
  （base_canonical 全部）**，以 trajectory 原文、screenshots/XML 取证逐条人工盲审建立。
  AI 推断模块的污染清单输出见 [`eval/ai_contamination_list.json`](../eval/ai_contamination_list.json)
  （盲审对答案用），标注台工作文件为 [`eval/annotation_metadata.jsonl`](../eval/annotation_metadata.jsonl)。
  覆盖：设置 toggle、收藏/点赞/关注（collected/liked/followed/preexisting）、好友/加群、
  发消息与删聊天记录（门控）、自建/删除内容、搜索历史、session 态无痕浏览、
  空清单反例；链式 run（q2/s3）因无截图证据已从金标集移除，原始轨迹保留；
- 指标（[score_inference.py](../scripts/score_inference.py)，2026-10-10，
  [score_report_v0.3.json](../results/score_report_v0.3.json)）：type+entity(+direction/
  attribution/来源) micro **P=0.987 / R=0.974 / F1=0.980**；status 1.000、
  搜索词召回 1.000、空清单特异性 1.000；门控决策 0.900；
  难例召回 0.929；
- 接地审计（[audit_grounding.py](../scripts/audit_grounding.py)，
  grounding_audit_*.json）：41 条污染清单**硬违规 0**；2 条 WARN 即下述已知弱点；
- **诚实记录的 3 个残留失败**（不放松金标/校验凑分）：
  1. `rimet_6`：好友申请实际是否提交成功不确定（点了发送掉进群聊、重搜"用户不存在"，
     疑似发给错人"倬**倬"），模型高置信(0.95)报 done 自治 → 门控漏挂（门控 0.9 的
     唯一来源）；
  2. `rimet_16`：变更真实发生但实体名写成容器"我的状态"而非选项"下班了" → 实体接地
     错误（审计 WARN 已抓）；
  3. `pinduoduo_27`：无生效反馈的字体点击，理想为 attempted_unknown+halt，模型给空
     清单静默跳过 → 不确定态的保守升级仍需加强；
- 教训：v0.2 小样本 1.000 是金标与轨迹同源下的健全性验证；扩样后立刻暴露上述真实
  弱点。下一步候选：终局 Thought 否定词（"不存在/未找到/无法"）强制同实体 done 降级
  重判、settings_toggle 选项名 vs 容器名的 prompt 强约束、attempted_unknown 默认升级。
  数据池：现有 2000+ 条已同步轨迹（无截图也可跑，Thought+Action 足够）。

模块②离线生成（2026-10-10，[`results/recovery_task_report_v0.json`](../results/recovery_task_report_v0.json)）：
对全部 41 条污染清单逐任务生成恢复任务集，**41/41 校验合格、覆盖率 1.0、挂起覆盖 1.0、
14 个无 this_task 残留的任务零输出**；共产出 32 个自动恢复任务、3 条人工挂起
（neteasemusic_20 删除旧笔记、q2/qq_10 已发消息、q2/qq_14 已删聊天记录，均
irreversible）；6 份用满 1 次修复后合格。抽读确认前置检查/断言具体可判定
（如"搜索历史列表中是否已不存在‘绕堤沙’条目？"）。
**重要级联观察**：生成器只会忠实地为污染清单服务——rimet_6 的推断错误（不确定的好友
申请被高置信报 done、实体名是疑似错人"倬\*\*倬"）被放大为一个**自主取消申请**
恢复任务，rimet_16 的容器名错误也原样进入恢复任务。说明模块①的不确定态门控必须在
阶段 B 之前补强（错误会沿管线向下游传播，恢复任务校验只能查接地、查不了事实真假）。

### 阶段 B（小批量真机）

- 对象：qq_1（搜索历史/群）、qq_4（好友）、qq_20/baidubrowser_14（toggle）；
- 指标：前置检查正确率、恢复成功率、连跑两次的**幂等率**、恢复者自审计副作用率、
  GATE_HALT 率与原因分布。

### 阶段 C（对比真机实验）

在 s3 的 4 任务子集（qq_1/qq_10/qq_13/qq_14）上跑三条件：
`none（无恢复）/ ours（本方法）/ official（人工 cleaner）`，直接续接动机研究的
ΔSR / CTCI / PASR / polluter lift 口径（qq_1 作为 predecessor 的条件失败率基线：
14/14 = 1.000 vs 0.610）。

## 7. RL 路线（11 月起，中期只讲设计与数据飞轮）

提示式 plus 执行器验证闭环后，把执行器换成可训练策略：

- **奖励无需人工标注**，全部来自状态机：
  `R = +1·1[VERIFY=yes] + 0.5·1[副作用为空] − 1·1[检出副作用] − 0.5·1[GATE_HALT] − 0.01·steps`；
- **训练数据**：阶段 B/C 攒下的（污染清单, 恢复任务, 恢复轨迹, 验证结果）即为 SFT 语料；
- **训练环境**：真机串行太慢（1239 episode/28h），用 AndroidWorld 模拟器快照做
  大规模并行训练（`backup/androidworld/` 支线在训练阶段复活），真机只做迁移评测；
- **模型**：开源权重 7B（UI-TARS-1.5-7B / Qwen2.5-VL，仓库已有对应 config），
  SFT warm-start → GRPO（验证器奖励，无需偏好标注）；
- planner（生成器，LLM）与 policy（执行器，RL）解耦，后期可联合优化。

## 8. 决策记录（2026-10-09 与项目负责人讨论）

| 决策点 | 结论 |
|---|---|
| 恢复触发时机 | **选择性恢复**：污染清单判定有持久化变更才触发，无变更直接跳过（污染任务特异性 + 最小动作面） |
| 恢复目标生成 | **LLM 自由生成**为主路径；稳定性靠证据接地 + 前置检查 + 后置验证 + 硬门控；模板仅作 oracle 基线 |
| 中期前执行器 | **qwen3-vl-plus 提示式**，先验证闭环；RL 执行器列入 11 月路线 |
| 失败/不确定 | **硬门控**：不猜、不重试超过 1 次，挂起等人工，人工干预率作为指标上报 |
| 前序轨迹利用 | 污染清单链式归因（v0.2）：carried_over 不重复触发恢复，只供前置检查去重；链断不传 |
| 链式归因实现（v0.3，10-10） | **模型只判本任务，代码管结转**：结转/旧词改判/搜索词规范化全部确定性后处理；模型温度 0 下的顽固分歧（漏登、空名塌键）不靠 prompt 堆规则解决 |
| 恢复任务触发粒度（10-10 定） | **逐任务触发**：每条污染清单只处置 this_task 变更；carried/preexisting 由源头任务负责，不重复生成 |
| 人工门控呈现（10-10 定） | 中期为**可读挂起清单**（残留、门控理由、人工操作建议）；真机交互式暂停留到阶段 B |
| 不确定残留 | attempted_unknown 条目仍登记在污染清单中（清单非空即需要恢复），但必须进 GATE_HALT；pdd27 暴露模型会静默空清单跳过，列入下一步强化项 |
| 代码位置 | `experiments/state_recovery/{docs,scripts,eval,results}`（按实验分目录约定） |
