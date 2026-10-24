#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""score_inference.py —— 阶段 A 离线推断质量评分（golden-labels/v1 口径，2026-10-17 修订）。

把 infer_mutations.py 产出的污染清单（results/ledgers）与
eval/golden_labels.json 人工金标对照。所有指标 100% 追溯到人工标注字段，
不读取任何模型自生成的统计字段。

指标口径（v1，检测与归因分离）：

  0. 检测范围：只评 this_task / preexisting 的变更（金标口径，与"逐任务触发"
     决策一致）；carried_over 结转残留不计入检测分母/分子，单列 skipped 计数；
  1. detection_micro（检测口径）：type + entity(kind/name) 匹配的
     micro precision / recall / F1 —— 衡量"有没有检出污染"，不受归因噪声影响；
     附 detection_micro_type_only 对照（只比 type），隔离"实体命名不一致"误差；
  2. attribute_accuracy（归因口径）：检测已匹配的条目上，direction /
     attribution 各自的正确率 —— 归因错误不再同时记 FP+FN；
  3. gate_accuracy：金标 expect_gate 条目的门控决策正确率（分 autonomous/halt）；
  4. search_term_recall：金标 search_terms_any 被预测词覆盖的比例；
  5. negative_case_specificity：金标空清单 case 预测也为空的比例；
  6. failed_case_detection_recall：judged_success=false 但金标确有变更的 case 中
     全部变更均被检出的比例（取代已废弃的 hard_case 口径；金标 v1 无 hard_case 字段）。

缺失污染清单的 case **显式排除出所有分母**（不按全漏检计），单独列在
excluded_missing_cases 并在控制台大声告警。

用法::

    mobile\\Scripts\\python.exe score_inference.py \
        --golden ..\\eval\\golden_labels.json \
        --ledger-root ..\\results\\ledgers \
        [--out ..\\results\\score_report_v1.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_GOLDEN = HERE.parent / "eval" / "golden_labels.json"
DEFAULT_LEDGER_ROOT = HERE.parent / "results" / "ledgers"


def norm(s) -> str:
    return (str(s) if s is not None else "").strip().lower().replace(" ", "")


# 检测范围口径（与"逐任务触发"决策一致）：金标只标注 this_task / preexisting
# 两类变更，从不标注 carried_over。结转残留的恢复责任在源头任务，不得在本任务
# 重复计账，否则顺序越靠后的任务 FP 越多（实测 fp 随任务序号单调增长的假象）。
IN_SCOPE_ATTRIBUTIONS = ("this_task", "preexisting")


def entity_matches(pred: dict, gold: dict) -> bool:
    ent = pred.get("entity") or {}
    if gold.get("entity_kind") and ent.get("kind") != gold["entity_kind"]:
        return False
    if gold.get("identifier"):
        if norm(gold["identifier"]) not in norm(ent.get("identifier")) \
                and norm(gold["identifier"]) not in norm(ent.get("name")):
            return False
    names = ([gold["name_any"]] if isinstance(gold.get("name_any"), str)
             else gold.get("name_any"))
    if names:
        blob = norm(ent.get("name")) + norm(ent.get("identifier"))
        if not any(norm(n) in blob for n in names):
            return False
    elif gold.get("name_contains"):
        blob = norm(ent.get("name")) + norm(ent.get("identifier"))
        if norm(gold["name_contains"]) not in blob:
            return False
    return True


def detect_match(pred: dict, gold: dict, strict: bool = True) -> bool:
    """检测口径：只看 type + entity 是否指同一变更，不看归因字段。

    strict=False 时只比 type（type-only 对照口径），用于把"变更类型检出能力"
    与"实体命名不一致"两类误差分开，避免一个指标混杂两种失败。
    """
    if pred.get("type") != gold.get("type"):
        return False
    return entity_matches(pred, gold) if strict else True


def pair_specificity(pred: dict, gold: dict) -> int:
    """匹配特异度：金标 name_contains 越长，该匹配越具体，优先占用预测条目。

    防止通用名金标条目先抢走预测、挤掉更具体的金标条目（贪心顺序偏差）。
    """
    return len(norm(gold.get("name_contains") or gold.get("name_any") or ""))


def match_pairs(preds: list, golds: list, strict: bool = True) -> list:
    """最优优先贪心匹配：所有合法 (gold, pred) 对按特异度降序分配，互不重复。"""
    pairs = []
    for gi, gm in enumerate(golds):
        for pi, pm in enumerate(preds):
            if detect_match(pm, gm, strict=strict):
                pairs.append((-pair_specificity(pm, gm), gi, pi))
    pairs.sort()
    used_g, used_p, matched = set(), set(), []
    for _, gi, pi in pairs:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        matched.append((gi, pi))
    return matched


def attribute_correct(pred: dict, gold: dict) -> dict:
    """归因口径：金标指定了该字段才计入正确率分母。"""
    out = {}
    if gold.get("direction"):
        out["direction_ok"] = pred.get("direction") == gold["direction"]
    if gold.get("attribution"):
        out["attribution_ok"] = pred.get("attribution") == gold["attribution"]
    return out


def gate_bucket(ledger: dict, mut_id) -> str:
    """mutation id 落在 _gate 的哪个桶里：autonomous / halt / noop / unknown。"""
    gate = ledger.get("_gate") or {}
    if mut_id in (gate.get("autonomous") or []):
        return "autonomous"
    for h in (gate.get("halt") or []):
        hid = h.get("id") if isinstance(h, dict) else h
        if hid == mut_id:
            return "halt"
    for n in (gate.get("noop") or []):
        nid = n.get("id") if isinstance(n, dict) else n
        if nid == mut_id:
            return "noop"
    return "unknown"


def load_ledger(root: Path, run_id: str, task_id: str):
    p = root / run_id / f"{task_id}_ledger.json"
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def prf(tp: int, fp: int, fn: int) -> dict:
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3)}


