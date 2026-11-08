#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量非阻塞提交分镜到 ComfyUI 队列。

用法:
  uv run python scripts/batch_submit.py --model wan22 --shots 1-6 --seed 42
  uv run python scripts/batch_submit.py --model minimax_h3 --shots 1-6 --seed 42
  uv run python scripts/batch_submit.py --model wan22 --shots 2-6 --res 832x480

特点: 提交后立即返回（不等待执行），ComfyUI 会按队列串行执行。
      适合一次性排入多个镜头，让 ComfyUI 自动跑完。
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
OUT_DIRS = {
    "wan22": Path(r"D:\models\sample\铁锈海的女儿\04_wan22"),
    "minimax_h3": Path(r"D:\models\sample\铁锈海的女儿\05_minimax_h3"),
}

DEFAULT_NEG = (
    "low quality, blurry, distorted, watermark, text, deformed, "
    "bad anatomy, extra limbs, lowres, jpeg artifacts, ugly, duplicate, morbid"
)


def load_shots() -> list[dict]:
    sb = json.loads(STORYBOARD.read_text(encoding="utf-8"))
    return sb["shots"]


def parse_shots(spec: str) -> list[int]:
    """解析 '1-6' 或 '1,3,5' 或 '2'。"""
    if "-" in spec:
        a, b = spec.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in spec.split(",")]


def build_wan22(prompt: str, negative: str, seed: int,
                w: int, h: int, length: int, prefix: str) -> dict:
    return {
        "1": {"class_type": "CLIPLoaderGGUF", "inputs": {
            "clip_name": r"umt5-xxl\umt5-xxl-encoder-Q5_K_M.gguf", "type": "wan"}},
        "2": {"class_type": "UnetLoaderGGUF", "inputs": {
            "unet_name": r"Wan2.2-TI2V-5B\Wan2.2-TI2V-5B-Q8_0.gguf"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": r"Wan2.2-TI2V-5B\Wan2.2_VAE.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": negative}},
        "6": {"class_type": "WanImageToVideo", "inputs": {
            "positive": ["4", 0], "negative": ["5", 0], "vae": ["3", 0],
            "width": w, "height": h, "length": length, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["2", 0], "positive": ["6", 0], "negative": ["6", 1],
            "latent_image": ["6", 2], "seed": seed, "steps": 20, "cfg": 3.5,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "CreateVideo", "inputs": {"images": ["8", 0], "fps": 24}},
        "10": {"class_type": "SaveVideo", "inputs": {
            "video": ["9", 0], "filename_prefix": f"story_video/{prefix}",
            "format": "mp4"}},
    }


def build_minimax(prompt: str, seed: int, w: int, h: int, length: int, prefix: str,
                  unet_name: str = "MiniMax-H3\\diffusion_models\\minimax_h3_fl2va_pruned_w6a8.safetensors") -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": unet_name,
            "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "MiniMax-H3\\encoder\\qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
            "type": "minimax"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": "MiniMax-H3\\vae\\minimax_h3_video_vae_fp16.safetensors"}},
        "4": {"class_type": "VAELoader", "inputs": {
            "vae_name": "MiniMax-H3\\vae\\minimax_h3_audio_vae_fp32.safetensors"}},
        "5": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["2", 0], "vae": ["3", 0], "prompt": prompt,
            "width": w, "height": h, "length": length}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
        "7": {"class_type": "MiniMaxH3SigmaShift", "inputs": {
            "model": ["1", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "8": {"class_type": "KSampler", "inputs": {
            "model": ["7", 0], "positive": ["5", 0], "negative": ["6", 0],
            "latent_image": ["5", 1], "seed": seed, "steps": 24, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["8", 0], "vae": ["4", 0]}},
        "11": {"class_type": "CreateVideo", "inputs": {
            "images": ["9", 0], "audio": ["10", 0], "fps": 24}},
        "12": {"class_type": "SaveVideo", "inputs": {
            "video": ["11", 0],
            "filename_prefix": f"story_video/{prefix}", "format": "mp4"}},
    }


def submit(wf_data: dict) -> str | None:
    wf = {"prompt": wf_data, "client_id": "batch-cli"}
    req = urllib.request.Request(
        f"{HOST}/prompt", data=json.dumps(wf).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
        return resp.get("prompt_id")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"  [FAIL] HTTP {e.code}: {body[:500]}", file=sys.stderr)
    except Exception as e:
        print(f"  [FAIL] {e}", file=sys.stderr)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="批量非阻塞提交分镜")
    ap.add_argument("--model", required=True, choices=["wan22", "minimax_h3"])
    ap.add_argument("--shots", default="1-6", help="镜头范围，如 1-6 或 1,3,5")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--res", default=None,
                    help="分辨率 WxH。默认 wan22=1088x608, minimax_h3=640x640")
    ap.add_argument("--length", type=int, default=73)
    ap.add_argument("--unet_name", default=None,
                    help="覆盖扩散模型文件（如 MiniMax-H3\\diffusion_models\\minimax_h3_fl2va_pruned_int8_convrot.safetensors）")
    ap.add_argument("--prefix", default=None,
                    help="输出文件名前缀，默认用 --model 名")
    args = ap.parse_args()

    default_res = {"wan22": "1088x608", "minimax_h3": "640x640"}[args.model]
    res = args.res or default_res
    w, h = map(int, res.split("x"))

    shots = load_shots()
    shot_nums = parse_shots(args.shots)
    prefix_model = args.prefix or args.model

    print(f"模型: {args.model}  分辨率: {w}x{h}x{args.length}  seed: {args.seed}")
    print(f"提交镜头: {shot_nums}")
    print("-" * 60)

    submitted = []
    for n in shot_nums:
        sid = f"shot_{n:03d}"
        shot = next((s for s in shots if s["shot_id"] == sid), None)
        if not shot:
            print(f"[SKIP] {sid} 未找到", file=sys.stderr)
            continue
        prefix = f"{prefix_model}_{sid}"
        if args.model == "wan22":
            wf = build_wan22(shot["wan_prompt"], DEFAULT_NEG, args.seed, w, h, args.length, prefix)
        else:
            wf = build_minimax(shot["minimax_prompt"], args.seed, w, h, args.length, prefix,
                               unet_name=args.unet_name or "MiniMax-H3\\diffusion_models\\minimax_h3_fl2va_pruned_w6a8.safetensors")
        pid = submit(wf)
        if pid:
            submitted.append((sid, pid))
            print(f"  {sid} -> prompt_id={pid}")
        else:
            print(f"  {sid} -> 提交失败", file=sys.stderr)
        time.sleep(1)  # 避免压爆 ComfyUI

    print("-" * 60)
    print(f"已提交 {len(submitted)}/{len(shot_nums)} 镜头")
    # 保存提交记录
    record_path = OUT_DIRS[args.model] / f"_batch_submit_{int(time.time())}.json"
    record_path.write_text(
        json.dumps({"model": args.model, "res": res, "length": args.length,
                    "seed": args.seed, "submitted": submitted}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"提交记录: {record_path}")
    print("ComfyUI 将按队列串行执行。可用以下命令轮询:")
    print(f"  python -c \"import urllib.request,json;r=urllib.request.urlopen('{HOST}/queue').read();print(json.loads(r))\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
