# -*- coding: utf-8 -*-
"""配置加载。

优先级：环境变量 AGENT_CONFIG 指定的文件 > 默认 configs/agent.json。
所有相对路径按 agent 根目录解析；配置项用 "a.b.c" 的点路径读取。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

AGENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = AGENT_ROOT / "configs" / "agent.json"


class Config:
    """只读配置树，支持 cfg.get("llm.model", 默认值)。"""

    def __init__(self, data: dict[str, Any], source: Path):
        self.data = data
        self.source = source

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        src = Path(path or os.environ.get("AGENT_CONFIG") or DEFAULT_CONFIG)
        if not src.exists():
            raise FileNotFoundError(f"配置文件不存在：{src}")
        with src.open("r", encoding="utf-8") as fh:
            return cls(json.load(fh), src)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for key in dotted.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    # ---- 路径便捷访问：统一转成绝对 Path ----
    def path(self, dotted: str) -> Path:
        raw = self.get(dotted)
        if not raw:
            raise KeyError(f"缺少路径配置：{dotted}")
        p = Path(raw)
        return p if p.is_absolute() else (AGENT_ROOT / p).resolve()

    def ensure_dirs(self) -> None:
        """创建运行期需要的目录（会话库、工作区、输出根）。"""
        for key in ("paths.db", "paths.workspace", "paths.output_root"):
            value = self.get(key)
            if not value:
                continue
            p = self.path(key)
            (p.parent if p.suffix else p).mkdir(parents=True, exist_ok=True)
