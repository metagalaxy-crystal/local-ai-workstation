#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MiniMax H3 文生视频+音频（T2VA）分镜提交器。

用法:
  uv run python scripts/submit_minimax_h3.py --shot 1            # 从 final_storyboard.json 取第 N 镜头
  uv run python scripts/submit_minimax_h3.py --shot 1 --res 832x480
  uv run python scripts/submit_minimax_h3.py "提示词" --seed 42  # 自定义 prompt

管线: UNETLoader(w6a8) + CLIPLoader(minimax) + 双VAE
      -> MiniMaxH3ImageToVideo -> SigmaShift -> KSampler
      -> VAEDecode(视频) + VAEDecodeAudio(音轨) -> CreateVideo -> SaveVideo

时间账本: 输出 <prefix>.time.json（提交时间戳、总耗时、各阶段日志解析）
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
OUT_DIR = Path(r"D:\models\sample\铁锈海的女儿\05_minimax_h3")
TIME_DIR = Path(r"D:\models\sample\铁锈海的女儿\05_minimax_h3")

# length 必须落在 17k+5 网格上（5,22,39,56,73,90,107,124...）。73 帧≈3s@24fps。
DEFAULT_LENGTH = 73
FPS = 24


def load_shot(shot_num: int) -> dict:
    sb = json.loads(STORYBOARD.read_text(encoding="utf-8"))
    sid = f"shot_{shot_num:03d}"
    for s in sb["shots"]:
        if s["shot_id"] == sid:
            return s
    raise KeyError(f"{sid} not found in storyboard")


