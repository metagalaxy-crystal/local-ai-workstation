# -*- coding: utf-8 -*-
"""模型选择：本地规则路由（难度启发 → 任务惯性），零额外调用。

迟滞设计（35B 级模型切换要几分钟，不能被一两个词轻易触发）：
- 硬性规则（看图→多模态）单词命中即生效，且不受冷却期限制——当前模型做不了就是做不了；
- 软性规则（重任务→旗舰）要求同一条规则命中 ≥2 个关键词，避免「详细」一个词就换模型；
- 当前在线模型已在候选列表里时不再切换（`current` 满足即返回 None）；
- 冷却期由调用方（webui._maybe_route）执行，见 router.switch_cooldown_sec。
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import Config


def _chat_models(cfg: Config) -> dict:
    """对话模型（排除 embed/rerank/router 等后端角色）。"""
    scripts = cfg.get("tools.scripts_dir", "")
    path = Path(scripts) / "llama_cpp" / "models.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {k: v for k, v in data.items()
            if not k.startswith("_") and v.get("role") not in ("embed", "rerank", "router")}


# ---------------------------------------------------------------------- 规则路由
# 本地启发式：不调用任何模型。按优先级匹配关键词，命中的第一个可用模型胜出。
# (关键词组, 候选模型（按注册表顺序取第一个存在的）, 理由, 最少命中数, 是否硬性)
# 注意：看图规则只收「暗示手头有图要分析」的词；「图片/照片/截图」这类词在
# 「搜索图片做PPT」「网页截图」等生成类任务里同样出现，曾把 PPT 任务误切到
# 工具调用能力弱的多模态模型，故剔除。
_RULES: list[tuple[tuple[str, ...], tuple[str, ...], str, int, bool]] = [
    (("看图", "这张图", "识别图", "图中", "ocr", "OCR"),
     ("qwen25vl", "minicpmv"), "看图任务 → 多模态", 1, True),
    (("小说", "剧本", "分镜", "长文", "章节", "完整方案", "详细", "深入",
      "论文", "代码", "重构", "架构", "调试"),
     ("qwen36",), "重任务 → 旗舰质量", 2, False),
]


def pick_by_rules(cfg: Config, task: str, current: str | None = None) -> dict | None:
    """规则路由：返回 {"key", "reason", "hard"}；无命中或当前模型已满足返回 None。

    current：当前在线模型 key；若已在候选列表内，说明能力已满足，不再切换。
    """
    registry = _chat_models(cfg)
    if not registry:
        return None
    text = task or ""
    for keywords, candidates, reason, min_hits, hard in _RULES:
        hits = sum(1 for k in keywords if k in text)
        if hits < min_hits:
            continue
        if current and current in candidates:
            return None  # 当前模型已能胜任，不折腾切换
        for key in candidates:
            if key in registry:
                return {"key": key, "reason": reason, "hard": hard}
    return None
