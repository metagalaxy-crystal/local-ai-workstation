# -*- coding: utf-8 -*-
r"""v2 电影化合成（去光流版）：
  直接用 H3 原始片段（145帧 = 6.04s），不再光流慢放。
  145帧 1120×480 → Lanczos 升到 1920 宽 → 中心裁到 2.39:1 有效画面 (804高)
  → 胶片洗印感（S 曲线/青橙分离色调/光晕/颗粒/片门微晃/色散）
  → 底部黑边字幕（与旁白对齐）
  → 镜头叠化（XFADE=0.60s）
  → 片尾标题卡 + 片头片尾淡入淡出
 输出 build\video_noaudio.mp4（1080p24，CRF20）。
用法： python scripts\render.py
"""
import json, os, sys, subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from txh_config import (BASE, BUILD, CLIPS, TXT, SHOTS, FPS, W, H, SCOPE_H,
                        FFMPEG, DIP, END_CARD, TITLE, SUBTITLE, CLIP_LEN)  # noqa: E402

TL = json.load(open(os.path.join(BUILD, "timeline.json"), encoding="utf-8"))
DURS, STARTS, NARR = TL["durs"], TL["starts"], TL["narr_at"]
TOTAL = TL["total"]
XF = TL["xfade"]
XF_F = int(round(XF * FPS))
TOTAL_F = int(round(TOTAL * FPS))
CARD_F = int(round(END_CARD * FPS))
BODY_F = TOTAL_F - CARD_F

FONT = ImageFont.truetype("STSONG.TTF", 40)
FONT_TITLE = ImageFont.truetype("STSONG.TTF", 68)
FONT_SUB = ImageFont.truetype("STSONG.TTF", 34)
SUB_FADE = 0.35


# ---------- 读取片段 ----------

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

_x = np.linspace(0, 1, 256)
_curve = np.clip(1.0 / (1.0 + np.exp(-(_x - 0.47) * 5.2)), 0, 1)
_curve = (_curve - _curve[0]) / (_curve[-1] - _curve[0])
_curve = np.clip(_curve * 0.92 + 0.045, 0, 1)
LUT = (_curve * 255).astype(np.uint8)

def _ca_maps(w, h, amt=1.2):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2, h / 2
    dx = (xx - cx) / cx
    dy = (yy - cy) / cy
    r = np.sqrt(dx * dx + dy * dy)
    return (xx + dx * r * amt).astype(np.float32), (yy + dy * r * amt).astype(np.float32), \
           (xx - dx * r * amt).astype(np.float32), (yy - dy * r * amt).astype(np.float32)

CA = None

_rng = np.random.default_rng(2019)
GRAIN_TILES = [_rng.standard_normal((SCOPE_H, W)).astype(np.float32) for _ in range(10)]

_yy, _xx = np.mgrid[0:SCOPE_H, 0:W].astype(np.float32)
_rr = np.sqrt(((_xx - W / 2) / (W / 2)) ** 2 + ((_yy - SCOPE_H / 2) / (SCOPE_H / 2)) ** 2)
VIG = np.clip(1.10 - 0.30 * _rr ** 2.2, 0.72, 1.0).astype(np.float32)

_weave = np.cumsum(_rng.standard_normal(TOTAL_F + 48) * 0.05)
_weave = np.convolve(_weave, np.ones(25) / 25, mode="same")
WEAVE = np.clip(_weave, -0.6, 0.6).astype(np.float32)


