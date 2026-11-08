# -*- coding: utf-8 -*-
"""混音：旁白 + ACE-Step 本地配乐 + 8 条环境音 stem，带旁白闪避。

  * 环境音分层 stem，按画面自动推子（env_audio.py 已写入增益曲线）。
  * 旁白做“段内响度一致”归一。
  * 音乐为 ACE-Step 本地生成（bgm_main 蓝海记忆 + bgm_rust 锈海暗层），
    按镜头强度弧线起伏，锈层自 S07 转场渐入，并对旁白闪避。
  * 所有 stem 在旁白出现时再轻微闪避，保证台词清晰。

运行：python scripts\\mix.py
产出：audio\\mix.wav（48k 立体声，未做母带）
"""
import json, os, sys
import numpy as np
from scipy import signal
from scipy.io import wavfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from txh_config import BASE, BUILD, AUDIO, STEMS, SHOTS, INTENSITY

SR = 48000
tl = json.load(open(os.path.join(BUILD, "timeline.json"), encoding="utf-8"))
STARTS, DURS, NARR, TOTAL = tl["starts"], tl["durs"], tl["narr_at"], tl["total"]
N = int(TOTAL * SR)

# 各 stem 的“场内”目标响度（RMS）
STEM_TARGET = dict(wind=0.020, waves=0.024, gulls=0.015, industry=0.013,
                   cloth=0.013, drone=0.015, horn=0.022, buzz=0.012)

import soundfile as sf

# ---------- 旁白 ----------
nar = np.zeros((N, 2))
for i in range(len(SHOTS)):
    x, _sr = sf.read(os.path.join(AUDIO, "lines", f"line{i+1:02d}.wav"), dtype="float32")
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

# ---------- 配乐 ----------
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
    inten = np.zeros(N)
    for i in range(len(SHOTS)):
        a = int(STARTS[i] * SR)
        b = min(N, int((STARTS[i] + DURS[i]) * SR))
        inten[a:b] = INTENSITY[i]
    k = signal.windows.gaussian(int(1.6 * SR), int(0.6 * SR))
    k /= k.sum()
    inten = signal.fftconvolve(inten, k)[:N]
    return inten / (inten.max() + 1e-9)


p_main = _find_music("bgm_main")
assert p_main, "music\\bgm_main.* 缺失，请先跑 gen_music.py"
mus = np.zeros((N, 2))
mMain = _load_stereo(p_main)
m = min(N, len(mMain))
mus[:m] = mMain[:m]
mus = mus / (np.sqrt(np.mean(mus ** 2)) + 1e-9) * 0.035
mus *= (0.35 + 0.65 * _intensity_env())[:, None]      # 镜头强度弧线
p_rust = _find_music("bgm_rust")                      # 锈海暗层自 S07 渐入
if p_rust:
    mc = _load_stereo(p_rust)
    a = int(STARTS[6] * SR)
    b = min(N, a + len(mc))
    envc = np.zeros(N)
    envc[a:b] = 1.0
    k = signal.windows.gaussian(int(2.4 * SR), int(0.9 * SR))
    k /= k.sum()
    envc = np.clip(signal.fftconvolve(envc, k)[:N], 0, 1)
    seg = np.zeros((N, 2))
    seg[a:b] = mc[:b - a]
    mus += seg * (envc * 0.40)[:, None]
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
