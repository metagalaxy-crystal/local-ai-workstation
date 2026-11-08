#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Strata 云端模型调用封装（从 bench_universal.py 提炼，可独立复用）。

协议: OpenAI 兼容 /v1/chat/completions（vLLM 服务，内网 10.203.239.162:8082）
依赖: 仅 Python 标准库，无第三方包

能力:
  - chat()         普通对话 / 多轮对话（返回完整文本 + usage + 耗时）
  - chat_stream()  流式对话（逐段产出增量文本）
  - image_content() 多模态消息构造（本地图片 -> base64 data URL）
  - reply_text()   从响应中提取回复文本（含 reasoning_content 回退）
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from pathlib import Path

HOST = "10.203.239.162"
PORT = 8082
KEY = os.environ.get("STRATA_API_KEY", "")
MODEL = "bench"            # 服务端注册的模型名，固定传 bench
DEFAULT_EFFORT = "low"     # 推理强度: low(快) / medium / high(慢而深)
BASE_URL = f"http://{HOST}:{PORT}/v1/chat/completions"

# 图片后缀 -> data URL mime
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp", ".gif": "image/gif"}


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if KEY:
        h["Authorization"] = f"Bearer {KEY}"
    return h


def reply_text(resp: dict) -> str:
    """提取回复文本；思考型输出无 content 时回退 reasoning_content。"""
    msg = resp.get("choices", [{}])[0].get("message", {})
    return msg.get("content", "") or msg.get("reasoning_content", "") or ""


def chat(messages: list, *, temperature: float = 0.7, max_tokens: int = 1024,
         effort: str = DEFAULT_EFFORT, timeout: int = 1800,
         **extra) -> tuple[str, dict, float]:
    """非流式对话。messages 为 OpenAI 格式，返回 (回复文本, usage, 耗时秒)。

    effort: reasoning_effort，Strata 推理强度，low 速度最快。
    extra:  透传其他 payload 字段（如 top_p、presence_penalty）。
    """
    payload = {"model": MODEL, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens,
               "stream": False, "reasoning_effort": effort}
    payload.update(extra)
    req = urllib.request.Request(
        BASE_URL, data=json.dumps(payload).encode(),
        headers=_headers(), method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read())
    return reply_text(resp), resp.get("usage", {}), time.time() - t0


def chat_stream(messages: list, *, temperature: float = 0.7,
                max_tokens: int = 1024, effort: str = DEFAULT_EFFORT,
                timeout: int = 1800, **extra):
    """流式对话，生成器逐段 yield 增量文本（SSE 协议解析）。"""
    payload = {"model": MODEL, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens,
               "stream": True, "reasoning_effort": effort}
    payload.update(extra)
    req = urllib.request.Request(
        BASE_URL, data=json.dumps(payload).encode(),
        headers=_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            delta = chunk.get("choices", [{}])[0].get("delta", {})
            piece = delta.get("content") or ""
            if piece:
                yield piece


def image_content(text: str, image_path: str | Path) -> list:
    """构造多模态 content：本地图片转 base64 data URL + 文本提问。

    返回值直接作为 messages 中 user 消息的 content 字段使用。
    """
    p = Path(image_path)
    mime = _MIME.get(p.suffix.lower())
    if mime is None:
        raise ValueError(f"不支持的图片格式: {p.suffix}（支持 png/jpg/jpeg/webp/gif）")
    b64 = base64.b64encode(p.read_bytes()).decode()
    return [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        {"type": "text", "text": text},
    ]
