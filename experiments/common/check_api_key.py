# -*- coding: utf-8 -*-
"""快速验证 DashScope API key 是否有效。"""
import sys
import json
import urllib.request

sys.path.insert(0, "experiments/common")
import mbl_env

key = mbl_env.api_key()
if not key:
    print("FAIL: 找不到 MBL_API_KEY")
    sys.exit(1)

print("key:", key[:7] + "..." + key[-4:], "len:", len(key))

url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
payload = json.dumps({
    "model": "qwen3-vl-plus",
    "messages": [{"role": "user", "content": "say ok"}],
    "max_tokens": 10,
}).encode()

req = urllib.request.Request(url, data=payload, headers={
    "Authorization": "Bearer " + key,
    "Content-Type": "application/json",
})

try:
    resp = urllib.request.urlopen(req, timeout=30)
    body = resp.read().decode()
    print("OK status:", resp.status)
    print("body:", body[:200])
except urllib.error.HTTPError as e:
    print("FAIL HTTP:", e.code)
    print("body:", e.read().decode()[:300])
except Exception as e:
    print("FAIL:", type(e).__name__, e)
