#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mmproj 多模态测试：给 VLM（MiniCPM-V / Qwen2.5-VL / Qwen3.6）传图片或视频提问。

前置：先用 start_server.py 启动带 mmproj 的模型，例如
    python start_server.py minicpmv

用法示例：
    python vlm_test.py                                  # 用内置测试图 + 默认提示词
    python vlm_test.py --image D:\\pic.png -p "描述这张图"
    python vlm_test.py --model qwen25vl --image a.jpg --image b.jpg -p "对比两张图"
    python vlm_test.py --video D:\\clip.mp4 -p "用三句话概括这个视频的内容"
    python vlm_test.py --model minicpmv --video a.mp4 --image b.png -p "视频和图片有什么关系"

媒体类型按后缀自动判断（图片: jpg/png/jpeg/webp/gif，其余按视频处理）。图片和视频可混用。

实现说明：优先走 OpenAI 兼容的 /v1/chat/completions（图片用 image_url、视频用
video_url，均为 base64 data URL）；若该版本服务端不支持，自动回退到原生
/completion 的 multimodal_data 形式（视频和图片字节都放进去，服务端自识别）。
产物写到 d:\\models\\output\\llama_cpp\\vlm\\。
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

DEFAULT_IMAGE = config.LLAMA_DIR / "src" / "tools" / "mtmd" / "test-1.jpeg"
DEFAULT_VIDEO = config.LLAMA_DIR / "src" / "tools" / "mtmd" / "test-3.mp4"
DEFAULT_PROMPT = "详细描述其内容，包括主体、场景、颜色与文字。"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def media_type(path: Path) -> str:
    return "image" if path.suffix.lower() in IMAGE_EXTS else "video"


def post(url: str, payload: dict, timeout: int = 600) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0]
    if not mime:
        mime = "image/png" if media_type(path) == "image" else "video/mp4"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def ask_via_chat(base: str, media: list[Path], prompt: str, max_tokens: int,
                 think: str | None = None) -> tuple[str, str]:
    content = [{"type": "text", "text": prompt}]
    for m in media:
        if media_type(m) == "image":
            content.append({"type": "image_url", "image_url": {"url": data_url(m)}})
        else:
            content.append({"type": "video_url", "video_url": {"url": data_url(m)}})
    payload = {"model": "local", "messages": [{"role": "user", "content": content}],
               "max_tokens": max_tokens, "temperature": 0.7}
    if think is not None:
        # 传进 chat template，控制模型是否先输出思考（MiniCPM-V / Qwen3 系列支持）
        payload["chat_template_kwargs"] = {"enable_thinking": think == "on"}
    resp = post(f"{base}/v1/chat/completions", payload)
    msg = resp["choices"][0]["message"]
    return msg.get("content") or "", msg.get("reasoning_content") or ""


def ask_via_completion(base: str, media: list[Path], prompt: str, max_tokens: int) -> str:
    resp = post(f"{base}/completion", {
        "prompt": {"prompt_string": prompt,
                   "multimodal_data": [base64.b64encode(m.read_bytes()).decode() for m in media]},
        "n_predict": max_tokens, "temperature": 0.7})
    return resp.get("content", "")


def main() -> int:
    ap = argparse.ArgumentParser(description="VLM 图片/视频理解测试（mmproj）")
    ap.add_argument("--model", default="minicpmv",
                    help="已启动的 VLM 是哪个 key（仅用于命名产物）：minicpmv / qwen25vl / qwen36")
    ap.add_argument("--image", action="append", help="图片路径，可多次")
    ap.add_argument("--video", action="append", help="视频路径，可多次（MiniCPM-V / Qwen3.6 等支持）")
    ap.add_argument("-p", "--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--max-tokens", dest="max_tokens", type=int, default=512)
    ap.add_argument("--think", choices=["on", "off"], help="是否让模型先输出思考（走 chat_template_kwargs）")
    ap.add_argument("--tag", help="产物文件名前缀，默认时间戳")
    opt = ap.parse_args()

    # 媒体收集：--image / --video 都没给时，用默认测试图（有视频模型则可用 --video 不传图）
    media: list[Path] = []
    if opt.image:
        media += [Path(p) for p in opt.image]
    if opt.video:
        media += [Path(p) for p in opt.video]
    if not media:
        media = [DEFAULT_IMAGE]

    missing = [str(m) for m in media if not m.exists()]
    if missing:
        print(f"[FAIL] 媒体文件不存在：{missing}", file=sys.stderr)
        return 1
    labels = [f"{media_type(m)}:{m.name}" for m in media]
    print(f"# 媒体：{', '.join(labels)}")
    print(f"# 提示词：{opt.prompt}", flush=True)

    base = f"http://{opt.host}:{opt.port}"
    t0 = time.time()
    try:
        text, think = ask_via_chat(base, media, opt.prompt, opt.max_tokens, opt.think)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        print(f"# chat/completions 失败（HTTP {e.code}: {detail}），回退 /completion ...", flush=True)
        try:
            text, think = ask_via_completion(base, media, opt.prompt, opt.max_tokens), ""
        except Exception as e2:
            print(f"[FAIL] 两种方式都失败：{e2}（确认服务端已用 -mm 加载 mmproj）", file=sys.stderr)
            return 1
    except Exception as e:
        print(f"[FAIL] {e}（确认 llama-server 已启动）", file=sys.stderr)
        return 1

    elapsed = time.time() - t0
    print("--- 思考 ---")
    print(think or "(无)")
    print("--- 输出 ---")
    print(text)

    tag = opt.tag or time.strftime("%Y%m%d-%H%M%S")
    d = config.out_dir("llama_cpp", "vlm")
    md = d / f"{opt.model}_{tag}.md"
    md.write_text(f"# 模型\n\n{opt.model}\n\n# 媒体\n\n" +
                  "\n".join(f"- {media_type(m)}: {m}" for m in media) +
                  f"\n\n# 提示词\n\n{opt.prompt}\n\n# 思考过程\n\n{think or '(无)'}\n\n# 输出\n\n{text}\n",
                  encoding="utf-8")
    print(f"\n# 耗时 {elapsed:.1f}s；产物：{md}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
