# -*- coding: utf-8 -*-
"""llama-server 的 OpenAI 兼容客户端。

只做三件事：发 chat/completions、累积流式增量、把 tool_calls / reasoning_content
整理成统一结构。模型名以服务端 /v1/models 实际返回为准（llama-server 单模型常驻，
请求里的 model 字段会被忽略，但对部分版本仍需传一个存在的名字）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

import requests
from openai import OpenAI

from .config import Config


class LLMError(RuntimeError):
    """模型端不可用或返回异常。"""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str

    def parsed_arguments(self) -> dict:
        try:
            data = json.loads(self.arguments or "{}")
        except json.JSONDecodeError:
            raise LLMError(f"工具参数不是合法 JSON：{self.arguments[:200]}")
        return data if isinstance(data, dict) else {"value": data}


@dataclass
class Reply:
    content: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        llm = cfg.get("llm", {})
        self.base_url: str = llm.get("base_url", "http://127.0.0.1:8080/v1")
        self.model: str = llm.get("model", "local")
        self.temperature: float = float(llm.get("temperature", 0.7))
        self.max_tokens: int = int(llm.get("max_tokens", 4096))
        self.enable_thinking: bool = bool(llm.get("enable_thinking", False))
        self.timeout: float = float(llm.get("timeout", 300))
        self._client = OpenAI(
            base_url=self.base_url,
            api_key=llm.get("api_key", "local"),
            timeout=self.timeout,
            max_retries=0,          # 重试交给 loop 统一控制
        )

    # ------------------------------------------------------------------ 基础
    def ping(self) -> str:
        """探测服务并返回实际模型 id；不可用时抛 LLMError。"""
        url = self.base_url.rstrip("/") + "/models"
        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            items = resp.json().get("data") or []
        except requests.RequestException as exc:
            raise LLMError(
                f"连不上模型服务 {self.base_url}：{exc}。"
                "请先启动 llama-server（scripts\\llama_cpp\\<模型>\\start.bat）"
            ) from exc
        if not items:
            raise LLMError(f"{self.base_url}/models 返回为空，服务可能仍在加载模型")
        model_id = items[0].get("id") or self.model
        if model_id:
            self.model = model_id
        return model_id

    def set_thinking(self, enabled: bool) -> None:
        self.enable_thinking = enabled

    def set_model(self, model: str) -> None:
        """P0 只改请求字段；跨端点切换由 router 在 P3 接管。"""
        self.model = model

    # ------------------------------------------------------------------ 对话
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        on_text: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Reply:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        # 思考开关：llama-server 通过 chat_template_kwargs 透传给模板
        kwargs["extra_body"] = {
            "chat_template_kwargs": {"enable_thinking": self.enable_thinking}
        }

        try:
            if stream:
                kwargs["stream"] = True
                kwargs["stream_options"] = {"include_usage": True}
                return self._chat_stream(kwargs, on_text, on_reasoning)
            return self._chat_once(kwargs)
        except LLMError:
            raise
        except Exception as exc:                      # openai 的各类异常统一收口
            raise LLMError(f"模型调用失败：{type(exc).__name__}: {exc}") from exc

    # ------------------------------------------------------------------ 内部
    def _chat_once(self, kwargs: dict[str, Any]) -> Reply:
        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message
        reply = Reply(
            content=(msg.content or "").strip(),
            reasoning=(getattr(msg, "reasoning_content", "") or "").strip(),
            usage=_usage_dict(getattr(resp, "usage", None)),
            model=getattr(resp, "model", self.model) or self.model,
        )
        for tc in (msg.tool_calls or []):
            reply.tool_calls.append(
                ToolCall(id=tc.id or f"call_{len(reply.tool_calls)}",
                         name=tc.function.name,
                         arguments=tc.function.arguments or "{}")
            )
        return reply

    def _chat_stream(
        self,
        kwargs: dict[str, Any],
        on_text: Callable[[str], None] | None,
        on_reasoning: Callable[[str], None] | None,
    ) -> Reply:
        reply = Reply(model=self.model)
        partial: dict[int, dict[str, str]] = {}
        try:
            stream = self._client.chat.completions.create(**kwargs)
        except TypeError:
            # 少数服务端不认 stream_options，去掉后重试一次
            kwargs.pop("stream_options", None)
            stream = self._client.chat.completions.create(**kwargs)

        for chunk in stream:
            if getattr(chunk, "usage", None):
                reply.usage = _usage_dict(chunk.usage)
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            text = getattr(delta, "content", None)
            if text:
                reply.content += text
                if on_text:
                    on_text(text)
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                reply.reasoning += reasoning
                if on_reasoning:
                    on_reasoning(reasoning)
            for tc in (getattr(delta, "tool_calls", None) or []):
                slot = partial.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if fn.name:
                        slot["name"] += fn.name
                    if fn.arguments:
                        slot["arguments"] += fn.arguments

        for index in sorted(partial):
            slot = partial[index]
            if not slot["name"]:
                continue
            reply.tool_calls.append(
                ToolCall(id=slot["id"] or f"call_{index}",
                         name=slot["name"],
                         arguments=slot["arguments"] or "{}")
            )
        reply.content = reply.content.strip()
        reply.reasoning = reply.reasoning.strip()
        return reply


def _usage_dict(usage: Any) -> dict[str, int]:
    if not usage:
        return {}
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }
