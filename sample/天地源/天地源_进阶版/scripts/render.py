# -*- coding: utf-8 -*-
"""画面合成（进阶版）：真实动态片段为主，静态关键帧为兜底。

流程：
  1. 每个镜头读入本地 ComfyUI 生成的 mp4（832x480/24fps），
     按目标时长做时间重映射（73 帧 → 6~8 秒的慢镜），帧间线性混合避免跳帧。
  2. 统一调色：以园景镜头的中位色统计为基准，每个镜头算一组固定偏移后整段套用，
     这样动态片段与静态关键帧之间不会“一镜一色”，也不会逐帧漂移。
  3. 氛围：双层漂移雾（按镜头强度）、胶片颗粒、暗角 + 底部压暗（保证字幕可读）。
  4. 字幕按绝对时间出现（跟旁白入点对齐），不再随镜头切片。
  5. 转场：默认 0.72s 叠化；三界/地狱等节点用轻微过黑，避免硬切。

运行：python scripts\\render.py            # 全片
      $env:TEST="1"; python scripts\\render.py   # 只渲染第一个镜头自检
产出：build\\video_noaudio.mp4
"""
import json, math, os, subprocess, sys
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (BASE, BUILD, IMG, CLIPS, SHOTS, FPS, W, H, XFADE, FFMPEG)

cv2.setNumThreads(4)
tl = json.load(open(os.path.join(BUILD, "timeline.json"), encoding="utf-8"))
rep = json.load(open(os.path.join(BUILD, "tts_report.json"), encoding="utf-8"))
DURS, STARTS, NARR, TOTAL = tl["durs"], tl["starts"], tl["narr_at"], tl["total"]
SPEECH = tl["speech"]
TEXTS = [l["text"] for l in rep["lines"]]
N = len(SHOTS)
OV = int(round(XFADE * FPS))
DIP = [0.0, 0.0, 0.0, 0.0, 0.0, 0.22, 0.34, 0.0, 0.0, 0.36, 0.18]

# 目标暗度弧线（沿用 v1 的手工标定，保证 11 个镜头亮度连贯）
TARGET_LS = [66, 64, 62, 64, 70, 46, 64, 56, 48, 46, 46]
TARGET_STD = 52.0


