#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一 LLM 分镜调用器（OpenAI 兼容 API）。

用法:
  uv run python 03_storyboard/llm_runner.py nanbeige 8090
  uv run python 03_storyboard/llm_runner.py lfm 8091
  uv run python 03_storyboard/llm_runner.py deepseek 8092
  uv run python 03_storyboard/llm_runner.py qwen35b 8093
  uv run python 03_storyboard/llm_runner.py strata 8082 --host 10.203.239.162 --key <APIkey> --effort low   # 云端 Strata（质量档首选）

输出:
  03_storyboard/llm_<name>.json      # 原始响应
  03_storyboard/llm_<name>.time.json # 时间账本（加载/首token/端到端）
"""
from __future__ import annotations
import argparse
import json
import time
import urllib.request
import urllib.error
import sys
from pathlib import Path

SECTION_FILE = Path(r"D:\models\sample\铁锈海的女儿\01_story_text\section1.txt")
OUT_DIR = Path(r"D:\models\sample\铁锈海的女儿\03_storyboard")

PROMPT_TEMPLATE = """你是一位资深电影分镜师。请阅读下面这段小说节选，然后产出一份结构化的分镜脚本。

# 小说节选
{story}

# 任务要求
1. **人物卡**：提取故事中所有人物，给出姓名、年龄、外貌特征（发型/瞳色/身材）、服装、性格标签。如小说未明确，按蒸汽朋克写实画风合理补全。
2. **场景卡**：列出所有场景，给出地点描述、光线方向与色温、氛围关键词。
3. **镜头清单**：把节选拆成 5-8 个镜头，每个镜头给出：
   - shot_id：序号（shot_001, shot_002 ...）
   - description：画面描述（蒸汽朋克写实风，含人物动作、环境、机位、景别）
   - camera_move：镜头运动（static/push_in/pull_out/pan_left/pan_right/tilt_up/tilt_down/tracking）
   - duration：秒数（3-8）
4. **整体风格**：steampunk_realistic

# 输出格式（严格 JSON，不要加 markdown 围栏）
{{
  "style": "steampunk_realistic",
  "characters": [
    {{"name": "...", "age": 0, "appearance": "...", "outfit": "...", "tags": ["..."]}}
  ],
  "scenes": [
    {{"location": "...", "lighting": "...", "mood": ["..."]}}
  ],
  "shots": [
    {{"shot_id": "shot_001", "description": "...", "camera_move": "push_in", "duration": 5}}
  ]
}}

# 画风关键词
铁锈、青铜、机械齿轮、蒸汽、工业污染、煤灰、油污、温暖琥珀光、冷蓝月光、
丝绸与齿轮混搭、铜管、铆钉、护目镜、黄铜怀表、皮革、带锈斧头。

