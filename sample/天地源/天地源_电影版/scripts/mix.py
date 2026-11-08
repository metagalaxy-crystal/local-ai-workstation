# -*- coding: utf-8 -*-
"""混音：旁白 + ACE-Step 本地配乐 + 11 条环境音 stem，带旁白闪避。

  * 环境音分层 stem，按画面自动推子（env_audio.py 已写入增益曲线）。
  * 旁白做“段内响度一致”归一，句与句之间不再忽大忽小。
  * 音乐为 ACE-Step 本地生成（bgm_main + bgm_climax），按镜头强度弧线起伏，并对旁白闪避；
    若 music\ 下无生成文件则回退到程序化配乐。
  * 所有 stem 在旁白出现时再轻微闪避，保证台词清晰。

运行：python scripts\\mix.py
产出：audio\\mix.wav（48k 立体声，未做母带）
"""
import json, os, sys
import numpy as np
from scipy import signal
from scipy.io import wavfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v3_config import BASE, BUILD, AUDIO, STEMS, SHOTS

SR = 48000
tl = json.load(open(os.path.join(BUILD, "timeline.json"), encoding="utf-8"))
STARTS, DURS, NARR, TOTAL = tl["starts"], tl["durs"], tl["narr_at"], tl["total"]
N = int(TOTAL * SR)

# 各 stem 的“场内”目标响度（RMS）；实际增益由 mix 阶段自动标定，
# 避免手动增益在“只在某个镜头出现”的声源上算错。
STEM_TARGET = dict(wind=0.020, leaves=0.012, city=0.014, steps=0.018, glass=0.015,
                   crystal=0.015, fire=0.022, paper=0.017, insects=0.014,
                   drips=0.012, bell=0.026)


def mtof(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)


def nail(n, tags, gain, pan):
    tt = np.arange(n) / SR
    f = mtof(tags)
    x = (np.sin(2 * np.pi * f * tt) + 0.5 * np.sin(2 * np.pi * 2 * f * tt) +
         0.2 * np.sin(2 * np.pi * 3 * f * tt))
    env = np.exp(-tt / 0.9) * (1 - np.exp(-tt / 0.006))
    mono = x * env * gain
    return np.stack([mono * (1 - pan), mono * pan], axis=1)


