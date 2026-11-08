# -*- coding: utf-8 -*-
"""分层环境音设计（进阶版）：每个声源独立成 stem，按镜头位置自动推子。

与 v1 的差别：
  * v1 只有一条“氛围噪声”，听起来和画面无关；这里拆成 11 条独立 stem：
    风 / 枝叶 / 城市远景 / 石子脚步 / 玻璃铁件 / 晶体 / 火 / 纸 / 虫 / 水滴 / 钟
  * 每个 stem 有自己的“场面增益”曲线（园外、小道、亭内、三界、人间、地狱、天堂），
    镜头切换时自动交叉过渡，所以声音跟着画面走。
  * 关键动作按旁白时间点排布：脚步落在“我迈步进入”，火星在“地狱”，
    纸片在“天堂”，光柱出现与结尾各有一声玻璃钟。

运行：python scripts\\env_audio.py
产出：audio\\stems\\*.wav（48k 立体声）+ build\\stems_report.json
"""
import json, math, os, sys
import numpy as np
from scipy import signal
from scipy.io import wavfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v3_config import BASE, BUILD, STEMS, SHOTS

SR = 48000
tl = json.load(open(os.path.join(BUILD, "timeline.json"), encoding="utf-8"))
STARTS, DURS, TOTAL = tl["starts"], tl["durs"], tl["total"]
N = int((TOTAL + 1.2) * SR)
t = np.arange(N) / SR

# 场景 → 各声源目标增益
PLACE = {
    "out":      dict(wind=1.00, leaves=0.85, city=0.55, insects=0.45, drips=0.30, glass=0.05),
    "path":     dict(wind=0.95, leaves=0.90, city=0.35, steps=0.55, drips=0.25, insects=0.20),
    "pavilion": dict(wind=0.42, leaves=0.28, glass=0.50, drips=0.10, steps=0.38),
    "three":    dict(wind=0.70, leaves=0.40, crystal=0.55, glass=0.22),
    "world":    dict(wind=0.28, city=0.28, crystal=0.30),
    "hell":     dict(wind=0.38, fire=0.85, city=0.12),
    "heaven":   dict(wind=0.68, leaves=0.22, paper=0.55, crystal=0.32),
}
STEM_NAMES = ["wind", "leaves", "city", "steps", "glass", "crystal", "fire",
              "paper", "insects", "drips", "bell"]

rng = np.random.default_rng(2022)


def noise(n, lo, hi, order=2):
    x = rng.normal(0, 1, n)
    sos = signal.butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    y = signal.sosfilt(sos, x)
    return y / (np.std(y) + 1e-9)


def slow_env(n, rates, amps, phase=None):
    tt = np.arange(n) / SR
    e = np.zeros(n)
    ph = 0 if phase is None else phase
    for r, a in zip(rates, amps):
        e += a * np.sin(2 * np.pi * r * tt + ph * (r * 13.7))
    return e


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
    # 片头淡入 / 片尾淡出
    g[:int(1.2 * SR)] *= np.linspace(0, 1, int(1.2 * SR))
    g[-int(3.0 * SR):] *= np.linspace(1, 0, int(3.0 * SR)) ** 1.4
    return np.clip(g, 0, 1.4)


def place_at(sig, at):
    """把一个单发事件叠加到整轨上，返回 (L, R) 或原地写入"""
    return int(at * SR)


def event_stem(events, name):
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


# ---------------- 单发事件合成 ----------------
def footstep(seed=0, dur=0.26):
    r = np.random.default_rng(seed)
    n = int(dur * SR)
    tt = np.arange(n) / SR
    x = r.normal(0, 1, n)
    sos = signal.butter(2, [700, 2600], btype="band", fs=SR, output="sos")
    x = signal.sosfilt(sos, x)
    x /= (np.max(np.abs(x)) + 1e-9)
    body = np.sin(2 * np.pi * 105 * tt) * np.exp(-tt / 0.035)
    env = np.exp(-tt / 0.035) * (1 - np.exp(-tt / 0.004))
    return (x * env * 0.55 + body * 0.35)


def drip(seed=0):
    r = np.random.default_rng(seed)
    n = int(0.13 * SR)
    tt = np.arange(n) / SR
    f = 1500 * np.exp(-tt / 0.03) + 700
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-tt / 0.035)
    x += r.normal(0, 1, n) * np.exp(-tt / 0.004) * 0.25
    return x * 0.6