def film_grade(img):
    global CA
    h, w = img.shape[:2]
    if CA is None or CA[0].shape[1] != w:
        CA = _ca_maps(w, h)
    f = img.astype(np.float32) / 255.0
    f = np.clip(f * 1.04, 0, 1)
    shadow = (1 - f.mean(2, keepdims=True)) ** 2
    high = f.mean(2, keepdims=True) ** 2
    f[..., 0] = np.clip(f[..., 0] + 0.020 * shadow[..., 0] - 0.012 * high[..., 0], 0, 1)
    f[..., 2] = np.clip(f[..., 2] - 0.016 * shadow[..., 0] + 0.018 * high[..., 0], 0, 1)
    g = f.mean(2, keepdims=True)
    f = np.clip(g + (f - g) * 0.88, 0, 1)
    img8 = LUT[(f * 255).astype(np.uint8)]
    f = img8.astype(np.float32) / 255.0
    lum = f.max(2)
    mask = np.clip((lum - 0.72) / 0.28, 0, 1) ** 2
    halo = cv2.GaussianBlur(mask, (0, 0), 9)
    f[..., 2] = np.clip(f[..., 2] + halo * 0.16, 0, 1)
    f[..., 1] = np.clip(f[..., 1] + halo * 0.05, 0, 1)
    pts = np.clip((lum - 0.88) / 0.12, 0, 1) ** 3
    streak = cv2.GaussianBlur(pts, (0, 0), sigmaX=42, sigmaY=1.2)
    f[..., 0] = np.clip(f[..., 0] + streak * 0.20, 0, 1)
    f[..., 2] = np.clip(f[..., 2] + streak * 0.10, 0, 1)
    return (np.clip(f, 0, 1) * 255).astype(np.uint8)


def finalize_frame(img, fi):
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


def apply_fades(canvas, fi):
    g = 1.0
    fi_in = int(0.8 * FPS)
    if fi < fi_in:
        g = (fi + 1) / (fi_in + 1)
    out_start = TOTAL_F - int(1.0 * FPS)
    if fi >= out_start:
        g = min(g, max(0.0, (TOTAL_F - fi) / (TOTAL_F - out_start)))
    if g < 1.0:
        canvas = (canvas.astype(np.float32) * g).astype(np.uint8)
    return canvas


