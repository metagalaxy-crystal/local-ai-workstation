#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基准测试：向已启动的 llama-server 发请求，测 tok/s 与显存峰值。

用法:
  uv run python scripts/llama_cpp/bench.py --port 8084
  uv run python scripts/llama_cpp/bench.py --port 8084 --prompt "写一首关于秋天的诗" --n 256
"""
import argparse
import subprocess
import sys
import time

import requests


def gpu_vram_mb() -> tuple[int, int] | None:
    """返回 (已用 MiB, 总量 MiB)。"""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        used, total = r.stdout.strip().split(",")
        return int(used.strip()), int(total.strip())
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="llama-server tok/s 基准")
    ap.add_argument("--port", type=int, default=8084, help="llama-server 端口")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--prompt", default="写一段 Python 快速排序的实现并解释其原理。")
    ap.add_argument("--n", type=int, default=256, help="生成 token 数")
    args = ap.parse_args()

    url = f"http://{args.host}:{args.port}/completion"
    payload = {"prompt": args.prompt, "n_predict": args.n, "stream": False}

    print(f"请求 {url}  (n_predict={args.n})", flush=True)
    before = gpu_vram_mb()
    t0 = time.time()
    try:
        resp = requests.post(url, json=payload, timeout=600)
    except requests.RequestException as e:
        print(f"[FAIL] 连接失败: {e}", file=sys.stderr)
        print("确认 llama-server 已启动（uv run python scripts/llama_cpp/start_server.py nanbeige）。", file=sys.stderr)
        return 1
    dt = time.time() - t0
    after = gpu_vram_mb()

    if resp.status_code != 200:
        print(f"[FAIL] HTTP {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
        return 1

    data = resp.json()
    timings = data.get("timings", {})
    tokens = timings.get("predicted_n", data.get("tokens_predicted", args.n))
    tps_server = timings.get("predicted_per_second")
    tps_local = tokens / dt if dt > 0 else 0

    print("\n=== 基准结果 ===")
    print(f"生成 token 数  : {tokens}")
    print(f"耗时           : {dt:.2f} s")
    if tps_server is not None:
        print(f"速度(server报) : {tps_server:.1f} tok/s")
    print(f"速度(本地测)   : {tps_local:.1f} tok/s")
    if before and after:
        print(f"显存峰值       : {after[0]} MiB / {after[1]} MiB  (推理前 {before[0]} MiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
