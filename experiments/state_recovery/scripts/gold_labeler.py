#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gold_labeler.py —— 人工金标标注工具（本地网页，纯标准库，不调 API/不连手机）。

启动::

    mobile\\Scripts\\python.exe experiments\\state_recovery\\scripts\\gold_labeler.py
    # 浏览器打开 http://127.0.0.1:8931

数据：
  - 证据：third_party/mobilebench-ol-main/results/<run>/<task>/（trajectory/step_*.png/xml）
  - CSV：third_party/mobilebench-ol-main/data/base_canonical.csv
  - AI 推断污染清单（盲审对答案用）：experiments/state_recovery/eval/ai_contamination_list.json
产出：
  - 标注元数据（逐条即时落盘）：experiments/state_recovery/eval/annotation_metadata.jsonl
  - 最终金标导出（页面按钮，喂下游评分）：experiments/state_recovery/eval/golden_labels.json
"""

from __future__ import annotations

import csv
import json
import os
import sys
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
RESULTS = REPO / "third_party" / "mobilebench-ol-main" / "results"
CSV_PATH = REPO / "third_party" / "mobilebench-ol-main" / "data" / "base_canonical.csv"
EVAL_DIR = HERE.parent / "eval"
LABELS_PATH = EVAL_DIR / "annotation_metadata.jsonl"
AI_DRAFT_PATH = EVAL_DIR / "ai_contamination_list.json"
APP_HTML = HERE / "gold_labeler_app.html"
EXPORT_PATH = EVAL_DIR / "golden_labels.json"

RUNS = ("base_canonical", "q2_A_1", "s3_A_1")
HOST, PORT = "127.0.0.1", 8931

RESET_ORDER = {"Need": 0, "Search": 1, "Unable": 2, "": 3}
_LOCK = threading.Lock()


# ---------------------------------------------------------------- 数据装载

def load_csv() -> dict:
    out = {}
    with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        level_key = next((k for k in (reader.fieldnames or [])
                          if k and k.startswith("level")), "")
        for r in reader:
            ident = (r.get("task_identifier") or "").strip()
            if ident:
                r["_level"] = (r.get(level_key) or "").strip()
                out[ident] = r
    return out


def load_ai_draft() -> dict:
    if not AI_DRAFT_PATH.exists():
        return {}
    d = json.loads(AI_DRAFT_PATH.read_text(encoding="utf-8"))
    return {(c["run_id"], c["task_id"]): c for c in d.get("cases", [])}


def load_human() -> dict:
    out = {}
    if not LABELS_PATH.exists():
        return out
    for line in LABELS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        c = json.loads(line)
        out[(c["run_id"], c["task_id"])] = c
    return out


def traj_dir(run_id: str, task_id: str) -> Path | None:
    p = (RESULTS / run_id / task_id).resolve()
    try:
        p.relative_to(RESULTS.resolve())
    except ValueError:
        return None
    return p if (p / "trajectory.json").exists() else None


def build_queue(csv_rows: dict, ai_draft: dict, human: dict) -> list[dict]:
    review, fresh = [], []
    for run_id in RUNS:
        run_dir = RESULTS / run_id
        if not run_dir.is_dir():
            continue
        for tdir in sorted(p for p in run_dir.iterdir() if p.is_dir()):
            if not (tdir / "trajectory.json").exists():
                continue
            tid = tdir.name
            row = csv_rows.get(tid, {})
            h = human.get((run_id, tid))
            # needs_rework：旧版前端（判断依据未强制 / 实体名称可空）遗留的草稿，
            # 不算完成态，需要在当前版本里重新标注一遍；重新提交时标记被清除。
            rework = bool(h and h.get("needs_rework"))
            item = {
                "run_id": run_id, "task_id": tid,
                "app": row.get("task_app_CHN", ""),
                "goal": row.get("goal", ""),
                "level": row.get("_level", ""),
                "golden_steps": row.get("golden_steps", ""),
                "reset": (row.get("Reset") or "").strip(),
                "has_keynodes": bool((row.get("key_nodes") or "").strip()),
                "has_png": any(tdir.glob("step_*.png")),
                "labeled": h is not None and not rework,
                "needs_rework": rework,
                "rework_reasons": (h or {}).get("rework_reasons", []),
                "n_mut": len(h.get("mutations", [])) if h else 0,
                "certainty": (h or {}).get("certainty", ""),
            }
            if (run_id, tid) in ai_draft:
                item["group"] = "review"
                review.append(item)
            else:
                item["group"] = "fresh"
                fresh.append(item)
    review.sort(key=lambda x: (x["run_id"], x["task_id"]))
    fresh.sort(key=lambda x: (RESET_ORDER.get(x["reset"], 9), x["task_id"]))
    return review + fresh


def smart_nodes(xml_text: str) -> list[dict]:
    """从 uiautomator dump 中抽标注关心的节点；解析失败返回空。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out, seen = [], set()
    for n in root.iter("node"):
        a = n.attrib
        text = (a.get("text") or "").strip()
        rid = (a.get("resource-id") or "").strip()
        cls = (a.get("class") or "")
        checkable = a.get("checkable") == "true"
        checked = a.get("checked")
        selected = a.get("selected")
        clickable = a.get("clickable") == "true"
        interesting = (
            checkable or checked not in (None, "false")
            or selected == "true"
            or any(k in cls for k in ("Switch", "CheckBox", "RadioButton", "Button",
                                      "CheckedTextView", "ToggleButton"))
            or (text and (clickable or rid))
        )
        if not interesting:
            continue
        key = (text, rid, cls, a.get("bounds"), checked, selected)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "text": text, "resource_id": rid, "class": cls.split(".")[-1],
            "checkable": checkable,
            "checked": checked if checked is not None else None,
            "selected": selected if selected is not None else None,
            "clickable": clickable, "bounds": a.get("bounds", ""),
        })
    return out[:200]


