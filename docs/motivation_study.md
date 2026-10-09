# Motivation Study

Core question: when MobileBench-OL runs real apps back to back, does the state left behind by one task change the success rate of later tasks? Does changing the task order change the evaluation results?

## Experiment Setup

| Item | Details |
|---|---|
| Dataset | **MobileBench-OL**, 310 tasks / 12 apps.<br>7 apps with 30 tasks each (Bilibili, Fanqie, NetEase Music, Pinduoduo, QQ, 58.com, Tonghuashun), 5 apps with 20 each (Toutiao, Amap, Baidu Browser, DingTalk, Meiyou).<br>Mean golden_steps 5.1, max 16; step cap min(3×golden, 20) |
| Order subset | The 65 tasks in `reset_canonical.csv` — the only subset in the benchmark with manual cleaner instructions (reset_query/reset_xpath), and therefore the only set on which a "reset × order" 2×2 is possible |
| Environment | Real phone Redmi 24129RT7CC (Android 16, 1220×2712, Chinese UI), USB + ADB |
| Models | **qwen3-vl-plus and qwen3-vl-flash**, served through a hosted API. Both use the norm coordinate convention (0–1000 normalized) |

- "Execution order" is simply the row order of the task-registration CSV: the benchmark neither sorts nor shuffles it. "Shuffling" means saving the same task set as another CSV with a different row order, with everything else unchanged — so the comparison differs only in starting order, without any instruction-rewriting confound.

- Because the benchmark runs Chinese apps on a real device, task side effects persist both on the device and on the server: group-join requests, friend requests, shopping carts, night-mode settings and the like carry over across tasks. Full-device emulator snapshots cannot represent this, so the measurement has to be done on a real phone.

- The 65 tasks are singled out because they come with a cleaner; the other 245 tasks have no cleaning instructions and can only be used for order comparisons.

- We compare two models, plus and flash: two capability tiers of the same family, plus stronger and flash weaker, to see whether order sensitivity is intrinsic to the environment or modulated by model capability. Their coordinate conventions are identical (0–1000 norm), so a coordinate-scale mismatch or "clicks landing off target" cannot be mistaken for order pollution.

## Experiment 1: Main Experiment

### Design

Two factors: order and cleaning.

| Factor | Levels |
|---|---|
| Order | canonical: the canonical CSV row order<br>shuffle: row order shuffled with a fixed seed |
| Reset | none: no cleaning between tasks, just returning to the home screen<br>official: running the benchmark's built-in cleaner, where the same GUI agent executes the manual reset_query |
| Model | qwen3-vl-plus<br>qwen3-vl-flash |

The task set is fixed to the same 65 common tasks; the four cells were run back to back in pairs on the same day with the same CSVs, giving 8 cells × 65 = 520 episodes.

| Contrast | What is fixed, what changes | Question answered |
|---|---|---|
| C1 | Canonical order in both; only the cleaner is turned off | How many points are lost without cleaning? |
| C2 | Cleaner on in both; only the row order is shuffled | Can the official cleaner block the order effect? |
| C3 | No cleaning plus shuffled order, vs. "cleaning + canonical order" | How much worse is the worst cell than the clean baseline? |

C2 ≈ 0 only shows that *this manual cleaner* blocks the *average* loss on *this pair of orders*; it does not mean order is unimportant in real evaluations — most online tasks have no cleaner at all. Moreover, "official" means letting the same GUI agent execute the cleaning instructions; it is not a snapshot rollback, and it mixes in the question of whether the cleaner actually cleaned everything, so the official cleaner must not be treated as a perfect reset.

### Metric Definitions

> A 95% CI excluding 0 is read as significant (stable direction); a CI crossing 0 but with one endpoint touching 0 is borderline; clearly crossing 0 is non-significant. Negative ΔSR means the treatment group is worse.
>
> Reference group = canonical order / cleaner-on group; treatment group = the group it is compared against. SR(t, o) is the success rate of task t under order o, where o ranges over the orders appearing in that group.

| Metric | Definition |
|---|---|
| SR | successful episodes ÷ total episodes |
| ΔSR | mean_t( SR(t, treatment) − SR(t, reference) ): paired per task first, then averaged across tasks; negative means the treatment is worse |
| 95% CI | 2000 bootstrap resamples of the per-task ΔSR series, taking the 2.5% / 97.5% quantiles |
| CTCI | mean_t( max_o SR(t,o) − min_o SR(t,o) ): the full success-rate range across orders for each task, averaged; **larger** means more order-sensitive |
| PASR | mean_t( min_o SR(t,o) ): success rate under the worst order for each task, averaged |
| victim | an order-victim task: success rate changes significantly when the order changes |
| polluter | a polluting predecessor: the immediately preceding task that raises a target task's conditional failure rate above baseline |
| C1/C2/C3 | C1: no cleaner vs. cleaner (both canonical)<br>C2: shuffled vs. canonical (both with cleaner)<br>C3: no cleaner + shuffled vs. cleaner + canonical |

