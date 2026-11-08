# -*- coding: utf-8 -*-
"""运行追踪：事件流 + 资源采样。

事件写入 JSONL（每行一条），看板与事后复盘共用同一份数据：
    output/agent/trace.jsonl

资源采样走 psutil + nvidia-smi；GPU 查询有 2 秒缓存，避免拖慢主循环。
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

import psutil


def _gpu() -> dict:
    """返回 {vram_used, vram_total, util}（MB / %）。无 NVIDIA 卡时为空。"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3)
        line = out.stdout.strip().splitlines()[0]
        used, total, util = [int(x.strip()) for x in line.split(",")]
        return {"vram_used": used, "vram_total": total, "gpu_util": util}
    except Exception:
        return {}


_gpu_cache: dict = {"ts": 0.0, "data": {}}


def sample_resources() -> dict:
    now = time.time()
    if now - _gpu_cache["ts"] > 2:
        _gpu_cache["data"] = _gpu()
        _gpu_cache["ts"] = now
    vm = psutil.virtual_memory()
    data = {
        "cpu": psutil.cpu_percent(interval=None),
        "ram_used": round(vm.used / 1073741824, 2),
        "ram_total": round(vm.total / 1073741824, 2),
        "ram_percent": vm.percent,
        "ts": round(now, 3),
    }
    data.update(_gpu_cache["data"])
    return data


class Trace:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        # 单文件超过 5MB 时轮转，避免无限增长
        if path.exists() and path.stat().st_size > 5 * 1024 * 1024:
            path.replace(path.with_suffix(".jsonl.1"))
        self.path = path
        self.run_id = ""
        self._lock = threading.Lock()

    def start(self, run_id: str, task: str, plan: dict | None = None,
              session_id: str = "") -> None:
        self.run_id = run_id
        self.event("run_start", task=task, plan=plan, session_id=session_id)

    def event(self, kind: str, **payload) -> None:
        record = {"ts": round(time.time(), 3), "run": self.run_id, "kind": kind}
        record.update(payload)
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    # ------------------------------------------------------------------ 读取
    def events(self, run_id: str | None = None, limit: int = 200) -> list[dict]:
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        records = []
        for line in lines[-limit:]:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if run_id and record.get("run") != run_id:
                continue
            records.append(record)
        return records

    def latest_run(self) -> str:
        """返回文件中最后一个 run id。"""
        if not self.path.exists():
            return ""
        with self._lock:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("kind") == "run_start":
                return record.get("run", "")
        return ""
