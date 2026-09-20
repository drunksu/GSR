#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""顺序敏感（OD flaky）实验用的任务目录。

用途
----
为「顺序执行 vs. 乱序执行」实验提供一份**可复现的任务子集**，并为每个任务标注：

* ``apps``           —— 任务会触达的 app（对应 AndroidWorld ``TaskEval.app_names``）。
* ``role``           —— 该任务对状态的**主要**作用方向：
                        ``write``      写 app 内数据（在 app 快照覆盖范围内）
                        ``read``       只读查询（天然的 victim 候选）
                        ``system_write`` 改系统级设置（**不在** app 快照覆盖范围内）
                        ``fs_write``   改共享文件系统（**不在** app 快照覆盖范围内）
* ``cluster``        —— 同 cluster = 同一状态域，用于构造 "writer -> reader" 对抗顺序。
* ``snapshot_scope`` —— ``in`` = 前序作用被 AndroidWorld 的 app 快照恢复覆盖；
                        ``out`` = 快照覆盖不到，**预测**为污染载体（可证伪假设 H3）。
* ``difficulty``     —— 来自 AndroidWorld 官方 task list，用于分层抽样。

依据
----
任务名、难度、标签取自 AndroidWorld 官方 task list
(https://google-research.github.io/android_world/task_list.html)；
``app_names`` 归属在落地时用 ``--verify-catalog`` 对 registry 做一次校验
（不同版本 app 字符串可能有出入，不要盲信本文件）。

注意：本文件只是**推荐清单**，不是 AndroidWorld 的一部分，
不会影响被测系统的行为。运行 ``python order_runner.py --verify-catalog``
可在装有 android_world 的环境里校验 app 归属。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskSpec:
    name: str
    apps: tuple[str, ...]
    role: str
    cluster: str
    snapshot_scope: str
    difficulty: str = "unknown"
    tags: tuple[str, ...] = ()
    note: str = ""

    @property
    def is_writer(self) -> bool:
        return self.role in ("write", "system_write", "fs_write")

    @property
    def is_reader(self) -> bool:
        return self.role == "read"


def _t(
    name: str,
    apps: tuple[str, ...],
    role: str,
    cluster: str,
    difficulty: str = "unknown",
    tags: tuple[str, ...] = (),
    note: str = "",
) -> TaskSpec:
    scope = "in" if role in ("write", "read") else "out"
    return TaskSpec(name, apps, role, cluster, scope, difficulty, tags, note)


# --------------------------------------------------------------------------
# 推荐实验任务集：26 个任务 / 7 个状态域
#   - 4 个 app 内状态域（markor / expense / calendar / music）：快照可覆盖，
#     是"官方重置是否真的彻底"的审计对象。
#   - 2 个系统 / 文件系统状态域：快照覆盖不到，是预测中的真实污染源。
#   - calendar / tasks 两个域自带 write->read 天然配对。
# --------------------------------------------------------------------------
CATALOG: tuple[TaskSpec, ...] = (
    # ---- cluster: markor (notes on disk, multi-app reachable) -------------
    _t("MarkorCreateNote", ("markor",), "write", "markor", "medium", ("data_entry",)),
    _t("MarkorEditNote", ("markor",), "write", "markor", "easy", ("data_edit",)),
    _t("MarkorAddNoteHeader", ("markor",), "write", "markor", "medium", ("data_entry",)),
    _t("MarkorDeleteNewestNote", ("markor",), "write", "markor", "easy", ("data_edit",)),
    _t("MarkorDeleteAllNotes", ("markor",), "write", "markor", "easy", ("data_edit", "repetition")),
    _t("MarkorMoveNote", ("markor",), "write", "markor", "medium", ("complex_ui_understanding",)),
    _t("MarkorCreateFolder", ("markor",), "write", "markor", "easy", ("data_entry",)),
    # ---- cluster: expense (pro expense) -----------------------------------
    _t("ExpenseAddSingle", ("pro expense",), "write", "expense", "easy", ("data_entry", "search")),
    _t("ExpenseAddMultiple", ("pro expense",), "write", "expense", "medium", ("data_entry",)),
    _t("ExpenseDeleteSingle", ("pro expense",), "write", "expense", "easy", ("screen_reading",)),
    _t("ExpenseDeleteMultiple", ("pro expense",), "write", "expense", "easy", ("data_edit",)),
    _t("ExpenseDeleteDuplicates", ("pro expense",), "write", "expense", "medium", ("data_edit",)),
    _t("ExpenseDeleteDuplicates2", ("pro expense",), "write", "expense", "medium", ("data_edit", "requires_setup")),
    # ---- cluster: calendar (write -> read pairing) ------------------------
    _t("SimpleCalendarAddOneEventTomorrow", ("simple calendar pro",), "write", "calendar", "easy", ("data_entry",)),
    _t("SimpleCalendarAddOneEvent", ("simple calendar pro",), "write", "calendar", "hard", ("data_entry",)),
    _t("SimpleCalendarDeleteEvents", ("simple calendar pro",), "write", "calendar", "easy", ("data_edit",)),
    _t("SimpleCalendarAnyEventsOnDate", ("simple calendar pro",), "read", "calendar", "easy", ("information_retrieval",)),
    _t("SimpleCalendarEventsOnDate", ("simple calendar pro",), "read", "calendar", "medium", ("information_retrieval",)),
    _t("SimpleCalendarNextEvent", ("simple calendar pro",), "read", "calendar", "easy", ("information_retrieval",)),
    _t("SimpleCalendarEventsInTimeRange", ("simple calendar pro",), "read", "calendar", "easy", ("information_retrieval",)),
    # ---- cluster: tasks (read-only app) -----------------------------------
    _t("TasksDueOnDate", ("tasks",), "read", "tasks", "easy", ("search",), "另一 reader 簇，跨 app 污染探针"),
    _t("TasksHighPriorityTasks", ("tasks",), "read", "tasks", "medium", ("information_retrieval",)),
    _t("TasksDueNextWeek", ("tasks",), "read", "tasks", "medium", ("information_retrieval",)),
    # ---- cluster: music ---------------------------------------------------
    _t("RetroCreatePlaylist", ("retro music",), "write", "music", "medium", ("data_entry", "repetition")),
    _t("RetroPlayingQueue", ("retro music",), "write", "music", "easy", ("repetition",)),
    _t("RetroSavePlaylist", ("retro music",), "write", "music", "hard", ("search", "repetition")),
    # ---- cluster: system / filesystem（快照覆盖不到，预测的污染源）--------
    _t("SystemCopyToClipboard", ("settings",), "system_write", "system", "easy", ("data_entry",), "剪贴板跨任务可见"),
    _t("SystemWifiTurnOff", ("settings",), "system_write", "system", "easy", ("screen_reading",), "系统设置不在 app 快照内"),
    _t("SystemBrightnessMax", ("settings",), "system_write", "system", "easy", (), "系统设置不在 app 快照内"),
    _t("FilesMoveFile", ("files",), "fs_write", "filesystem", "medium", ("search",), "共享存储：跨 app 可见"),
    _t("FilesDeleteFile", ("files",), "fs_write", "filesystem", "medium", ("data_edit",), "共享存储：跨 app 可见"),
    _t("SaveCopyOfReceiptTaskEval", ("files",), "fs_write", "filesystem", "hard", ("complex_ui_understanding",), "DCIM->Download 复制"),
    _t("SimpleDrawProCreateDrawing", ("simple draw pro",), "fs_write", "filesystem", "easy", ("data_entry",), "写入 Pictures 目录"),
)


BY_NAME: dict[str, TaskSpec] = {t.name: t for t in CATALOG}


# --------------------------------------------------------------------------
# 任务集分层：主实验（快照内，检验"重置是否彻底"）vs. 扩展（快照外，预测污染）
# --------------------------------------------------------------------------
def select(name: str) -> TaskSpec:
    if name not in BY_NAME:
        raise KeyError(
            f"未知任务 {name!r}。可用任务见 task_catalog.CATALOG（或用 --verify-catalog 与 registry 比对）"
        )
    return BY_NAME[name]


def catalog_as_dicts() -> list[dict[str, Any]]:
    return [dict(vars(t)) for t in CATALOG]


if __name__ == "__main__":  # pragma: no cover - 人工查看
    from collections import Counter

    print(f"任务数: {len(CATALOG)}")
    print("cluster 分布:", dict(Counter(t.cluster for t in CATALOG)))
    print("role    分布:", dict(Counter(t.role for t in CATALOG)))
    print("快照覆盖:", dict(Counter(t.snapshot_scope for t in CATALOG)))
    for t in CATALOG:
        print(f"  {t.name:38s} {t.cluster:11s} {t.role:13s} scope={t.snapshot_scope}")
