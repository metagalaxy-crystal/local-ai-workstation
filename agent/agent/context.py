# -*- coding: utf-8 -*-
"""上下文治理：工具结果压缩 + 按轮次裁剪历史。

本地模型上下文有限（agent 默认 16K），长任务里工具输出最容易撑爆窗口。
策略：
1. 先把单条工具结果截断到上限（保留头尾，中间标记省略）；
2. 再按「轮」为最小单位从最旧处丢弃，保证 assistant.tool_calls 与其
   tool 结果不会被拆散（拆散会导致接口报错或模型混乱）。
"""
from __future__ import annotations

import json
import re
from typing import Any

Message = dict[str, Any]

_CJK = re.compile(r"[\u3000-\u9fff\uff00-\uffef]")


def estimate_tokens(text: str) -> int:
    """粗估 token 数：中文按 1 字 1 token，其他按 ~3.5 字符 1 token。

    本地 llama-server 的 ctx 上限是硬限制，宁可略高估也不能低估。
    """
    if not text:
        return 0
    s = str(text)
    cjk = len(_CJK.findall(s))
    return cjk + int((len(s) - cjk) / 3.5) + 1


def message_chars(msg: Message) -> int:
    total = len(msg.get("content") or "")
    for tc in msg.get("tool_calls") or []:
        total += len(json.dumps(tc, ensure_ascii=False))
    return total


def total_chars(messages: list[Message]) -> int:
    return sum(message_chars(m) for m in messages)


def total_tokens(messages: list[Message]) -> int:
    total = 0
    for msg in messages:
        total += estimate_tokens(msg.get("content") or "")
        for tc in msg.get("tool_calls") or []:
            total += estimate_tokens(json.dumps(tc, ensure_ascii=False))
    return total


def truncate_tool_results(messages: list[Message], limit: int) -> int:
    """就地截断工具消息，返回截断的条数。"""
    changed = 0
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        content = msg.get("content") or ""
        if len(content) > limit:
            head = content[: int(limit * 0.7)]
            tail = content[-int(limit * 0.2):]
            msg["content"] = f"{head}\n...（已截断 {len(content) - limit} 字符）...\n{tail}"
            changed += 1
    return changed


def _split_units(messages: list[Message]) -> list[list[Message]]:
    """把 system 之后的对话按 user 消息切成若干「轮」。"""
    units: list[list[Message]] = []
    current: list[Message] = []
    for msg in messages[1:]:
        if msg.get("role") == "user" and current:
            units.append(current)
            current = [msg]
        else:
            current.append(msg)
    if current:
        units.append(current)
    return units


def split_trim(
    messages: list[Message],
    max_chars: int,
    tool_max_chars: int = 3000,
    keep_units: int = 2,
) -> tuple[list[Message], list[Message], int]:
    """返回 (新消息列表, 被丢弃的消息, 丢弃的轮数)。不修改传入列表。

    丢弃内容可用于归档（如写入向量知识库作长期记忆）。
    """
    result = [dict(m) for m in messages]
    if not result:
        return result, [], 0
    truncate_tool_results(result, tool_max_chars)
    if total_chars(result) <= max_chars:
        return result, [], 0

    system, units = result[0], _split_units(result)
    dropped_msgs: list[Message] = []
    dropped_rounds = 0
    while len(units) > keep_units and total_chars([system] + [m for u in units for m in u]) > max_chars:
        dropped_msgs.extend(units.pop(0))
        dropped_rounds += 1
    return [system] + [m for u in units for m in u], dropped_msgs, dropped_rounds


def trim_history(
    messages: list[Message],
    max_chars: int,
    tool_max_chars: int = 3000,
    keep_units: int = 2,
) -> tuple[list[Message], int]:
    """返回 (新消息列表, 丢弃的轮数)。不修改传入列表。"""
    trimmed, _dropped_msgs, dropped_rounds = split_trim(
        messages, max_chars, tool_max_chars, keep_units)
    return trimmed, dropped_rounds


