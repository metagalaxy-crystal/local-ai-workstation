# -*- coding: utf-8 -*-
"""分层环境音设计：每个声源独立成 stem，按镜头位置自动推子。

声源：海浪 / 崖风 / 海鸥 / 工业镇 / 衣物猎猎 / 锈海低鸣 / 汽笛 / 机械蜻蜓
  * 蓝海段（town/cliff）：海浪+海鸥+暖风，远景工业低鸣；
  * 转场（trans）：风增强，锈海低鸣渐入，一声远汽笛；
  * 锈海段（rust）：寒风+重浪+低鸣，玛莲风衣猎猎，海鸥消失。

运行：python scripts\\env_audio.py
产出：audio\\stems\\*.wav（48k 立体声）+ build\\stems_report.json
"""
import json, os, sys
import numpy as np
from scipy import signal
from scipy.io import wavfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from txh_config import BASE, BUILD, STEMS, SHOTS

SR = 48000
tl = json.load(open(os.path.join(BUILD, "timeline.json"), encoding="utf-8"))
STARTS, DURS, TOTAL = tl["starts"], tl["durs"], tl["total"]
N = int((TOTAL + 1.2) * SR)
t = np.arange(N) / SR

# 场景 → 各声源目标增益
PLACE = {
    "town":  dict(wind=0.55, waves=0.45, gulls=0.40, industry=0.85),
    "cliff": dict(wind=0.85, waves=1.00, gulls=0.55, industry=0.12, cloth=0.35),
    "trans": dict(wind=0.95, waves=0.80, gulls=0.10, industry=0.25, drone=0.55),
    "rust":  dict(wind=1.00, waves=0.85, industry=0.15, drone=0.75, cloth=0.55),
}
STEM_NAMES = ["wind", "waves", "gulls", "industry", "cloth", "drone", "horn", "buzz"]

rng = np.random.default_rng(2019)


def noise(n, lo, hi, order=2):
    x = rng.normal(0, 1, n)
    sos = signal.butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    y = signal.sosfilt(sos, x)
    return y / (np.std(y) + 1e-9)


