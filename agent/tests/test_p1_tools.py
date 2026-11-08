# -*- coding: utf-8 -*-
"""P1 工具单测：注册装配、切片逻辑、搜索兜底（离线不依赖外网的部分）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.config import Config
from agent.memory import rag
from agent.tools import build_registry


def make_cfg(root: Path, enabled=("files", "shell", "sandbox", "search", "browser", "rag")) -> Config:
    return Config({
        "llm": {"base_url": "http://127.0.0.1:1/v1"},
        "loop": {"max_rounds": 4, "max_history_chars": 20000, "tool_result_max_chars": 2000},
        "tools": {
            "enabled": list(enabled),
            "tool_timeout": 20, "retry": 0,
            "allowed_roots": [str(root)],
            "shell_whitelist": [], "blocked_patterns": [],
            "search": {"provider": "duckduckgo", "max_results": 5},
            "browser": {"headless": True},
        },
        "rag": {"embed_url": "http://127.0.0.1:1/v1",
                "rerank_url": "http://127.0.0.1:1/rerank",
                "chunk_size": 120, "chunk_overlap": 30, "top_k": 3, "recall_candidates": 10},
        "paths": {"workspace": str(root / "ws"), "db": str(root / "s.db"),
                  "vectors_db": str(root / "v.db"), "output_root": str(root / "out")},
    }, Path("test-config"))


class RegistryBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_all_families_registered(self) -> None:
        reg = build_registry(make_cfg(self.root))
        names = reg.names()
        for expected in ("web_search", "browser_open", "browser_click", "browser_fill",
                         "browser_press", "browser_scroll", "browser_extract", "browser_close",
                         "kb_ingest", "kb_search", "kb_stats"):
            self.assertIn(expected, names)

    def test_schemas_valid_for_llm(self) -> None:
        reg = build_registry(make_cfg(self.root))
        for schema in reg.schemas():
            self.assertEqual(schema["type"], "function")
            self.assertIn("name", schema["function"])
            self.assertEqual(schema["function"]["parameters"]["type"], "object")


class ChunkTests(unittest.TestCase):
    def test_chunk_size_and_overlap(self) -> None:
        text = "句子一。" * 200  # 800 字符
        rag._chunk_size, rag._chunk_overlap = 120, 30
        chunks = rag._chunk(text)
        self.assertGreater(len(chunks), 3)
        self.assertTrue(all(len(c) <= 130 for c in chunks))
        joined = "".join(chunks)
        self.assertIn("句子一", joined)

    def test_empty_text(self) -> None:
        self.assertEqual(rag._chunk(""), [])


class SearchFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        reg = build_registry(make_cfg(self.root))
        self.reg = reg

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_web_search_format(self) -> None:
        fake = [("标题A", "https://a.example", "摘要A"), ("标题B", "https://b.example", "摘要B")]
        with patch("agent.tools.search._search_ddg", return_value=fake), \
                patch("agent.tools.search._search_bing", return_value=[]), \
                patch("agent.tools.search._search_bocha", return_value=[]):
            result = self.reg.call("web_search", {"query": "测试"})
        self.assertTrue(result.ok)
        self.assertIn("标题A", result.output)
        self.assertIn("https://b.example", result.output)

    def test_web_search_empty(self) -> None:
        with patch("agent.tools.search._search_ddg", return_value=[]), \
                patch("agent.tools.search._search_bing", return_value=[]), \
                patch("agent.tools.search._search_bocha", return_value=[]):
            result = self.reg.call("web_search", {"query": "xyz"})
        self.assertIn("未找到结果", result.output)


if __name__ == "__main__":
    unittest.main()