def tick(seed=0):
    r = np.random.default_rng(seed)
    n = int(0.22 * SR)
    tt = np.arange(n) / SR
    f0 = r.uniform(2100, 4200)
    x = (np.sin(2 * np.pi * f0 * tt) * 0.5 +
         np.sin(2 * np.pi * f0 * 2.41 * tt) * 0.22 +
         np.sin(2 * np.pi * f0 * 3.77 * tt) * 0.10)
    x *= np.exp(-tt / 0.045)
    x += r.normal(0, 1, n) * np.exp(-tt / 0.003) * 0.18
    return x * 0.5


def bell(seed=0, dur=2.8):
    r = np.random.default_rng(seed)
    n = int(dur * SR)
    tt = np.arange(n) / SR
    f = 1180
    x = np.zeros(n)
    for mult, amp, dec in ((1, 1.0, 1.5), (2.02, 0.5, 1.1), (3.01, 0.28, 0.8),
                           (4.19, 0.15, 0.6), (5.43, 0.08, 0.45)):
        x += amp * np.sin(2 * np.pi * f * mult * tt) * np.exp(-tt / dec)
    x *= (1 - np.exp(-tt / 0.003))
    return x * 0.22


def cricket(seed=0):
    r = np.random.default_rng(seed)
    n = int(0.30 * SR)
    tt = np.arange(n) / SR
    f = r.uniform(4100, 5200)
    pulse = (np.sin(2 * np.pi * 38 * tt) > -0.2).astype(float)
    env = pulse * np.exp(-tt / 0.18)
    return np.sin(2 * np.pi * f * tt) * env * 0.20


def paper(seed=0):
    r = np.random.default_rng(seed)
    n = int(0.30 * SR)
    tt = np.arange(n) / SR
    x = r.normal(0, 1, n)
    sos = signal.butter(2, [1200, 4800], btype="band", fs=SR, output="sos")
    x = signal.sosfilt(sos, x)
    x /= (np.max(np.abs(x)) + 1e-9)
    env = np.sin(np.pi * np.clip(tt / 0.28, 0, 1)) ** 1.5
    flutter = 0.6 + 0.4 * np.sin(2 * np.pi * 23 * tt)
    return x * env * flutter * 0.5


def ember(seed=0):
    r = np.random.default_rng(seed)
    n = int(0.09 * SR)
    tt = np.arange(n) / SR
    x = r.normal(0, 1, n) * np.exp(-tt / 0.012)
    x = np.convolve(x, np.ones(3) / 3, "same")
    return x * 0.5


# ---------------- 连续声床 ----------------
def make_wind():
    base = noise(N, 35, 240) * 0.55 + noise(N, 240, 900) * 0.30
    hiss = noise(N, 1800, 6500) * 0.12
    gust = slow_env(N, [0.055, 0.11, 0.21], [0.45, 0.30, 0.18])
    gust = 0.55 + 0.45 * np.tanh(gust * 1.6)
    flutter = 0.85 + 0.15 * np.sin(2 * np.pi * 0.9 * t)
    l = (base + hiss) * gust * flutter
    r = (noise(N, 35, 240) * 0.55 + noise(N, 240, 900) * 0.30 +
         noise(N, 1800, 6500) * 0.12) * np.roll(gust, int(0.37 * SR)) * flutter
    return l, r, gust


def make_leaves(gust):
    l = noise(N, 2600, 7800) * 0.35
    r = noise(N, 2600, 7800) * 0.35
    fl = 0.5 + 0.5 * np.sin(2 * np.pi * 4.7 * t + 1.1)
    fl2 = 0.5 + 0.5 * np.sin(2 * np.pi * 6.3 * t + 2.4)
    amp = np.clip(gust ** 1.6, 0, 1)
    return l * fl * amp, r * fl2 * amp


def make_city():
    rumble = noise(N, 45, 170) * 0.5
    hum = noise(N, 170, 620) * 0.16
    l = rumble + hum
    r = np.roll(rumble, int(0.8 * SR)) * 0.9 + np.roll(hum, int(0.5 * SR))
    return l, r


