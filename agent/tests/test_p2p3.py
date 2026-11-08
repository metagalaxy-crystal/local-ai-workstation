# -*- coding: utf-8 -*-
"""P2 剩余 + P3 单测：定时任务、Web UI、Prometheus 指标。"""
from __future__ import annotations

import json
import socket
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from agent.config import Config
from agent.monitor import Monitor
from agent.scheduler import Scheduler, SchedulerRunner
from agent.tools import build_registry
from agent.trace import Trace
from agent.webui import WebUI


def make_cfg(root: Path) -> Config:
    return Config({
        "llm": {"base_url": "http://127.0.0.1:1/v1"},
        "loop": {"max_rounds": 4, "max_history_chars": 20000, "tool_result_max_chars": 2000},
        "tools": {
            "enabled": ["files", "shell", "sandbox", "search", "browser", "rag", "schedule"],
            "tool_timeout": 20, "retry": 0,
            "allowed_roots": [str(root)],
            "scripts_dir": str(root / "scripts"),
            "shell_whitelist": [], "blocked_patterns": [],
            "search": {"provider": "duckduckgo", "max_results": 5},
            "browser": {"headless": True},
        },
        "rag": {"embed_url": "http://127.0.0.1:1/v1",
                "rerank_url": "http://127.0.0.1:1/rerank",
                "chunk_size": 120, "chunk_overlap": 30, "top_k": 3, "recall_candidates": 10},
        "paths": {"workspace": str(root / "ws"), "db": str(root / "s.db"),
                  "vectors_db": str(root / "v.db"), "output_root": str(root / "out"),
                  "preview": str(root / "preview"), "trace": str(root / "trace.jsonl")},
    }, Path("test-config"))


class SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "tasks.json"
        self.sched = Scheduler(self.path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_add_and_list(self) -> None:
        t = self.sched.add("测试任务", "daily", daily_time="09:00")
        self.assertEqual(t.schedule_type, "daily")
        tasks = self.sched.list()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["daily_time"], "09:00")

    def test_persistence(self) -> None:
        self.sched.add("持久化", "once", run_at="2026-10-24T08:00:00")
        s2 = Scheduler(self.path)
        self.assertEqual(len(s2.list()), 1)

    def test_cancel(self) -> None:
        t = self.sched.add("待取消", "once", run_at="2026-10-24T08:00:00")
        self.assertTrue(self.sched.cancel(t.id))
        self.assertFalse(self.sched.cancel("nonexistent"))

    def test_due_once(self) -> None:
        past = "2020-01-01T00:00:00"
        t = self.sched.add("已过期", "once", run_at=past)
        due = self.sched.due()
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].id, t.id)

    def test_mark_run(self) -> None:
        t = self.sched.add("记录", "once", run_at="2020-01-01T00:00:00")
        self.sched.mark_run(t.id)
        tasks = self.sched.list()
        self.assertEqual(tasks[0]["run_count"], 1)
        self.assertNotEqual(tasks[0]["last_run"], "")

    def test_runner_executes_due(self) -> None:
        executed = []
        runner = SchedulerRunner(self.sched, lambda t: executed.append(t) or "done")
        self.sched.add("立即执行", "once", run_at="2020-01-01T00:00:00")
        runner._run_task(self.sched.due()[0])
        self.assertEqual(executed, ["立即执行"])
        self.assertEqual(len(runner.recent_logs()), 1)
        self.assertEqual(runner.recent_logs()[0]["status"], "ok")


class ScheduleToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = make_cfg(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_tools_registered(self) -> None:
        reg = build_registry(self.cfg)
        for name in ("schedule_task", "list_scheduled", "cancel_scheduled"):
            self.assertIn(name, reg.names())

    def test_schedule_tool(self) -> None:
        reg = build_registry(self.cfg)
        result = reg.call("schedule_task", {
            "task": "每天早上提醒我喝水",
            "schedule_type": "daily",
            "daily_time": "09:00",
        })
        self.assertTrue(result.ok)
        self.assertIn("已安排任务", result.output)

    def test_list_tool(self) -> None:
        reg = build_registry(self.cfg)
        reg.call("schedule_task", {
            "task": "测试", "schedule_type": "interval", "interval_seconds": 3600,
        })
        result = reg.call("list_scheduled", {})
        self.assertTrue(result.ok)
        self.assertIn("每 3600s", result.output)


class MetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.cfg = make_cfg(root)
        self.trace = Trace(root / "trace.jsonl")
        self.trace.start("r1", "测试")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.monitor = Monitor(self.trace, root / "preview", self.port)
        self.assertTrue(self.monitor.start())

    def tearDown(self) -> None:
        self.monitor.stop()
        self._tmp.cleanup()

    def _get(self, path: str) -> bytes:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as resp:
            return resp.read()

    def test_metrics_endpoint(self) -> None:
        body = self._get("/metrics").decode("utf-8")
        self.assertIn("agent_runs_total", body)
        self.assertIn("agent_tokens_total", body)
        self.assertIn("agent_sessions", body)


class WebUITests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.cfg = make_cfg(self.root)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.webui: WebUI | None = None

    def tearDown(self) -> None:
        if self.webui:
            self.webui.stop()
        import gc, time
        gc.collect()
        time.sleep(0.2)
        self._tmp.cleanup()

    def test_page_loads(self) -> None:
        self.webui = WebUI(self.cfg, self.port)
        self.assertTrue(self.webui.start())
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=5) as resp:
            html = resp.read().decode("utf-8")
        self.assertIn("本地模型工作站", html)

    def test_sessions_endpoint(self) -> None:
        self.webui = WebUI(self.cfg, self.port)
        self.assertTrue(self.webui.start())
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/sessions", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertIsInstance(data, list)


if __name__ == "__main__":
    unittest.main()