def case_payload(run_id: str, task_id: str, csv_rows: dict) -> dict | None:
    tdir = traj_dir(run_id, task_id)
    if tdir is None:
        return None
    traj = json.loads((tdir / "trajectory.json").read_text(encoding="utf-8"))
    actions = []
    for i, a in enumerate(traj.get("history_action", [])):
        actions.append({
            "step": i + 1, "action": a.get("action"),
            "params": a.get("params", {}),
        })
    # 步骤以轨迹动作为准（0=启动首页，1..n=每个动作）；截图/XML 是否存在单独标记。
    # 链式 run（q2/s3 的 QQ 任务）执行时未保存截图与 XML，但仍可凭 Action/Thought 标注。
    n_steps = len(actions)
    steps = []
    for n in range(n_steps + 1):
        steps.append({
            "n": n,
            "has_png": (tdir / f"step_{n}.png").exists(),
            "has_xml": (tdir / f"step_{n}.xml").exists(),
        })
    row = csv_rows.get(task_id, {})
    return {
        "run_id": run_id, "task_id": task_id,
        "goal": traj.get("task_goal") or row.get("goal", ""),
        "success": traj.get("success"),
        "summary": traj.get("summary", []),
        "actions": actions,
        "responses": traj.get("history_response", []),
        "steps": steps,
        "has_any_png": any(s["has_png"] for s in steps),
        "has_any_xml": any(s["has_xml"] for s in steps),
        "csv": {
            "app": row.get("task_app_CHN", ""),
            "pkg": row.get("adb_home_page", ""),
            "feature": row.get("功能点", ""),
            "level": row.get("_level", ""),
            "golden_steps": row.get("golden_steps", ""),
            "reset": (row.get("Reset") or "").strip(),
            "key_nodes": row.get("key_nodes", ""),
        },
    }


def save_label(label: dict) -> None:
    key = (label["run_id"], label["task_id"])
    # 重新提交即视为复标完成：由服务端确定性地摘除待修改标记，
    # 不依赖前端是否记得清理（前端 hydrate 会把旧标记带进表单）。
    label.pop("needs_rework", None)
    label.pop("rework_reasons", None)
    label.pop("rework_flagged_at", None)
    with _LOCK:
        human = load_human()
        human[key] = label
        lines = [json.dumps(c, ensure_ascii=False) for c in
                 (human[k] for k in sorted(human, key=lambda x: (x[0], x[1])))]
        tmp = LABELS_PATH.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, LABELS_PATH)


