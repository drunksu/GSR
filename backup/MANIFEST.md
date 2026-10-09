# backup/ — Files Outside the Motivation Study

Created 2026-10-09. Everything here was produced **before or alongside** the motivation study
(`docs/motivation_study.md`) but is **not cited by that document's experiments, metrics, or
conclusions**. Files were moved, not deleted; relative directory names are preserved.

The study's authoritative data stays in place:

| Study section | Run directories (`third_party/mobilebench-ol-main/results/`) | Report | Task CSVs (`.../data/`) |
|---|---|---|---|
| Experiment 1 — 2×2 main, 65 tasks, 520 episodes | `p1_none_can`, `p1_off_can`, `p2_none_shf`, `p2_off_shf`, `f_none_can`, `f_off_can`, `f_none_shf`, `f_off_shf` | `twomodel_2x2/` | `reset_canonical.csv`, `reset_shuffle0.csv` |
| Experiment 2a — QQ 8-task repeats, 192 episodes | `q2_A_1..6`, `q2_B_1..6`, `q2_Af_1..6`, `q2_Bf_1..6` | `repeat_analysis/` | `qqset_canonical.csv`, `qqset_reverse.csv` |
| Experiment 2b/c — 4-task subset + polluter table | `s3_A_1..14`, `s3_B_*` (13 dirs, B_5 never ran), `s3_Af_1..2`, `s3_Bf_1..2` | `victim_analysis/` | `qqvar4_canonical.csv`, `qqvar4_reverse.csv` |
| Experiment 3 — full scale, 310 tasks, 1239 episodes | `base_canonical`, `base_shuffle`, `baseflash_canonical`, `baseflash_shuffle` | `scale_analysis/` | `base_canonical.csv`, `base_shuffle0.csv` |
| Finding "manual restoration is mandatory" (the failed no-restoration rerun, plus side, 96 identical episodes) | `qqset_A_r1..6`, `qqset_B_r1..6` | `qqset_analysis/` | — |

## What Is Here and Why

### `mobilebench-ol-results/` — superseded runs and extra experiments

| Item | Category | Why moved |
|---|---|---|
| `pilot12_canonical`, `pilot12_shuffle`, `pilot12flash_canonical`, `pilot12flash_shuffle`, `pilot12_analysis/` | early pilot | 12-task pilot before the study's three experiments; not cited |
| `reset_can`, `reset_shf` | superseded | Standalone 09-23 reset runs. The study uses the same-day paired cells (`p1_off_can`, `p2_off_shf`), which control for day effects |
| `base_analysis/`, `master_analysis/`, `repeat_subset/` | superseded reports | Older single-model / interim analyses replaced by `scale_analysis/`, `twomodel_2x2/`, and `victim_analysis/` respectively |
| `qqset_Af_r1..6`, `qqset_Bf_r1..6`, `qqset_multiagent_analysis/` | extra | Flash side of the first (no-restoration) repeat design. The study cites only the plus-side 96-episode run, which stays in place; this is the same flawed design on the second model and is not cited |
| `smoke/`, `val1/`, `reset_smoke/` | smoke tests | Pipeline-validation runs (2 tasks each), not study data |

### `mobilebench-ol-data/` — extra task-set CSVs

| Item | Category |
|---|---|
| `longtail.csv`, `longtail-reset.csv`, `top12.csv`, `top12-reset.csv` | task sets for experiments outside the study |
| `order_canonical.csv`, `order_reverse.csv`, `order_shuffle0.csv` | earliest 12-task order set (smoke/pilot era) |
| `reset_smoke_2task.csv` | reset-channel smoke test input |

Deliberately **kept in place**: `pilot12_canonical.csv` / `pilot12_shuffle0.csv` (the small
12-task default of `pilot.ps1`; a bare `pilot.cmd` must remain a cheap safe dry run) and
`smoke_2task.csv` (environment self-check input).

### `experiments-results/` — side-line and exploration artifacts

| Item | Category |
|---|---|
| `plan/`, `sim/` | AndroidWorld side line: dry-run plan and regenerable synthetic data (`sim/` is gitignored; regenerate with `make_sim_data.py`) |
| `mbl_audit/audit.json` | CSV audit covering only the extra longtail/top12/Explo/Long-Horizon sets |
| `app_checklist_longtail.md` | install checklist for the extra longtail set; the base 12-app checklist stays in `experiments/results/` |

### `experiments-data/`

`pilot_tasks.txt` — AndroidWorld pilot task list (side line).

### `experiments-scripts/`

`mbl_api_smoketest.py` — early endpoint smoke test (P0–P3 probes) from initial bring-up;
superseded by `mbl_api_probe.py` + `mbl_coord_convention_check.py`, which stay in
`experiments/scripts/`.

## Notes

- The AndroidWorld **scripts** (`task_catalog.py`, `order_runner.py`, `make_sim_data.py`,
  `power_analysis.py`) intentionally stay in `experiments/scripts/` because `selftest.py`
  imports and guards them; only their generated artifacts moved.
- Vendored benchmark files in `third_party/mobilebench-ol-main/config/` and the raw upstream
  CSVs (`MobileBench-OL - *.csv`) were left untouched.
- `run_all.cmd` predates this cleanup: its `master_analysis` line still references the moved
  `reset_can` / `reset_shf` directories. It is a historical full-run entry point; trim or
  update it before the next full rerun.
