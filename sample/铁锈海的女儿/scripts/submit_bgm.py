#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提交 ACE-Step 1.5 BGM 生成任务到 ComfyUI（蒸汽朋克风格）。

用法:
  python scripts/submit_bgm.py [--seconds 19] [--seed 42]
输出: ComfyUI/output/story_audio/bgm_steampunk_*.flac
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

HOST = "http://127.0.0.1:8188"
OUT_DIR = Path(r"D:\models\ComfyUI\output\story_audio")

TAGS = ("cinematic steampunk orchestral, industrial percussion, brass ensemble, "
        "cello, ambient ocean wind, melancholic, nostalgic, film score, instrumental")
LYRICS = "[inst]"


def build_graph(seconds: float, seed: int) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": r"ACE-Step-1.5\diffusion_models\acestep_v1.5_xl_base_bf16.safetensors",
            "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": r"ACE-Step-1.5\text_encoders\qwen_0.6b_ace15.safetensors",
            "clip_name2": r"ACE-Step-1.5\text_encoders\qwen_1.7b_ace15.safetensors",
            "type": "ace", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": r"ACE-Step-1.5\vae\ace_1.5_vae.safetensors"}},
        "4": {"class_type": "TextEncodeAceStepAudio1.5", "inputs": {
            "clip": ["2", 0], "tags": TAGS, "lyrics": LYRICS, "seed": seed,
            "bpm": 90, "duration": seconds, "timesignature": "4",
            "language": "en", "keyscale": "E minor", "generate_audio_codes": True,
            "cfg_scale": 2.0, "temperature": 0.85, "top_p": 0.9,
            "top_k": 0, "min_p": 0.0}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "7": {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {
            "seconds": seconds, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {
            "model": ["6", 0], "positive": ["4", 0], "negative": ["5", 0],
            "latent_image": ["7", 0], "seed": seed, "steps": 30, "cfg": 2.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveAudio", "inputs": {
            "audio": ["9", 0], "filename_prefix": "story_audio/bgm_steampunk"}},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=19.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--wait", action="store_true", help="阻塞等待完成并打印输出文件")
    args = ap.parse_args()

    wf = {"prompt": build_graph(args.seconds, args.seed), "client_id": "bgm-cli"}
    req = urllib.request.Request(
        f"{HOST}/prompt", data=json.dumps(wf).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"[FAIL] HTTP {e.code}: {e.read().decode(errors='replace')[:800]}", file=sys.stderr)
        return 1
    pid = resp.get("prompt_id")
    print(f"prompt_id={pid}")

    if not args.wait:
        return 0

    while True:
        time.sleep(10)
        try:
            with urllib.request.urlopen(f"{HOST}/history/{pid}", timeout=10) as r:
                hist = json.loads(r.read()).get(pid, {})
        except Exception as e:
            print(f"poll err: {e}", flush=True)
            continue
        if not hist:
            continue
        st = hist.get("status", {})
        if st.get("completed"):
            if st.get("status_str") == "error":
                msgs = st.get("messages", [])
                print("[FAIL] 执行出错", file=sys.stderr)
                for m in msgs:
                    if len(m) > 1 and isinstance(m[1], dict) and "exception_message" in m[1]:
                        print(m[1]["exception_message"], file=sys.stderr)
                return 2
            for nid, out in hist.get("outputs", {}).items():
                for a in out.get("audio", []):
                    print(f"OK {OUT_DIR / a['filename']}")
            return 0


if __name__ == "__main__":
    sys.exit(main())
