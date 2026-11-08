# -*- coding: utf-8 -*-
r"""1080p 合成：镜头叠化 + 轻家庭录像调色/颗粒 + 结尾硬切黑屏 + 混音封装。

运行： python render.py
产物： build\video_noaudio.mp4、out\午后生活_30s_1080p.mp4
"""
from __future__ import annotations

import json, subprocess, sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import zwj_config as C  # noqa: E402

TL = json.load(open(Path(C.BUILD) / "timeline.json", encoding="utf-8"))
DURS, STARTS, TOTAL = TL["durs"], TL["starts"], TL["total"]
XF = TL["xfade"]
XF_F = int(round(XF * C.FPS))

_x = np.linspace(0, 1, 256)
_c = np.clip(1.0 / (1.0 + np.exp(-(_x - 0.5) * 3.2)), 0, 1)
_c = (_c - _c[0]) / (_c[-1] - _c[0])
LUT = (np.clip(_c * 0.94 + 0.030, 0, 1) * 255).astype(np.uint8)

_yy, _xx = np.mgrid[0:C.H, 0:C.W].astype(np.float32)
_rr = np.sqrt(((_xx - C.W / 2) / (C.W / 2)) ** 2 + ((_yy - C.H / 2) / (C.H / 2)) ** 2)
VIG = np.clip(1.06 - 0.12 * _rr ** 2.4, 0.93, 1.0).astype(np.float32)
_rng = np.random.default_rng(2026)
GRAIN = [_rng.standard_normal((C.H, C.W)).astype(np.float32) for _ in range(8)]


def read_clip(path: Path) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    fs = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        fs.append(fr)
    cap.release()
    return fs


def to_frame(fr: np.ndarray) -> np.ndarray:
    """等比放大到 1080p，按 16:9 中心裁切（源为 16:9 时只做轻微裁边）。"""
    h, w = fr.shape[:2]
    target_ar = C.W / C.H
    if abs(w / h - target_ar) > 0.002:
        nw = int(round(h * target_ar))
        x0 = max(0, (w - nw) // 2)
        fr = fr[:, x0:x0 + nw]
    return cv2.resize(fr, (C.W, C.H), interpolation=cv2.INTER_LANCZOS4)


def grade(img: np.ndarray, fi: int) -> np.ndarray:
    f = img.astype(np.float32) / 255.0
    f = np.clip(f * 1.015, 0, 1)
    g = f.mean(2, keepdims=True)
    f = np.clip(g + (f - g) * 1.045, 0, 1)           # 轻微提饱和
    high = g ** 2
    shadow = (1 - g) ** 2
    f[..., 2] = np.clip(f[..., 2] + 0.012 * high[..., 0] - 0.006 * shadow[..., 0], 0, 1)  # 暖高光
    f[..., 0] = np.clip(f[..., 0] + 0.010 * shadow[..., 0], 0, 1)                         # 冷阴影
    out = LUT[(f * 255).astype(np.uint8)].astype(np.float32)
    out = (out + GRAIN[fi % 8][..., None] * 2.2) * VIG[..., None]
    return np.clip(out, 0, 255).astype(np.uint8)


def black() -> np.ndarray:
    return np.zeros((C.H, C.W, 3), np.uint8)


def main() -> int:
    raw = Path(C.BUILD) / "video_noaudio.mp4"
    cmd = [C.FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{C.W}x{C.H}",
           "-r", str(C.FPS), "-i", "-", "-an",
           "-c:v", "libx264", "-crf", "18", "-preset", "slow",
           "-pix_fmt", "yuv420p", str(raw)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    for si, s in enumerate(C.SHOTS):
        clip = Path(C.CLIPS) / f"{s['clip']}.mp4"
        frames = read_clip(clip)
        need = int(round(DURS[si] * C.FPS))
        if not frames:
            raise SystemExit(f"片段为空：{clip}")
        if len(frames) < need:
            frames += [frames[-1]] * (need - len(frames))
        frames = [grade(to_frame(f), int(STARTS[si] * C.FPS) + k) for k, f in enumerate(frames[:need])]
        last = si == len(C.SHOTS) - 1
        # 硬切：每镜只写 need-XF_F 帧（叠化区计入时间轴但不做画面混合），避免景别突变重影
        keep = need if last else need - XF_F

        if si == 0:
            fade = max(1, int(0.5 * C.FPS))
            for k in range(keep):
                img = frames[k]
                if k < fade:
                    a = k / fade
                    img = cv2.addWeighted(black(), 1 - a, img, a, 0)
                proc.stdin.write(img.tobytes())
        else:
            for k in range(keep):
                proc.stdin.write(frames[k].tobytes())
        print(f"[{s['id']}] {keep}f ok", flush=True)

    for _ in range(int(round(C.END_BLACK * C.FPS))):
        proc.stdin.write(black().tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg 编码失败")

    master = Path(C.AUDIO) / "master.wav"
    subprocess.run([C.FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(Path(C.AUDIO) / "mix.wav"),
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", str(C.SR), str(master)], check=True)

    out = Path(C.OUT) / "午后生活_30s_1080p.mp4"
    subprocess.run([C.FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(raw), "-i", str(master),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart", str(out)], check=True)
    print("out ->", out, round(out.stat().st_size / 1e6, 1), "MB", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
