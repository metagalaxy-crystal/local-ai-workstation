#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拼接分镜 mp4 -> final.mp4。

用法:
  uv run python scripts/concat_shots.py --model wan22        # 拼接 04_wan22/shots
  uv run python scripts/concat_shots.py --model minimax_h3  # 拼接 05_minimax_h3/shots
  uv run python scripts/concat_shots.py --model wan22 --reencode  # 强制重编码（音轨对齐）

依赖: 系统ffmpeg需在PATH。脚本会用subprocess调用。
"""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\models\sample\铁锈海的女儿")
# ComfyUI SaveVideo 不允许写到 output 外，所以成品落在 ComfyUI output/story_video/
COMFY_OUT = Path(r"D:\models\ComfyUI\output\story_video")
MODEL_DIRS = {
    "wan22": ROOT / "04_wan22",
    "minimax_h3": ROOT / "05_minimax_h3",
}


def find_shots(model_dir: Path, prefix: str) -> list[Path]:
    """从 ComfyUI output/story_video/ 按 shot_001..shot_006 顺序收集文件。"""
    shots = []
    for i in range(1, 7):
        sid = f"shot_{i:03d}"
        # 匹配前缀包含 shot_001 的文件（ComfyUI 可能加 _00001 后缀）
        candidates = sorted(COMFY_OUT.glob(f"{prefix}_{sid}*.mp4"))
        if candidates:
            shots.append(candidates[0])
    return shots


def main() -> int:
    ap = argparse.ArgumentParser(description="拼接分镜 mp4")
    ap.add_argument("--model", required=True, choices=list(MODEL_DIRS.keys()))
    ap.add_argument("--out", default=None, help="输出文件名，默认 final_<model>.mp4")
    ap.add_argument("--reencode", action="store_true",
                    help="强制重编码（音轨/参数不一致时用，较慢）")
    args = ap.parse_args()

    model_dir = MODEL_DIRS[args.model]
    prefix = f"{args.model}"
    # wan22 前缀是 wan22_shot_001，minimax_h3 前缀是 minimax_h3_shot_001
    shots = find_shots(model_dir, prefix)
    if not shots:
        print(f"[FAIL] 在 {model_dir} 未找到 {prefix}_shot_* 文件", file=sys.stderr)
        return 1

    print(f"找到 {len(shots)} 个分镜:")
    for s in shots:
        print(f"  {s.name}")
    missing = [i for i in range(1, 7) if not any(
        f"shot_{i:03d}" in s.name for s in shots)]
    if missing:
        print(f"[WARN] 缺失分镜: {missing}")

    out_name = args.out or f"final_{args.model}.mp4"
    out_path = model_dir / out_name

    # 写 concat 列表文件
    list_file = model_dir / "_concat_list.txt"
    lines = [f"file '{s.as_posix()}'" for s in shots]
    list_file.write_text("\n".join(lines), encoding="utf-8")

    if args.reencode:
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
               "-i", str(list_file), "-c:v", "libx264", "-crf", "18",
               "-preset", "medium", "-c:a", "aac", "-b:a", "128k",
               "-pix_fmt", "yuv420p", str(out_path)]
    else:
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
               "-i", str(list_file), "-c", "copy", str(out_path)]

    print(f"运行: {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[FAIL] ffmpeg 失败:\n{r.stderr[-2000:]}", file=sys.stderr)
        # copy 模式失败时回退重编码
        if not args.reencode:
            print("尝试重编码模式...")
            cmd2 = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(list_file), "-c:v", "libx264", "-crf", "18",
                    "-preset", "medium", "-c:a", "aac", "-b:a", "128k",
                    "-pix_fmt", "yuv420p", str(out_path)]
            r2 = subprocess.run(cmd2, capture_output=True, text=True)
            if r2.returncode != 0:
                print(f"[FAIL] 重编码也失败:\n{r2.stderr[-2000:]}", file=sys.stderr)
                return 2
    print(f"完成: {out_path}")
    try:
        size_mb = out_path.stat().st_size / 1024 / 1024
        print(f"大小: {size_mb:.2f} MB")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
