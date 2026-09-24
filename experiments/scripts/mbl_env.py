# -*- coding: utf-8 -*-
"""共用的小工具：让"直连 API 的诊断脚本"自己找到 API key。

为什么需要
==========
`mobile.env.ps1` 里用 `$env:MBL_API_KEY = '...'` 设置 key，而 `run_mbl.ps1` / `pilot.ps1`
会 dot-source 它。但这两个诊断脚本（`mbl_api_probe.py`、`mbl_coord_convention_check.py`）
是**纯标准库、直连托管 API**的，不经过 PowerShell —— 所以在新开的 cmd 窗口里直接跑
`%PY% %S%\mbl_coord_convention_check.py ...` 会直接报：

    ❌ 未设置 MBL_API_KEY

实测踩过（2026-09-24）：README 的「全量实验一键流程」块里第 0 段就会撞上这个，
自检能过、坐标检测却挂掉。与其要求用户在每个新窗口手动 `set`（还要把 key 抄一遍、
等于把密钥又复制到一个地方），不如让脚本自己去仓库根的 `mobile.env.ps1` 里读。

查找顺序
========
1. 环境变量 `MBL_API_KEY`（显式设置优先，便于临时换 key）
2. 从本文件位置往上找 `mobile.env.ps1`（脚本在 <repo>/experiments/scripts/ 下）
3. 都没找到 → 返回 None，调用方自己给提示
"""

from __future__ import annotations

import os
import re

_FILE = "mobile.env.ps1"
# $env:MBL_API_KEY = 'sk-...'      （PS 里字符串可以是单引号或双引号）
_KEY_RE = re.compile(r"\$env:MBL_API_KEY\s*=\s*['\"]([^'\"]+)['\"]")


def _candidates() -> list[str]:
    """可能的 mobile.env.ps1 位置：从脚本目录逐级往上找。"""
    here = os.path.dirname(os.path.abspath(__file__))
    out: list[str] = []
    cur = here
    for _ in range(6):
        out.append(os.path.join(cur, _FILE))
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    out.append(os.path.join(os.getcwd(), _FILE))
    return out


def find_env_file() -> str | None:
    for p in _candidates():
        if os.path.isfile(p):
            return p
    return None


def api_key() -> str | None:
    """返回 API key；优先环境变量，其次 mobile.env.ps1。找不到返回 None。"""
    env = (os.environ.get("MBL_API_KEY") or "").strip()
    if env:
        return env
    path = find_env_file()
    if not path:
        return None
    try:
        with open(path, encoding="utf-8-sig") as fh:
            for line in fh:
                if line.lstrip().startswith("#"):
                    continue
                m = _KEY_RE.search(line)
                if m:
                    return m.group(1).strip()
    except OSError:
        return None
    return None


def require_api_key() -> str:
    """拿到 key，拿不到就抛出带操作指引的异常。"""
    key = api_key()
    if key:
        return key
    # 注意：Python 3.10 的 f-string 表达式里不能出现反斜杠，
    # 所以带 `\` 的默认路径先在 f-string 外面拼好（这里踩过一次 SyntaxError）。
    envf = find_env_file() or ("<repo root>" + os.sep + _FILE)
    raise SystemExit(
        "❌ 找不到 MBL_API_KEY。两种办法：\n"
        "   1) 在 cmd 里临时设置： set MBL_API_KEY=sk-你的key\n"
        "   2) 填进配置文件（推荐，一次就好）：\n"
        f"      {envf}  里的  $env:MBL_API_KEY = '...'  那一行"
    )


if __name__ == "__main__":  # 手工排查用：python mbl_env.py
    p = find_env_file()
    k = api_key()
    print(f"mobile.env.ps1 : {p or '（没找到）'}")
    print(f"MBL_API_KEY    : {'已找到 (' + k[:7] + '…, len=' + str(len(k)) + ')' if k else '未找到'}")
