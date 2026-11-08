#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台监督 ComfyUI 任务完成情况（BGM + int8 批次）。

用法: python scripts/wait_batch.py <prompt_id> [prompt_id ...]
日志: 06_compare/wait_int8.log，全部完成后退出码 0，有失败退出码 2。
"""
from __future__ import annotations
import json
import sys
import time
import urllib.request
from pathlib import Path

HOST = "http://127.0.0.1:8188"
LOG = Path(r"D:\models\sample\铁锈海的女儿\06_compare\wait_int8.log")


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    pids = sys.argv[1:]
    done: dict[str, str] = {}
    start = time.time()
    while len(done) < len(pids):
        time.sleep(30)
        lines = []
        for pid in pids:
            if pid in done:
                continue
            try:
                with urllib.request.urlopen(f"{HOST}/history/{pid}", timeout=10) as r:
                    hist = json.loads(r.read()).get(pid, {})
            except Exception:
                continue
            if not hist:
                continue
            st = hist.get("status", {})
            if st.get("completed"):
                status = st.get("status_str", "?")
                done[pid] = status
                lines.append(f"{pid[:8]} -> {status}")
        if lines:
            log(f"done={len(done)}/{len(pids)} | " + " | ".join(lines))
        elif int(time.time() - start) % 300 == 0:
            log(f"等待中 done={len(done)}/{len(pids)} elapsed={int(time.time()-start)}s")
    failed = [p for p, s in done.items() if s != "success"]
    log(f"全部完成: {len(done)-len(failed)} 成功 / {len(failed)} 失败")
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
