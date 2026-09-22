# -*- coding: utf-8 -*-
"""修复 run_manifest.json / episodes.jsonl 里被写错的重置条件标签。

为什么需要
==========
`run_mbl.ps1` 早期版本用

    ((Get-Content $cfg | Select-String '^reset=') -match 'true').Count -gt 0

判定 reset 开关，这行**永远为真**：
  * config 里实际写的是 `[reset=false]`（带方括号），`^reset=` 匹配不到；
  * 匹配不到 → `$null -match 'true'` 得到标量 `$false`；
  * PowerShell 3+ 连标量都有 `.Count` 属性（恒为 1）→ `1 -gt 0` = `$true`。

于是**所有**用 `reset=false` 的 base.conf 跑出来的轮次，都被标成
`reset=True / condition=official` —— 把"没跑 cleaner"的轮次标成了官方重置。
拿这种标签去做 2×2 析因，两格会被合并成一格，**交互项静默消失**。

本脚本不重新跑实验，只按每个 run 的 `config` 字段把标签**改正**：
重新解析 config 里的 `[reset=true|false]`，据此写回 manifest 与 episodes.jsonl。

用法
====
    python mbl_fix_condition_labels.py --run-dir results/base_canonical results/base_shuffle
    python mbl_fix_condition_labels.py --run-dir results/base_canonical --dry-run
    python mbl_fix_condition_labels.py --run-dir results/x --condition official   # 手动指定

`--condition` 用于当时显式传过 `-Condition` 的轮次（config 推不出来）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

RESET_RE = re.compile(r"^\s*\[?\s*reset\s*=\s*(true|false)", re.IGNORECASE | re.MULTILINE)


def read_reset_flag(config_path: str) -> bool | None:
    """从 config 里读 `[reset=true|false]`；找不到返回 None。

    跳过以 # 开头的注释行（reset.conf 的注释里出现过 `[reset] reset=true` 字样）。
    """
    if not os.path.isfile(config_path):
        return None
    with open(config_path, encoding="utf-8-sig") as fh:
        for line in fh:
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            m = RESET_RE.match(line)
            if m:
                return m.group(1).lower() == "true"
    return None


def find_config(repo: str, config_field: str, run_dir: str) -> str | None:
    """把 manifest 里的 config 字段解析成真实路径（试几种基准目录）。"""
    if not config_field:
        return None
    cands = [
        os.path.join(repo or "", config_field),
        os.path.join(run_dir, config_field),
        config_field,
    ]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    # 最后兜底：在 repo/config 下按文件名找
    if repo:
        base = os.path.basename(config_field)
        c = os.path.join(repo, "config", base)
        if os.path.isfile(c):
            return c
    return None


def fix_one(run_dir: str, override: str | None, dry_run: bool) -> dict:
    """返回一条修复记录。run_dir 可以是运行目录，也可以是它的 episodes.jsonl。"""
    if os.path.isfile(run_dir):
        run_dir = os.path.dirname(run_dir)
    run_dir = run_dir.rstrip("/\\")
    mpath = os.path.join(run_dir, "run_manifest.json")
    epath = os.path.join(run_dir, "episodes.jsonl")

    rec: dict = {"run_dir": run_dir, "changed": False, "note": ""}
    if not os.path.exists(mpath) and not os.path.exists(epath):
        rec["note"] = "既没有 run_manifest.json 也没有 episodes.jsonl，跳过"
        return rec

    manifest: dict = {}
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8-sig") as fh:
            manifest = json.load(fh)

    repo = manifest.get("repo", "")
    cfg_path = find_config(repo, manifest.get("config", ""), run_dir)

    if override:
        new_reset = override == "official"
        src = f"命令行 --condition {override}"
    elif cfg_path:
        flag = read_reset_flag(cfg_path)
        if flag is None:
            rec["note"] = f"{os.path.basename(cfg_path)} 里没有 reset= 开关"
            return rec
        new_reset = flag
        src = f"config {os.path.basename(cfg_path)} → reset={str(flag).lower()}"
    else:
        rec["note"] = f"找不到 config（manifest.config={manifest.get('config')!r}）"
        return rec

    new_cond = "official" if new_reset else "none"
    old_cond, old_reset = manifest.get("condition"), manifest.get("reset")
    rec.update(new_reset=new_reset, new_condition=new_cond,
               old_condition=old_cond, old_reset=old_reset, source=src)

    if old_cond == new_cond and old_reset == new_reset:
        rec["note"] = "标签本来就是对的"
        return rec

    rec["changed"] = True

    n_ep = 0
    if os.path.exists(epath):
        with open(epath, encoding="utf-8-sig") as fh:
            rows = [json.loads(ln) for ln in fh if ln.strip()]
        for r in rows:
            if r.get("condition") != new_cond:
                r["condition"] = new_cond
                n_ep += 1
        rec["episodes_fixed"] = n_ep
        rec["episodes_total"] = len(rows)
        if not dry_run:
            with open(epath, "w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    if manifest and not dry_run:
        manifest["condition"] = new_cond
        manifest["reset"] = new_reset
        manifest["label_fixed_at"] = "mbl_fix_condition_labels.py"
        manifest["label_source"] = src
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)

    if dry_run:
        rec["note"] = "（--dry-run：未写入）"
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="修正 run_manifest/episodes 的重置条件标签")
    ap.add_argument("--run-dir", nargs="+", required=True)
    ap.add_argument("--condition", default=None, choices=("official", "none"),
                    help="手动指定；不传则从 config 推")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    recs = [fix_one(d, args.condition, args.dry_run) for d in args.run_dir]
    print(f"{'运行目录':<46} {'旧标签':<22} {'新标签':<22} 说明")
    print("-" * 130)
    n_changed = 0
    for r in recs:
        tag = os.path.basename(r["run_dir"])
        old = f"cond={r.get('old_condition')} reset={r.get('old_reset')}" if "old_condition" in r else "—"
        new = f"cond={r.get('new_condition')} reset={r.get('new_reset')}" if "new_condition" in r else "—"
        print(f"{tag:<46} {old:<22} {new:<22} {r.get('note') or r.get('source','')}")
        if r["changed"]:
            n_changed += 1
            print(f"{'':<46} └─ 改写 episodes: {r.get('episodes_fixed')}/{r.get('episodes_total')} 行")
    print("-" * 130)
    print(f"共 {len(recs)} 个目录，需要改标签的有 {n_changed} 个"
          + ("（--dry-run 未落盘）" if args.dry_run else ""))
    if n_changed and not args.dry_run:
        print("\n下一步：重跑分析，注意 --official-condition 现在应当是 official：")
        print("  analyze_order_effects.py --input ... --official-condition official")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