def build_workflow(prompt: str, seed: int, width: int, height: int, length: int) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "MiniMax-H3\\diffusion_models\\minimax_h3_fl2va_pruned_w6a8.safetensors",
            "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "MiniMax-H3\\encoder\\qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
            "type": "minimax"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": "MiniMax-H3\\vae\\minimax_h3_video_vae_fp16.safetensors"}},
        "4": {"class_type": "VAELoader", "inputs": {
            "vae_name": "MiniMax-H3\\vae\\minimax_h3_audio_vae_fp32.safetensors"}},
        "5": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["2", 0], "vae": ["3", 0],
            "prompt": prompt, "width": width, "height": height, "length": length}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {
            "conditioning": ["5", 0]}},
        "7": {"class_type": "MiniMaxH3SigmaShift", "inputs": {
            "model": ["1", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "8": {"class_type": "KSampler", "inputs": {
            "model": ["7", 0], "positive": ["5", 0], "negative": ["6", 0],
            "latent_image": ["5", 1], "seed": seed, "steps": 24, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {
            "samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "VAEDecodeAudio", "inputs": {
            "samples": ["8", 0], "vae": ["4", 0]}},
        "11": {"class_type": "CreateVideo", "inputs": {
            "images": ["9", 0], "audio": ["10", 0], "fps": FPS}},
        "12": {"class_type": "SaveVideo", "inputs": {
            "video": ["11", 0], "filename_prefix": "minimax_h3_shot", "format": "mp4"}},
    }


def parse_progress_from_log(log_path: Path, prompt_id: str) -> dict:
    """从 ComfyUI 主日志解析采样进度（尽力而为）。"""
    info = {"sampler_steps_total": None, "sampler_step_secs_avg": None,
            "model_init_secs": None, "prompt_executed_secs": None}
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return info
    # 找最后一段包含本 prompt 的进度条（粗略：取最后一段 0/24 或 0/20 进度块）
    # 这里仅提取全局指标：Prompt executed in X seconds
    import re
    m = re.findall(r"Prompt executed in ([\d.]+) seconds", text)
    if m:
        info["prompt_executed_secs"] = float(m[-1])
    # 采样每步耗时（最后一个进度块）
    steps = re.findall(r"(\d+)%\|.*?\|\s*(\d+)/(\d+)\s*\[([\d:]+)<([\d:]+),\s*([\d.]+)s/it", text)
    if steps:
        last = steps[-1]
        info["sampler_steps_total"] = int(last[2])
        info["sampler_step_secs_avg"] = float(last[5])
    return info


def main() -> int:
    ap = argparse.ArgumentParser(description="MiniMax H3 T2VA 分镜提交器")
    ap.add_argument("--shot", type=int, help="从分镜取第 N 镜头")
    ap.add_argument("prompt", nargs="?", help="自定义 prompt（与 --shot 二选一）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--res", default="640x640",
                    help="分辨率 WxH。MiniMax H3 对尺寸挑剔，默认 640x640 已验证；"
                         "1088x608 / 832x480 需测试是否支持")
    ap.add_argument("--length", type=int, default=DEFAULT_LENGTH,
                    help="帧数，须落在 17k+5 网格 (5,22,39,56,73,90,107,124...)")
    ap.add_argument("--log", default=r"C:\Users\junsheng\AppData\Local\Temp\trae-agent-toolhost\jobs\job-948ada3e01ac4132b58d19a2a004d5b4\output.log",
                    help="ComfyUI 主日志路径，用于解析采样进度")
    args = ap.parse_args()

    if args.shot:
        shot = load_shot(args.shot)
        prompt = shot["minimax_prompt"]
        prefix = f"minimax_h3_{shot['shot_id']}"
        print(f"分镜 {shot['shot_id']}: {shot['camera_move']} {shot['duration']}s", flush=True)
        print(f"  prompt: {prompt[:80]}...", flush=True)
    elif args.prompt:
        prompt = args.prompt
        prefix = "minimax_h3_custom"
    else:
        ap.error("需要 --shot N 或位置参数 prompt")

    w, h = map(int, args.res.split("x"))
    print(f"分辨率 {w}x{h}x{args.length}帧 (≈{args.length/FPS:.1f}s) seed={args.seed}", flush=True)

    wf_data = build_workflow(prompt, args.seed, w, h, args.length)
    wf_data["12"]["inputs"]["filename_prefix"] = f"story_video/{prefix}"
    wf = {"prompt": wf_data, "client_id": "minimax-h3-cli"}

    submit_ts = time.time()
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
    print("等待生成...", flush=True)

    t0 = time.time()
    while True:
        time.sleep(15)
        try:
            with urllib.request.urlopen(f"{HOST}/history/{pid}", timeout=15) as r:
                hist = json.loads(r.read())
        except Exception:
            continue
        if pid not in hist:
            if time.time() - t0 > 7200:
                print("[FAIL] 超时 2 小时", file=sys.stderr)
                return 2
            continue
        st = hist[pid].get("status", {})
        if st.get("completed"):
            done_ts = time.time()
            outs = hist[pid].get("outputs", {})
            out_files = []
            for node_out in outs.values():
                for v in node_out.get("gifs", []) or node_out.get("video", []) or []:
                    fn = v.get("fullpath") or v.get("filename")
                    out_files.append(fn)
                    print(f"完成: {fn}")
            total = done_ts - t0
            print(f"总耗时 {total:.0f}s", flush=True)

            # 写时间账本
            log_info = parse_progress_from_log(Path(args.log), pid)
            time_record = {
                "prompt_id": pid,
                "shot_id": shot["shot_id"] if args.shot else "custom",
                "resolution": f"{w}x{h}",
                "length": args.length,
                "seed": args.seed,
                "submit_ts": submit_ts,
                "done_ts": done_ts,
                "total_wall_secs": round(total, 2),
                "sampler_steps_total": log_info.get("sampler_steps_total"),
                "sampler_step_secs_avg": log_info.get("sampler_step_secs_avg"),
                "prompt_executed_secs": log_info.get("prompt_executed_secs"),
                "output_files": out_files,
            }
            tf = TIME_DIR / f"{prefix}.time.json"
            tf.write_text(json.dumps(time_record, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"时间账本: {tf}", flush=True)
            return 0
        if st.get("status_str") == "error":
            print(f"[FAIL] 工作流出错: {json.dumps(st, ensure_ascii=False)[:800]}",
                  file=sys.stderr)
            return 3


if __name__ == "__main__":
    sys.exit(main())
