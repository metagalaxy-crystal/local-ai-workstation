# -*- coding: utf-8 -*-
"""模型路由表：读 scripts\\llama_cpp\\models.json，列出任务类型 → 模型的映射。

CLI `--check` 用它打印路由表；WebUI 模型面板读同一份注册表。
（任务难度路由的在线逻辑在 task_router.py，本模块只是注册表的只读视图。）
"""
from __future__ import annotations

import json
from pathlib import Path

_REGISTRY = Path(__file__).resolve().parents[2] / "scripts" / "llama_cpp" / "models.json"


class Router:
    """models.json 的只读视图：role 角色标签 + 任务描述。"""

    def __init__(self, registry_path: Path | None = None):
        self.path = registry_path or _REGISTRY
        self.models = self._load()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {k: v for k, v in data.items()
                if not k.startswith("_") and isinstance(v, dict)}

    def pick(self, keyword: str) -> str | None:
        """按关键字找模型 key（匹配 task/desc/name），找不到返回 None。"""
        for key, m in self.models.items():
            haystack = f"{m.get('task', '')} {m.get('desc', '')} {m.get('name', '')}"
            if keyword in haystack:
                return key
        return None

    def describe(self) -> str:
        if not self.models:
            return f"路由表：未找到或无法解析 {self.path}"
        lines = [f"路由表（{self.path.name}）："]
        for key, m in self.models.items():
            role = m.get("role")
            tag = f"[{role}] " if role else ""
            lines.append(f"  {key:<10} {tag}{m.get('name', '')} — {m.get('task', '')}")
        return "\n".join(lines)
