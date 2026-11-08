#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 llama-server 发提示词，支持思考开关 / 采样参数 / 流式输出。

用法示例：
    python chat.py -p "用三句话介绍蒸汽朋克"
    python chat.py --system "你是分镜师" -p "给锈海少女写 3 个镜头" --temp 0.8
    python chat.py -p "9.11 和 9.9 哪个大？" --think on --max-tokens 2048   # 需服务端支持
    python chat.py -p "写一段 python 快排" --stream

思考内容由服务端 `--reasoning-format` 决定是否放进 reasoning_content 字段；
本脚本会同时保存正文与思考过程。产物写到 d:\\models\\output\\llama_cpp\\chat\\。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402


def post(url: str, payload: dict, timeout: int = 600) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def stream_post(url: str, payload: dict, timeout: int = 600):
    """逐块产出 (content_delta, reasoning_delta)。"""
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                break
            try:
                delta = json.loads(body)["choices"][0].get("delta", {})
            except Exception:
                continue
            yield delta.get("content") or "", delta.get("reasoning_content") or ""


def main() -> int:
    ap = argparse.ArgumentParser(description="llama-server 提示词客户端")
    ap.add_argument("-p", "--prompt", help="提示词")
    ap.add_argument("--prompt-file", help="从文件读提示词（UTF-8）")
    ap.add_argument("--system", help="system 消息")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--model", default="local", help="请求里的 model 名，随便填，服务端不校验")
    ap.add_argument("--think", choices=["on", "off"], help="请求级思考开关（走 chat_template_kwargs）")
    ap.add_argument("--chat-template-kwargs", dest="ctk",
                    help='原始 JSON 覆盖，如 \'{"enable_thinking": true}\'')
    ap.add_argument("--temp", type=float, help="temperature")
    ap.add_argument("--top-p", dest="top_p", type=float)
    ap.add_argument("--top-k", dest="top_k", type=int)
    ap.add_argument("--repeat-penalty", dest="repeat_penalty", type=float)
    ap.add_argument("--max-tokens", dest="max_tokens", type=int, default=1024)
    ap.add_argument("--stream", action="store_true", help="流式输出到终端")
    ap.add_argument("--tag", help="产物文件名前缀，默认时间戳")
    ap.add_argument("--timeout", type=int, default=900)
    opt = ap.parse_args()

    if opt.prompt_file:
        prompt = Path(opt.prompt_file).read_text(encoding="utf-8")
    else:
        prompt = opt.prompt
    if not prompt:
        ap.error("需要 -p/--prompt 或 --prompt-file")

    messages = ([{"role": "system", "content": opt.system}] if opt.system else [])
    messages.append({"role": "user", "content": prompt})

    payload: dict = {"model": opt.model, "messages": messages,
                     "max_tokens": opt.max_tokens, "stream": bool(opt.stream)}
    for key, val in (("temperature", opt.temp), ("top_p", opt.top_p),
                     ("top_k", opt.top_k), ("repeat_penalty", opt.repeat_penalty)):
        if val is not None:
            payload[key] = val
    if opt.ctk:
        payload["chat_template_kwargs"] = json.loads(opt.ctk)
    elif opt.think:
        payload["chat_template_kwargs"] = {"enable_thinking": opt.think == "on"}

    url = f"http://{opt.host}:{opt.port}/v1/chat/completions"
    t0 = time.time()
    try:
        if opt.stream:
            content, reasoning = [], []
            print("--- 思考 ---" if opt.think != "off" else "--- 输出 ---", flush=True)
            for c, r in stream_post(url, payload, opt.timeout):
                if r:
                    reasoning.append(r)
                    sys.stdout.write(r)
                if c:
                    content.append(c)
                    sys.stdout.write(c)
                sys.stdout.flush()
            text, think_txt = "".join(content), "".join(reasoning)
        else:
            resp = post(url, payload, opt.timeout)
            msg = resp["choices"][0]["message"]
            text, think_txt = msg.get("content") or "", msg.get("reasoning_content") or ""
            print("--- 思考 ---")
            print(think_txt or "(无)")
            print("--- 输出 ---")
            print(text)
    except urllib.error.HTTPError as e:
        print(f"[FAIL] HTTP {e.code}: {e.read().decode(errors='replace')[:500]}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[FAIL] {e}（确认 llama-server 已启动且端口正确）", file=sys.stderr)
        return 1

    elapsed = time.time() - t0
    tag = opt.tag or time.strftime("%Y%m%d-%H%M%S")
    d = config.out_dir("llama_cpp", "chat")
    md = d / f"{tag}.md"
    md.write_text(f"# 提示词\n\n{prompt}\n\n# 思考过程\n\n{think_txt or '(无)'}\n\n# 输出\n\n{text}\n",
                  encoding="utf-8")
    (d / f"{tag}.json").write_text(json.dumps(
        {"prompt": prompt, "reasoning": think_txt, "content": text,
         "elapsed_secs": round(elapsed, 2), "request": payload}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"\n# 耗时 {elapsed:.1f}s；产物：{md}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
