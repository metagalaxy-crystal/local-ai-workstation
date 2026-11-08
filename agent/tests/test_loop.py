# -*- coding: utf-8 -*-
"""主循环单测：用假 LLM 驱动，验证工具执行、消息回灌与护栏。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.config import Config
from agent.context import estimate_tokens, split_trim_tokens, total_tokens
from agent.llm import LLMError, Reply, ToolCall
from agent.loop import AgentLoop
from agent.memory.store import SessionStore
from agent.tools import build_registry


class FakeLLM:
    """按脚本依次返回预设 Reply，并记录收到的消息。"""

    def __init__(self, replies: list[Reply]):
        self.replies = list(replies)
        self.seen: list[list[dict]] = []

    def chat(self, messages, tools=None, stream=False, on_text=None, on_reasoning=None):
        self.seen.append(list(messages))
        return self.replies.pop(0)


def make_cfg(root: Path, max_rounds: int = 4) -> Config:
    return Config({
        "llm": {"base_url": "http://127.0.0.1:1/v1"},
        "loop": {"max_rounds": max_rounds, "max_history_chars": 20000,
                 "tool_result_max_chars": 2000},
        "tools": {"enabled": ["files"], "tool_timeout": 20, "retry": 0,
                  "allowed_roots": [str(root)], "shell_whitelist": [],
                  "blocked_patterns": []},
        "paths": {"workspace": str(root / "ws"), "db": str(root / "s.db"),
                  "output_root": str(root / "out")},
    }, Path("test-config"))


class ContextBudgetTests(unittest.TestCase):
    """上下文窗口硬上限相关：估算、按 token 裁剪、超限自动压缩重试。"""

    def test_estimate_counts_cjk_heavier(self) -> None:
        self.assertGreater(estimate_tokens("中文" * 100), estimate_tokens("a" * 200))

    def test_split_trim_tokens_respects_budget(self) -> None:
        msgs = [{"role": "system", "content": "系统"}]
        for i in range(6):
            msgs.append({"role": "user", "content": "提问" * 250})
            msgs.append({"role": "assistant", "content": "回答" * 250})
        trimmed, dropped, rounds = split_trim_tokens(msgs, 2500)
        self.assertLessEqual(total_tokens(trimmed), 2500)
        self.assertEqual(trimmed[0]["role"], "system")
        self.assertGreater(rounds, 0)
        self.assertTrue(dropped)

    def test_trim_inside_one_turn_when_tool_results_flood(self) -> None:
        """同一个 user 轮里连续十几次大工具结果：只按轮丢历史是丢不动的，
        必须在单元内继续压缩，否则 prompt 会一路顶着窗口上限。"""
        msgs = [{"role": "system", "content": "系统提示" * 100},
                {"role": "user", "content": "帮我搜集资料并做成 PPT"}]
        for i in range(12):
            msgs.append({"role": "assistant", "content": "",
                         "tool_calls": [{"id": f"c{i}", "type": "function",
                                         "function": {"name": "web_search",
                                                      "arguments": "{}"}}]})
            msgs.append({"role": "tool", "tool_call_id": f"c{i}",
                         "name": "web_search", "content": "搜索结果" * 1500})
        trimmed, dropped, _ = split_trim_tokens(msgs, 4000)
        self.assertLessEqual(total_tokens(trimmed), 4000)
        self.assertEqual(trimmed[0]["role"], "system")
        # 当前任务的那条 user 消息必须留着
        self.assertTrue(any(m["role"] == "user" for m in trimmed))
        self.assertTrue(any("截断" in (m.get("content") or "") for m in trimmed)
                        or dropped)
        # tool_calls 与 tool 结果必须成对，不能留孤立的 tool 消息
        pending: set[str] = set()
        for m in trimmed:
            if m["role"] == "assistant":
                for tc in m.get("tool_calls") or []:
                    pending.add(tc["id"])
            elif m["role"] == "tool":
                self.assertIn(m["tool_call_id"], pending)
                pending.discard(m["tool_call_id"])

    def test_oversized_user_message_is_hard_truncated(self) -> None:
        msgs = [{"role": "system", "content": "sys"},
                {"role": "user", "content": "长" * 20000}]
        trimmed, _, _ = split_trim_tokens(msgs, 2000)
        self.assertLessEqual(total_tokens(trimmed), 2000)
        self.assertIn("已截断", trimmed[-1]["content"])

    def test_est_ratio_shrinks_budget(self) -> None:
        """实测 prompt 比本地估计大时，预算要按比例收窄，给回答留空间。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = make_cfg(root)
            loop = AgentLoop(
                Config({**cfg.data, "llm": {**cfg.data["llm"], "context_size": 16384}},
                       Path("test-config")),
                FakeLLM([]), build_registry(cfg))
            full = loop._prompt_budget_tokens()
            loop._est_ratio = 2.0
            half = loop._prompt_budget_tokens()
            self.assertLess(half, full)
            self.assertGreaterEqual(half, 768)

    def test_budget_accounts_for_window_and_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = make_cfg(root)
            loop = AgentLoop(
                Config({**cfg.data, "llm": {**cfg.data["llm"], "context_size": 8192}},
                       Path("test-config")),
                FakeLLM([]), build_registry(cfg))
            budget = loop._prompt_budget_tokens()
            self.assertGreater(budget, 512)
            self.assertLess(budget, 8192)

    def test_context_overflow_retries_with_shrunk_history(self) -> None:
        class OverflowLLM(FakeLLM):
            def chat(self, messages, tools=None, stream=False, **kw):
                self.seen.append(list(messages))
                if len(self.seen) == 1:
                    raise LLMError(
                        "Error code: 400 - request (16556 tokens) exceeds the "
                        "available context size (16384 tokens)")
                return Reply(content="压缩后完成")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SessionStore(root / "s.db")
            try:
                sid = store.create_session("超限")
                cfg = make_cfg(root)
                llm = OverflowLLM([])
                loop = AgentLoop(cfg, llm, build_registry(cfg), store=store)
                for _ in range(5):  # 先把历史堆长
                    store.append_message(sid, {"role": "user", "content": "很长的历史" * 300})
                    store.append_message(sid, {"role": "assistant", "content": "很长的回答" * 300})
                result = loop.run("继续", sid)
                self.assertEqual(result.content, "压缩后完成")
                self.assertEqual(len(llm.seen), 2)
                self.assertLess(total_tokens(llm.seen[1]), total_tokens(llm.seen[0]))
            finally:
                store.close()


class LoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = SessionStore(self.root / "s.db")
        self.sid = self.store.create_session("测试")

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def _loop(self, llm, max_rounds: int = 4) -> AgentLoop:
        return AgentLoop(make_cfg(self.root, max_rounds), llm,
                         build_registry(make_cfg(self.root, max_rounds)),
                         store=self.store)

    def test_tool_then_answer(self) -> None:
        llm = FakeLLM([
            Reply(tool_calls=[ToolCall("c1", "write_file",
                                       '{"path": "report.txt", "content": "ok"}')]),
            Reply(content="已生成报告。"),
        ])
        result = self._loop(llm).run("写个报告", self.sid)
        self.assertEqual(result.content, "已生成报告。")
        self.assertEqual(result.rounds, 2)
        self.assertEqual(result.tool_calls, 1)
        self.assertTrue((self.root / "ws" / "report.txt").exists())
        # 第二次请求必须带上 assistant.tool_calls 与 tool 结果
        roles = [m["role"] for m in llm.seen[-1]]
        self.assertIn("tool", roles)

    def test_llm_error_is_persisted(self) -> None:
        """模型调不通时，报错要进会话历史与 runs 账本（刷新后还能看到）。"""
        class DownLLM(FakeLLM):
            def chat(self, *args, **kw):
                raise LLMError("connection refused")

        llm = DownLLM([])
        result = self._loop(llm).run("任务", self.sid)
        self.assertEqual(result.stopped_reason, "llm_error")
        contents = [m.get("content") or "" for m in self.store.load_messages(self.sid)]
        self.assertTrue(any("模型调用失败" in c for c in contents))
        rows = self.store.runs_detail()
        self.assertIn("模型调用失败", rows[0]["error"] or "")

    def test_empty_answer_is_failure_not_done(self) -> None:
        """模型回空（prompt 贴满窗口的典型表现）不能算完成：要判失败并留 ⚠。"""
        llm = FakeLLM([Reply(content="")])
        result = self._loop(llm).run("做个 PPT", self.sid)
        self.assertEqual(result.stopped_reason, "empty_answer")
        self.assertIn("上下文窗口", result.content)
        contents = [m.get("content") or "" for m in self.store.load_messages(self.sid)]
        self.assertTrue(any("⚠" in c for c in contents))

    def test_empty_after_tools_retries_then_succeeds(self) -> None:
        """调过工具后回空：先收窄历史催一次，别把半截任务当完成。"""
        llm = FakeLLM([
            Reply(tool_calls=[ToolCall("c1", "list_dir", '{"path": "."}')]),
            Reply(content=""),
            Reply(content="已保存 deck.pptx"),
        ])
        result = self._loop(llm, max_rounds=5).run("做个 PPT", self.sid)
        self.assertEqual(result.stopped_reason, "done")
        self.assertEqual(result.content, "已保存 deck.pptx")

    def test_max_rounds_guard(self) -> None:
        replies = [Reply(tool_calls=[ToolCall(f"c{i}", "list_dir", '{"path": "."}')])
                   for i in range(6)]
        llm = FakeLLM(replies)
        result = self._loop(llm, max_rounds=2).run("无限循环", self.sid)
        self.assertEqual(result.stopped_reason, "max_rounds")
        self.assertEqual(result.rounds, 2)

    def test_repeat_guard(self) -> None:
        same = Reply(tool_calls=[ToolCall("c", "list_dir", '{"path": "."}')])
        llm = FakeLLM([same, same, same, Reply(content="结束")])
        result = self._loop(llm, max_rounds=4).run("重复调用", self.sid)
        self.assertEqual(result.content, "结束")
        tool_msgs = [m for m in result.messages if m["role"] == "tool"]
        self.assertTrue(any("护栏" in m["content"] for m in tool_msgs))

    def test_persistence(self) -> None:
        llm = FakeLLM([Reply(content="直接回答")])
        self._loop(llm).run("你好", self.sid)
        stored = self.store.load_messages(self.sid)
        self.assertEqual([m["role"] for m in stored], ["user", "assistant"])
        self.assertEqual(stored[-1]["content"], "直接回答")

    def test_rescue_text_tool_call(self) -> None:
        """模型把工具调用 JSON 当正文输出：应捞回真调用并执行，而不是假完成。"""
        llm = FakeLLM([
            Reply(content='我先创建文件：\n```json\n'
                          '{"tool": "write_file", "tool_args": '
                          '{"path": "a.txt", "content": "hi"}}\n```'),
            Reply(content="文件已写好。"),
        ])
        result = self._loop(llm).run("写个文件", self.sid)
        self.assertEqual(result.tool_calls, 1)
        self.assertTrue((self.root / "ws" / "a.txt").exists())
        self.assertEqual(result.content, "文件已写好。")

    def test_rescue_ignores_unknown_tool(self) -> None:
        """正文里的 JSON 若指向未注册工具，不得捞成调用。"""
        llm = FakeLLM([
            Reply(content='示例：{"tool": "no_such_tool", "tool_args": {}}'),
            Reply(content="讲完"),
        ])
        result = self._loop(llm).run("讲讲", self.sid)
        self.assertEqual(result.tool_calls, 0)

    def test_fake_call_nudge(self) -> None:
        """伪工具调用 JSON 已损坏捞不回来：应催促走正式通道，而不是直接算完成。"""
        llm = FakeLLM([
            Reply(content='{"tool": "write_file", "tool_args": {broken'),
            Reply(content="直接给结果"),
        ])
        result = self._loop(llm).run("任务", self.sid)
        self.assertEqual(result.content, "直接给结果")
        self.assertTrue(any("正式的工具调用通道" in (m.get("content") or "")
                            for m in llm.seen[-1] if m["role"] == "user"))


if __name__ == "__main__":
    unittest.main()
