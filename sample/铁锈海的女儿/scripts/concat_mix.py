#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyAV 拼接 + 音视频合成（无需 ffmpeg CLI）。

用法:
  python scripts/concat_mix.py concat              # wan22 6 镜头 -> 静音成片（重编码统一 832x480）
  python scripts/concat_mix.py native              # minimax 六镜头直拼（视频重编码 + 原生音轨原样重编码）
  python scripts/concat_mix.py bgm                 # wan22 静音成片 + ACE-Step BGM -> final_wan22_bgm.mp4
  python scripts/concat_mix.py all                 # 依次执行

音频方案（原方案，2026-10-08 定稿）:
  - Wan2.2 无原生音轨：画面 + 工作流生成的 BGM（ACE-Step）
  - MiniMax H3：直接使用与视频一起生成的原生同步音效，不做混音
  - 时间轴混音方案已弃用（各镜头响度不一 + 叠加导致音量忽大忽小）
"""
from __future__ import annotations
import argparse
import sys
import wave
from fractions import Fraction
from pathlib import Path

import numpy as np
import av

ROOT = Path(r"D:\models\sample\铁锈海的女儿")
COMFY_OUT = Path(r"D:\models\ComfyUI\output\story_video")
WAN_DIR = ROOT / "04_wan22"
MM_DIR = ROOT / "05_minimax_h3"

TARGET_W, TARGET_H, FPS = 832, 480, 24
SR = 44100
CH = 1024          # AAC 每帧样本数
BGM_FADE = 1.0     # BGM 首尾淡化(秒)
SPEECH_GAIN = 0.75  # 语音峰值归一目标
SPEECH_DIR = ROOT / "06_compare" / "speech"
# (起始秒, 文件名)：shot2 对话 3.04-6.08s；shot4 父亲低语 9.12-12.17s
SPEECH_CLIPS = [
    (3.6, "line1_father.wav"),
    (4.8, "line2_girl.wav"),
    (9.4, "line3_father.wav"),
]


def find_shots(prefix: str) -> list[Path]:
    shots = []
    for i in range(1, 7):
        cands = sorted(COMFY_OUT.glob(f"{prefix}_shot_{i:03d}*.mp4"))
        if not cands:
            raise FileNotFoundError(f"缺少 {prefix}_shot_{i:03d}")
        shots.append(cands[0])
    return shots


def process_frame(frame: av.VideoFrame) -> av.VideoFrame:
    """cover 缩放 + 居中裁剪到 832x480（不变形不留黑边）。"""
    w, h = frame.width, frame.height
    if (w, h) == (TARGET_W, TARGET_H):
        arr = frame.to_ndarray(format="rgb24")
    else:
        scale = max(TARGET_W / w, TARGET_H / h)
        nw, nh = round(w * scale), round(h * scale)
        arr = frame.reformat(width=nw, height=nh).to_ndarray(format="rgb24")
        x0 = (nw - TARGET_W) // 2
        y0 = (nh - TARGET_H) // 2
        arr = arr[y0:y0 + TARGET_H, x0:x0 + TARGET_W]
    return av.VideoFrame.from_ndarray(arr, format="rgb24")


def concat_video(prefix: str, out_path: Path) -> int:
    """重编码拼接，返回总帧数。"""
    shots = find_shots(prefix)
    print(f"[{prefix}] 拼接 {len(shots)} 镜头 -> {out_path.name}")
    out = av.open(out_path, "w")
    st = out.add_stream("libx264", rate=FPS)
    st.width, st.height, st.pix_fmt = TARGET_W, TARGET_H, "yuv420p"
    st.time_base = Fraction(1, FPS)
    st.options = {"crf": "18", "preset": "medium"}
    idx = 0
    for p in shots:
        n = 0
        with av.open(p) as c:
            for frame in c.decode(video=0):
                f = process_frame(frame)
                f.pts = idx
                f.time_base = Fraction(1, FPS)
                for pkt in st.encode(f):
                    out.mux(pkt)
                idx += 1
                n += 1
        print(f"  {p.name}: {n} 帧")
    for pkt in st.encode(None):
        out.mux(pkt)
    out.close()
    dur = idx / FPS
    print(f"  完成: {idx} 帧 = {dur:.2f}s, {out_path.stat().st_size/1024/1024:.2f}MB")
    return idx


def decode_audio(path: Path) -> np.ndarray:
    """解码音频 -> float32 (2, N) @ 44100 stereo。"""
    rs = av.AudioResampler(format="fltp", layout="stereo", rate=SR)
    chunks = []
    with av.open(path) as c:
        for frame in c.decode(audio=0):
            out = rs.resample(frame)
            if out is None:
                continue
            if not isinstance(out, list):
                out = [out]
            for rf in out:
                arr = rf.to_ndarray()
                if arr.shape[0] == 1:
                    arr = np.repeat(arr, 2, axis=0)
                chunks.append(arr.astype(np.float32))
    if not chunks:
        return np.zeros((2, 0), dtype=np.float32)
    return np.concatenate(chunks, axis=1)


def mix_speech(buf: np.ndarray) -> np.ndarray:
    """把对白按时间轴位置混入音频缓冲（峰值归一 SPEECH_GAIN）。"""
    for start_s, name in SPEECH_CLIPS:
        p = SPEECH_DIR / name
        if not p.exists():
            print(f"  [SKIP] 无语音 {p}")
            continue
        pcm = decode_audio(p)
        peak = float(np.abs(pcm).max())
        if peak <= 0:
            continue
        pcm = pcm * (SPEECH_GAIN / peak)
        s0 = int(round(start_s * SR))
        n = min(pcm.shape[1], buf.shape[1] - s0)
        if n > 0:
            buf[:, s0:s0 + n] += pcm[:, :n]
            print(f"  speech {name} @ {start_s:.2f}s ({n/SR:.2f}s)")
    return buf


def _encode_audio(ast, out, pcm: np.ndarray, pts: int = 0, flush: bool = True) -> int:
    """PCM (2,N) float32 -> AAC 编码，返回下一个 pts。"""
    total = pcm.shape[1]
    for s in range(0, total, CH):
        seg = pcm[:, s:s + CH]
        if seg.shape[1] < CH:
            seg = np.pad(seg, ((0, 0), (0, CH - seg.shape[1])))
        f = av.AudioFrame.from_ndarray(np.ascontiguousarray(seg), format="fltp", layout="stereo")
        f.sample_rate = SR
        f.time_base = Fraction(1, SR)
        f.pts = pts
        pts += CH
        for pkt in ast.encode(f):
            out.mux(pkt)
    if flush:
        for pkt in ast.encode(None):
            out.mux(pkt)
    return pts


def native_concat(prefix: str, out_path: Path) -> None:
    """六镜头顺序直拼：视频重编码 + 原生音轨原样重编码（不做混音/响度处理）。"""
    shots = find_shots(prefix)
    print(f"[{prefix}] 原生音轨直拼 {len(shots)} 镜头 -> {out_path.name}")
    out = av.open(out_path, "w")
    vst = out.add_stream("libx264", rate=FPS)
    vst.width, vst.height, vst.pix_fmt = TARGET_W, TARGET_H, "yuv420p"
    vst.time_base = Fraction(1, FPS)
    vst.options = {"crf": "18", "preset": "medium"}
    ast = out.add_stream("aac", rate=SR)
    ast.time_base = Fraction(1, SR)
    try:
        ast.layout = "stereo"
    except Exception:
        pass
    vidx = 0
    shot_audio: list[np.ndarray] = []
    for p in shots:
        with av.open(p) as c:
            for frame in c.decode(video=0):
                f = process_frame(frame)
                f.pts = vidx
                f.time_base = Fraction(1, FPS)
                for pkt in vst.encode(f):
                    out.mux(pkt)
                vidx += 1
        rs = av.AudioResampler(format="fltp", layout="stereo", rate=SR)
        chunks = []
        with av.open(p) as c:
            for frame in c.decode(audio=0):
                res = rs.resample(frame)
                if res is None:
                    continue
                if not isinstance(res, list):
                    res = [res]
                for rf in res:
                    arr = rf.to_ndarray()
                    if arr.shape[0] == 1:
                        arr = np.repeat(arr, 2, axis=0)
                    chunks.append(arr.astype(np.float32))
        pcm = np.concatenate(chunks, axis=1) if chunks else np.zeros((2, 0), dtype=np.float32)
        shot_audio.append(pcm)
        print(f"  {p.name}: {pcm.shape[1]/SR:.2f}s 音频")
    for pkt in vst.encode(None):
        out.mux(pkt)
    # 音频缓冲顺序拼接 + 对白按时间轴混入
    total_n = int(round(vidx / FPS * SR))
    buf = np.zeros((2, total_n), dtype=np.float32)
    pos = 0
    for pcm in shot_audio:
        n = min(pcm.shape[1], total_n - pos)
        if n > 0:
            buf[:, pos:pos + n] += pcm[:, :n]
        pos += pcm.shape[1]
    mix_speech(buf)
    _encode_audio(ast, out, buf)
    out.close()
    print(f"  完成: {vidx} 帧 = {vidx/FPS:.2f}s, {out_path.stat().st_size/1024/1024:.2f}MB")


def bgm_mux(video_in: Path, bgm_path: Path, out_path: Path) -> None:
    """静音画面 + 工作流生成的 BGM（峰值归一 0.85，首尾 1s 淡化）。"""
    pcm = decode_audio(bgm_path)
    peak = float(np.abs(pcm).max()) if pcm.size else 0
    if peak > 0:
        pcm = pcm * (0.85 / peak)
    vin = av.open(video_in)
    out = av.open(out_path, "w")
    # mp4 要求所有流在首个 packet 前创建，否则崩溃
    vst = out.add_stream("libx264", rate=FPS)
    vst.width, vst.height, vst.pix_fmt = TARGET_W, TARGET_H, "yuv420p"
    vst.time_base = Fraction(1, FPS)
    vst.options = {"crf": "18", "preset": "fast"}
    ast = out.add_stream("aac", rate=SR)
    ast.time_base = Fraction(1, SR)
    try:
        ast.layout = "stereo"
    except Exception:
        pass
    idx = 0
    for frame in vin.decode(video=0):
        f = process_frame(frame)
        f.pts = idx
        f.time_base = Fraction(1, FPS)
        for pkt in vst.encode(f):
            out.mux(pkt)
        idx += 1
    for pkt in vst.encode(None):
        out.mux(pkt)
    vin.close()
    total_n = int(round(idx / FPS * SR))
    n = min(pcm.shape[1], total_n)
    seg = pcm[:, :n]
    if n < total_n:
        seg = np.pad(seg, ((0, 0), (0, total_n - n)))
    fb = int(BGM_FADE * SR)
    if total_n > 2 * fb:
        ramp = np.ones(total_n, dtype=np.float32)
        ramp[:fb] = np.linspace(0, 1, fb)
        ramp[-fb:] = np.linspace(1, 0, fb)
        seg = seg * ramp
    seg = mix_speech(seg)
    _encode_audio(ast, out, seg.astype(np.float32))
    out.close()
    print(f"AV 成片 -> {out_path} ({out_path.stat().st_size/1024/1024:.2f}MB)")


def latest_bgm() -> Path | None:
    cands = sorted((COMFY_OUT.parent / "story_audio").glob("bgm_steampunk_*.flac"))
    return cands[-1] if cands else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["concat", "native", "bgm", "all"])
    ap.add_argument("--bgm", default=None, help="BGM 文件路径，缺省用最新 story_audio/bgm_steampunk_*.flac")
    args = ap.parse_args()

    bgm = Path(args.bgm) if args.bgm else latest_bgm()
    print(f"BGM: {bgm if bgm and bgm.exists() else '(无)'}")

    if args.stage in ("concat", "all"):
        concat_video("wan22", WAN_DIR / "final_wan22_silent.mp4")

    if args.stage in ("native", "all"):
        native_concat("minimax_h3", MM_DIR / "final_minimax_native.mp4")

    if args.stage in ("bgm", "all"):
        if not (bgm and bgm.exists()):
            print("[FAIL] 未找到 BGM，先跑 scripts/submit_bgm.py", file=sys.stderr)
            return 1
        bgm_mux(WAN_DIR / "final_wan22_silent.mp4", bgm, WAN_DIR / "final_wan22_bgm.mp4")

    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
