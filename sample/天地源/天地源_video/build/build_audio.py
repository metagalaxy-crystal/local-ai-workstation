import json, os, subprocess, sys
import numpy as np
from scipy import signal
from scipy.io import wavfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from filmconfig import SHOTS, OVERLAP, BASE

SR = 48000
FFMPEG = r"C:\Program Files\EVCapture\ffmpeg.exe"
AUD = os.path.join(BASE, "audio")
BUILD = os.path.join(BASE, "build")

meta = json.load(open(os.path.join(BUILD, "lines.json"), encoding="utf-8"))
lines = meta["lines"]
adur = meta["durations"]

# ---------- timeline ----------
durs = []
for i, d in enumerate(adur):
    durs.append(round(d + (3.2 if i == len(adur) - 1 else 1.25), 3))
durs = [max(d, 4.3) if i < len(durs) - 1 else d for i, d in enumerate(durs)]
starts = [round(sum(durs[:i]) - i * OVERLAP, 3) for i in range(len(durs))]
total = round(starts[-1] + durs[-1], 3)
narr_at = [round(s + (1.90 if i == 0 else 0.62), 3) for i, s in enumerate(starts)]
print("durs", durs)
print("starts", starts)
print("total", total)

json.dump({"durs": durs, "starts": starts, "narr_at": narr_at, "total": total},
          open(os.path.join(BUILD, "timeline.json"), "w"), indent=1)

# ---------- music ----------
def mtof(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)

