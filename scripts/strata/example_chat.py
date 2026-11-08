#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Strata 云端对话示例：单轮 / 多轮 / 流式三种用法。"""
from strata_client import chat, chat_stream


def demo_single():
    print("=" * 60)
    print("[1] 单轮对话")
    messages = [{"role": "user", "content": "用两句话介绍一下丝绸之路。"}]
    text, usage, dt = chat(messages, max_tokens=256)
    print(text)
    print(f"-- 耗时 {dt:.1f}s | 输入 {usage.get('prompt_tokens', 0)} tok | "
          f"输出 {usage.get('completion_tokens', 0)} tok")


def demo_multi_turn():
    print("=" * 60)
    print("[2] 多轮对话（messages 累积上下文）")
    messages = [
        {"role": "system", "content": "你是一个简洁的中文助手。"},
        {"role": "user", "content": "唐代长安城有什么特点？"},
    ]
    text, _, _ = chat(messages, max_tokens=256)
    print("助手:", text[:120], "...")
    messages.append({"role": "assistant", "content": text})
    messages.append({"role": "user", "content": "当时最有名的胡商来自哪里？"})
    text, _, _ = chat(messages, max_tokens=256)
    print("追问:", text)


def demo_stream():
    print("=" * 60)
    print("[3] 流式输出")
    messages = [{"role": "user", "content": "写一句关于秋天的短句。"}]
    for piece in chat_stream(messages, max_tokens=128):
        print(piece, end="", flush=True)
    print()


if __name__ == "__main__":
    demo_single()
    demo_multi_turn()
    demo_stream()