### Results and Analysis

| agent | contrast | SR(reference) | SR(treatment) | ΔSR | 95% CI | Reading |
|---|---|---|---|---|---|---|
| plus | C1 pollution main effect | 0.738 | 0.585 | **−0.154** | **[−0.292, −0.031]** | significant |
| plus | C2 order main effect | 0.738 | 0.738 | +0.000 | [−0.077, +0.092] | not significant |
| plus | C3 combined | 0.738 | 0.600 | −0.138 | [−0.277, −0.015] | significant |
| flash | C1 pollution main effect | 0.646 | 0.523 | −0.123 | [−0.262, +0.015] | borderline |
| flash | C2 order main effect | 0.646 | 0.600 | −0.046 | [−0.138, +0.046] | not significant |
| flash | C3 combined | 0.646 | 0.523 | −0.123 | [−0.262, +0.000] | borderline |

| agent | condition | canonical | shuffled | ΔSR | CTCI | PASR |
|---|---|---|---|---|---|---|
| plus | none | 0.585 | 0.600 | +0.015 | 0.138 | 0.523 |
| plus | official | 0.738 | 0.738 | +0.000 | 0.123 | 0.677 |
| flash | none | 0.523 | 0.523 | +0.000 | 0.092 | 0.477 |
| flash | official | 0.646 | 0.600 | −0.046 | 0.138 | 0.554 |

- Under pollution, model success rate drops significantly.

- When the order is shuffled, model success rate is not significantly affected.

## Experiment 2: QQ Repeat Experiment (8 tasks, 192 episodes)

### Design

| Item | Details |
|---|---|
| Task set | 8 QQ tasks from the task set: state-writing qq_1 (group-join request) and qq_4 (friend request), followed by qq_10–qq_14, which failed consecutively after them in pilot runs |
| Schedule | 2 orders (writer first / writer last) × 6 rounds × 2 models = 24 runs, 192 episodes |
| Key | Manual state restoration between every round (leaving groups / deleting friends / unpinning chats, etc.) |

> QQ was chosen because a series of likely polluting tasks was observed (qq_1 and qq_4 write state; qq_10–qq_14 then failed consecutively). The repeat experiment tests whether this chain is stable and whether the predecessor can be statistically identified as a polluter.

### Results and Analysis

#### a) Full 8-task set, 6 rounds (192 episodes)

| agent | canonical | reverse | ΔSR | 95% CI | PASR | Reading |
|---|---|---|---|---|---|---|
| plus | 0.562 | 0.583 | +0.021 | [+0.000, +0.062] | 0.562 | not significant |
| flash | 0.375 | 0.271 | −0.104 | [−0.188, −0.021] | 0.271 | significant |

With all 8 tasks pooled, the effect for plus is not significant. The weaker model's overall success rate moves with order; the stronger model's does not.

#### b) Pre-registered 4-task subset, with more rounds

After using `--tasks` to filter out tasks whose success rate is fixed at 0/1 under both orders and therefore cannot flip:

| agent | rounds | canonical | reverse | ΔSR | 95% CI | Reading |
|---|---|---|---|---|---|---|
| plus | 20 / 19 | 0.363 | 0.395 | +0.032 | [+0.016, +0.065] | significant |
| flash | 8 / 7 | 0.438 | 0.286 | −0.152 | [−0.214, −0.107] | significant |

| task | plus ΔSR (n=20/19) | flash ΔSR (n=8/7) |
|---|---|---|
| qq_1 | +0.082 | −0.143 |
| qq_10 | +0.016 | −0.107 |
| qq_13 | +0.016 | −0.107 |
| qq_14 | +0.016 | −0.250 |

The "model × order" interaction on the subset (paired per task): −0.184 [−0.245, −0.123], significant.

#### c) First significant entries in the polluter table (plus)

| Predecessor | n (times appearing as predecessor) | conditional failure rate | baseline failure rate |
|---|---|---|---|
| qq_1 | 14 | 1.000 | 0.610 |
| qq_13 | 33 | 0.818 | 0.610 |