def make_music(dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    L = np.zeros(n)
    R = np.zeros(n)
    rng = np.random.default_rng(7)

    chords = [
        [50, 57, 62, 65, 69],     # Dm(add9)
        [46, 53, 58, 62, 65],     # Bb maj7
        [41, 53, 60, 65, 69],     # F add9
        [43, 50, 58, 62, 67],     # Gm
        [45, 52, 57, 64, 69],     # Am
    ]
    seg = 11.5
    fade = 2.6
    k = 0
    while k * seg < dur:
        chord = chords[k % len(chords)]
        t0 = k * seg
        t1 = min(dur, t0 + seg)
        dur_seg = t1 - t0
        ns = int(dur_seg * SR)
        ts = np.arange(ns) / SR
        env = np.ones(ns)
        nf = min(int(fade * SR), ns // 2)
        env[:nf] = 0.5 - 0.5 * np.cos(np.pi * np.arange(nf) / nf)
        env[-nf:] = 0.5 + 0.5 * np.cos(np.pi * np.arange(nf) / nf)
        segL = np.zeros(ns)
        segR = np.zeros(ns)
        for vi, note in enumerate(chord):
            f = mtof(note)
            phase = rng.uniform(0, 2 * np.pi, 4)
            for det, pan in ((-0.0011, 0.30), (0.0009, 0.62)):
                fd = f * (1 + det + 0.0004 * np.sin(2 * np.pi * 0.03 * ts + phase[0]))
                osc = (np.sin(2 * np.pi * fd * ts + phase[1])
                       + 0.18 * np.sin(2 * np.pi * 2 * fd * ts + phase[2])
                       + 0.07 * np.sin(2 * np.pi * 3 * fd * ts + phase[3]))
                trem = 1 - 0.16 * (0.5 + 0.5 * np.sin(2 * np.pi * (0.05 + 0.012 * vi) * ts + phase[0]))
                amp = (0.150 if vi == 0 else (0.075 if vi < 3 else 0.050))
                s = osc * trem * amp * 0.5
                segL += s * (1 - pan)
                segR += s * pan
        segL *= env
        segR *= env
        i0 = int(t0 * SR)
        i1 = min(i0 + ns, n)
        L[i0:i1] += segL[:i1 - i0]
        R[i0:i1] += segR[:i1 - i0]
        k += 1

    # fragile glass bells
    bell_times = [7.5, 20.0, 33.5, 46.0, 55.0, 59.0]
    bell_notes = [86, 81, 84, 81, 86, 77]
    for bt, mn in zip(bell_times, bell_notes):
        if bt >= dur:
            continue
        ns = int(min(6.0, dur - bt) * SR)
        ts = np.arange(ns) / SR
        f = mtof(mn)
        env = np.exp(-ts / 1.6) * (1 - np.exp(-ts / 0.02))
        sig = (np.sin(2 * np.pi * f * ts)
               + 0.45 * np.sin(2 * np.pi * 2.01 * f * ts)
               + 0.22 * np.sin(2 * np.pi * 3.02 * f * ts)
               + 0.10 * np.sin(2 * np.pi * 4.98 * f * ts))
        sig *= env * 0.030
        i0 = int(bt * SR)
        i1 = min(i0 + ns, n)
        pan = rng.uniform(0.25, 0.75)
        L[i0:i1] += sig[:i1 - i0] * (1 - pan)
        R[i0:i1] += sig[:i1 - i0] * pan

    # air / noise bed
    noise = rng.normal(0, 1, n)
    sos = signal.butter(4, [180, 1700], btype="band", fs=SR, output="sos")
    band = signal.sosfilt(sos, noise)
    band /= (np.max(np.abs(band)) + 1e-9)
    mod = 0.5 + 0.5 * np.sin(2 * np.pi * 0.045 * t)
    L += band * 0.020 * mod
    R += np.roll(band, 977) * 0.020 * mod

    # reverb
    ir_t = np.arange(int(2.9 * SR)) / SR
    ir = rng.normal(0, 1, len(ir_t)) * np.exp(-ir_t / 0.75)
    ir[:int(0.012 * SR)] *= np.linspace(0, 1, int(0.012 * SR))
    ir /= np.sqrt(np.sum(ir ** 2))
    wetL = signal.fftconvolve(L, ir)[:n]
    ir2 = rng.normal(0, 1, len(ir_t)) * np.exp(-ir_t / 0.78)
    ir2 /= np.sqrt(np.sum(ir2 ** 2))
    wetR = signal.fftconvolve(R, ir2)[:n]
    L = L * 0.72 + wetL * 0.55
    R = R * 0.72 + wetR * 0.55

    st = np.stack([L, R], 1)
    st /= (np.max(np.abs(st)) + 1e-9)
    st *= 0.55
    return st

music = make_music(total + 1.0)
wavfile.write(os.path.join(AUD, "music.wav"), SR, (music * 32767).astype(np.int16))
print("music", music.shape, round(music.shape[0] / SR, 2))

# ---------- narration ----------
n_total = int(total * SR)
narr = np.zeros(n_total, dtype=np.float64)
for i in range(len(lines)):
    sr, d = wavfile.read(os.path.join(AUD, f"line{i+1:02d}.wav"))
    x = d.astype(np.float64) / 32768.0
    # trim leading/trailing silence
    thr = 0.004
    idx = np.where(np.abs(x) > thr)[0]
    if len(idx) > 10:
        a, b = max(0, idx[0] - int(0.05 * SR)), min(len(x), idx[-1] + int(0.08 * SR))
        x = x[a:b]
    # level all lines to the same speech RMS
    rms = np.sqrt(np.mean(x ** 2)) + 1e-9
    x = x * (0.118 / rms)
    x = np.clip(x, -0.92, 0.92)
    f = int(0.025 * SR)
    x[:f] *= np.linspace(0, 1, f)
    x[-f:] *= np.linspace(1, 0, f)
    i0 = int(narr_at[i] * SR)
    i1 = min(i0 + len(x), n_total)
    narr[i0:i1] += x[:i1 - i0]

# ---------- ducking ----------
act = (np.abs(narr) > 0.004).astype(np.float64)
ker = signal.windows.gaussian(int(0.55 * SR), int(0.22 * SR))
ker /= ker.sum()
smooth = signal.fftconvolve(act, ker)[:n_total]
smooth = np.clip(smooth, 0, 1)
duck = 1.0 - 0.55 * smooth

m = music[:n_total, :].copy()
# music fade in / out
fi = int(4.5 * SR)
m[:fi] *= np.linspace(0, 1, fi)[:, None]
fo = int(6.5 * SR)
m[-fo:] *= np.linspace(1, 0, fo)[:, None] ** 1.5
m *= (duck * 0.32)[:, None]

narr_st = np.stack([narr, narr], 1)
mix = m + narr_st
# gentle soft limiter
mix = np.tanh(mix * 1.05) * 0.94
peak = np.max(np.abs(mix))
print("raw peak", round(peak, 3))
mix = mix / max(1.0, peak / 0.89)

wavfile.write(os.path.join(AUD, "mix.wav"), SR, (mix * 32767).astype(np.int16))
print("mix written", round(len(mix) / SR, 2))
