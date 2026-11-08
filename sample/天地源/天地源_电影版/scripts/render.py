# -*- coding: utf-8 -*-
r"""电影版画面合成：
光流重定时（Farneback 双向插帧慢放）→ 2.39:1 遮幅 → 胶片洗印感
（S 曲线/青橙分离色调/光晕 halation/变形宽银幕拉丝眩光/颗粒/片门微晃/边缘色散）
→ 底部黑边字幕 → 镜头叠化。输出 build\video_noaudio.mp4（1080p24，CRF20）。
用法： python scripts\render.py        # 全片
       set TEST=1 && python scripts\render.py   # 只渲首镜自检
"""
import json, os, sys, subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from v3_config import BASE, BUILD, CLIPS, LINES, TXT, SHOTS, FPS, W, H, SCOPE_H, FFMPEG  # noqa: E402

TL = json.load(open(os.path.join(BUILD, "timeline.json"), encoding="utf-8"))
DURS, STARTS, NARR = TL["durs"], TL["starts"], TL["narr_at"]
TOTAL = TL["total"]
XF = TL["xfade"]
XF_F = int(round(XF * FPS))
TOTAL_F = int(round(TOTAL * FPS))
TEST = os.environ.get("TEST") == "1"

# 底部黑边字幕（电影遮幅字幕位于下黑边）
FONT = ImageFont.truetype("STSONG.TTF", 40)
SUB_FADE = 0.35

# 过黑镜头（虚无/三界/天堂）：DIP 为叠化中混入黑色的权重
DIP = [0, 0, 0, 0, 0, 0.22, 0.34, 0, 0, 0.36, 0.18]


# ---------- 光流重定时 ----------