def make_music(dur):
    n = int((dur + 0.5) * SR)
    t = np.arange(n) / SR
    L = np.zeros(n)
    R = np.zeros(n)
    rng = np.random.default_rng(7)

    # 情绪弧线：按镜头给强度
    inten = np.zeros(n)
    vals = [0.45, 0.52, 0.34, 0.55, 0.42, 0.78, 0.92, 0.46, 0.95, 0.82, 0.36]
    for i in range(len(SHOTS)):
        a = int(STARTS[i] * SR)
        b = min(n, int((STARTS[i] + DURS[i]) * SR))
        inten[a:b] = vals[i]
    k = signal.windows.gaussian(int(1.6 * SR), int(0.6 * SR))
    inten = signal.fftconvolve(inten, k / k.sum())[:n]
    inten = np.clip(inten, 0, 1)

    chords = [[50, 57, 62, 65, 69], [46, 53, 58, 62, 65], [41, 53, 60, 65, 69],
              [43, 50, 58, 62, 67], [45, 52, 57, 64, 69]]
    seg = 11.5
    fade = 2.8
    beat = 0
    while beat * seg < dur:
        ch = chords[beat % len(chords)]
        t0 = beat * seg
        t1 = min(dur, t0 + seg)
        ns = int((t1 - t0) * SR)
        if ns <= 0:
            break
        ts = np.arange(ns) / SR
        env = np.ones(ns)
        nf = min(int(fade * SR), ns // 2)
        env[:nf] = 0.5 - 0.5 * np.cos(np.pi * np.arange(nf) / nf)
        env[-nf:] = 0.5 + 0.5 * np.cos(np.pi * np.arange(nf) / nf)
        segL = np.zeros(ns)
        segR = np.zeros(ns)
        for vi, note in enumerate(ch):
            f = mtof(note)
            ph = rng.uniform(0, 2 * np.pi, 4)
            for det, pan in ((-0.0012, 0.30), (0.0010, 0.62)):
                fd = f * (1 + det + 0.0004 * np.sin(2 * np.pi * 0.03 * ts + ph[0]))
                osc = (np.sin(2 * np.pi * fd * ts + ph[1])
                       + 0.18 * np.sin(2 * np.pi * 2 * fd * ts + ph[2])
                       + 0.07 * np.sin(2 * np.pi * 3 * fd * ts + ph[3]))
                trem = 1 - 0.15 * (0.5 + 0.5 * np.sin(2 * np.pi * (0.05 + 0.012 * vi) * ts + ph[0]))
                amp = 0.150 if vi == 0 else (0.072 if vi < 3 else 0.048)
                s = osc * trem * amp * 0.5
                segL += s * (1 - pan)
                segR += s * pan
        # 低音持续音
        f0 = mtof(ch[0] - 12)
        dr = np.sin(2 * np.pi * f0 * ts) * (0.075 + 0.02 * np.sin(2 * np.pi * 0.07 * ts))
        segL += dr * 0.9
        segR += dr * 0.9
        i0 = int(t0 * SR)
        i1 = min(i0 + ns, n)
        segL *= env
        segR *= env
        L[i0:i1] += segL[:i1 - i0]
        R[i0:i1] += segR[:i1 - i0]
        beat += 1

    # 稀疏的钢琴点（随强度变密）
    notes = [69, 74, 72, 77, 76, 79, 74, 69, 65, 72, 71, 76]
    tt = 3.0
    idx = 0
    while tt < dur - 2.0:
        i0 = int(tt * SR)
        if inten[min(i0, n - 1)] > 0.3:
            gain = 0.055 * (0.6 + 0.6 * inten[min(i0, n - 1)])
            p = rng.uniform(0.30, 0.70)
            hit = nail(int(3.4 * SR), notes[idx % len(notes)], gain, p)
            i1 = min(n, i0 + len(hit))
            L[i0:i1] += hit[:i1 - i0, 0]
            R[i0:i1] += hit[:i1 - i0, 1]
            idx += 1
        tt += 4.5 + rng.uniform(0, 2.5)

    # 空气感噪声床
    noise = rng.normal(0, 1, n)
    sos = signal.butter(4, [180, 1700], btype="band", fs=SR, output="sos")
    band = signal.sosfilt(sos, noise)
    band /= (np.max(np.abs(band)) + 1e-9)
    L += band * 0.014 * inten
    R += np.roll(band, 977) * 0.014 * inten

    # 弦乐般的缓涌（低通锯齿 + 慢颤音）
    saw = 2 * (t * 110 % 1) - 1
    saw = signal.sosfilt(signal.butter(2, 900, btype="low", fs=SR, output="sos"), saw)
    swell = (0.5 + 0.5 * np.sin(2 * np.pi * 0.035 * t - 1.2)) ** 2 * inten * 0.020
    L += saw * swell
    R += np.roll(saw, 1200) * swell

    # 混响
    for ch, seed in ((0, 1), (1, 2)):
        r = np.random.default_rng(seed)
        ir_t = np.arange(int(3.4 * SR)) / SR
        ir = r.normal(0, 1, len(ir_t)) * np.exp(-ir_t / 0.95)
        ir[:int(0.014 * SR)] *= np.linspace(0, 1, int(0.014 * SR))
        ir /= np.sqrt(np.sum(ir ** 2))
        src = L if ch == 0 else R
        wet = signal.fftconvolve(src, ir)[:n]
        if ch == 0:
            L = L * 0.70 + wet * 0.62
        else:
            R = R * 0.70 + wet * 0.62

    st = np.stack([L, R], 1)[:int(dur * SR)]
    st /= (np.max(np.abs(st)) + 1e-9)
    return st * 0.85


# ---------- 旁白 ----------
import soundfile as _sf
nar = np.zeros((N, 2))
for i in range(len(SHOTS)):
    x, _sr = _sf.read(os.path.join(AUDIO, "lines", f"line{i+1:02d}.wav"), dtype="float32")
    x = x.astype(np.float64)
    if x.ndim > 1:
        x = x[:, 0]
    rms = np.sqrt(np.mean(x ** 2)) + 1e-9
    x = x * (0.112 / rms)          # 全片统一到同一语音响度
    x = np.clip(x, -0.93, 0.93)
    i0 = int(NARR[i] * SR)
    i1 = min(N, i0 + len(x))
    nar[i0:i1, 0] += x[:i1 - i0]
    nar[i0:i1, 1] += x[:i1 - i0]

# ---------- 闪避包络 ----------
act = (np.abs(nar[:, 0]) > 0.004).astype(np.float64)
ker = signal.windows.gaussian(int(0.55 * SR), int(0.20 * SR))
ker /= ker.sum()
env = np.clip(signal.fftconvolve(act, ker)[:N], 0, 1)
music_duck = 1.0 - 0.55 * env
sfx_duck = 1.0 - 0.22 * env

# ---------- 配乐（ACE-Step 本地生成；文件缺失时回退程序化配乐） ----------
import soundfile as sf


def _find_music(name):
    for ext in (".flac", ".wav", ".mp3", ".ogg"):
        p = os.path.join(BASE, "music", name + ext)
        if os.path.exists(p):
            return p
    return None


def _load_stereo(path):
    d, sr = sf.read(path, dtype="float32", always_2d=True)
    if sr != SR:
        n2 = int(len(d) * SR / sr)
        xi = np.linspace(0, len(d) - 1, n2)
        d = np.stack([np.interp(xi, np.arange(len(d)), d[:, c])
                      for c in range(d.shape[1])], 1)
    return d.astype(np.float64)


def _intensity_env():
    vals = [0.45, 0.52, 0.34, 0.55, 0.42, 0.78, 0.92, 0.46, 0.95, 0.82, 0.36]
    inten = np.zeros(N)
    for i in range(len(SHOTS)):
        a = int(STARTS[i] * SR)
        b = min(N, int((STARTS[i] + DURS[i]) * SR))
        inten[a:b] = vals[i]
    k = signal.windows.gaussian(int(1.6 * SR), int(0.6 * SR))
    k /= k.sum()
    inten = signal.fftconvolve(inten, k)[:N]
    return inten / (inten.max() + 1e-9)


p_main = _find_music("bgm_main")
if p_main:
    mus = np.zeros((N, 2))
    mMain = _load_stereo(p_main)
    m = min(N, len(mMain))
    mus[:m] = mMain[:m]
    mus = mus / (np.sqrt(np.mean(mus ** 2)) + 1e-9) * 0.035
    mus *= (0.35 + 0.65 * _intensity_env())[:, None]      # 镜头强度弧线
    p_clx = _find_music("bgm_climax")                     # 高潮层铺在三界→天堂
    if p_clx:
        mc = _load_stereo(p_clx)
        a = int(STARTS[6] * SR)
        b = min(N, a + len(mc))
        envc = np.zeros(N)
        envc[a:b] = 1.0
        k = signal.windows.gaussian(int(2.4 * SR), int(0.9 * SR))
        k /= k.sum()
        envc = np.clip(signal.fftconvolve(envc, k)[:N], 0, 1)
        seg = np.zeros((N, 2))
        seg[a:b] = mc[:b - a]
        mus += seg * (envc * 0.38)[:, None]
else:
    mus = make_music(TOTAL)[:N]
    mus = mus / (np.sqrt(np.mean(mus ** 2)) + 1e-9) * 0.035
fi = int(3.5 * SR)
mus[:fi] *= np.linspace(0, 1, fi)[:, None]
fo = int(5.0 * SR)
mus[-fo:] *= np.linspace(1, 0, fo)[:, None] ** 1.4
mus *= (0.55 * music_duck)[:, None]

msgs = [f"music rms {np.sqrt(np.mean(mus**2)):.4f}"]
mix = mus + nar * 1.0


def scene_rms(x, frac=0.5):
    n = int(frac * SR)
    if len(x) < n:
        return float(np.sqrt(np.mean(x ** 2)) + 1e-9)
    r = np.sqrt(np.mean(x[:len(x) // n * n].reshape(-1, n, x.shape[1]) ** 2, axis=1))
    r = r[r > 1e-5]
    return float(np.percentile(r, 95) + 1e-9) if len(r) else 1e-9


# ---------- 环境音 ----------
for name, target in STEM_TARGET.items():
    sr, d = wavfile.read(os.path.join(STEMS, name + ".wav"))
    x = d.astype(np.float64)
    x = x[:N] if len(x) >= N else np.pad(x, ((0, N - len(x)), (0, 0)))
    g = target / scene_rms(x)
    x = x * g
    x *= sfx_duck[:, None]
    mix += x
    msgs.append(f"{name:8s} gain {g:6.2f} 场内 {20*np.log10(scene_rms(x)+1e-12):6.1f} dBFS")

peak = np.max(np.abs(mix))
msgs.append(f"raw peak {peak:.3f}")
mix = np.tanh(mix * 1.02) * 0.96
mix = mix / max(1.0, np.max(np.abs(mix)) / 0.89)

wavfile.write(os.path.join(AUDIO, "mix.wav"), SR, (mix * 32767).astype(np.int16))
print("\n".join(msgs))
print("mix", round(len(mix) / SR, 2), "s ->", os.path.join(AUDIO, "mix.wav"))
