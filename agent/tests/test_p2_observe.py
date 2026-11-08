# -*- coding: utf-8 -*-
"""P2a 观测层单测：规划解析、事件追踪、看板快照。"""
from __future__ import annotations

import json
import socket
import tempfile
import unittest
import urllib.request
from pathlib import Path

from agent.monitor import Monitor
from agent.planner import Plan, make_plan, parse_plan
from agent.trace import Trace, sample_resources


class PlanParseTests(unittest.TestCase):
    def test_valid_json(self) -> None:
        raw = ('```json\n{"approach":"本地知识库","reason":"已有资料",'
               '"est_cost":"low","steps":[{"goal":"检索资料","tool":"kb_search"},'
               '{"goal":"汇总并给出结论","tool":"none"}]}\n```')
        plan = parse_plan(raw, "任务")
        self.assertEqual(plan.approach, "本地知识库")
        self.assertEqual(plan.est_cost, "low")
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].tool, "kb_search")

    def test_invalid_json_falls_back(self) -> None:
        plan = parse_plan("这里没有 JSON", "原始任务")
        self.assertEqual(plan.approach, "direct")
        self.assertEqual(plan.steps[0].goal, "原始任务")

    def test_empty_steps_falls_back(self) -> None:
        plan = parse_plan('{"approach":"x","steps":[]}', "t")
        self.assertEqual(plan.approach, "direct")

    def test_step_cap(self) -> None:
        steps = [{"goal": f"g{i}", "tool": "none"} for i in range(10)]
        plan = parse_plan(json.dumps({"steps": steps}), "t")
        self.assertEqual(len(plan.steps), 6)

    def test_make_plan_llm_error(self) -> None:
        class Broken:
            model = "fake"

            def chat(self, *a, **k):
                raise RuntimeError("boom")
                # 非 LLMError 不应被吞掉，此处仅确认不返回 None
        with self.assertRaises(RuntimeError):
            make_plan(Broken(), "t")
        self.assertEqual(Plan.fallback("t").est_cost, "unknown")


class TraceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "trace.jsonl"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_event_roundtrip(self) -> None:
        trace = Trace(self.path)
        trace.start("r1", "测试任务", {"steps": [{"goal": "a", "tool": "none"}]})
        trace.event("tool_call", name="read_file", args="{}")
        self.assertEqual(trace.latest_run(), "r1")
        events = trace.events("r1")
        self.assertEqual(events[0]["kind"], "run_start")
        self.assertEqual(events[0]["plan"]["steps"][0]["goal"], "a")
        self.assertEqual(events[1]["name"], "read_file")

    def test_filter_by_run(self) -> None:
        trace = Trace(self.path)
        trace.start("r1", "a")
        trace.start("r2", "b")
        self.assertEqual([e["run"] for e in trace.events("r2")], ["r2"])

    def test_read_missing_file(self) -> None:
        trace = Trace(Path(self._tmp.name) / "none.jsonl")
        self.assertEqual(trace.events("x"), [])
        self.assertEqual(trace.latest_run(), "")

    def test_sample_resources_keys(self) -> None:
        res = sample_resources()
        for key in ("cpu", "ram_used", "ram_total", "ram_percent"):
            self.assertIn(key, res)
        self.assertGreater(res["ram_total"], 0)


class MonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.trace = Trace(root / "trace.jsonl")
        self.trace.start("r9", "看板任务", {"approach": "direct", "est_cost": "low",
                                            "steps": [{"goal": "一步", "tool": "none"}]})
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.monitor = Monitor(self.trace, root, self.port)
        self.assertTrue(self.monitor.start())

    def tearDown(self) -> None:
        self.monitor.stop()
        self._tmp.cleanup()

    def _get(self, path: str) -> bytes:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as resp:
            return resp.read()

    def test_state_snapshot(self) -> None:
        data = json.loads(self._get("/state"))
        self.assertEqual(data["run"], "r9")
        self.assertEqual(data["events"][0]["task"], "看板任务")
        self.assertIn("cpu", data["resources"])
        self.assertIn("preview", data)

    def test_index_page(self) -> None:
        page = self._get("/").decode("utf-8")
        self.assertIn("运行看板", page)
        self.assertIn("/state", page)

    def test_trace_endpoint(self) -> None:
        body = self._get("/trace.jsonl").decode("utf-8")
        self.assertIn('"run_start"', body)


if __name__ == "__main__":
    unittest.main()