def ratio(ok: int, total: int):
    return round(ok / total, 3) if total else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    ap.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER_ROOT)
    ap.add_argument("--out", type=Path, help="报告 JSON 输出路径")
    args = ap.parse_args()

    with open(args.golden, "r", encoding="utf-8") as f:
        golden = json.load(f)

    tp = fp = fn = 0
    t_tp = t_fp = t_fn = 0
    dir_ok = dir_tot = 0
    attr_ok = attr_tot = 0
    gate_ok = gate_tot = 0
    gate_by_want = {"autonomous": [0, 0], "halt": [0, 0]}
    term_hit = term_tot = 0
    per_case = []
    neg_total = neg_correct = 0
    fail_total = fail_hit = 0
    missing = []

    for case in golden["cases"]:
        run_id, task_id = case["run_id"], case["task_id"]
        ledger = load_ledger(args.ledger_root, run_id, task_id)
        if ledger is None:
            # 缺失污染清单显式排除，不按全漏检计（旧口径的缺陷之一）。
            missing.append(f"{run_id}/{task_id}")
            per_case.append({"case": f"{run_id}/{task_id}", "status": "missing"})
            continue

        preds = [m for m in ledger.get("mutations", [])
                 if (m.get("attribution") or "this_task") in IN_SCOPE_ATTRIBUTIONS]
        n_carried_skipped = len(ledger.get("mutations", [])) - len(preds)
        golds = case["mutations"]
        matched = match_pairs(preds, golds)
        matched_g = {gi for gi, _ in matched}
        matched_p = {pi for _, pi in matched}
        tp += len(matched)
        fn += len(golds) - len(matched)
        fp += len(preds) - len(matched)

        # type-only 对照：同样范围，只比 type，隔离"实体命名不一致"误差
        t_matched = match_pairs(preds, golds, strict=False)
        t_tp += len(t_matched)
        t_fn += len(golds) - len(t_matched)
        t_fp += len(preds) - len(t_matched)

        n_dir_bad = n_attr_bad = 0
        n_gate_bad = 0
        for gi, pi in matched:
            gm, pm = golds[gi], preds[pi]
            ac = attribute_correct(pm, gm)
            if "direction_ok" in ac:
                dir_tot += 1
                if ac["direction_ok"]:
                    dir_ok += 1
                else:
                    n_dir_bad += 1
            if "attribution_ok" in ac:
                attr_tot += 1
                if ac["attribution_ok"]:
                    attr_ok += 1
                else:
                    n_attr_bad += 1
            if gm.get("expect_gate"):
                gate_tot += 1
                want = gm["expect_gate"]
                got = gate_bucket(ledger, pm.get("id"))
                bucket = gate_by_want.setdefault(want, [0, 0])
                bucket[1] += 1
                if got == want:
                    gate_ok += 1
                    bucket[0] += 1
                else:
                    n_gate_bad += 1

        # 搜索词覆盖
        pred_terms = [norm(t) for t in ledger.get("search_terms", [])]
        for term in case.get("search_terms_any", []):
            term_tot += 1
            if any(norm(term) in pt for pt in pred_terms):
                term_hit += 1

        # 反例（金标为空）
        if not golds:
            neg_total += 1
            if not preds:
                neg_correct += 1

        # 失败但确有变更的 case（取代 hard_case）：全部金标条目命中才算覆盖
        if not case.get("judged_success") and golds:
            fail_total += 1
            if len(matched_g) == len(golds):
                fail_hit += 1

        per_case.append({
            "case": f"{run_id}/{task_id}",
            "tp": len(matched_g), "fp": len(preds) - len(matched_p),
            "fn": len(golds) - len(matched_g),
            "n_direction_bad": n_dir_bad, "n_attribution_bad": n_attr_bad,
            "n_gate_bad": n_gate_bad,
            "n_pred_terms": len(pred_terms),
            "n_carried_skipped": n_carried_skipped,
            "failed_but_polluted": (not case.get("judged_success")) and bool(golds),
        })

    report = {
        "schema": "score-report/v1",
        "golden_schema": golden.get("schema", "golden?"),
        "n_cases": len(golden["cases"]),
        "n_scored": len(golden["cases"]) - len(missing),
        "n_gold_mutations": sum(len(c["mutations"]) for c in golden["cases"]),
        "detection_micro": prf(tp, fp, fn),
        "detection_micro_type_only": prf(t_tp, t_fp, t_fn),
        "attribute_accuracy": {
            "direction_accuracy": ratio(dir_ok, dir_tot),
            "attribution_accuracy": ratio(attr_ok, attr_tot),
            "n_pairs": attr_tot,
        },
        "gate_accuracy": {
            "overall": ratio(gate_ok, gate_tot),
            "by_expect": {k: ratio(v[0], v[1]) for k, v in gate_by_want.items() if v[1]},
            "n_scored": gate_tot,
        },
        "search_term_recall": ratio(term_hit, term_tot),
        "negative_case_specificity": ratio(neg_correct, neg_total),
        "failed_case_detection_recall": ratio(fail_hit, fail_total),
        "n_carried_over_skipped": sum(
            c.get("n_carried_skipped", 0) for c in per_case),
        "excluded_missing_cases": missing,
        "per_case": per_case,
    }

    print("=" * 64)
    print(f"Mutation inference score ({report['golden_schema']})")
    print("=" * 64)
    m = report["detection_micro"]
    print(f"detection micro  P={m['precision']:.3f} R={m['recall']:.3f} "
          f"F1={m['f1']:.3f}  (tp={m['tp']} fp={m['fp']} fn={m['fn']})")
    t = report["detection_micro_type_only"]
    print(f"  ↳ type-only 对照  P={t['precision']:.3f} R={t['recall']:.3f} "
          f"F1={t['f1']:.3f}  (tp={t['tp']} fp={t['fp']} fn={t['fn']})")
    aa = report["attribute_accuracy"]
    print(f"direction accuracy           : {aa['direction_accuracy']}  "
          f"(on {aa['n_pairs']} matched pairs)")
    print(f"attribution accuracy         : {aa['attribution_accuracy']}")
    print(f"gate decision accuracy       : {report['gate_accuracy']['overall']}  "
          f"by expect={report['gate_accuracy']['by_expect']}")
    print(f"search term recall           : {report['search_term_recall']}")
    print(f"negative-case specificity    : {report['negative_case_specificity']}")
    print(f"failed-case detection recall : {report['failed_case_detection_recall']}")
    print(f"carried-over residue skipped : {report['n_carried_over_skipped']} "
          f"(out of detection scope)")
    if missing:
        print(f"⚠ [FATAL] 缺失污染清单 {len(missing)} 条，已排除出所有分母（非全漏检）: "
              f"{', '.join(missing)}")
    print("-" * 64)
    for c in per_case:
        if c.get("status") == "missing":
            print(f"  {c['case']:<32} MISSING (excluded)")
        else:
            tag = " FAIL-W-POLLUTION" if c["failed_but_polluted"] else ""
            extra = ""
            if c["n_direction_bad"] or c["n_attribution_bad"] or c["n_gate_bad"]:
                extra = (f"  attr_err[dir={c['n_direction_bad']}"
                         f" attr={c['n_attribution_bad']} gate={c['n_gate_bad']}]")
            print(f"  {c['case']:<32} tp={c['tp']} fp={c['fp']} fn={c['fn']}{tag}{extra}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n报告已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
