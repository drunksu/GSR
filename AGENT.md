# AGENT.md — Handbook for AI Coding Agents

> This file is for AI agents working in this repository: what the project is, where to edit,
> how to verify changes, and what must never be done. The authoritative operations manual is
> [`README.md`](README.md) (root, with 19 documented real-world pitfalls); the latest
> experimental results and conventions live in [`docs/motivation_study.md`](docs/motivation_study.md).
> This file gives rules and a map only — it does not duplicate the full command reference.

## 1. What This Project Is

This is the experimental workbench for a **Fudan University Xiyuan Undergraduate Research
Program (曦源本科生自主项目)** project titled *"Detecting and recovering from application
state pollution in mobile-GUI-agent evaluation"*. It is **not** a graduation thesis.

The repository serves one concrete experiment: **does task execution order change a GUI
agent's success rate (order-dependent / OD flaky tests)?**

- **Main line (MobileBench-OL):** a real Android phone + 12 real Chinese apps + a hosted
  LLM API (`qwen3-vl-plus` / `qwen3-vl-flash`), running a 2×2 factorial study of
  **order (canonical/shuffle) × reset (official/none)**. Real conclusions have been produced.
- **Phase 2 (state recovery, current focus):** `experiments/state_recovery/` builds the
  **Execute → Audit → Planner → Execute** closed loop that detects persistent state
  pollution from an execution trajectory (contamination list), generates grounded recovery
  tasks, and (Stage B, phone) executes them under a pre-check / verify / hard-gate state
  machine. Stage A (offline inference + recovery-task generation) is complete; Stage B/C
  require the phone.
- **Side line (AndroidWorld):** an emulator-based route. Code and synthetic-data self-tests
  passed historically, but the real-device path was never verified. The whole route
  (`order_runner.py`, `task_catalog.py`, `make_sim_data.py`, `power_analysis.py` plus its
  artifacts) is archived under `backup/androidworld/` with its own README — rarely touched.

This is **scientific experiment code**: no change may silently shift the data pipeline or
metric definitions. Fail loudly, never silently — pitfalls #10/#13/#19 in the README were all
cases where "the run finished" but every result was wrong.

**Time constraint:** the **mid-term defense is on 2026-10-29**. When weighing work, prefer
rebuilding/polishing reports and analysis from existing data over launching expensive new
phone runs (a full set is ~28 h / ~177M tokens). Propose any new long run explicitly and
state its cost first.

## 2. Repository Layout

| Path | What it is | Rules for changing it |
|---|---|---|
| `run_all.cmd` | The single entry point for the full experiment set (~28 h, needs the phone) | Pure ASCII; agents must not run it proactively |
| `run_mbl.cmd` / `run_mbl.ps1` | One run: self-check → write manifest → execute → convert to `episodes.jsonl` | See §5 encoding rules |
| `pilot.cmd` / `pilot.ps1` | Two order passes + automatic analysis | Same |
| `run_repeats.cmd` / `sync.cmd` | Repeated-runs scheduler / one-command add-verify-commit-push | Same |
| `mobile.env.ps1` | **Environment config**: API key (plaintext), model→coordinate registry, device serial, paths | See §6 security |
| `experiments/selftest.py` | Regression self-check (statistics + encoding guards); no phone/key needed | Must stay green; run after any edit |
| `experiments/common/` | Cross-experiment MobileBench-OL infrastructure: key lookup, API patch, endpoint/coord probes, app checklist | Reusable for future experiments |
| `experiments/motivation_study/` | Code/docs for the completed motivation study (`docs/motivation_study.md`): analyzer, episode converter, CSV/purge/audit/forensics scripts | New experiments get sibling dirs, e.g. `experiments/<name>/{scripts,docs,results}` |
| `experiments/state_recovery/` | **Phase 2 (current)**. `scripts/`: `infer_mutations.py` (trajectory → contamination list), `mutation_taxonomy.py` (schema/gate), `audit_grounding.py` (grounding + deterministic conservatism), `recovery_task.py` (recovery-task schema/validation), `generate_tasks.py` / `score_tasks.py`; `docs/design.md` is the authoritative design log, `docs/method.md` its Chinese narrative; `eval/` holds three files: `annotation_metadata.jsonl` (labeler working file), `golden_labels.json` (final human gold, 310 base_canonical cases, feeds `score_inference.py`), `ai_contamination_list.json` (AI inference output, for review comparison); `results/ledgers/` (lists on disk) and `results/recovery_tasks/` are evidence | Bump schema strings + versions when changing formats; rerun `score_inference.py` / `score_tasks.py` after prompt/validator changes; never hand-edit `results/` JSON to make scores pass — fix the generator |
| `backup/` | Superseded/extra runs, CSVs, the AndroidWorld side line — never silently delete; see `backup/MANIFEST.md` | Archived evidence |
| `third_party/mobilebench-ol-main/` | The **patched** benchmark: `run.py`, `config/`, `data/*.csv`, `results/` | See §4; never hand-edit generated patches |
| `third_party/platform-tools/` | Bundled adb (3 committed files) | Do not touch |
| `docs/` | Proposal, early-stage experiment notes (latest result conventions) | Documentation |