def automation(stem):
    """按镜头 place 生成该 stem 的增益曲线，边界用 0.9s 交叉"""
    g = np.zeros(N)
    for i, s in enumerate(SHOTS):
        v = PLACE[s["place"]].get(stem, 0.0)
        a, b = int(STARTS[i] * SR), int((STARTS[i] + DURS[i]) * SR)
        a, b = max(0, a), min(N, b)
        seg = np.ones(b - a) * v
        f = min(int(0.45 * SR), (b - a) // 2)
        if f > 0:
            seg[:f] *= np.linspace(0, 1, f)
            seg[-f:] *= np.linspace(1, 0, f)
        g[a:b] = np.maximum(g[a:b], seg)
    ker = signal.windows.gaussian(int(0.55 * SR), int(0.18 * SR))
    ker /= ker.sum()
    g = signal.fftconvolve(g, ker)[:N]
    g[:int(1.2 * SR)] *= np.linspace(0, 1, int(1.2 * SR))
    g[-int(3.0 * SR):] *= np.linspace(1, 0, int(3.0 * SR)) ** 1.4
    return np.clip(g, 0, 1.4)


def event_stem(events):
    L = np.zeros(N)
    R = np.zeros(N)
    for at, mono, pan, gain in events:
        i0 = int(at * SR)
        if i0 >= N:
            continue
        i1 = min(N, i0 + len(mono))
        L[i0:i1] += mono[:i1 - i0] * (1 - pan) * gain
        R[i0:i1] += mono[:i1 - i0] * pan * gain
    return L, R


# ---------------- 连续声床 ----------------
def make_wind():
    base = noise(N, 35, 240) * 0.55 + noise(N, 240, 900) * 0.30
    hiss = noise(N, 1800, 6500) * 0.12
    tt = np.arange(N) / SR
    gust = (0.45 * np.sin(2 * np.pi * 0.055 * tt) +
            0.30 * np.sin(2 * np.pi * 0.11 * tt + 1.3) +
            0.18 * np.sin(2 * np.pi * 0.21 * tt + 2.6))
    gust = 0.55 + 0.45 * np.tanh(gust * 1.6)
    flutter = 0.85 + 0.15 * np.sin(2 * np.pi * 0.9 * tt)
    l = (base + hiss) * gust * flutter
    r = (noise(N, 35, 240) * 0.55 + noise(N, 240, 900) * 0.30 +
         noise(N, 1800, 6500) * 0.12) * np.roll(gust, int(0.37 * SR)) * flutter
    return l, r, gust


def make_waves():
    """海浪：低频涌动 + 周期性碎浪。"""
    tt = np.arange(N) / SR
    swell = 0.5 + 0.5 * np.sin(2 * np.pi * 0.072 * tt + 0.6)
    swell = swell ** 1.6
    body = noise(N, 60, 420) * (0.45 + 0.55 * swell)
    splash = noise(N, 900, 3400) * (swell ** 3) * 0.5
    l = body + splash
    r = (noise(N, 60, 420) * (0.45 + 0.55 * np.roll(swell, int(0.9 * SR))) +
         noise(N, 900, 3400) * (np.roll(swell, int(0.9 * SR)) ** 3) * 0.5)
    # 碎浪事件
    crashes = []
    at = 2.0
    while at < TOTAL - 2.0:
        n = int(1.6 * SR)
        te = np.arange(n) / SR
        x = rng.normal(0, 1, n)
        sos = signal.butter(2, [240, 2600], btype="band", fs=SR, output="sos")
        x = signal.sosfilt(sos, x)
        env = (1 - np.exp(-te / 0.06)) * np.exp(-te / 0.75)
        crashes.append((at, x * env * 0.55, rng.uniform(0.3, 0.7), 0.5))
        at += rng.uniform(6.5, 11.0)
    cl, cr = event_stem(crashes)
    return l + cl, r + cr


def make_industry():
    """灰炉镇工业远景：低鸣 + 蒸汽嘶声 + 稀疏金属撞击。"""
    rumble = noise(N, 40, 140) * 0.55
    hiss = noise(N, 2800, 6200) * 0.10
    tt = np.arange(N) / SR
    hiss_env = 0.5 + 0.5 * np.sin(2 * np.pi * 0.16 * tt + 2.0)
    l = rumble + hiss * hiss_env
    r = np.roll(rumble, int(0.8 * SR)) * 0.9 + np.roll(hiss, int(0.5 * SR)) * hiss_env
    # 金属撞击
    clanks = []
    at = 1.5
    while at < TOTAL - 1.0:
        n = int(0.5 * SR)
        te = np.arange(n) / SR
        f0 = rng.uniform(380, 720)
        x = sum(a * np.sin(2 * np.pi * f0 * m * te) * np.exp(-te / d)
                for m, a, d in ((1, 1.0, 0.30), (2.76, 0.4, 0.18), (5.40, 0.2, 0.10)))
        x += rng.normal(0, 1, n) * np.exp(-te / 0.008) * 0.4
        clanks.append((at, x * 0.4, rng.uniform(0.25, 0.75), 0.35))
        at += rng.uniform(4.5, 9.0)
    cl, cr = event_stem(clanks)
    return l + cl, r + cr


def make_drone():
    """锈海低鸣：失谐低正弦 + 缓慢脉动，不安感。"""
    tt = np.arange(N) / SR
    pulse = 0.5 + 0.5 * np.sin(2 * np.pi * 0.05 * tt)
    l = (np.sin(2 * np.pi * 55 * tt) * 0.5 +
         np.sin(2 * np.pi * 82.4 * tt) * 0.25 +
         noise(N, 150, 420) * 0.30) * (0.4 + 0.6 * pulse)
    r = (np.sin(2 * np.pi * 55.7 * tt) * 0.5 +
         np.sin(2 * np.pi * 82.9 * tt) * 0.25 +
         noise(N, 150, 420) * 0.30) * (0.4 + 0.6 * np.roll(pulse, int(0.6 * SR)))
    return l * 0.5, r * 0.5


def make_cloth():
    """衣物猎猎：不规则阵风拍的噪声爆发。"""
    l = np.zeros(N)
    r = np.zeros(N)
    at = 0.5
    while at < TOTAL - 0.5:
        dur = rng.uniform(0.16, 0.42)
        n = int(dur * SR)
        te = np.arange(n) / SR
        x = noise(n, 400, 1800)
        flut = 0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(14, 22) * te)
        env = np.sin(np.pi * np.clip(te / dur, 0, 1)) ** 1.3
        pan = rng.uniform(0.35, 0.65)
        g = rng.uniform(0.25, 0.6)
        i0 = int(at * SR)
        i1 = min(N, i0 + n)
        l[i0:i1] += (x * flut * env)[:i1 - i0] * (1 - pan) * g
        r[i0:i1] += (x * flut * env)[:i1 - i0] * pan * g
        at += rng.uniform(0.9, 2.6)
    return l, r