def optflow_retime(frames, n_out):
    """frames: list of uint8 (h,w,3)；输出 n_out 帧双向光流插值。"""
    n_in = len(frames)
    if n_in < 2 or n_out <= n_in:
        idx = np.linspace(0, n_in - 1, n_out).round().astype(int)
        return [frames[i] for i in idx]
    small = [cv2.cvtColor(cv2.resize(f, (f.shape[1] // 2, f.shape[0] // 2)),
                          cv2.COLOR_BGR2GRAY) for f in frames]
    flows = []
    for i in range(n_in - 1):
        fl = cv2.calcOpticalFlowFarneback(small[i], small[i + 1], None,
                                          0.5, 3, 15, 3, 5, 1.2, 0)
        flows.append(fl * 2.0)  # 半分辨率 → 全分辨率位移
    out = []
    h, w = frames[0].shape[:2]
    grid_x, grid_y = np.meshgrid(np.arange(w, dtype=np.float32),
                                 np.arange(h, dtype=np.float32))
    for k in range(n_out):
        t = k * (n_in - 1) / max(n_out - 1, 1)
        i = min(int(t), n_in - 2)
        f = t - i
        if f < 1e-4:
            out.append(frames[i])
            continue
        fl = cv2.resize(flows[i], (w, h))
        # 前向：帧 i 沿 flow*f；后向：帧 i+1 沿 -flow*(1-f)
        map1 = (grid_x + fl[..., 0] * f, grid_y + fl[..., 1] * f)
        map2 = (grid_x - fl[..., 0] * (1 - f), grid_y - fl[..., 1] * (1 - f))
        a = cv2.remap(frames[i], map1[0].astype(np.float32), map1[1].astype(np.float32),
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        b = cv2.remap(frames[i + 1], map2[0].astype(np.float32), map2[1].astype(np.float32),
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        out.append(cv2.addWeighted(a, 1 - f, b, f, 0))
    return out


def read_clip(path):
    cap = cv2.VideoCapture(path)
    fs = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        fs.append(fr)
    cap.release()
    return fs


# ---------- 胶片化 ----------

# S 曲线（filmic toe+shoulder 近似）
_x = np.linspace(0, 1, 256)
_curve = np.clip(1.0 / (1.0 + np.exp(-(_x - 0.47) * 5.2)), 0, 1)
_curve = (_curve - _curve[0]) / (_curve[-1] - _curve[0])
_curve = np.clip(_curve * 0.92 + 0.045, 0, 1)  # 抬黑位、压白位
LUT = (_curve * 255).astype(np.uint8)

# 边缘径向色散 remap（R 外扩、B 内收）
def _ca_maps(w, h, amt=1.2):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2, h / 2
    dx = (xx - cx) / cx
    dy = (yy - cy) / cy
    r = np.sqrt(dx * dx + dy * dy)
    mr_x = xx + dx * r * amt
    mr_y = yy + dy * r * amt
    mb_x = xx - dx * r * amt
    mb_y = yy - dy * r * amt
    return (mr_x.astype(np.float32), mr_y.astype(np.float32),
            mb_x.astype(np.float32), mb_y.astype(np.float32))

CA = None  # 按内容尺寸惰性初始化

# 胶片颗粒（预生成 10 张）
_rng = np.random.default_rng(2022)
GRAIN_TILES = [_rng.standard_normal((SCOPE_H, W)).astype(np.float32) for _ in range(10)]

# 暗角
_yy, _xx = np.mgrid[0:SCOPE_H, 0:W].astype(np.float32)
_rr = np.sqrt(((_xx - W / 2) / (W / 2)) ** 2 + ((_yy - SCOPE_H / 2) / (SCOPE_H / 2)) ** 2)
VIG = np.clip(1.10 - 0.30 * _rr ** 2.2, 0.72, 1.0).astype(np.float32)

# 片门微晃：慢随机游走
_weave = np.cumsum(_rng.standard_normal(TOTAL_F + 48) * 0.05)
_weave = np.convolve(_weave, np.ones(25) / 25, mode="same")
WEAVE = np.clip(_weave, -0.6, 0.6).astype(np.float32)


def film_grade(img):
    """img uint8 BGR（内容区 1920x804）→ 胶片化 uint8 BGR"""
    global CA
    h, w = img.shape[:2]
    if CA is None or CA[0].shape[1] != w:
        CA = _ca_maps(w, h)
    f = img.astype(np.float32) / 255.0
    # 曝光与分离色调：暗部偏青、高光偏暖
    f = np.clip(f * 1.04, 0, 1)
    shadow = (1 - f.mean(2, keepdims=True)) ** 2
    high = f.mean(2, keepdims=True) ** 2
    f[..., 0] = np.clip(f[..., 0] + 0.020 * shadow[..., 0] - 0.012 * high[..., 0], 0, 1)
    f[..., 2] = np.clip(f[..., 2] - 0.016 * shadow[..., 0] + 0.018 * high[..., 0], 0, 1)
    # 轻降饱和
    g = f.mean(2, keepdims=True)
    f = np.clip(g + (f - g) * 0.88, 0, 1)
    img8 = LUT[(f * 255).astype(np.uint8)]
    f = img8.astype(np.float32) / 255.0
    # halation：高光红橙光晕
    lum = f.max(2)
    mask = np.clip((lum - 0.72) / 0.28, 0, 1) ** 2
    halo = cv2.GaussianBlur(mask, (0, 0), 9)
    f[..., 2] = np.clip(f[..., 2] + halo * 0.16, 0, 1)
    f[..., 1] = np.clip(f[..., 1] + halo * 0.05, 0, 1)
    # 变形宽银幕拉丝眩光：极亮点横向拉丝（青蓝）
    pts = np.clip((lum - 0.88) / 0.12, 0, 1) ** 3
    streak = cv2.GaussianBlur(pts, (0, 0), sigmaX=42, sigmaY=1.2)
    f[..., 0] = np.clip(f[..., 0] + streak * 0.20, 0, 1)
    f[..., 2] = np.clip(f[..., 2] + streak * 0.10, 0, 1)
    return (np.clip(f, 0, 1) * 255).astype(np.uint8)


def finalize_frame(img, fi):
    """色散 + 颗粒 + 暗角 + 片门微晃 + 遮幅。img 为内容区 uint8"""
    b, g, r = cv2.split(img)
    r = cv2.remap(r, CA[0], CA[1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    b = cv2.remap(b, CA[2], CA[3], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    img = cv2.merge((b, g, r)).astype(np.float32)
    img += GRAIN_TILES[fi % 10][..., None] * 5.0
    img *= VIG[..., None]
    img = np.clip(img, 0, 255).astype(np.uint8)
    dx = float(WEAVE[fi % len(WEAVE)])
    M = np.float32([[1, 0, dx], [0, 1, dx * 0.6]])
    img = cv2.warpAffine(img, M, (img.shape[1], img.shape[0]),
                         flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    canvas = np.zeros((H, W, 3), np.uint8)
    y0 = (H - SCOPE_H) // 2
    canvas[y0:y0 + SCOPE_H] = img
    return canvas


def content_resize(fr):
    """1120x480 → 1920 宽，中心裁到 1920x804（2.39:1）"""
    up = cv2.resize(fr, (W, int(fr.shape[0] * W / fr.shape[1])), interpolation=cv2.INTER_LANCZOS4)
    y0 = max(0, (up.shape[0] - SCOPE_H) // 2)
    return up[y0:y0 + SCOPE_H]


def draw_sub(canvas, t):
    """在下黑边绘制字幕（绝对时间对齐旁白入点）"""
    for i, na in enumerate(NARR):
        dur = TL["speech"][i]
        if na - SUB_FADE <= t <= na + dur + SUB_FADE:
            a = min(1.0, (t - (na - SUB_FADE)) / SUB_FADE,
                        ((na + dur + SUB_FADE) - t) / SUB_FADE)
            a = max(0.0, a)
            txt = TXT[i + 1]
            pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
            dr = ImageDraw.Draw(pil)
            bw = dr.textlength(txt, font=FONT)
            x = (W - bw) / 2
            y = H - (H - SCOPE_H) // 4 - 26
            alpha = int(255 * a)
            dr.text((x + 2, y + 2), txt, font=FONT, fill=(0, 0, 0, alpha))
            dr.text((x, y), txt, font=FONT, fill=(235, 235, 228, alpha))
            return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return canvas


# ---------- 主流程 ----------

def main():
    tmp = os.path.join(BUILD, "video_raw.mp4")
    final = os.path.join(BUILD, "video_noaudio.mp4")
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    prev_tail = None   # 上一镜头末尾 XF_F 帧（已做内容处理，未遮幅）
    prev_dip = 0.0
    shot_ranges = []
    for si, s in enumerate(SHOTS):
        if TEST and si > 0:
            break
        n_out = int(round(DURS[si] * FPS))
        clip_path = os.path.join(CLIPS, s["clip"] + ".mp4")
        frames = read_clip(clip_path)
        print(f"[{s['key']}] {len(frames)}f -> {n_out}f 光流重定时…", flush=True)
        frames = optflow_retime(frames, n_out)
        frames = [content_resize(f) for f in frames]
        start_f = int(round(STARTS[si] * FPS))
        shot_ranges.append((start_f, n_out))
        for k in range(n_out):
            fi = start_f + k
            img = frames[k]
            if prev_tail is not None and k < XF_F:
                a = (k + 1) / (XF_F + 1)
                img = cv2.addWeighted(prev_tail[k], 1 - a, img, a, 0)
                if prev_dip > 0:
                    black = np.zeros_like(img)
                    m = np.sin(np.pi * a) * prev_dip
                    img = cv2.addWeighted(img, 1 - m, black, m, 0)
            img = film_grade(img)
            frames[k] = img
            if k < n_out - XF_F:
                canvas = finalize_frame(img, fi)
                canvas = draw_sub(canvas, fi / FPS)
                vw.write(canvas)
        prev_tail = frames[-XF_F:]
        prev_dip = DIP[si] if si + 1 < len(SHOTS) else 0
        print(f"[{s['key']}] done", flush=True)
    # 片尾：补上最后一镜的尾部帧
    if prev_tail is not None:
        base_fi = int(round(STARTS[min(len(SHOTS) - 1, 10)] * FPS)) + \
            int(round(DURS[min(len(SHOTS) - 1, 10)] * FPS)) - XF_F
        for k, img in enumerate(prev_tail):
            canvas = finalize_frame(img, base_fi + k)
            canvas = draw_sub(canvas, (base_fi + k) / FPS)
            vw.write(canvas)
    vw.release()
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", tmp,
                    "-c:v", "libx264", "-crf", "20", "-preset", "slow",
                    "-pix_fmt", "yuv420p", final], check=True)
    os.remove(tmp)
    print("video ->", final, flush=True)


if __name__ == "__main__":
    main()
