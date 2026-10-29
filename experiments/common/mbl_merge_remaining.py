"""把 MobileBench-OL 除 base_canonical 之外、本地已有的子集合并成一份统一格式 CSV。

处理规则：
1. 输出列与 base_canonical.csv 完全一致，可被 run_pipeline.py --csv 直接读取。
2. 以 base_canonical.csv 为基准去重：identifier 相同、或 (App, goal) 相同的任务视为已用，直接跳过。
   本地 Explo_already.csv（GUI-Reasoning）的 60 条与 base 完全重复，会被全部剔除。
3. task_id 重新编号，避免与 base 冲突。

本地没下载的子集（long-tail 340、noise-robust 310）只要把对应 CSV 放进 data 目录，
脚本会自动纳入：longtail.csv / noise-robust.csv。

用法：
    python mbl_merge_remaining.py
    python mbl_merge_remaining.py --out <path> --start-id 2001
"""

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MBL_DATA = ROOT / "third_party" / "mobilebench-ol-main" / "data"
BASE_CSV = MBL_DATA / "base_canonical.csv"
DEFAULT_OUT = ROOT / "datasets" / "扩充后数据集" / "mbl_remaining_canonical.csv"

# 按顺序尝试；不存在就跳过。Explo_already 保留在列表里是为了显式展示去重效果。
CANDIDATES = [
    "longtail.csv",
    "MobileBench-OL - Long-Horizon.csv",
    "MobileBench-OL - Explo_already.csv",
    "noise-robust.csv",
]

HEADER = [
    "task_id",
    "task_identifier",
    "task_app",
    "task_app_CHN",
    "adb_home_page",
    "功能点",
    "真机/模拟器",
    "level（easy步数少<5步，是APP的基础操作,主页一眼就能看到，medium步数较多,但每一步都能直接看到。或是需要探索一下但步数特别少(<4)，hard经过的一些功能需要探索才能发现）",
    "golden_steps",
    "goal",
    "key_nodes",
    "Reset",
]
LEVEL_COL = HEADER[7]

# 官方各子集 CSV 的列名不统一，这里做别名映射（源列名 -> 统一列名）
ALIASES = {
    "functional_point": "功能点",
    "difficulty_level": LEVEL_COL,
}


def load(path: Path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def key_of(row):
    return ((row.get("task_app") or "").strip(), (row.get("goal") or "").strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--start-id", type=int, default=2001)
    args = ap.parse_args()

    base_rows = load(BASE_CSV)
    used_ids = {(r.get("task_identifier") or "").strip() for r in base_rows}
    used_keys = {key_of(r) for r in base_rows}

    kept = []
    report = []
    for name in CANDIDATES:
        src = MBL_DATA / name
        if not src.exists():
            report.append({"源": name, "状态": "本地未下载", "读入": 0, "保留": 0, "跳过原因": "-"})
            continue
        rows = load(src)
        n_keep = 0
        n_dup_base = 0
        n_dup_self = 0
        n_nokey = 0
        for row in rows:
            ident = (row.get("task_identifier") or "").strip()
            if not (row.get("key_nodes") or "").strip():
                n_nokey += 1
                continue
            if ident in used_ids or key_of(row) in used_keys:
                n_dup_base += 1
                continue
            used_ids.add(ident)
            used_keys.add(key_of(row))
            n_keep += 1
            kept.append(row)
        report.append(
            {
                "源": name,
                "状态": "已合并",
                "读入": len(rows),
                "保留": n_keep,
                "跳过原因": "与 base 重复 %d / 无 key_nodes %d" % (n_dup_base, n_nokey)
                if (n_dup_base or n_nokey)
                else "-",
            }
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    levels = {}
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        for idx, row in enumerate(kept):
            out_row = {c: "" for c in HEADER}
            for c in HEADER:
                if c in row and row[c] is not None:
                    out_row[c] = row[c]
            for src_col, dst_col in ALIASES.items():
                if not (out_row[dst_col] or "").strip() and (row.get(src_col) or "").strip():
                    out_row[dst_col] = row[src_col]
            out_row["task_id"] = args.start_id + idx
            out_row["真机/模拟器"] = ""
            lv = (out_row[LEVEL_COL] or "").strip() or "?"
            levels[lv] = levels.get(lv, 0) + 1
            writer.writerow(out_row)

    print("合并明细：")
    for r in report:
        print("  %-36s %-8s 读入 %3d  保留 %3d  %s" % (r["源"], r["状态"], r["读入"], r["保留"], r["跳过原因"]))
    apps = sorted({(r.get("task_app") or "").strip() for r in kept})
    print("合计保留: %d 条" % len(kept))
    print("覆盖 App: %d 个" % len(apps))
    print("level 分布: %s" % levels)
    print("输出: %s" % out_path)


if __name__ == "__main__":
    main()