def content_resize(fr):
    """原始分辨率（1120×480 或其他）→ 1920 宽 → 中心裁到 804 高"""
    up = cv2.resize(fr, (W, int(fr.shape[0] * W / fr.shape[1])), interpolation=cv2.INTER_LANCZOS4)
    y0 = max(0, (up.shape[0] - SCOPE_H) // 2)
    return up[y0:y0 + SCOPE_H]


def _wrap_text(dr, txt):
    if dr.textlength(txt, font=FONT) <= W * 0.86:
        return [txt]
    mid = len(txt) // 2
    best = None
    for k in range(len(txt)):
        for j in (mid + k, mid - k):
            if 0 < j < len(txt) and txt[j - 1] in "，。；？！、":
                best = j; break
        if best: break
    j = best or mid
    return [txt[:j], txt[j:]]


def draw_sub(canvas, t):
    for i, na in enumerate(NARR):
        dur = DURS[i] - 0.90    # 旁白在镜头后 0.45s 入，时长到镜头前 0.45s
        if na - SUB_FADE <= t <= na + dur + SUB_FADE:
            a = min(1.0, (t - (na - SUB_FADE)) / SUB_FADE,
                        ((na + dur + SUB_FADE) - t) / SUB_FADE)
            a = max(0.0, a)
            txt = TXT[i + 1]
            pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
            dr = ImageDraw.Draw(pil)
            lines = _wrap_text(dr, txt)
            y_base = H - (H - SCOPE_H) // 4 - 26
            if len(lines) > 1:
                y_base -= 30
            alpha = int(255 * a)
            for li, ln in enumerate(lines):
                bw = dr.textlength(ln, font=FONT)
                x = (W - bw) / 2
                y = y_base + li * 54
                dr.text((x + 2, y + 2), ln, font=FONT, fill=(0, 0, 0, alpha))
                dr.text((x, y), ln, font=FONT, fill=(235, 235, 228, alpha))
            return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return canvas


def card_frame(k):
    fi_in = int(0.6 * FPS)
    fi_out = CARD_F - int(0.6 * FPS)
    if k < fi_in:
        a = k / fi_in
    elif k >= fi_out:
        a = max(0.0, (CARD_F - k) / (CARD_F - fi_out))
    else:
        a = 1.0
    canvas = np.zeros((H, W, 3), np.float32)
    canvas += _rng.standard_normal((H, W, 1)).astype(np.float32) * 1.6
    canvas = np.clip(canvas, 0, 255).astype(np.uint8)
    pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    dr = ImageDraw.Draw(pil)
    alpha = int(255 * a)
    bw = dr.textlength(TITLE, font=FONT_TITLE)
    dr.text(((W - bw) / 2, H / 2 - 78), TITLE, font=FONT_TITLE,
            fill=(232, 230, 222, alpha))
    bw2 = dr.textlength(SUBTITLE, font=FONT_SUB)
    dr.text(((W - bw2) / 2, H / 2 + 26), SUBTITLE, font=FONT_SUB,
            fill=(150, 148, 140, alpha))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


# ---------- 主流程 ----------

def main():
    tmp = os.path.join(BUILD, "video_raw.mp4")
    final = os.path.join(BUILD, "video_noaudio.mp4")
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    prev_tail = None
    prev_dip = 0.0

    for si, s in enumerate(SHOTS):
        # 每个镜头需要的帧数 = duration × FPS
        need_f = int(round(DURS[si] * FPS))
        clip_path = os.path.join(CLIPS, s["clip"] + ".mp4")
        frames = read_clip(clip_path)
        print(f"[{s['key']}] 片段 {len(frames)}f → 需要 {need_f}f 直接用", flush=True)

        if len(frames) == 0:
            print(f"  !! {s['key']} 片段为空，跳过")
            continue

        # 直接用原始帧；如果不够就在尾部做缓慢衰减的"定格"补足
        if len(frames) < need_f:
            # 最后几帧做成渐变定格（最后 10 帧 + 逐帧叠加极轻微噪点）
            tail = frames[-10:].copy()
            while len(frames) < need_f:
                # 取尾部一帧，叠加极轻微的随机噪点和极细微抖动，避免完美定格感
                src = tail[len(frames) % 10].copy()
                jitter_x = float((np.random.random() - 0.5) * 0.8)
                jitter_y = float((np.random.random() - 0.5) * 0.6)
                M = np.float32([[1, 0, jitter_x], [0, 1, jitter_y]])
                src = cv2.warpAffine(src, M, (src.shape[1], src.shape[0]),
                                     flags=cv2.INTER_LINEAR,
                                     borderMode=cv2.BORDER_REPLICATE)
                noise = (np.random.random(src.shape).astype(np.float32) - 0.5) * 2.0
                src = np.clip(src.astype(np.float32) + noise, 0, 255).astype(np.uint8)
                frames.append(src)
        frames = frames[:need_f]

        frames = [content_resize(f) for f in frames]
        start_f = int(round(STARTS[si] * FPS))

        for k in range(need_f):
            fi = start_f + k
            img = frames[k]
            # 与上一镜尾部叠化（除非是第一镜）
            if prev_tail is not None and k < XF_F:
                a = (k + 1) / (XF_F + 1)
                img = cv2.addWeighted(prev_tail[k], 1 - a, img, a, 0)
                if prev_dip > 0:
                    black = np.zeros_like(img)
                    m = np.sin(np.pi * a) * prev_dip
                    img = cv2.addWeighted(img, 1 - m, black, m, 0)

            img = film_grade(img)
            frames[k] = img

            if k < need_f - XF_F:
                canvas = finalize_frame(img, fi)
                canvas = draw_sub(canvas, fi / FPS)
                canvas = apply_fades(canvas, fi)
                vw.write(canvas)

        # 保存尾部用于下一次叠化
        prev_tail = frames[-XF_F:] if XF_F > 0 else None
        prev_dip = DIP[si] if si + 1 < len(SHOTS) else 0
        print(f"[{s['key']}] done", flush=True)

    # 最后一镜的尾部帧
    if prev_tail is not None:
        li = len(SHOTS) - 1
        base_fi = int(round(STARTS[li] * FPS)) + int(round(DURS[li] * FPS)) - XF_F
        for k, img in enumerate(prev_tail):
            canvas = finalize_frame(img, base_fi + k)
            canvas = draw_sub(canvas, (base_fi + k) / FPS)
            canvas = apply_fades(canvas, base_fi + k)
            vw.write(canvas)

    # 片尾标题卡
    for k in range(CARD_F):
        canvas = card_frame(k)
        canvas = apply_fades(canvas, BODY_F + k)
        vw.write(canvas)

    vw.release()
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", tmp,
                    "-c:v", "libx264", "-crf", "20", "-preset", "slow",
                    "-pix_fmt", "yuv420p", final], check=True)
    os.remove(tmp)
    print("video ->", final, flush=True)


if __name__ == "__main__":
    main()
