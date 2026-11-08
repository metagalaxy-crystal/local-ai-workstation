# -*- coding: utf-8 -*-
"""工具层单测：路径越界、读写、Shell 白名单、沙箱执行。

运行：python -m unittest discover -s tests -t .  （在 d:\\models\\agent 下）
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.config import Config
from agent.tools import build_registry


def make_cfg(root: Path) -> Config:
    return Config({
        "llm": {"base_url": "http://127.0.0.1:1/v1"},
        "loop": {"max_rounds": 4, "max_history_chars": 20000, "tool_result_max_chars": 2000},
        "tools": {
            "enabled": ["files", "shell", "sandbox"],
            "tool_timeout": 30,
            "retry": 0,
            "allowed_roots": [str(root)],
            "shell_whitelist": ["python", "python.exe", "echo", "dir"],
            "blocked_patterns": ["rm -rf", "del /s"],
        },
        "paths": {
            "workspace": str(root / "ws"),
            "db": str(root / "session.db"),
            "output_root": str(root / "out"),
        },
    }, Path("test-config"))


class ToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.reg = build_registry(make_cfg(self.root))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_write_read_list(self) -> None:
        out = self.reg.call("write_file", {"path": "a.txt", "content": "你好\n第二行"})
        self.assertTrue(out.ok, out.error)
        text = self.reg.call("read_file", {"path": "a.txt"})
        self.assertTrue(text.ok)
        self.assertIn("你好", text.output)
        listing = self.reg.call("list_dir", {"path": "."})
        self.assertIn("a.txt", listing.output)

    def test_tool_timeout_runs_in_daemon_thread(self) -> None:
        """超时工具的残留线程必须是 daemon。

        之前用 ThreadPoolExecutor：worker 是非 daemon 线程，Python 退出时会 join，
        只要工具有一个卡在 MCP/网络读取里，Ctrl+C 就永久挂住不返回。
        """
        import threading
        import time as _t

        @self.reg.tool("slow_tool", "sleep", {"type": "object", "properties": {}},
                       timeout=0.2)
        def _slow() -> str:
            _t.sleep(5)
            return "done"

        res = self.reg.call("slow_tool", {})
        self.assertFalse(res.ok)
        self.assertIn("超时", res.error or "")
        leftovers = [t for t in threading.enumerate()
                     if t.name.startswith("tool-slow_tool")]
        self.assertTrue(leftovers)
        self.assertTrue(all(t.daemon for t in leftovers))

    def test_move(self) -> None:
        self.reg.call("write_file", {"path": "a.txt", "content": "x"})
        moved = self.reg.call("move_path", {"src": "a.txt", "dst": "sub/b.txt"})
        self.assertTrue(moved.ok, moved.error)
        self.assertTrue((self.root / "ws" / "sub" / "b.txt").exists())

    def test_outside_root_rejected(self) -> None:
        result = self.reg.call("read_file", {"path": "C:/Windows/win.ini"})
        self.assertFalse(result.ok)
        self.assertIn("超出允许范围", result.error)

    def test_shell_whitelist(self) -> None:
        ok = self.reg.call("run_command", {"command": 'python -c "print(6*7)"'})
        self.assertTrue(ok.ok, ok.error)
        self.assertIn("42", ok.output)
        rejected = self.reg.call("run_command", {"command": "powershell Get-Date"})
        self.assertIn("拒绝执行", rejected.output)

    def test_shell_quoted_separator(self) -> None:
        # python -c 里的分号属于引号内部，不能被当作命令分隔符
        ok = self.reg.call("run_command",
                           {"command": 'python -c "import sys; print(6*7)"'})
        self.assertTrue(ok.ok, ok.error)
        self.assertIn("42", ok.output)
        piped = self.reg.call("run_command", {"command": "echo hi | findstr hi"})
        self.assertIn("拒绝执行", piped.output)

    def test_shell_blocked_pattern(self) -> None:
        rejected = self.reg.call("run_command", {"command": "python -c \"print(1)\" && rm -rf C:/"})
        self.assertIn("禁止", rejected.output)

    def test_sandbox(self) -> None:
        result = self.reg.call("run_python", {"code": "print(6*7)"})
        self.assertTrue(result.ok, result.error)
        self.assertIn("42", result.output)

    def test_unknown_tool(self) -> None:
        result = self.reg.call("no_such_tool", {})
        self.assertFalse(result.ok)
        self.assertIn("未注册", result.error)


class McpCloseTests(unittest.TestCase):
    def test_close_all_closes_tracked_sessions(self) -> None:
        """退出时要关掉常驻 MCP 会话，否则 deckcraft 之类的子进程会留在后台。"""
        from agent import mcp_router

        closed: list[float] = []

        class Fake:
            def close(self, timeout: float = 8.0) -> None:
                closed.append(timeout)

        track = {"a": (["x"], Fake()), "b": (["y"], Fake())}
        mcp_router.close_all(track)
        self.assertEqual(len(closed), 2)
        self.assertEqual(track, {})


if __name__ == "__main__":
    unittest.main()