# ---------------- 单发事件 ----------------
def gull(seed=0):
    """远鸥：下行 FM 啁啾 + 两次回声。"""
    r = np.random.default_rng(seed)
    n = int(0.42 * SR)
    tt = np.arange(n) / SR
    f = 1350 - (1350 - 880) * (tt / tt[-1]) ** 0.8
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph + 0.3 * np.sin(2 * np.pi * 24 * tt))
    x += 0.3 * np.sin(2 * ph)
    env = np.sin(np.pi * np.clip(tt / tt[-1], 0, 1)) ** 1.2
    x = x * env * 0.5
    sos = signal.butter(2, 2600 / (SR / 2), "low", output="sos")
    x = signal.sosfilt(sos, x)
    # 回声
    echo = np.zeros(n + int(0.5 * SR))
    echo[:n] += x
    d1 = int(0.18 * SR)
    echo[d1:d1 + n] += x * 0.4
    d2 = int(0.36 * SR)
    echo[d2:d2 + n] += x * 0.18
    return echo * r.uniform(0.7, 1.0)


def horn(seed=0, dur=3.2):
    """雾中汽笛：小三度双音，软起音，远距离低通。"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    x = (np.sin(2 * np.pi * 220 * tt) * 0.6 +
         np.sin(2 * np.pi * 261.6 * tt) * 0.45 +
         np.sin(2 * np.pi * 440 * tt) * 0.10)
    env = np.minimum(1, tt / 0.5) * np.exp(-np.maximum(0, tt - (dur - 1.3)) / 0.55)
    x = x * env
    sos = signal.butter(2, 900 / (SR / 2), "low", output="sos")
    x = signal.sosfilt(sos, x)
    return x * 0.5


def buzz(seed=0, dur=2.4):
    """机械蜻蜓：翅膀拍频 AM 的金属嗡鸣，左右游移。"""
    r = np.random.default_rng(seed)
    n = int(dur * SR)
    tt = np.arange(n) / SR
    f0 = 172
    x = sum(a * np.sin(2 * np.pi * f0 * m * tt)
            for m, a in ((1, 1.0), (2, 0.5), (3, 0.28), (5, 0.12)))
    am = 0.5 + 0.5 * np.sin(2 * np.pi * 38 * tt)
    sos = signal.butter(2, [900, 4200], btype="band", fs=SR, output="sos")
    x = signal.sosfilt(sos, x) * am
    env = np.minimum(1, tt / 0.25) * np.exp(-np.maximum(0, tt - (dur - 0.5)) / 0.22)
    return x * env * 0.5, r


stems = {}

w_l, w_r, gust = make_wind()
stems["wind"] = (w_l, w_r)
stems["waves"] = make_waves()
stems["industry"] = make_industry()
stems["drone"] = make_drone()
stems["cloth"] = make_cloth()

# 事件：海鸥（仅蓝海段 S01-S06）
gulls = []
for i in range(0, 6):
    at = STARTS[i] + rng.uniform(0.6, 1.4)
    while at < STARTS[i] + DURS[i] - 1.2:
        gulls.append((at, gull(int(at * 13) % 9999), rng.uniform(0.2, 0.8),
                      rng.uniform(0.30, 0.55)))
        at += rng.uniform(3.2, 7.5)
stems["gulls"] = event_stem(gulls)

# 事件：汽笛（S01 开场远处 + S07 转场）
horns = [(STARTS[0] + 2.6, horn(1), 0.62, 0.9),
         (STARTS[6] + 1.6, horn(2), 0.45, 0.8)]
stems["horn"] = event_stem(horns)

# 事件：机械蜻蜓（S03，从左到右游移）
bz, r0 = buzz(3)
i0 = int((STARTS[2] + 1.8) * SR)
n = len(bz)
pan = np.linspace(0.25, 0.75, n)
bz_l = np.zeros(N)
bz_r = np.zeros(N)
i1 = min(N, i0 + n)
bz_l[i0:i1] += (bz * (1 - pan))[:i1 - i0] * 0.9
bz_r[i0:i1] += (bz * pan)[:i1 - i0] * 0.9
stems["buzz"] = (bz_l, bz_r)

report = {}
for name in STEM_NAMES:
    l, r = stems[name]
    if name in ("horn", "buzz"):
        g = np.ones(N)
        g[:int(0.4 * SR)] *= np.linspace(0, 1, int(0.4 * SR))
        g[-int(0.6 * SR):] *= np.linspace(1, 0, int(0.6 * SR))
    else:
        g = automation(name)
    l = l * g
    r = r * g
    st = np.stack([l, r], 1)
    peak = np.max(np.abs(st)) + 1e-9
    if peak > 0.9:
        st = st / peak * 0.9
    wavfile.write(os.path.join(STEMS, name + ".wav"), SR, st.astype(np.float32))
    report[name] = dict(peak=round(float(np.max(np.abs(st))), 3),
                        rms=round(float(np.sqrt(np.mean(st ** 2))), 4))
    print(f"{name:8s} peak={report[name]['peak']:.3f} rms={report[name]['rms']:.4f}")

json.dump(report, open(os.path.join(BUILD, "stems_report.json"), "w", encoding="utf-8"), indent=1)
print("stems written ->", STEMS)
