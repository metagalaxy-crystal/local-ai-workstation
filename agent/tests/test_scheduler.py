# -*- coding: utf-8 -*-
"""调度内核单测：资源推断、依赖解析、同驻留优先排序、异常不死循环。"""
from __future__ import annotations

import threading
import unittest
from pathlib import Path

from agent.config import Config
from agent.orchestrator import PlannedRun, PlannedRunner
from agent.planner import (RES_COMFY, RES_CPU, RES_LLM, RES_MCP, RES_VOICE,
                           Plan, PlanStep, parse_plan, resource_of_tool)


def make_runner(reorder: bool = True, guard: bool = False) -> PlannedRunner:
    cfg = Config({"scheduler": {"reorder": reorder, "guard": guard}}, Path("test-config"))
    runner = PlannedRunner(cfg, None, None, None, threading.Lock())  # type: ignore[arg-type]
    runner.trace = None
    runner._emit = lambda run, kind, **payload: None  # 单测不发事件、不落库
    return runner


class ResourceMapTests(unittest.TestCase):
    def test_tool_mapping(self) -> None:
        self.assertEqual(resource_of_tool("none"), RES_LLM)
        self.assertEqual(resource_of_tool(""), RES_LLM)
        self.assertEqual(resource_of_tool("generate_image"), RES_COMFY)
        self.assertEqual(resource_of_tool("generate_video"), RES_COMFY)
        self.assertEqual(resource_of_tool("tts_speak"), RES_VOICE)
        self.assertEqual(resource_of_tool("asr_transcribe"), RES_VOICE)
        self.assertEqual(resource_of_tool("mcp_playwright_navigate"), RES_MCP)
        self.assertEqual(resource_of_tool("read_file"), RES_CPU)

    def test_explicit_resource_override(self) -> None:
        self.assertEqual(PlanStep("x", "tts_speak", "comfy", []).resource_key(), RES_COMFY)
        # 未知取值不采信，回落到工具推断
        self.assertEqual(PlanStep("x", "tts_speak", "bogus", []).resource_key(), RES_VOICE)


class ParsePlanTests(unittest.TestCase):
    def test_depends_on_keeps_only_backward_refs(self) -> None:
        raw = ('{"steps":[{"goal":"a","tool":"none"},'
               '{"goal":"b","tool":"generate_image","resource":"comfy",'
               '"depends_on":[0,1,9,"x"]}]}')
        plan = parse_plan(raw, "任务")
        self.assertEqual(plan.steps[1].resource, "comfy")
        self.assertEqual(plan.steps[1].depends_on, [0])

    def test_missing_fields_fall_back(self) -> None:
        plan = parse_plan('{"steps":[{"goal":"写文案","tool":"none"}]}', "任务")
        step = plan.steps[0]
        self.assertEqual(step.resource, "")
        self.assertEqual(step.resource_key(), RES_LLM)
        self.assertEqual(step.depends_on, [])


class ScheduleOrderTests(unittest.TestCase):
    def _order(self, steps: list[PlanStep], reorder: bool = True,
               fail_at: int | None = None) -> list[int]:
        runner = make_runner(reorder)
        run = PlannedRun("run", "sess", "task", "qwen36")
        order: list[int] = []

        def fake_step(run_, llm, step, i, ctx):
            order.append(i)
            if i == fail_at:
                raise RuntimeError("boom")
            return f"out{i}"

        runner._run_step = fake_step  # type: ignore[method-assign]
        runner._exec_steps(run, None, Plan(steps=steps), 0, [], threading.Event())
        return order

    def test_same_resource_steps_are_pulled_together(self) -> None:
        steps = [
            PlanStep("写大纲", "none"),          # 0 gpu_llm
            PlanStep("出图", "generate_image"),  # 1 comfy
            PlanStep("写旁白", "none"),          # 2 gpu_llm，独立
            PlanStep("出图2", "generate_image"),  # 3 comfy
        ]
        self.assertEqual(self._order(steps), [0, 2, 1, 3])

    def test_dependency_blocks_pull_forward(self) -> None:
        steps = [
            PlanStep("写大纲", "none"),
            PlanStep("出图", "generate_image"),
            PlanStep("看图写文案", "none", depends_on=[1]),
            PlanStep("出图2", "generate_image"),
        ]
        self.assertEqual(self._order(steps), [0, 1, 3, 2])

    def test_reorder_off_keeps_plan_order(self) -> None:
        steps = [
            PlanStep("写大纲", "none"),
            PlanStep("出图", "generate_image"),
            PlanStep("写旁白", "none"),
        ]
        self.assertEqual(self._order(steps, reorder=False), [0, 1, 2])

    def test_unresolvable_deps_never_hang(self) -> None:
        steps = [
            PlanStep("a", "none", depends_on=[1]),
            PlanStep("b", "none", depends_on=[0]),
            PlanStep("c", "none"),
        ]
        order = self._order(steps)
        self.assertEqual(sorted(order), [0, 1, 2])
        self.assertEqual(len(order), 3)

    def test_step_failure_does_not_block_queue(self) -> None:
        steps = [
            PlanStep("a", "none"),
            PlanStep("b", "generate_image"),
            PlanStep("c", "none"),
        ]
        self.assertEqual(self._order(steps, fail_at=1), [0, 2, 1])


if __name__ == "__main__":
    unittest.main()
