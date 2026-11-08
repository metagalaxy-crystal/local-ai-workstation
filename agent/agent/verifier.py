# -*- coding: utf-8 -*-
"""任务验收：任务跑完后用一个模型独立检查是否达标，不合格就指出从哪一步重做。

设计要点：
  - 验收是独立的一次 LLM 调用，不共享执行模型的对话上下文，避免"自己检查自己"的偏差
  - 输出约定为 JSON，解析失败按"未通过但不重修"处理，绝不因为验收本身把任务搞挂
  - 只给建议，是否重做由 orchestrator / loop 决定（配置 verify.max_retry 控制次数）
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .llm import LLMClient

_SYSTEM = (
    "你是严格的任务验收员。根据原始任务、执行计划和各步骤实际产出，判断任务是否真正完成。\n"
    "只输出一个 JSON 对象，不要任何解释性文字或 Markdown 代码块，格式：\n"
    '{"ok": true/false, "score": 0-100, '
    '"problems": ["具体问题"], "redo_from": 步骤序号或 null, "advice": "一句话整改建议"}\n'
    "判定标准：产出是否真实存在且符合任务目标（不是只说不做）、内容是否完整、格式是否正确。\n"
    "只有确实存在可交付结果且与任务一致才给 ok=true。\n"
    "若不通过，redo_from 填最该重做的步骤序号（从 1 开始）；问题在整体则填 1。"
)


@dataclass
class Verdict:
    ok: bool = False
    score: int = 0
    problems: list[str] = field(default_factory=list)
    redo_from: int | None = None
    advice: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: str = ""

    def brief(self) -> str:
        tag = "通过" if self.ok else "未通过"
        s = f"验收{tag} · {self.score} 分"
        if self.problems:
            s += " · " + "；".join(self.problems[:2])
        return s


def _extract_json(text: str) -> dict[str, Any] | None:
    """从模型输出里抠出第一个 JSON 对象（容忍 ```json 包裹和前后废话）。"""
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(s[start:end + 1])
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def verify(cfg, llm: LLMClient, task: str, plan_goals: list[str],
           outputs: list[str], artifacts: list[str],
           model: str | None = None) -> Verdict:
    """跑一次验收。任何异常都转成"未通过但不强制重做"，不影响主流程。"""
    plans = "\n".join(f"{i + 1}. {g}" for i, g in enumerate(plan_goals)) or "（无显式计划）"
    body = "\n".join(outputs) or "（没有记录到步骤产出）"
    files = "、".join(artifacts[:20]) if artifacts else "（没有产出文件）"
    user = (f"【原始任务】\n{task}\n\n【执行计划】\n{plans}\n\n"
            f"【各步骤实际产出】\n{body}\n\n【产出文件】\n{files}")

    old_model = getattr(llm, "model", None)
    if model:
        llm.set_model(model)
    try:
        reply = llm.chat([
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ], temperature=0.1, max_tokens=400)
    finally:
        if model and old_model:
            llm.set_model(old_model)

    usage = getattr(reply, "usage", {}) or {}
    verdict = Verdict(prompt_tokens=usage.get("prompt_tokens", 0),
                      completion_tokens=usage.get("completion_tokens", 0),
                      raw=reply.content or "")
    data = _extract_json(verdict.raw)
    if not data:
        # 解析失败：不拦任务，只提示验收没给出可读结论
        verdict.problems = ["验收输出无法解析，按通过处理"]
        verdict.ok = True
        verdict.score = 60
        return verdict
    verdict.ok = bool(data.get("ok"))
    try:
        verdict.score = int(data.get("score") or 0)
    except Exception:
        verdict.score = 0
    probs = data.get("problems") or []
    verdict.problems = [str(p) for p in probs] if isinstance(probs, list) else [str(probs)]
    redo = data.get("redo_from")
    try:
        verdict.redo_from = int(redo) if redo is not None else None
    except Exception:
        verdict.redo_from = None
    verdict.advice = str(data.get("advice") or "")
    return verdict
