#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""英文基准批量驱动：对全部本地文本/多模态模型依次执行
「start_server 起服 → bench_universal --lang en 全量 → 杀进程」。

用法：
    python run_en_bench.py                # 全部模型（已跑过的自动跳过）
    python run_en_bench.py qwen35b nanbeige  # 只跑指定 label

断点续跑：若 bench_results/<label>_en/summary.json 已存在则跳过。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent          # scripts/llama_cpp
BENCH = Path(r"D:\models\scripts\strata\bench\bench_universal.py")
RESULTS = Path(r"D:\models\docs\bench_results")
LOG = Path(r"C:\Users\junsheng\AppData\Local\Temp\en_bench_run.log")
PY = sys.executable

# (bench label, 注册表 key, 端口, 是否跳过多模态)
MODELS = [
    ("nanbeige", "nanbeige", 8090, True),
    ("lfm", "lfm", 8091, True),
    ("qwen35b", "qwen36", 8093, False),
    ("qwen25vl", "qwen25vl", 8094, False),
    ("minicpm", "minicpmv", 8095, False),
]


def log(msg: str, fh) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    fh.write(line + "\n")
    fh.flush()


def wait_health(port: int, srv: subprocess.Popen, timeout: int = 600) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if srv.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
                if r.status == 200 and b'"ok"' in r.read():
                    return True
        except Exception:
            pass
        time.sleep(3)
    return False


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    only = set(sys.argv[1:])
    todo = [m for m in MODELS if not only or m[0] in only]
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        log(f"===== 英文基准批量运行：{len(todo)} 款 =====", fh)
        for label, key, port, skip_mm in todo:
            out = RESULTS / f"{label}_en" / "summary.json"
            if out.exists():
                log(f"[{label}] 已有英文结果，跳过", fh)
                continue
            log(f"[{label}] 启动服务（key={key} port={port}）...", fh)
            srv_log = (LOG.parent / f"en_bench_{label}.log").open("w", encoding="utf-8")
            srv = subprocess.Popen(
                [PY, str(HERE / "start_server.py"), key,
                 "--host", "127.0.0.1", "--port", str(port)],
                stdout=srv_log, stderr=subprocess.STDOUT, cwd=str(HERE))
            try:
                if not wait_health(port, srv):
                    log(f"[{label}] ✗ 服务未起来，跳过（见 {srv_log.name}）", fh)
                    continue
                log(f"[{label}] 服务就绪，开始英文全量测试", fh)
                cmd = [PY, str(BENCH), "--preset", label, "--lang", "en"]
                if skip_mm:
                    cmd.append("--skip-mm")
                rc = subprocess.call(cmd, cwd=str(BENCH.parent))
                log(f"[{label}] 测试结束 rc={rc}", fh)
            finally:
                kill_tree(srv.pid)
                srv_log.close()
                time.sleep(8)          # 等显存释放
        log("===== 全部完成 =====", fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