## 3. Environment (Windows only)

- Windows + cmd / PowerShell 5.1; Python 3.10 (scripts require 3.8+).
- The venv **must** be at the repository root and **must be named `mobile`**: the interpreter
  path is `mobile\Scripts\python.exe` (both scripts and `.ps1` files resolve it there).
- venv packages: `uiautomator2 pillow opencv-python numpy openai defusedxml lxml requests`.
- The **analysis-chain scripts use the Python standard library only** (Fisher's exact test,
  Benjamini–Hochberg FDR, and bootstrap CI are hand-rolled; no scipy/pandas/numpy). Keep new
  analysis code dependency-free.
- Phone/API work happens on a separate "phone machine"; this machine is typically the
  "analysis machine" with no phone attached.

## 4. Architecture and Data Flow (understand before editing)

```
data/<order>.csv  ── row order IS execution order
                     (csv.DictReader reads sequentially; no sorting, no shuffling)
      │
run_mbl.ps1 ── writes run_manifest.json (order / reset-condition / agent labels)
      │
third_party/mobilebench-ol-main/results/<run>/  (trajectory.json, result_list.txt, screenshots…)
      │
mbl_traj_to_episodes.py ──> episodes.jsonl   (one row per task: success / steps / duration)
      │
analyze_order_effects.py ──> results/<name>/report.md
                              (§0 empty-table diagnostics + C1/C2/C3/DiD + victim/polluter)
```

- **Order is determined entirely by CSV row order.** "Shuffling" means saving the same task
  set as another CSV with a different row order, generated by `mbl_make_task_csv.py`. The
  filename must contain `canonical` / `reverse` / `shuffle<digits>` / `adversarial`, or the
  manifest cannot infer the order mode (the seed is the digits).