def rd(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def lab_stats(im):
    lab = cv2.cvtColor(im, cv2.COLOR_BGR2LAB).astype(np.float32)
    return [lab[..., i].mean() for i in range(3)] + [lab[..., 0].std()]


# ---------- 统一调色：每个镜头算一组固定变换 ----------
garden = [0, 1, 2, 6, 10]
ref = [np.median([lab_stats(rd(os.path.join(IMG, SHOTS[i]["img"] + ".jpg")))[k]
                  for i in garden]) for k in range(4)]
TARGET_L, TARGET_A, TARGET_B = ref[0], ref[1] - 128, ref[2] - 128


def shot_transform(probe, idx):
    lab = cv2.cvtColor(probe, cv2.COLOR_BGR2LAB).astype(np.float32)
    m = lab[..., 0].mean()
    s = max(lab[..., 0].std(), 1.0)
    gain = 1 + 0.28 * (TARGET_STD / s - 1)
    tl_ = TARGET_LS[idx]
    kL = 0.78 if idx in (5, 9) else 0.90
    da = (TARGET_A + 128) - lab[..., 1].mean()
    db = (TARGET_B + 128) - lab[..., 2].mean()
    return dict(m=m, gain=gain, target=tl_, kL=kL, da=da * 0.72, db=db * 0.72)


def apply_transform(im, p):
    lab = cv2.cvtColor(im, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = (lab[..., 0] - p["m"]) * p["gain"] + p["m"]
    L = L + (p["target"] - p["m"]) * p["kL"]
    lab[..., 0] = L
    lab[..., 1] += p["da"]
    lab[..., 2] += p["db"]
    np.clip(lab, 0, 255, out=lab)
    return cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)


def film_grade(img):
    x = img.astype(np.float32) / 255.0
    lum = (x[..., 2] * 0.299 + x[..., 1] * 0.587 + x[..., 0] * 0.114)[..., None]
    x = (x - 0.5) * 1.045 + 0.5
    x = x * 0.975 + 0.012
    x = lum + (x - lum) * 0.87
    x[..., 0] += lum[..., 0] * 0.013
    x[..., 2] += (1 - lum[..., 0]) * 0.030
    x[..., 1] += (1 - lum[..., 0]) * 0.010
    return np.clip(x * 255.0, 0, 255).astype(np.uint8)


# ---------- 素材：动态片段 → 1080p 帧序列 ----------
def to_hd(frame):
    """832x480 → 1920x1080，等比放大后中心裁切（不拉伸）"""
    sc = W / frame.shape[1]
    h2 = int(round(frame.shape[0] * sc))
    im = cv2.resize(frame, (W, h2), interpolation=cv2.INTER_CUBIC)
    if h2 > H:
        y0 = (h2 - H) // 2
        im = im[y0:y0 + H]
    elif h2 < H:
        pad = (H - h2) // 2
        im = cv2.copyMakeBorder(im, pad, H - h2 - pad, 0, 0, cv2.BORDER_REPLICATE)
    return im


def read_clip(path):
    cap = cv2.VideoCapture(path)
    frames = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        frames.append(fr)
    cap.release()
    return frames


def build_shot(idx):
    s = SHOTS[idx]
    ntarget = int(round(DURS[idx] * FPS))
    clip_path = os.path.join(CLIPS, (s["clip"] + ".mp4") if s["clip"] else "__none__")
    if s["clip"] and os.path.exists(clip_path):
        src = read_clip(clip_path)
        probe = src[len(src) // 2]
        par = shot_transform(probe, idx)
        nsrc = len(src)
        out = np.empty((ntarget, H, W, 3), dtype=np.uint8)
        for j in range(ntarget):
            pos = j * (nsrc - 1) / max(ntarget - 1, 1)
            i0 = int(math.floor(pos))
            i1 = min(i0 + 1, nsrc - 1)
            w = pos - i0
            fr = (src[i0].astype(np.float32) * (1 - w) + src[i1].astype(np.float32) * w)
            im = to_hd(fr.astype(np.uint8))
            out[j] = film_grade(apply_transform(im, par))
        print(f"  {s['key']} clip {nsrc}f → {ntarget}f  slow×{ntarget/nsrc:.2f}", flush=True)
        return out
    # 兜底：静态关键帧 + 缓动推拉
    im = rd(os.path.join(IMG, s["img"] + ".jpg"))
    im = film_grade(apply_transform(im, shot_transform(im, idx)))
    plate = cv2.resize(im, (W * 2, H * 2), interpolation=cv2.INTER_LANCZOS4)
    out = np.empty((ntarget, H, W, 3), dtype=np.uint8)
    for j in range(ntarget):
        u = j / max(ntarget - 1, 1)
        e = 0.5 - 0.5 * math.cos(math.pi * u)
        z = s["z"][0] + (s["z"][1] - s["z"][0]) * e
        cx = (s["c0"][0] + (s["c1"][0] - s["c0"][0]) * e) * W * 2
        cy = (s["c0"][1] + (s["c1"][1] - s["c0"][1]) * e) * H * 2
        hw, hh = W / z, H / z
        cx = min(max(cx, hw), 2 * W - hw)
        cy = min(max(cy, hh), 2 * H - hh)
        M = np.array([[1 / z, 0, W / 2 - cx / z], [0, 1 / z, H / 2 - cy / z]], np.float32)
        out[j] = cv2.warpAffine(plate, M, (W, H), flags=cv2.INTER_CUBIC,
                                borderMode=cv2.BORDER_REFLECT)
    print(f"  {s['key']} still → {ntarget}f", flush=True)
    return out


# ---------- 氛围 ----------
def make_fog(w, h, seed, scale=10):
    rng = np.random.default_rng(seed)
    n = rng.normal(0, 1, (max(2, h // scale), max(2, w // scale))).astype(np.float32)
    n = cv2.resize(n, (w, h), interpolation=cv2.INTER_CUBIC)
    n = cv2.GaussianBlur(n, (0, 0), sigmaX=w / 30, sigmaY=h / 30)
    n = (n - n.min()) / (n.max() - n.min() + 1e-6)
    n = np.clip((n - 0.45) * 2.4, 0, 1) ** 1.25
    return n.astype(np.float32)


FW, FH = W + 420, H + 100
fogA = make_fog(FW, FH, 11, scale=6)
fogB = make_fog(FW, FH, 29, scale=9)
yy = np.linspace(0, 1, H, dtype=np.float32)[:, None]
VMASK = (np.clip((yy - 0.22) / 0.55, 0, 1) ** 1.5)
VMASK = np.tile(VMASK, (1, W)).astype(np.float32)

x = np.linspace(-1, 1, W, dtype=np.float32)[None, :]
y = np.linspace(-1, 1, H, dtype=np.float32)[:, None]
r = np.sqrt(x ** 2 * 0.82 + y ** 2)
vig = np.clip(1.0 - 0.30 * np.clip((r - 0.45) / 0.85, 0, 1) ** 1.6, 0, 1)
yg = np.linspace(0, 1, H, dtype=np.float32)
bot = np.clip((yg - 0.66) / 0.34, 0, 1) ** 1.7
vig = vig * (1.0 - 0.30 * bot)[:, None]
VIG = np.dstack([(vig * 255)] * 3).astype(np.uint8)

rng = np.random.default_rng(5)
GRAIN = [rng.normal(0, 1.7, (H, W, 1)).repeat(3, axis=2).astype(np.int16) for _ in range(10)]

# ---------- 字幕 ----------
FONT = ImageFont.truetype(r"C:\Windows\Fonts\STSONG.TTF", 42)
SUB_Y = H - 170


def wrap(text, maxlen=26):
    parts, cur = [], ""
    for ch in text:
        cur += ch
        if ch in "，。：——？" and len(cur) >= maxlen - 6:
            parts.append(cur)
            cur = ""
    if cur:
        parts.append(cur)
    out = []
    for p in parts:
        while len(p) > maxlen:
            out.append(p[:maxlen])
            p = p[maxlen:]
        out.append(p)
    if len(out) > 2:
        out = [out[0], "".join(out[1:])]
    return out


def sub_image(text):
    lines = wrap(text)
    im = Image.new("RGBA", (W, 58 * len(lines) + 26), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        bb = d.textbbox((0, 0), ln, font=FONT)
        px = (W - (bb[2] - bb[0])) // 2
        py = 8 + i * 58
        d.text((px + 2, py + 2), ln, font=FONT, fill=(0, 0, 0, 160))
        d.text((px, py), ln, font=FONT, fill=(238, 235, 228, 255))
    arr = np.array(im)
    return arr[..., [2, 1, 0, 3]].astype(np.float32)


SUBS = [sub_image(t) for t in TEXTS]


def sub_at(t):
    """返回 (idx, alpha)：按绝对时间决定当前字幕和透明度"""
    for i in range(N):
        a = NARR[i] - 0.15
        b = NARR[i] + SPEECH[i] + 0.55
        if a <= t <= b:
            al = min(1.0, (t - a) / 0.35, (b - t) / 0.35)
            return i, max(0.0, al)
    return -1, 0.0


def montage_sub(fr, idx, alpha):
    im = SUBS[idx]
    h, w = im.shape[:2]
    y0 = SUB_Y
    roi = fr[y0:y0 + h, 0:w].astype(np.float32)
    al = (im[..., 3:4] / 255.0) * alpha
    fr[y0:y0 + h, 0:w] = (roi * (1 - al) + im[..., :3] * al).astype(np.uint8)
    return fr


def atmos(fr, idx, t_local, j):
    s = SHOTS[idx]
    if s["fog"] > 0:
        ox = int(t_local * 7.5 + SUM_DURS_BEFORE[idx] * 40) % (FW - W)
        oy = int(t_local * 1.8) % (FH - H)
        a1 = fogA[oy:oy + H, ox:ox + W] * VMASK * s["fog"] * 0.78
        fr = fr.astype(np.float32) * (1 - a1[..., None]) + np.array([205, 208, 212], np.float32) * a1[..., None]
        ox2 = int(t_local * 3.2 + 61) % (FW - W)
        a2 = fogB[0:H, ox2:ox2 + W] * VMASK * s["fog"] * 0.55
        fr = fr * (1 - a2[..., None]) + np.array([196, 200, 206], np.float32) * a2[..., None]
        fr = fr.astype(np.uint8)
    fr = cv2.multiply(fr, VIG, scale=1 / 255.0)
    fr = np.clip(fr.astype(np.int16) + GRAIN[j % 10], 0, 255).astype(np.uint8)
    return fr


SUM_DURS_BEFORE = [0.0] + [sum(DURS[:i]) for i in range(1, N)]

TEST = os.environ.get("TEST") == "1"
out_path = os.path.join(BUILD, "test.mp4" if TEST else "video_noaudio.mp4")
cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
       "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
       "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "20",
       "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path]
PROC = subprocess.Popen(cmd, stdin=subprocess.PIPE)

total_frames = int(round(TOTAL * FPS))
fade_in, fade_out = int(1.6 * FPS), int(2.8 * FPS)
prev_tail = None
done = 0

for i in range(N):
    if TEST and i > 0:
        break
    frames = build_shot(i)
    nframes = len(frames)
    tail = []
    for j in range(nframes):
        t_local = j / FPS
        t_abs = STARTS[i] + t_local
        fr = atmos(frames[j], i, t_local, j)
        if i > 0 and j < OV and prev_tail is not None and j < len(prev_tail):
            a = 0.5 - 0.5 * math.cos(math.pi * (j + 1) / OV)
            if DIP[i] > 0:
                w = math.sin(math.pi * a)
                fr = (fr.astype(np.float32) * (1 - DIP[i] * 0.55 * w)).astype(np.uint8)
            prev = (prev_tail[j].astype(np.float32) * (1 - DIP[i] * 0.55 * math.sin(math.pi * a)))
            fr = cv2.addWeighted(prev.astype(np.uint8), 1 - a, fr, a, 0)
        si, sa = sub_at(t_abs)
        if si >= 0:
            fr = montage_sub(fr, si, sa)
        if j >= nframes - OV:
            tail.append(fr)
            continue
        g = 1.0
        if done < fade_in:
            g = 0.5 - 0.5 * math.cos(math.pi * done / fade_in)
        elif done > total_frames - fade_out:
            g = 0.5 - 0.5 * math.cos(math.pi * (total_frames - done) / fade_out)
        PROC.stdin.write((np.clip(fr * g, 0, 255).astype(np.uint8)).tobytes())
        done += 1
        if done % 120 == 0:
            print("frames", done, "/", total_frames, flush=True)
    prev_tail = tail

for fr in prev_tail:
    g = 1.0
    if done > total_frames - fade_out:
        g = 0.5 - 0.5 * math.cos(math.pi * (total_frames - done) / fade_out)
    PROC.stdin.write((np.clip(fr * g, 0, 255).astype(np.uint8)).tobytes())
    done += 1

PROC.stdin.close()
PROC.wait()
print("done", out_path, done)