def export_golden() -> int:
    human = load_human()
    cases = []
    n_rework = 0
    for (run_id, tid), c in sorted(human.items(), key=lambda x: (x[0][0], x[0][1])):
        # 待修改的旧版草稿不得作为金标导出，避免污染下游评分
        if c.get("needs_rework"):
            n_rework += 1
            continue
        terms = list(c.get("search_terms_any", []))
        muts = []
        for m in c.get("mutations", []):
            m = dict(m)
            # 搜索历史硬口径防御性归一（兼容修复前保存的记录）
            if m.get("type") == "search_history":
                m["direction"] = "created"
                m["entity_kind"] = "search"
                nm = (m.get("name") or "").strip()
                if nm and nm not in terms:
                    terms.append(nm)
            gm = {
                "type": m["type"],
                "entity_kind": m.get("entity_kind", "other"),
            }
            if m.get("name"):
                gm["name_contains"] = m["name"]
            if m.get("identifier"):
                gm["identifier"] = m["identifier"]
            if m.get("direction"):
                gm["direction"] = m["direction"]
            if m.get("attribution"):
                gm["attribution"] = m["attribution"]
            if m.get("carried_over_from_task"):
                gm["carried_over_from_task"] = m["carried_over_from_task"]
            if m.get("expect_gate"):
                gm["expect_gate"] = m["expect_gate"]
            if m.get("evidence_steps"):
                gm["evidence_steps"] = m["evidence_steps"]
            muts.append(gm)
        # 有搜索词但缺对应 search_history 条目（修复前的旧记录）→ 自动补齐
        have_names = {g.get("name_contains") for g in muts
                      if g["type"] == "search_history"}
        for t in terms:
            if t and t not in have_names:
                muts.append({
                    "type": "search_history", "entity_kind": "search",
                    "name_contains": t, "direction": "created",
                    "attribution": "this_task",
                })
        cases.append({
            "run_id": run_id, "task_id": tid,
            "task_goal": c.get("task_goal", ""),
            "judged_success": c.get("judged_success"),
            "mutations": muts,
            "search_terms_any": terms,
            "human_verified": True,
            "certainty": c.get("certainty", ""),
            "evidence_basis": c.get("evidence_basis", []),
            "labeler": c.get("labeler", "human"),
            "labeled_at": c.get("labeled_at", ""),
            "human_notes": c.get("notes", ""),
        })
    doc = {
        "schema": "golden-labels/v1",
        "note": "人工盲审金标：标注者只看轨迹/截图/XML 证据，提交后才与 AI 草稿对答案。",
        "n_cases": len(cases),
        "n_rework": n_rework,
        "cases": cases,
    }
    EXPORT_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return len(cases)


# ---------------------------------------------------------------- HTTP

CSV_ROWS = load_csv()
AI_DRAFT = load_ai_draft()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _qs(self) -> dict:
        q = urllib.parse.urlparse(self.path).query
        return {k: v[0] for k, v in urllib.parse.parse_qs(q).items()}

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/" or path == "/index.html":
                self._send(200, APP_HTML.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/queue":
                human = load_human()
                self._json(build_queue(CSV_ROWS, AI_DRAFT, human))
            elif path == "/api/case":
                q = self._qs()
                p = case_payload(q.get("run", ""), q.get("id", ""), CSV_ROWS)
                self._json(p or {}, 200 if p is not None else 404)
            elif path == "/api/xml":
                q = self._qs()
                tdir = traj_dir(q.get("run", ""), q.get("id", ""))
                if tdir is None:
                    self._json({"error": "bad case"}, 404); return
                xp = tdir / f"step_{q.get('step')}.xml"
                xp = xp.resolve()
                xp.relative_to(RESULTS.resolve())
                if not xp.exists():
                    self._json({"raw": "", "nodes": []}); return
                text = xp.read_text(encoding="utf-8", errors="replace")
                self._json({"raw": text, "nodes": smart_nodes(text)})
            elif path == "/img":
                q = self._qs()
                tdir = traj_dir(q.get("run", ""), q.get("id", ""))
                if tdir is None:
                    self.send_error(404); return
                fp = (tdir / urllib.parse.unquote(q.get("file", ""))).resolve()
                fp.relative_to(RESULTS.resolve())
                if not fp.exists() or fp.suffix.lower() != ".png":
                    self.send_error(404); return
                data = fp.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                # 轨迹截图为不可变历史产物，允许浏览器缓存，切步不重复下载
                self.send_header("Cache-Control", "private, max-age=3600")
                self.end_headers()
                self.wfile.write(data)
            elif path == "/api/aidraft":
                q = self._qs()
                c = AI_DRAFT.get((q.get("run", ""), q.get("id", "")))
                self._json(c or None)
            elif path == "/api/human":
                q = self._qs()
                self._json(load_human().get((q.get("run", ""), q.get("id", ""))))
            elif path == "/api/progress":
                human = load_human()
                review_done = sum(1 for k, c in human.items()
                                  if k in AI_DRAFT and not c.get("needs_rework"))
                self._json({
                    "labeled": sum(1 for c in human.values()
                                   if not c.get("needs_rework")),
                    "rework": sum(1 for c in human.values() if c.get("needs_rework")),
                    "review_total": len(AI_DRAFT),
                    "review_done": review_done,
                })
            else:
                self.send_error(404)
        except (ValueError, OSError) as e:
            self._json({"error": str(e)}, 400)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            if path == "/api/save":
                if not body.get("task_id") or not body.get("run_id"):
                    self._json({"error": "missing id"}, 400); return
                save_label(body)
                self._json({"ok": True})
            elif path == "/api/export":
                self._json({"ok": True, "n": export_golden(),
                            "path": str(EXPORT_PATH)})
            else:
                self.send_error(404)
        except (ValueError, KeyError) as e:
            self._json({"error": str(e)}, 400)


def main() -> int:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"金标标注工具已启动: http://{HOST}:{PORT}")
    print(f"标注结果实时写入: {LABELS_PATH}")
    print("Ctrl+C 停止。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