n is the number of times the predecessor appears immediately before some task across all runs; polluter identification requires n ≥ 3 — too little support is excluded from the statistics.

Tasks immediately following qq_1 failed 14/14 times.

## Experiment 3: Full-Benchmark-Scale Validation (310 tasks, 1239 episodes)

### Design

Experiment 3 fixes reset at none (no cleaning between tasks), expands the task set from 65 to all 310 tasks, and compares only the two orders (canonical vs. fixed-seed shuffle) across two models: 1239 episodes in total. Of these, 309 tasks have results for both models and are used for the paired "model × order" comparison. The goal is to test the Experiment-2 finding — that the weaker model is more order-dependent — on the 8 QQ tasks at full scale.

### Results and Analysis

| agent | n | canonical | shuffled | ΔSR | 95% CI | CTCI | PASR |
|---|---|---|---|---|---|---|---|
| plus | 310 | 0.571 | 0.594 | +0.023 | [−0.019, +0.065] | 0.152 | 0.506 |
| flash | 309 | 0.576 | 0.524 | −0.052 | [−0.097, −0.003] | 0.194 | 0.453 |

Without a cleaner, shuffling the order significantly lowers flash's success rate (CI excludes 0); plus is unaffected.

Per-task paired test of the "model × order" interaction (n=309):

| Quantity | ΔSR | 95% CI | Reading |
|---|---|---|---|
| plus order effect | +0.026 | [−0.019, +0.068] | not significant |
| flash order effect | −0.052 | [−0.097, −0.003] | significant |
| interaction (flash − plus) | −0.078 | [−0.139, −0.016] | significant |

With the cleaner off and the task set expanded to the full benchmark, only flash degrades significantly; the model × order interaction is significant. Shuffling costs flash 5.2 points.

## Case Analysis

| Phenomenon | Evidence |
|---|---|
| Cross-run state residue | The canonical order switches Baidu Browser to night mode (final-frame brightness 44.7); the first frame of the shuffled run is already 34.4 |
| QQ group/friend pollution chain | qq_1 is literally "search QQ for the DND group" and is judged successful, but it only submits a group-join request without verifying that joining succeeded; qq_4 adds a friend → the following qq_10–qq_14 fail five times in a row |
| Evaluator problem | qq_17 (view QQ Wallet) is judged failed 12/12 times, but in the trajectory the agent has already terminated saying the view is complete → reset_xpath does not match this app version |

Baidu Browser is configuration pollution, and it persists across runs. The screen was already dark at the end of the canonical run, so the first frame of the shuffled run was not a clean start. Pressing Home between tasks cannot clear this kind of setting; cleaning has to happen inside the app.

QQ groups and friends are data pollution, and some write operations happen inside trajectories whose task is judged successful. Some tasks require the other party to act to complete; if the other party does not act, completion of later tasks is disturbed.

qq_17 is an evaluator-script problem. It is judged failed all 12 times even though the trajectory shows the agent finishing and claiming completion; it is more consistent with reset_xpath not matching the current app version.

## Findings Across the Experiments

### The dataset's Reset labels may be inappropriate

The MobileBench-OL authors tagged some tasks with the **Reset=Need** label, meaning "this task needs its state reset after running".

We examined 65 adjacent task pairs and found that when a predecessor carried the Reset=Need label, the failure rate of the following task was **0.400**, while the overall baseline failure rate was **0.429** — the tasks "the authors believed needed resetting" did not in fact raise their successors' failure rate.

### Manual restoration is necessary

When we first ran the repeat experiment (Experiment 2), we **did not restore state between rounds** (no leaving groups, deleting friends, or unpinning chats).

We ran 96 episodes, and the results of the two orders were pairwise identical.

After the first round, every group that should be joined had been joined and every friend added. Whatever order the second round used, it started from the same saturated state, so the outcomes were of course identical. The first order fixes the starting point of the later order; repeating it any number of times merely copies the same endpoint.

Manual restoration between rounds is not optional — it is **mandatory**. From now on, any experiment estimating per-task variance must restore state between rounds, or adding rounds carries no statistical meaning.

## Stage Conclusions

- State pollution genuinely exists: without the cleaner, success rate drops 12–15 points.

- When the cleaner is present, the order effect does not change results.

- Order sensitivity is model-dependent: the effect is not significant for plus and is significant for flash.

- Pollution is task-specific, and the officially annotated Reset=Need label has little bearing on the following task.

- Detecting order-sensitive tasks has a cost: many rounds must be run.
