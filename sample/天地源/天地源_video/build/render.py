import json, os, subprocess, sys, math
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from filmconfig import SHOTS, FPS, W, H, PW, PH, BASE, OVERLAP

cv2.setNumThreads(4)
BUILD = os.path.join(BASE, "build")
IMG = os.path.join(BASE, "images")
FFMPEG = r"C:\Program Files\EVCapture\ffmpeg.exe"

tl = json.load(open(os.path.join(BUILD, "timeline.json")))
meta = json.load(open(os.path.join(BUILD, "lines.json"), encoding="utf-8"))
LINES = meta["lines"]
DURS, STARTS, NARR_AT, TOTAL = tl["durs"], tl["starts"], tl["narr_at"], tl["total"]
N = len(SHOTS)
OV = int(round(OVERLAP * FPS))


def rd(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


# ---------- colour unification ----------
def stats(im):
    lab = cv2.cvtColor(im, cv2.COLOR_BGR2LAB).astype(np.float32)
    return [lab[..., i].mean() for i in range(3)] + [lab[..., 0].std()]

garden_idx = [0, 1, 2, 6, 10]
ref = [np.median([stats(rd(os.path.join(IMG, SHOTS[i]["img"] + ".jpg"))) [k] for i in garden_idx]) for k in range(4)]
TARGET_L, TARGET_A, TARGET_B, TARGET_STD = ref[0], ref[1] - 128, ref[2] - 128, 52.0
TARGET_LS = [66, 64, 62, 64, 70, 46, 64, 56, 48, 46, 46]
DIPS = [0.0, 0.15, 0.20, 0.25, 0.40, 0.95, 0.90, 0.60, 0.90, 0.80, 0.85]
print("target", round(TARGET_L, 1), round(TARGET_A, 1), round(TARGET_B, 1))


def unify(im, idx):
    lab = cv2.cvtColor(im, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[..., 0]
    m, s = L.mean(), max(L.std(), 1.0)
    L = (L - m) * (1 + 0.28 * (TARGET_STD / s - 1)) + m
    tl_ = TARGET_LS[idx]
    kL = 0.78 if idx in (5, 9) else 0.90
    L = L + (tl_ - m) * kL
    lab[..., 0] = L
    for ch, target, k in ((1, TARGET_A, 0.72), (2, TARGET_B, 0.72)):
        lab[..., ch] = lab[..., ch] + ((target + 128) - lab[..., ch].mean()) * k
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


def plate(idx):
    p = os.path.join(IMG, SHOTS[idx]["img"] + ".jpg")
    im = rd(p)
    im = unify(im, idx)
    im = film_grade(im)
    return cv2.resize(im, (PW, PH), interpolation=cv2.INTER_LANCZOS4)


# ---------- atmosphere ----------
def make_fog(w, h, seed, scale=10):
    rng = np.random.default_rng(seed)
    n = rng.normal(0, 1, (max(2, h // scale), max(2, w // scale))).astype(np.float32)
    n = cv2.resize(n, (w, h), interpolation=cv2.INTER_CUBIC)
    n = cv2.GaussianBlur(n, (0, 0), sigmaX=w / 30, sigmaY=h / 30)
    n = (n - n.min()) / (n.max() - n.min() + 1e-6)
    n = np.clip((n - 0.45) * 2.4, 0, 1) ** 1.25
    return n.astype(np.float32)


FW, FH = W + 460, H + 120
fogA = make_fog(FW, FH, 11, scale=6)
fogB = make_fog(FW, FH, 29, scale=9)

yy = np.linspace(0, 1, H, dtype=np.float32)[:, None]
VMASK = np.clip((yy - 0.22) / 0.55, 0, 1)[:, :] ** 1.5
VMASK = np.tile(VMASK, (1, W)).astype(np.float32)

# vignette
x = np.linspace(-1, 1, W, dtype=np.float32)[None, :]
y = np.linspace(-1, 1, H, dtype=np.float32)[:, None]
r = np.sqrt(x ** 2 * 0.82 + y ** 2)
vig = np.clip(1.0 - 0.30 * np.clip((r - 0.45) / 0.85, 0, 1) ** 1.6, 0, 1)
# bottom falloff for subtitle legibility
yg = np.linspace(0, 1, H, dtype=np.float32)
bot = np.clip((yg - 0.66) / 0.34, 0, 1) ** 1.7
vig = vig * (1.0 - 0.30 * bot)[:, None]
VIG = np.dstack([(vig * 255)] * 3).astype(np.uint8)

# grain tiles
rng = np.random.default_rng(5)
GRAIN = []
for i in range(10):
    g = rng.normal(0, 1.8, (H, W, 1)).repeat(3, axis=2)
    GRAIN.append(g.astype(np.int16))

# ---------- subtitles ----------
FONT = ImageFont.truetype(r"C:\Windows\Fonts\STSONG.TTF", 40)
SUB_Y = H - 128


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
    im = Image.new("RGBA", (W, 56 * len(lines) + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        bb = d.textbbox((0, 0), ln, font=FONT)
        tw = bb[2] - bb[0]
        px = (W - tw) // 2
        py = 10 + i * 56
        d.text((px + 2, py + 2), ln, font=FONT, fill=(0, 0, 0, 150))
        d.text((px, py), ln, font=FONT, fill=(238, 235, 228, 255))
    arr = np.array(im)
    return arr[..., [2, 1, 0, 3]].astype(np.float32)  # BGRA


SUBS = [sub_image(t) for t in LINES]


def ease(u):
    u = min(max(u, 0.0), 1.0)
    return 0.5 - 0.5 * math.cos(math.pi * u)


SHOT_PH = [(np.random.default_rng(100 + i).uniform(0, 6.283, 4)) for i in range(N)]
OOS = 0


def render(pl, i, j, nframes, t_local):
    s = SHOTS[i]
    u = j / max(nframes - 1, 1)
    e = ease(u)
    z0, z1 = s["z"]
    z = z0 + (z1 - z0) * e
    cx = s["c0"][0] + (s["c1"][0] - s["c0"][0]) * e
    cy = s["c0"][1] + (s["c1"][1] - s["c0"][1]) * e
    ph = SHOT_PH[i]
    dx = 0.0016 * math.sin(2 * math.pi * 0.11 * t_local + ph[0]) + 0.0009 * math.sin(2 * math.pi * 0.27 * t_local + ph[1])
    dy = 0.0011 * math.sin(2 * math.pi * 0.09 * t_local + ph[2]) + 0.0007 * math.sin(2 * math.pi * 0.23 * t_local + ph[3])
    z *= 1 + 0.004 * math.sin(2 * math.pi * 0.06 * t_local + ph[0])
    cx += dx / z
    cy += dy / z

    half_w = PW / (2 * z)
    half_h = PH / (2 * z)
    cxp = min(max(cx * PW, half_w), PW - half_w)
    cyp = min(max(cy * PH, half_h), PH - half_h)
    sc = W * z / PW
    M = np.array([[sc, 0, W / 2 - sc * cxp], [0, sc, H / 2 - sc * cyp]], dtype=np.float32)
    fr = cv2.warpAffine(pl, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)

    # fog drift
    if s["fog"] > 0:
        ox = int(t_local * 8 + OOS) % (FW - W)
        oy = int(t_local * 2.0 + OOS * 0.3) % (FH - H)
        a1 = fogA[oy:oy + H, ox:ox + W] * VMASK * s["fog"] * 0.82
        fr = (fr.astype(np.float32) * (1 - a1[..., None]) + np.array([205, 208, 212], np.float32) * a1[..., None])
        ox2 = int(t_local * 3.4 + OOS * 2) % (FW - W)
        a2 = fogB[0:H, ox2:ox2 + W] * VMASK * s["fog"] * 0.6
        fr = (fr * (1 - a2[..., None]) + np.array([196, 200, 206], np.float32) * a2[..., None])
        fr = fr.astype(np.uint8)

    fr = cv2.multiply(fr, VIG, scale=1 / 255.0)
    fr = np.clip(fr.astype(np.int16) + GRAIN[j % 10], 0, 255).astype(np.uint8)
    return fr


def emit(fr, g=1.0):
    if g < 1.0:
        fr = (fr.astype(np.float32) * g).astype(np.uint8)
    PROC.stdin.write(fr.tobytes())


def montage_subs(fr, i, t_local, dur):
    if t_local < 0.45 or t_local > dur - 0.62:
        return fr
    a = min(1.0, (t_local - 0.45) / 0.55, (dur - 0.62 - t_local) / 0.42)
    if a <= 0:
        return fr
    im = SUBS[i]
    h, w = im.shape[:2]
    y0 = H - 172
    roi = fr[y0:y0 + h, 0:w].astype(np.float32)
    al = (im[..., 3:4] / 255.0) * a
    roi = roi * (1 - al) + im[..., :3] * al
    fr[y0:y0 + h, 0:w] = roi.astype(np.uint8)
    return fr


TEST = os.environ.get("TEST") == "1"
out_path = os.path.join(BASE, "build", "test.mp4" if TEST else "video_noaudio.mp4")
cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
       "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
       "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "21",
       "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path]
PROC = subprocess.Popen(cmd, stdin=subprocess.PIPE)

total_frames = int(round(TOTAL * FPS))
fade_in = int(1.9 * FPS)
fade_out = int(3.4 * FPS)
prev_tail = None
done = 0

for i in range(N):
    if TEST and i > 0:
        break
    PL = plate(i)
    nframes = int(round(DURS[i] * FPS))
    OOS = sum(DURS[:i]) * 12
    raw_tail = []
    for j in range(nframes):
        t_local = j / FPS
        fr = render(PL, i, j, nframes, t_local)
        if i > 0 and j < OV and prev_tail is not None:
            a = ease((j + 1) / OV)
            if DIPS[i] >= 0.8:
                # dip-through-black bridge: no double exposure
                if j < OV // 2:
                    k = 1.0 - ease(j / max(OV / 2 - 1, 1))
                    fr = (prev_tail[j].astype(np.float32) * k).astype(np.uint8)
                else:
                    k = ease((j - OV // 2) / max(OV / 2 - 1, 1))
                    fr = (fr.astype(np.float32) * k).astype(np.uint8)
            else:
                fr = cv2.addWeighted(prev_tail[j], 1 - a, fr, a, 0)
                w = math.sin(math.pi * a)
                if DIPS[i] > 0:
                    fr = (fr.astype(np.float32) * (1 - DIPS[i] * w)).astype(np.uint8)
        fr = montage_subs(fr, i, t_local, DURS[i])
        if j >= nframes - OV:
            raw_tail.append(fr)
            continue
        g = 1.0
        if done < fade_in:
            g = ease(done / fade_in)
        elif done > total_frames - fade_out:
            g = ease((total_frames - done) / fade_out)
        emit(fr, g)
        done += 1
        if done % 120 == 0:
            print("frames", done, "/", total_frames, flush=True)
    prev_tail = raw_tail

# flush the held tail of the final shot
for k, fr in enumerate(prev_tail):
    g = 1.0
    if done > total_frames - fade_out:
        g = ease((total_frames - done) / fade_out)
    emit(fr, g)
    done += 1

PROC.stdin.close()
PROC.wait()
print("done", out_path, done)
