# -*- coding: utf-8 -*-
"""任务规划：让模型在已知手段中挑一条成本最低的可行路线。

注意：这里不是让模型「发明」方案，而是在已实现的工具能力内做路线选择。
规划失败时回退为单步直执行，保证主流程永不因规划而卡死。
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from .llm import LLMClient, LLMError

# ---------------------------------------------------------------- 资源类型
# 调度只认这五类资源：GPU 上的三个服务互斥（8GB 显存放不下第二个），CPU/MCP 可并发。
RES_LLM = "gpu_llm"
RES_COMFY = "comfy"
RES_VOICE = "voice"
RES_CPU = "cpu"
RES_MCP = "mcp"
RESOURCES = {RES_LLM, RES_COMFY, RES_VOICE, RES_CPU, RES_MCP}
GPU_RESOURCES = {RES_LLM, RES_COMFY, RES_VOICE}

_COMFY_STEPS = {"generate_image", "generate_video", "generate_music"}
_VOICE_STEPS = {"tts_speak", "asr_transcribe"}


def resource_of_tool(tool: str) -> str:
    """按工具名推断占用哪类资源；未登记的本地工具走 CPU。"""
    name = (tool or "none").strip()
    if name in ("", "none"):
        return RES_LLM
    if name.startswith("mcp_"):
        return RES_MCP
    if name in _COMFY_STEPS:
        return RES_COMFY
    if name in _VOICE_STEPS:
        return RES_VOICE
    return RES_CPU


PLAN_PROMPT = """你是任务规划器。根据用户任务，在下列已有能力中选一条**成本最低且可行**的路线。

可用手段与相对成本（从低到高）：
1. kb_search 本地知识库：最快、最省 token；已有入库文档时优先。
2. read_file / list_dir / run_python：本地文件与计算，快。
3. web_search：联网检索标题摘要，中等成本。
4. browser_open：打开网页读正文，**最贵**（文本长），每个页面最多打开一次。

规则：
- 能用低成本的就不用高成本；只有需要网页正文时才用 browser。
- 步骤 2~5 步，每步是一个可独立完成的小目标，最后一步必须是「汇总并给出结论」。
- 只输出 JSON，不要解释、不要代码块标记。

输出格式：
{"approach":"采用的路线名","reason":"一句话理由","est_cost":"low|medium|high",
 "steps":[{"goal":"这一步要做什么","tool":"建议工具名或 none"}]}

用户任务：{task}
"""


@dataclass
class PlanStep:
    goal: str
    tool: str = "none"
    resource: str = ""  # 空 = 按 tool 推断；规划模型给出的值需在 RESOURCES 内才采信
    depends_on: list[int] = field(default_factory=list)  # 仅允许指向前面的步骤

    def resource_key(self) -> str:
        return self.resource if self.resource in RESOURCES else resource_of_tool(self.tool)


@dataclass
class Plan:
    approach: str = "direct"
    reason: str = ""
    est_cost: str = "medium"
    steps: list[PlanStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def fallback(cls, task: str) -> "Plan":
        return cls(approach="direct", reason="规划不可用，直接执行", est_cost="unknown",
                   steps=[PlanStep(task, "none")])


def parse_plan(raw: str, task: str, max_steps: int = 6) -> Plan:
    """从不规整的模型输出里抠出 JSON 并校验。"""
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return Plan.fallback(task)
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return Plan.fallback(task)

    steps: list[PlanStep] = []
    for item in (data.get("steps") or [])[:max_steps]:
        resource = ""
        deps: list[int] = []
        if isinstance(item, dict):
            goal = str(item.get("goal", "")).strip()
            tool = str(item.get("tool", "none")).strip() or "none"
            raw_res = str(item.get("resource", "")).strip()
            resource = raw_res if raw_res in RESOURCES else ""
            for d in item.get("depends_on") or []:
                try:
                    k = int(d)
                except (TypeError, ValueError):
                    continue
                if 0 <= k < len(steps):  # 只接受指向前序步骤的依赖，环与越界直接丢弃
                    deps.append(k)
        else:
            goal, tool = str(item).strip(), "none"
        if goal:
            steps.append(PlanStep(goal[:300], tool[:40], resource, sorted(set(deps))))
    if not steps:
        return Plan.fallback(task)
    return Plan(
        approach=str(data.get("approach", "model-plan"))[:40],
        reason=str(data.get("reason", ""))[:200],
        est_cost=str(data.get("est_cost", "medium"))[:10],
        steps=steps,
    )


def make_plan(llm: LLMClient, task: str) -> Plan:
    if not llm.model:
        return Plan.fallback(task)
    try:
        reply = llm.chat(
            [{"role": "user", "content": PLAN_PROMPT.replace("{task}", task)}],
            temperature=0.2, max_tokens=800)
    except LLMError:
        return Plan.fallback(task)
    return parse_plan(reply.content, task)
