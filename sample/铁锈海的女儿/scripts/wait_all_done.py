#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阻塞等待 ComfyUI 队列所有指定 prompt 完成，完成后自动跑 collect_timebook。

用法:
  uv run python scripts/wait_all_done.py --timeout 14400 --poll 60
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

HOST = "http://127.0.0.1:8188"
ROOT = Path(r"D:\models\sample\铁锈海的女儿")
PROMPT_IDS = [
    # Wan2.2 6 镜头（shot1 重跑中）
    "6fc0d299-4638-46f0-ac40-6ff7dfc3c5a7",  # shot1
    "8b6460be-4c27-46b5-a343-397875257aa2",  # shot2
    "e89dcba8-236e-4831-96dc-f13ab5726533",  # shot3
    "9211a69f-6c89-49b7-853a-12bd04743899",  # shot4
    "33e5a4ab-20dc-4cbf-b479-bfc78f2e338a",  # shot5
    "be402aa7-6618-4f46-aaa7-75daa2a67411",  # shot6
    # MiniMax H3 6 镜头
    "63a32b0f-d4ed-4d97-b130-83aa1d1f26ac",  # shot1
    "67708b1a-983b-492f-a048-1a3c45ee0516",  # shot2
    "c244d90f-3fad-4441-ac37-1b7d94141886",  # shot3
    "07f76911-b7f2-4eab-a891-161f37be18f4",  # shot4
    "e1369254-3979-4372-ac09-ccb347660a7a",  # shot5
    "8e3425d8-3be7-4d2e-a5d9-2574b150c2bb",  # shot6
]


def fetch_history(pid: str) -> dict:
    try:
        with urllib.request.urlopen(f"{HOST}/history/{pid}", timeout=10) as r:
            return json.loads(r.read()).get(pid, {})
    except Exception:
        return {}


def fetch_queue() -> dict:
    try:
        with urllib.request.urlopen(f"{HOST}/queue", timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return {"queue_running": [], "queue_pending": []}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=21600)  # 6h
    ap.add_argument("--poll", type=int, default=60)
    args = ap.parse_args()

    start = time.time()
    log_path = ROOT / "06_compare" / "wait_progress.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_f = log_path.open("a", encoding="utf-8")

    def log(msg: str):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        log_f.write(line + "\n")
        log_f.flush()

    log(f"开始等待 {len(PROMPT_IDS)} 个 prompt 完成。轮询间隔 {args.poll}s，超时 {args.timeout}s")

    last_state = {}
    while True:
        elapsed = time.time() - start
        if elapsed > args.timeout:
            log(f"[TIMEOUT] 已超时 {elapsed:.0f}s，退出")
            return 1
        # 队列状态
        q = fetch_queue()
        n_run = len(q.get("queue_running", []))
        n_pending = len(q.get("queue_pending", []))
        # 历史
        done = 0
        failed = 0
        running = 0
        pending = 0
        for pid in PROMPT_IDS:
            h = fetch_history(pid)
            if not h:
                # 不在 history，说明在 queue
                # 看是不是在跑
                in_running = any(p and len(p) > 1 and p[1] == pid for p in q.get("queue_running", []))
                if in_running:
                    running += 1
                else:
                    pending += 1
                continue
            st = h.get("status", {})
            if st.get("completed"):
                done += 1
            else:
                # 失败
                msgs = st.get("messages", [])
                exc = any(isinstance(m, list) and len(m) >= 2 and isinstance(m[1], dict) and "exception_message" in m[1] for m in msgs)
                if exc:
                    failed += 1
                else:
                    running += 1

        state = (done, failed, running, pending, n_run, n_pending)
        if state != last_state:
            log(f"done={done} failed={failed} running={running} pending={pending} "
                f"(queue: run={n_run} pend={n_pending}) elapsed={elapsed:.0f}s")
            last_state = state

        if done + failed == len(PROMPT_IDS):
            log(f"全部完成: done={done} failed={failed}")
            break
        if running == 0 and pending == 0 and done + failed < len(PROMPT_IDS):
            log(f"[STUCK] 没有运行也没全完成: done={done} failed={failed}")
            # 这种情况可能是某个 prompt 既不在 queue 也不在 history
            # 继续等几次，如果还不变就退出
            time.sleep(args.poll * 5)
            continue
        time.sleep(args.poll)

    log("等待结束。运行 collect_timebook.py 采集时间账本...")
    log_f.close()
    # 跑时间账本采集
    import subprocess
    r = subprocess.run([sys.executable, "scripts/collect_timebook.py"],
                       cwd=str(ROOT), capture_output=True, text=True)
    log2 = log_path.open("a", encoding="utf-8")
    log2.write(r.stdout + "\n" + r.stderr + "\n")
    log2.close()
    print(r.stdout)
    print(r.stderr, file=sys.stderr)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
