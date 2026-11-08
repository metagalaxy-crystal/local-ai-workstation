# -*- coding: utf-8 -*-
"""定时任务调度器：标准库实现，零外部依赖。

支持三种触发方式：
- once    : 一次性，指定 ISO 时间戳（如 2026-10-23T15:30:00）
- interval: 周期性，每隔 N 秒
- daily   : 每天固定时间（HH:MM）

任务持久化到 JSON 文件，调度线程每 30 秒检查一次到期任务。
执行动作由调用方注入（通常是 AgentLoop.run），避免循环导入。
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable


@dataclass
class ScheduledTask:
    id: str
    task: str
    schedule_type: str          # once | interval | daily
    run_at: str = ""            # ISO 时间戳（once）
    interval_seconds: int = 0   # interval
    daily_time: str = ""        # HH:MM（daily）
    enabled: bool = True
    created_at: str = ""
    last_run: str = ""
    run_count: int = 0

    def next_run(self, now: datetime) -> datetime | None:
        if not self.enabled:
            return None
        if self.schedule_type == "once":
            if self.last_run:
                return None
            return datetime.fromisoformat(self.run_at)
        if self.schedule_type == "interval":
            base = datetime.fromisoformat(self.last_run) if self.last_run else datetime.fromisoformat(self.created_at)
            return base + timedelta(seconds=self.interval_seconds)
        if self.schedule_type == "daily":
            hh, mm = map(int, self.daily_time.split(":"))
            candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            # 如果今天已经跑过且时间已过，跳过
            if self.last_run:
                last = datetime.fromisoformat(self.last_run)
                if last.date() == now.date() and last.time() >= candidate.time():
                    candidate += timedelta(days=1)
            return candidate
        return None

    def due(self, now: datetime) -> bool:
        nxt = self.next_run(now)
        return nxt is not None and nxt <= now


class Scheduler:
    """任务存储 + 到期检测。"""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._tasks: dict[str, ScheduledTask] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for item in data:
                t = ScheduledTask(**item)
                self._tasks[t.id] = t
        except Exception:
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(t) for t in self._tasks.values()]
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, task: str, schedule_type: str,
            run_at: str = "", interval_seconds: int = 0, daily_time: str = "") -> ScheduledTask:
        tid = uuid.uuid4().hex[:8]
        now = datetime.now().isoformat()
        t = ScheduledTask(
            id=tid, task=task, schedule_type=schedule_type,
            run_at=run_at, interval_seconds=interval_seconds, daily_time=daily_time,
            created_at=now,
        )
        with self._lock:
            self._tasks[tid] = t
            self._save()
        return t

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            t = self._tasks.get(task_id)
            if t:
                t.enabled = False
                self._save()
                return True
            return False

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(t) for t in sorted(self._tasks.values(), key=lambda x: x.created_at)]

    def due(self) -> list[ScheduledTask]:
        now = datetime.now()
        with self._lock:
            return [t for t in self._tasks.values() if t.due(now)]

    def mark_run(self, task_id: str) -> None:
        with self._lock:
            t = self._tasks.get(task_id)
            if t:
                t.last_run = datetime.now().isoformat()
                t.run_count += 1
                self._save()


# ------------------------------------------------------------------ 后台执行线程
class SchedulerRunner:
    """在后台线程中定期检查并执行到期任务。"""

    def __init__(self, scheduler: Scheduler, execute: Callable[[str], str],
                 interval: float = 30.0):
        self.scheduler = scheduler
        self.execute = execute      # 输入 task 文本，返回执行结果摘要
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.logs: list[dict[str, str]] = []
        self._log_lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            for task in self.scheduler.due():
                self._run_task(task)
            self._stop.wait(self.interval)

    def _run_task(self, task: ScheduledTask) -> None:
        started = time.strftime("%H:%M:%S")
        try:
            result = self.execute(task.task)
            status = "ok"
        except Exception as exc:
            result = f"{type(exc).__name__}: {exc}"
            status = "error"
        self.scheduler.mark_run(task.id)
        with self._log_lock:
            self.logs.append({
                "time": started,
                "task_id": task.id,
                "task": task.task[:80],
                "status": status,
                "result": result[:200],
            })
            if len(self.logs) > 100:
                self.logs = self.logs[-100:]

    def recent_logs(self, limit: int = 20) -> list[dict[str, str]]:
        with self._log_lock:
            return self.logs[-limit:]
