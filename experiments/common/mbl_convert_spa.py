"""把 SPA-Bench 中文单 App 任务转换成项目统一的 MobileBench-OL CSV 格式。

只做字段映射，不做污染类型分类。输出列与 base_canonical.csv 完全一致，
可被 run_pipeline.py --csv 直接读取。

用法：
    python mbl_convert_spa.py
    python mbl_convert_spa.py --in <spa csv> --out <output csv> --start-id 1001
"""

import argparse
import ast
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IN = ROOT / "datasets" / "可扩充数据集" / "SPA-Bench" / "data" / "single-app-CHN.csv"
DEFAULT_OUT = ROOT / "datasets" / "扩充后数据集" / "spa_canonical.csv"

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

LEVEL_MAP = {"1": "easy", "2": "medium", "3": "hard"}


def parse_components(raw: str):
    """key_component_final 形如 ['港币','欧元']，解析成字符串列表。"""
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        val = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return []
    if isinstance(val, str):
        return [val]
    return [str(x).strip() for x in val if str(x).strip()]


def build_key_nodes(components):
    """按项目既有写法把关键组件拼成 xpath 判定节点。"""
    if not components:
        return ""
    conds = " and ".join('contains(@text, "%s")' % c for c in components)
    xpath = '//*[%s]' % conds
    return json.dumps({"xpath": [xpath]}, ensure_ascii=False)


def convert(in_path: Path, out_path: Path, start_id: int):
    with open(in_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    kept, dropped = [], []
    for row in rows:
        if (row.get("is_cross_app") or "").strip().upper() == "Y":
            dropped.append((row["task_identifier"], "跨 App 任务"))
            continue
        components = parse_components(row.get("key_component_final"))
        pkg = (row.get("adb_app") or "").strip()
        act = (row.get("adb_home_page") or "").strip()
        if not components:
            dropped.append((row["task_identifier"], "无 key_component，结束态不可判定"))
            continue
        if not pkg or not act:
            dropped.append((row["task_identifier"], "缺 App 包名或首页 Activity"))
            continue
        kept.append((row, components, pkg, act))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        for idx, (row, components, pkg, act) in enumerate(kept):
            writer.writerow(
                {
                    "task_id": start_id + idx,
                    "task_identifier": "spa_" + row["task_identifier"].strip(),
                    "task_app": (row.get("task_app") or "").strip(),
                    "task_app_CHN": (row.get("task_app_CHN") or "").strip(),
                    "adb_home_page": "%s/%s" % (pkg, act),
                    "功能点": "",
                    "真机/模拟器": "",
                    "level（easy步数少<5步，是APP的基础操作,主页一眼就能看到，medium步数较多,但每一步都能直接看到。或是需要探索一下但步数特别少(<4)，hard经过的一些功能需要探索才能发现）": LEVEL_MAP.get(
                        (row.get("task_difficulty") or "").strip(), ""
                    ),
                    "golden_steps": (row.get("golden_steps") or "").strip(),
                    "goal": (row.get("task_description") or "").strip(),
                    "key_nodes": build_key_nodes(components),
                    "Reset": "",
                }
            )

    apps = sorted({(r[0].get("task_app") or "").strip() for r in kept})
    print("输入任务: %d" % len(rows))
    print("保留任务: %d" % len(kept))
    print("剔除任务: %d" % len(dropped))
    for tid, why in dropped:
        print("  - %s: %s" % (tid, why))
    print("覆盖 App: %d -> %s" % (len(apps), ", ".join(apps)))
    print("输出: %s" % out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", default=str(DEFAULT_IN))
    ap.add_argument("--out", dest="out_path", default=str(DEFAULT_OUT))
    ap.add_argument("--start-id", type=int, default=1001)
    args = ap.parse_args()
    convert(Path(args.in_path), Path(args.out_path), args.start_id)


if __name__ == "__main__":
    main()