def make_crystal():
    l = np.zeros(N)
    r = np.zeros(N)
    for f, amp, pan in ((523.25, 0.5, 0.35), (783.99, 0.35, 0.62), (1046.5, 0.22, 0.48),
                        (1567.98, 0.12, 0.72)):
        vib = 1 + 0.0035 * np.sin(2 * np.pi * 0.11 * t + f)
        sig = np.sin(2 * np.pi * f * vib * t) * amp
        sig *= 0.55 + 0.45 * np.sin(2 * np.pi * (0.045 + f / 90000) * t) ** 2
        l += sig * (1 - pan)
        r += sig * pan
    return l * 0.16, r * 0.16


def make_fire():
    roar = noise(N, 40, 380) * 0.55
    mid = noise(N, 380, 1400) * 0.18
    l = roar + mid
    r = np.roll(roar, int(0.6 * SR)) + np.roll(mid, int(0.3 * SR))
    return l, r


stems = {}

# 连续声床
w_l, w_r, gust = make_wind()
stems["wind"] = (w_l, w_r)
stems["leaves"] = make_leaves(gust)
stems["city"] = make_city()
stems["crystal"] = make_crystal()
stems["fire"] = make_fire()

# 事件：脚步（S02 走近 + S03 迈入）
steps = []
i2, i3 = 1, 2
for k, off in enumerate((1.9, 3.0, 4.1)):
    steps.append((STARTS[i2] + off, footstep(20 + k), 0.42 + 0.1 * k, 0.9))
for k, off in enumerate((0.15, 0.95, 1.75, 2.55)):
    steps.append((STARTS[i3] + off, footstep(40 + k, dur=0.3), 0.5 + 0.06 * k, 1.0))
stems["steps"] = event_stem(steps, "steps")

# 事件：水滴（S01/S02 湿地面）
drips = []
for k in range(9):
    at = STARTS[0] + 1.0 + k * 1.55 + rng.uniform(-0.3, 0.3)
    drips.append((at, drip(100 + k), rng.uniform(0.3, 0.7), 0.55))
for k in range(4):
    at = STARTS[1] + 1.2 + k * 1.4 + rng.uniform(-0.2, 0.2)
    drips.append((at, drip(200 + k), rng.uniform(0.3, 0.7), 0.45))
stems["drips"] = event_stem(drips, "drips")

# 事件：玻璃 / 铁件的轻响（亭内）
ticks = []
for i in (2, 4, 5):
    for k in range(3):
        at = STARTS[i] + 0.6 + k * (DURS[i] - 1.2) / 3 + rng.uniform(-0.25, 0.25)
        ticks.append((at, tick(300 + i * 10 + k), rng.uniform(0.25, 0.75), 0.5))
stems["glass"] = event_stem(ticks, "glass")

# 事件：虫鸣（S01 与 S11 的夜）
ins = []
for i in (0, 10):
    at = STARTS[i] + 0.8
    while at < STARTS[i] + DURS[i] - 0.9:
        ins.append((at, cricket(int(at * 10) % 9999), rng.uniform(0.2, 0.8), 0.5))
        at += rng.uniform(0.85, 1.5)
stems["insects"] = event_stem(ins, "insects")

# 事件：纸片翻飞（天堂）
pap = []
for k in range(9):
    at = STARTS[9] + 0.4 + k * 0.8 + rng.uniform(-0.2, 0.2)
    pap.append((at, paper(500 + k), rng.uniform(0.2, 0.8), 0.55))
stems["paper"] = event_stem(pap, "paper")

# 事件：火星（地狱）
emb = []
for k in range(26):
    at = STARTS[8] + rng.uniform(0.2, DURS[8] - 0.3)
    emb.append((at, ember(700 + k), rng.uniform(0.15, 0.85), rng.uniform(0.3, 0.9)))
stems["fire"] = (stems["fire"][0] + event_stem(emb, "e")[0] * 2.2,
                 stems["fire"][1] + event_stem(emb, "e")[1] * 2.2)

# 事件：玻璃钟（三界光柱 + 结尾）
bells = [(STARTS[6] + 1.15, bell(1), 0.55, 1.0),
         (TOTAL - 4.4, bell(2), 0.5, 0.85)]
stems["bell"] = event_stem(bells, "bell")

report = {}
for name in STEM_NAMES:
    l, r = stems[name]
    if name == "bell":
        # 钟声是单发事件，不跟镜头推子，只在片头片尾做淡入淡出
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
