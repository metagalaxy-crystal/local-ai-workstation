#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云端 Strata 性能对比测试。

与本地 llm_bench.md 使用完全相同的分镜 prompt，结果可直接对比。

用法:
  python bench_strata.py                      # 速度探针 + 完整分镜任务
  python bench_strata.py --probe-only         # 只跑速度探针
  python bench_strata.py --effort none        # 指定 reasoning_effort
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "03_storyboard"))
from llm_runner import SECTION_FILE, PROMPT_TEMPLATE, validate_json  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "03_storyboard"

DEFAULT_HOST = "10.203.239.162"
DEFAULT_PORT = 8082
DEFAULT_KEY = os.environ.get("STRATA_API_KEY", "")  # 见 API密钥管理方案.md


def chat(host: str, port: int, key: str, messages: list, max_tokens: int,
         effort: str | None = None) -> tuple[dict, float]:
    """调 /v1/chat/completions，返回 (响应JSON, 墙钟秒)。"""
    payload = {
        "model": "strata",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if effort:
        payload["reasoning_effort"] = effort
    req = urllib.request.Request(
        f"http://{host}:{port}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1800) as r:
        resp = json.loads(r.read())
    return resp, time.time() - t0


def probe(host: str, port: int, key: str, effort: str | None, runs: int = 3) -> None:
    """速度探针：固定中文提示词 max_tokens=256，跑 runs 次取中位数。"""
    print(f"\n=== 速度探针（{runs} 次，max_tokens=256, effort={effort}）===")
    speeds = []
    for i in range(runs):
        resp, dt = chat(host, port, key,
                        [{"role": "user", "content":
                          "用中文详细介绍蒸汽朋克美学的起源、视觉特征与代表作品。"}],
                        256, effort)
        usage = resp.get("usage", {})
        ct = usage.get("completion_tokens", 0)
        speed = ct / dt if dt > 0 else 0
        speeds.append(speed)
        print(f"  第{i+1}次: {dt:.1f}s, completion={ct} tok, {speed:.1f} tok/s")
    speeds.sort()
    print(f"  中位数: {speeds[len(speeds)//2]:.1f} tok/s")


def storyboard(host: str, port: int, key: str, effort: str | None) -> None:
    """完整分镜任务：与本地 llm_bench 同一 prompt，结果存入 03_storyboard/llm_strata.*"""
    print(f"\n=== 分镜任务（与本地 bench 同 prompt, effort={effort}）===")
    story = SECTION_FILE.read_text(encoding="utf-8")
    prompt = PROMPT_TEMPLATE.format(story=story)
    resp, dt = chat(host, port, key,
                    [{"role": "system", "content": "你是结构化 JSON 分镜师。只输出 JSON。"},
                     {"role": "user", "content": prompt}],
                    8192, effort)
    msg = resp.get("choices", [{}])[0].get("message", {})
    text = msg.get("content", "") or msg.get("reasoning_content", "") or ""
    usage = resp.get("usage", {})
    ct = usage.get("completion_tokens", 0)
    pt = usage.get("prompt_tokens", 0)

    parsed, err = validate_json(text)
    raw_path = OUT_DIR / "llm_strata.json"
    if parsed:
        raw_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    else:
        raw_path.write_text(text, encoding="utf-8")

    timing = {
        "name": "strata_cloud",
        "endpoint": f"http://{host}:{port}",
        "reasoning_effort": effort,
        "total_wall_sec": round(dt, 2),
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "tokens_per_sec": round(ct / dt, 1) if dt > 0 else 0,
        "finish_reason": resp.get("choices", [{}])[0].get("finish_reason", ""),
        "json_ok": bool(parsed),
        "parse_error": err or None,
    }
    time_path = OUT_DIR / "llm_strata.time.json"
    time_path.write_text(json.dumps(timing, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    print(f"  耗时 {dt:.1f}s | prompt={pt} completion={ct} | "
          f"{timing['tokens_per_sec']} tok/s | JSON={'OK' if parsed else 'FAIL: '+err}")
    print(f"  结果 → {raw_path}\n  账本 → {time_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--key", default=DEFAULT_KEY)
    ap.add_argument("--effort", default="low",
                    help="reasoning_effort: none/low/medium/high（默认 low）")
    ap.add_argument("--probe-only", action="store_true")
    args = ap.parse_args()

    try:
        req = urllib.request.Request(
            f"http://{args.host}:{args.port}/health",
            headers={"Authorization": f"Bearer {args.key}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            print(f"health: {r.read().decode()[:200]}")
    except Exception as e:
        print(f"[FAIL] 连不上 http://{args.host}:{args.port} —— {e}\n"
              f"请到主机启动 run-iq2_xs.bat 和 run-gateway.bat", file=sys.stderr)
        return 2

    probe(args.host, args.port, args.key, args.effort)
    if not args.probe_only:
        storyboard(args.host, args.port, args.key, args.effort)
    return 0


if __name__ == "__main__":
    sys.exit(main())
