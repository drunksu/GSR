"""把三份任务清单合并成全量清单（SCAR-Bench）。

输入：
  third_party/mobilebench-ol-main/data/base_canonical.csv         310 条
  datasets/base/spa_canonical.csv                                  149 条
  datasets/base/mbl_remaining_canonical.csv                        400 条
输出：
  datasets/base/scar_bench.csv                                     859 条

合并规则：
  task_id 统一按行序重排为 1..N，避免各来源 id 区间重叠；
  task_identifier 全局去重，重复的直接报错，不做静默丢弃；
  其余列原样保留，三个来源表头已对齐。
"""

import csv
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJECT = Path(__file__).resolve().parents[2]
DATA = PROJECT / "third_party" / "mobilebench-ol-main" / "data"

SOURCES = [
    ("base", DATA / "base_canonical.csv"),
    ("spa", PROJECT / "datasets" / "base" / "spa_canonical.csv"),
    ("mbl", PROJECT / "datasets" / "base" / "mbl_remaining_canonical.csv"),
]

OUT = PROJECT / "datasets" / "base" / "scar_bench.csv"


def read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def main():
    header = None
    merged = []
    for label, path in SOURCES:
        if not path.exists():
            raise SystemExit(f"缺少输入文件：{path}")
        cols, rows = read(path)
        if header is None:
            header = cols
        elif cols != header:
            raise SystemExit(f"表头不一致：{path}")
        print(f"{label:<5} {len(rows):>4} 条  {path.name}")
        merged.extend(rows)

    ids = [r["task_identifier"].strip() for r in merged]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise SystemExit(f"task_identifier 重复 {len(dup)} 个，例如：{sorted(dup)[:5]}")

    for idx, row in enumerate(merged, start=1):
        row["task_id"] = idx

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(merged)

    apps = {r["adb_home_page"].split("/")[0] for r in merged if r["adb_home_page"]}
    print(f"\n合计 {len(merged)} 条 / {len(apps)} 个 App")
    print(f"输出：{OUT}")


if __name__ == "__main__":
    main()