- Every **order × reset-condition × model** combination needs its **own `-Output` directory**:
  `result_list.txt` is a resume cache, and reusing a directory makes every task get silently
  skipped (pitfall #2).
- Reset-condition labels: runs using the benchmark cleaner are `official`; runs without it
  are `none` (parsed from the config's `[reset=true|false]`; pitfall #13 once mislabeled every
  run as `official`).
- Benchmark patches are generated idempotently by `mbl_apply_api_patch.py`
  (`--revert` rolls back; `.bak` backups are kept). **Change patch behavior in the patcher
  script**: the full text of `mbl_api_shim.py` lives in that script's `SHIM` constant, so
  editing the generated file directly gets overwritten on the next patch. `.gitattributes`
  enforces LF because patching relies on exact multiline text anchors — CRLF makes every
  anchor fail to match.
- Artifact commit policy: small files (`episodes.jsonl`, `run_manifest.json`,
  `trajectory.json`, `result_list.txt`, `report.md`) **are committed**; GB-scale screenshots
  (`step_*.png/xml`, `*_som.png`) are **ignored** (see `.gitignore`, pitfall #9).

## 5. Hard Rules for Code and Encoding (guarded by self-test)

After editing any `.ps1`, `.cmd`, or Python file, **run the self-test first** (~1 second,
no phone or API key needed):

```powershell
mobile\Scripts\python.exe experiments\selftest.py
```

It guards both statistical correctness and this repository's own pitfalls (G1/G2). Required:

1. **`.cmd` / `.bat` files must be pure ASCII.** cmd.exe parses them in the local code page
   (GBK on Chinese Windows); a single UTF-8 Chinese byte eats the start of the next line
   (pitfalls #5/#18 — once made a 28-hour experiment block "finish" in 1 second). Use `%%r`
   for loop variables. Put Chinese explanations in `.md` files, never in batch files.
2. **`.ps1` files containing Chinese must have a UTF-8 BOM.** PowerShell 5.1 decodes
   BOM-less files as GBK (pitfall #11). If your editor strips the BOM, re-run the self-test
   to verify G1.
3. **Never rewrite Chinese-containing files with `Get-Content | Set-Content`** — it decodes
   as GBK and writes back double-encoded mojibake (pitfall #12). Use an editor / dedicated
   editing tools; if you must read/write from PowerShell, use
   `[System.IO.File]::ReadAllText/WriteAllText` with an explicit UTF8Encoding.
4. In PowerShell, **pass arguments with explicit parameter names**; never build an array of
   switches and splat it (pitfall #19 destroyed a 12-hour run). Also note: scalars have
   `.Count` too, and variable names are case-insensitive (`$Config` collides with `$CONFIG`).
5. Python scripts: `from __future__ import annotations` header; Chinese docstrings are fine;
   scripts run directly from cmd should themselves call
   `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` as a fallback (a GBK console
   cannot even encode `✅`; pitfall #16).
6. **Do not add one-off scripts to the repository root.** Single-round backfill scripts are
   deleted after use (the README already removed `run_missing.cmd` and friends). The only
   long-term entry points are `run_all.cmd`, `run_mbl.cmd`, and `pilot.cmd`.
7. Failure paths must **raise explicitly** (throw / non-zero exit / `[FATAL]`); never
   `except: print` and swallow — an API hiccup silently turned into an invalid action gets
   misread as an order effect.

## 6. Security

- `mobile.env.ps1` contains a **plaintext API key and is currently tracked by git** (a
  historical fact). Do not copy the key into new files, logs, commit messages, or chat
  output. Scripts needing the key should go through `mbl_env.py` (environment variable first,
  then parse that file) — never hardcode the key in a second place.
- Do not introduce new private data (real account/friend/group IDs beyond what the experiment
  already records) into code or output.

## 7. Agent Behavior Boundaries

- **Never start phone experiments on your own** (`run_all.cmd` / `run_mbl.cmd` /
  `pilot.cmd` / adb commands): they need a physical phone, ~28 hours, millions of tokens, and
  12 manual `pause` points where a human restores QQ state. Do so only when the user
  explicitly asks. Phone-free rehearsal uses `-DryRun`.
- State-recovery **Stage A scripts are phone-free** and may be run freely (they do call the
  text LLM API, so they cost tokens): `infer_mutations.py`, `generate_tasks.py`,
  `score_inference.py`, `score_tasks.py`, `audit_grounding.py`; `--dry-run` prints prompts
  without any API call. **Stage B/C recovery execution on the phone falls under the same
  phone-experiment ban** — wait for an explicit request and state the expected task count
  and pause points first.
- **Do not delete, reorder, or rename directories under `results/` or the CSV task sets** —
  they are experimental evidence, and directory names are the analyzer's grouping inputs.
  Cleaning is only allowed via `mbl_purge_tasks.py --blank-failed-only` (**not**
  `--blank-only`, which would also remove successful music/IM episodes whose final frame is
  dark because the screen turned off after success).
- **Do not add runs or tweak data just to fill a table.** When the report's §0 empty-table
  diagnostics say data is missing, the conclusion is "threshold not reached", **not "no
  effect"**. Record effect sizes, CIs, and failed rounds honestly (the README section F
  tradition).
- Before switching/adding a model, run `mbl_coord_convention_check.py --model <name>
  --repo <repo>` and register it in the `$MBL_MODELS` table in `mobile.env.ps1`. A wrong
  norm/pixel convention means every click crowds into the top-left corner and every task fails
  with no visible cause (pitfall #1).
- Do not `git commit` / `git push` unless the user explicitly asks. When an upload is needed,
  use `sync.cmd` (it verifies that files under `results\` actually got staged).
- The standard analysis-machine workflow is in README section "二、分析机": pull →
  `mbl_fix_condition_labels.py --dry-run` to verify labels → coordinate re-check →
  `analyze_order_effects.py` to rebuild reports → **read §0 before the tables**.

## 8. Common Commands (analysis machine, PowerShell)

```powershell
# Self-test (run after every code change)
mobile\Scripts\python.exe experiments\selftest.py

# Rehearse one run without touching the phone
.\run_mbl.cmd -TaskFile data\smoke_2task.csv -Output results\_selftest -DryRun

# Rebuild a report from episodes (CWD = third_party\mobilebench-ol-main)
..\..\mobile\Scripts\python.exe ..\..\experiments\motivation_study\scripts\analyze_order_effects.py `
  --input results\p1_none_can results\p1_off_can --out results\demo --official-condition official

# Phase 2, Stage A — all phone-free (CWD = experiments\state_recovery\scripts)
..\..\..\mobile\Scripts\python.exe score_inference.py --golden ..\eval\golden_labels.json
..\..\..\mobile\Scripts\python.exe score_tasks.py --out ..\results\recovery_task_report_v0.json
..\..\..\mobile\Scripts\python.exe generate_tasks.py --run base_canonical --task articlenews_16 --dry-run
```

For the full command set (deployment, B1–B10, backfills, sync), see the corresponding README
sections.

## 9. Terminology

OD flaky (a task whose result depends on execution order) · victim (a task that fails when
order changes) · polluter (a preceding task that dirties state and causes later failures) ·
CTCI (success-rate range across orders) · PASR (success rate under the worst order — a
trustworthy lower bound) · DiD (order × reset interaction) · C1 pollution main effect /
C2 order main effect / C3 combined effect.

Phase 2 (state recovery) terms:

- Agents: **Audit Agent** (offline inference) → **Planner Agent** (recovery-task generation)
  → **Execute Agent** (the reused benchmark executor; also runs recovery). No other names
  (Detector/Restorer/Packet) may appear in docs or user-facing strings.
- **Contamination list** = the Audit Agent's structured output, schema
  `contamination-list/v0.1`, one entry per persistent state change with evidence + gate.
  **Recovery task** = the Planner Agent's output, schema `recovery-task-set/v0.1`
  (`recovery-task/v0.1` per item; the set key is `tasks`), equivalent to a benchmark goal
  plus safety shell (precondition / expected_end_state / risk_level / idempotent).
- **Implementation aliases (intentional, do not "fix"):** internal Python variables keep the
  name `ledger`, lists are written as `results/ledgers/<run>/*_ledger.json`, and cross-task
  carry-over is referred to as "结转" in Chinese prompts. These are internal storage names;
  all product/documentation language says contamination list / recovery task.
- Gate: `autonomous` (high-confidence, UI-reversible → auto recovery task) vs `halt`
  (irreversible / uncertain → human_gate list, never auto-executed). The golden rule stays
  "generation may be free, execution must be gated" — wrong recovery is new pollution.
