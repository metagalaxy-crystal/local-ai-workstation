#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wan2.2-TI2V-5B 文生视频（T2V）工作流提交器。

用法:
  uv run python scripts/submit_wan22.py --prompt "英文提示词" --seed 42
  uv run python scripts/submit_wan22.py --shot 1            # 从 final_storyboard.json 取第 N 镜头
  uv run python scripts/submit_wan22.py --shot 1 --res 832x480  # 回退分辨率

管线: UnetLoaderGGUF + CLIPLoaderGGUF(umt5-xxl) + VAELoader
      -> CLIPTextEncode×2 -> WanImageToVideo -> KSampler
      -> VAEDecode -> CreateVideo -> SaveVideo
"""
from __future__ import annotations
import argparse
import json
import time
import urllib.request
import urllib.error
import sys
from pathlib import Path

HOST = "http://127.0.0.1:8188"

STORYBOARD = Path(r"D:\models\sample\铁锈海的女儿\03_storyboard\final_storyboard.json")
OUT_DIR = Path(r"D:\models\sample\铁锈海的女儿\04_wan22")

DEFAULT_NEG = (
    "low quality, blurry, distorted, watermark, text, deformed, "
    "bad anatomy, extra limbs, lowres, jpeg artifacts, ugly, duplicate, morbid"
)


def load_shot(shot_num: int) -> dict:
    sb = json.loads(STORYBOARD.read_text(encoding="utf-8"))
    sid = f"shot_{shot_num:03d}"
    for s in sb["shots"]:
        if s["shot_id"] == sid:
            return s
    raise KeyError(f"{sid} not found in storyboard")


def build_workflow(prompt: str, negative: str, seed: int,
                   width: int, height: int, length: int) -> dict:
    return {
        "1": {"class_type": "CLIPLoaderGGUF", "inputs": {
            "clip_name": r"umt5-xxl\umt5-xxl-encoder-Q5_K_M.gguf",
            "type": "wan"}},
        "2": {"class_type": "UnetLoaderGGUF", "inputs": {
            "unet_name": r"Wan2.2-TI2V-5B\Wan2.2-TI2V-5B-Q8_0.gguf"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": r"Wan2.2-TI2V-5B\Wan2.2_VAE.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["1", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["1", 0], "text": negative}},
        "6": {"class_type": "WanImageToVideo", "inputs": {
            "positive": ["4", 0], "negative": ["5", 0], "vae": ["3", 0],
            "width": width, "height": height, "length": length, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["2", 0],
            "positive": ["6", 0], "negative": ["6", 1],
            "latent_image": ["6", 2],
            "seed": seed, "steps": 20, "cfg": 3.5,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {
            "samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "CreateVideo", "inputs": {
            "images": ["8", 0], "fps": 24}},
        "10": {"class_type": "SaveVideo", "inputs": {
            "video": ["9", 0], "filename_prefix": "wan22_shot", "format": "mp4"}},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Wan2.2 T2V 提交器")
    ap.add_argument("--prompt", help="正面提示词（英文）")
    ap.add_argument("--negative", default=DEFAULT_NEG, help="负向提示词")
    ap.add_argument("--shot", type=int, help="从分镜取第 N 镜头（覆盖 --prompt）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--res", default="1088x608", help="分辨率 WxH，回退用 832x480")
    ap.add_argument("--length", type=int, default=73, help="帧数")
    args = ap.parse_args()

    # 取 prompt
    if args.shot:
        shot = load_shot(args.shot)
        prompt = shot["wan_prompt"]
        prefix = f"wan22_{shot['shot_id']}"
        print(f"分镜 {shot['shot_id']}: {shot['camera_move']} {shot['duration']}s", flush=True)
    elif args.prompt:
        prompt = args.prompt
        prefix = "wan22_custom"
    else:
        ap.error("需要 --prompt 或 --shot")

    w, h = map(int, args.res.split("x"))
    print(f"分辨率 {w}x{h}x{args.length}帧 (≈{args.length/24:.1f}s) seed={args.seed}", flush=True)

    wf_data = build_workflow(prompt, args.negative, args.seed, w, h, args.length)
    wf_data["10"]["inputs"]["filename_prefix"] = f"story_video/{prefix}"

    wf = {"prompt": wf_data, "client_id": "wan22-cli"}
    req = urllib.request.Request(
        f"{HOST}/prompt", data=json.dumps(wf).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"[FAIL] 提交失败 HTTP {e.code}: {body[:800]}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[FAIL] 提交失败: {e}", file=sys.stderr)
        return 1

    pid = resp.get("prompt_id")
    print(f"已提交 prompt_id={pid}", flush=True)
    print("等待生成（预计 5-15 分钟）...", flush=True)

    t0 = time.time()
    while True:
        time.sleep(15)
        try:
            with urllib.request.urlopen(f"{HOST}/history/{pid}", timeout=15) as r:
                hist = json.loads(r.read())
        except Exception:
            continue
        if pid not in hist:
            if time.time() - t0 > 3600:
                print("[FAIL] 超时 1 小时", file=sys.stderr)
                return 2
            continue
        st = hist[pid].get("status", {})
        if st.get("completed"):
            outs = hist[pid].get("outputs", {})
            for node_out in outs.values():
                for v in node_out.get("gifs", []) or node_out.get("video", []) or []:
                    print(f"完成: {v.get('fullpath', v.get('filename'))}")
            print(f"总耗时 {time.time()-t0:.0f}s")
            return 0
        if st.get("status_str") == "error":
            print(f"[FAIL] 工作流出错: {json.dumps(st, ensure_ascii=False)[:800]}",
                  file=sys.stderr)
            return 3


if __name__ == "__main__":
    sys.exit(main())