直接输出 JSON，不要任何解释。
"""


def wait_for_server(port: int, timeout: int = 180,
                    host: str = "127.0.0.1", key: str | None = None) -> tuple[float, bool]:
    """轮询 /health，返回 (等待耗时, 是否就绪)。"""
    t0 = time.time()
    url = f"http://{host}:{port}/health"
    while time.time() - t0 < timeout:
        try:
            req = urllib.request.Request(url)
            if key:
                req.add_header("Authorization", f"Bearer {key}")
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
                if data.get("status") == "ok":
                    return time.time() - t0, True
        except Exception:
            pass
        time.sleep(2)
    return time.time() - t0, False


def call_llm(port: int, story: str, no_think: bool = False,
             host: str = "127.0.0.1", key: str | None = None,
             effort: str | None = None) -> tuple[str, dict]:
    """调用 OpenAI 兼容 /v1/chat/completions，返回 (响应文本, 时间账本)。"""
    prompt = PROMPT_TEMPLATE.format(story=story)
    payload = {
        "messages": [
            {"role": "system", "content": "你是结构化 JSON 分镜师。只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 8192,
        "stream": False,
    }
    if no_think:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    if effort:  # Strata 引擎的思考力度：none/low/medium/high
        payload["reasoning_effort"] = effort
    body = json.dumps(payload).encode()
    url = f"http://{host}:{port}/v1/chat/completions"

    t_start = time.time()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            t_first = time.time()
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}")
    except TimeoutError as e:
        raise RuntimeError(f"timeout after 1800s: {e}")

    t_end = time.time()
    msg = resp.get("choices", [{}])[0].get("message", {})
    text = msg.get("content", "") or ""
    reasoning = msg.get("reasoning_content", "") or ""
    finish_reason = resp.get("choices", [{}])[0].get("finish_reason", "")
    # 推理模型：content 为空时回退到 reasoning_content（可能含最终 JSON）
    source = "content"
    if not text.strip() and reasoning.strip():
        text = reasoning
        source = "reasoning_content"

    timing = {
        "total_wall_sec": round(t_end - t_start, 2),
        "first_byte_sec": round(t_first - t_start, 2),
        "tokens_used": resp.get("usage", {}).get("total_tokens", 0),
        "prompt_tokens": resp.get("usage", {}).get("prompt_tokens", 0),
        "completion_tokens": resp.get("usage", {}).get("completion_tokens", 0),
        "finish_reason": finish_reason,
        "content_source": source,
        "reasoning_tokens": len(reasoning) // 4 if reasoning else 0,
    }
    return text, timing


def validate_json(text: str) -> tuple[dict | None, str]:
    """尝试解析 JSON，返回 (dict, 原始文本) 或 (None, 错误)。"""
    # 先直接试
    try:
        return json.loads(text), ""
    except json.JSONDecodeError:
        pass
    # 兼容：剥掉 markdown 围栏
    import re
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1)), ""
        except json.JSONDecodeError as e:
            return None, f"fenced parse fail: {e}"
    # 寻找第一个 { 到最后一个 } 之间
    s = text.find("{")
    e_idx = text.rfind("}")
    if 0 <= s < e_idx:
        try:
            return json.loads(text[s:e_idx + 1]), ""
        except json.JSONDecodeError as e:
            return None, f"substr parse fail: {e}"
    return None, "no JSON found"


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM 分镜调用")
    ap.add_argument("name", help="LLM 名称（用于输出文件名）")
    ap.add_argument("port", type=int, help="服务端口")
    ap.add_argument("--host", default="127.0.0.1", help="服务地址（默认本机）")
    ap.add_argument("--key", default=None, help="API Key（如 Strata 网关需要）")
    ap.add_argument("--effort", default=None,
                    help="reasoning_effort: none/low/medium/high（Strata 引擎用）")
    ap.add_argument("--no-wait", action="store_true", help="不等待 /health")
    ap.add_argument("--no-think", action="store_true", help="禁用推理模式")
    args = ap.parse_args()

    story = SECTION_FILE.read_text(encoding="utf-8")
    print(f"[{args.name}] 加载小说 {len(story)} 字符", flush=True)

    if not args.no_wait:
        print(f"[{args.name}] 等待 server {args.host}:{args.port} 就绪...", flush=True)
        load_t, ready = wait_for_server(args.port, host=args.host, key=args.key)
        if not ready:
            print(f"[{args.name}] [FAIL] server 未就绪，等待 {load_t:.0f}s", file=sys.stderr)
            return 2
        print(f"[{args.name}] server 就绪（等待 {load_t:.1f}s）", flush=True)

    print(f"[{args.name}] 开始调用{' (no-think)' if args.no_think else ''}...", flush=True)
    try:
        text, timing = call_llm(args.port, story, no_think=args.no_think,
                                host=args.host, key=args.key, effort=args.effort)
    except Exception as e:
        print(f"[{args.name}] [FAIL] 调用失败: {e}", file=sys.stderr)
        return 3

    print(f"[{args.name}] 完成，耗时 {timing['total_wall_sec']}s "
          f"(tokens {timing['tokens_used']})", flush=True)

    # 保存原始响应
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = OUT_DIR / f"llm_{args.name}.json"
    parsed, err = validate_json(text)
    if parsed:
        raw_path.write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{args.name}] JSON 解析成功，保存 {raw_path}", flush=True)
    else:
        # 保存原始文本
        raw_path.write_text(text, encoding="utf-8")
        print(f"[{args.name}] [WARN] JSON 解析失败: {err}，保存原始文本到 {raw_path}",
              file=sys.stderr)

    # 保存时间账本
    time_path = OUT_DIR / f"llm_{args.name}.time.json"
    timing["name"] = args.name
    timing["port"] = args.port
    timing["json_ok"] = bool(parsed)
    time_path.write_text(
        json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{args.name}] 时间账本 → {time_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