def split_trim_tokens(
    messages: list[Message],
    max_tokens: int,
    tool_max_chars: int = 3000,
    keep_units: int = 2,
) -> tuple[list[Message], list[Message], int]:
    """按「估计 token」裁剪历史。用于 ctx 硬上限（如 llama-server 16384）。

    与 split_trim 同构：先截断单条工具结果，再按轮从最旧处丢弃，
    保证 assistant.tool_calls 与对应 tool 结果不被拆散。

    只按「轮」丢历史有个硬伤：同一个 user 轮里连着几十次工具调用时，
    当前这一轮自己就超预算，而 keep_units 又保证它丢不动，
    结果 prompt 一路顶着窗口上限（16384）把回答挤成空。
    因此这里补两级单元内压缩：
      ① 二分缩小单条工具结果上限；
      ② 丢掉当前轮里最早的 assistant/tool 组（保留当前任务那条 user 消息）；
      ③ 仍超就硬截断最长的消息内容（超长粘贴的输入也能兜住）。
    """
    result = [dict(m) for m in messages]
    if not result:
        return result, [], 0
    truncate_tool_results(result, tool_max_chars)
    if total_tokens(result) <= max_tokens:
        return result, [], 0

    system, units = result[0], _split_units(result)
    dropped_msgs: list[Message] = []
    dropped_rounds = 0
    while len(units) > keep_units and \
            total_tokens([system] + _flatten(units)) > max_tokens:
        dropped_msgs.extend(units.pop(0))
        dropped_rounds += 1
    kept = [system] + _flatten(units)
    if total_tokens(kept) <= max_tokens:
        return kept, dropped_msgs, dropped_rounds

    # ① 单元内压缩：二分找能塞进预算的单条工具结果上限
    shrunk = _shrink_tool_results(kept[1:], max_tokens - total_tokens([system]))
    if shrunk is not None:
        return [system] + shrunk, dropped_msgs, dropped_rounds

    # ② 仍超：保留当前任务那条 user 消息，丢掉它之后最早的 assistant/tool 组
    last_user = max((i for i, m in enumerate(kept) if m.get("role") == "user"), default=0)
    head, tail = kept[: last_user + 1], kept[last_user + 1:]
    groups = _message_groups(tail)
    while len(groups) > 1 and \
            total_tokens(head + [m for g in groups for m in g]) > max_tokens:
        dropped_msgs.extend(groups.pop(0))
    kept = head + [m for g in groups for m in g]
    if total_tokens(kept) <= max_tokens:
        return kept, dropped_msgs, dropped_rounds

    # ③ 仍超：从最长内容开始硬截断（超长粘贴、超大工具输出）
    for idx in sorted(range(1, len(kept)),
                      key=lambda i: -len(kept[i].get("content") or "")):
        need = total_tokens(kept) - max_tokens
        if need <= 0:
            break
        content = str(kept[idx].get("content") or "")
        if not content:
            continue
        keep_len = max(80, len(content) - need - 50)
        if keep_len >= len(content):
            continue
        kept[idx] = {**kept[idx],
                     "content": content[:keep_len] + "\n…（内容过长已截断）"}
    return kept, dropped_msgs, dropped_rounds


def _flatten(units: list[list[Message]]) -> list[Message]:
    return [m for u in units for m in u]


def _message_groups(messages: list[Message]) -> list[list[Message]]:
    """按「user 消息 / 带 tool_calls 的 assistant + 它的 tool 结果」分组。

    丢整组才不会把 assistant.tool_calls 和对应的 tool 消息拆散。
    """
    groups: list[list[Message]] = []
    current: list[Message] = []
    for msg in messages:
        role = msg.get("role")
        starts_new = role == "user" or (role == "assistant" and not msg.get("tool_calls"))
        if starts_new and current:
            groups.append(current)
            current = [msg]
        else:
            current.append(msg)
    if current:
        groups.append(current)
    return groups


def _shrink_tool_results(messages: list[Message], max_tokens: int,
                         low: int = 64) -> list[Message] | None:
    """二分求单条工具结果的字符上限；能塞进预算就返回新列表，否则 None。"""
    original = [dict(m) for m in messages]
    hi = max((len(str(m.get("content") or "")) for m in original), default=low)
    best: list[Message] | None = None
    while low <= hi:
        mid = (low + hi) // 2
        cand = [dict(m) for m in original]
        truncate_tool_results(cand, mid)
        if total_tokens(cand) <= max_tokens:
            best = cand
            hi = mid - 1
        else:
            low = mid + 1
    return best
