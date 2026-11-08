# -*- coding: utf-8 -*-
r"""音频：H3 原生音效 + 夏日环境声床 + 两句台词，按镜头叠化时间轴混音。

运行： python audio_mix.py
产物： audio\mix.wav（48k 立体声）+ build\timeline.json + build\audio_report.json
"""
from __future__ import annotations

import json, subprocess, sys
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

sys.path.insert(0, str(Path(__file__).parent))
import zwj_config as C  # noqa: E402

SR = C.SR
CLIP_SEC = C.CLIP_LEN / C.FPS
N_SHOTS = len(C.SHOTS)
DURS = [CLIP_SEC] * N_SHOTS
STARTS = [round(sum(DURS[:i]) - i * C.XFADE, 4) for i in range(N_SHOTS)]
TOTAL = round(STARTS[-1] + DURS[-1], 4)
N = int(round((TOTAL + C.END_BLACK) * SR))
rng = np.random.default_rng(2026)


def timeline():
    tts_at = []
    for ln in C.LINES:
        shot = next((s for s in C.SHOTS if s["id"] == ln["at"]), None)
        idx = C.SHOTS.index(shot)
        tts_at.append(dict(id=ln["id"], at=round(STARTS[idx] + ln["offset"], 3),
                           text=ln["text"], gain=ln["gain"]))
    return dict(fps=C.FPS, xfade=C.XFADE, shot_sec=round(CLIP_SEC, 4), durs=DURS,
                starts=STARTS, total=TOTAL, end_black=C.END_BLACK, tts=tts_at)


def extract_audio(clip: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    subprocess.run([C.FFMPEG, "-y", "-loglevel", "error", "-i", str(clip),
                    "-vn", "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", str(dest)], check=True)
    return dest


def load_wav(path: Path) -> np.ndarray:
    sr, d = wavfile.read(path)
    x = d.astype(np.float64) / 32768.0
    if x.ndim == 1:
        x = np.stack([x, x], 1)
    if sr != SR:
        n = int(len(x) * SR / sr)
        x = np.stack([np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x[:, c])
                      for c in range(x.shape[1])], 1)
    return x


def envelope(x: np.ndarray, fin: float, fout: float) -> np.ndarray:
    n = len(x)
    e = np.ones(n)
    a = min(int(fin * SR), n // 2)
    b = min(int(fout * SR), n // 2)
    if a > 0:
        e[:a] = np.sin(np.linspace(0, np.pi / 2, a)) ** 2
    if b > 0:
        e[-b:] = np.cos(np.linspace(0, np.pi / 2, b)) ** 2
    return x * e[:, None]


def noise(n: int, lo: float, hi: float, order: int = 2) -> np.ndarray:
    x = rng.normal(0, 1, n)
    sos = signal.butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    return signal.sosfilt(sos, x)


def bed() -> np.ndarray:
    """夏日午后环境床：蝉鸣、鸟叫、树叶风、远处人声低语、自行车铃、摩托、手持噪声。"""
    t = np.arange(N) / SR
    # 树叶/微风
    gust = 0.55 + 0.45 * np.tanh(0.5 * np.sin(2 * np.pi * 0.05 * t) +
                                 0.3 * np.sin(2 * np.pi * 0.13 * t + 1.1))
    wind_l = noise(N, 180, 900) * gust * 0.2
    wind_r = noise(N, 180, 900) * np.roll(gust, int(0.3 * SR)) * 0.2
    # 蝉鸣：4.6kHz 窄带 + 38Hz 振幅调制
    cic = noise(N, 4300, 7800, 3) * (0.35 + 0.65 * (0.5 + 0.5 * np.sin(2 * np.pi * 37 * t)))
    cic *= 0.12
    # 鸟叫：几声短促上扬啁啾
    birds = np.zeros((N, 2))
    for at in [1.2, 4.8, 8.1, 12.4, 17.6, 21.9, 26.2]:
        n = int(0.28 * SR)
        te = np.arange(n) / SR
        f = 2600 + 1600 * (te / te[-1]) ** 1.4
        ph = 2 * np.pi * np.cumsum(f) / SR
        v = np.sin(ph + 0.4 * np.sin(2 * np.pi * 33 * te)) * np.sin(np.pi * te / te[-1]) ** 2
        i0 = int(at * SR)
        if i0 + n < N:
            pan = rng.uniform(0.15, 0.85)
            birds[i0:i0 + n, 0] += v * (1 - pan) * 0.05
            birds[i0:i0 + n, 1] += v * pan * 0.05
    # 远处人声低语（社区背景，非台词）
    murmur = noise(N, 120, 420, 2) * (0.45 + 0.55 * np.sin(2 * np.pi * 0.09 * t + 2.0)) * 0.02
    # 自行车铃（S02 附近两声）
    bell = np.zeros((N, 2))
    for at in [STARTS[1] + 1.1, STARTS[1] + 1.55]:
        n = int(0.5 * SR)
        te = np.arange(n) / SR
        v = (np.sin(2 * np.pi * 3150 * te) + 0.7 * np.sin(2 * np.pi * 3950 * te)) * np.exp(-te / 0.12)
        i0 = int(at * SR)
        if i0 + n < N:
            bell[i0:i0 + n] += v[:, None] * 0.03
    # 远处摩托经过（S05 前）
    moto = np.zeros(N)
    a0 = int((STARTS[4] - 1.0) * SR)
    n = int(3.2 * SR)
    te = np.arange(n) / SR
    f0 = 95 + 45 * np.sin(np.pi * te / te[-1]) ** 2
    v = sum(np.sin(2 * np.pi * f0 * k * te) / k for k in (1, 2, 3, 4))
    v *= (0.5 + 0.5 * np.sin(2 * np.pi * 11 * te)) * 0.05
    sos = signal.butter(2, 1200 / (SR / 2), "low", output="sos")
    v = signal.sosfilt(sos, v)
    b = min(N, a0 + n)
    moto[a0:b] = v[:b - a0]
    # 手持摄像机噪声 + 轻碰
    hand = noise(N, 40, 160) * 0.008
    thumps = np.zeros(N)
    for i, st in enumerate(STARTS[1:], start=1):
        n = int(0.18 * SR)
        te = np.arange(n) / SR
        v = np.sin(2 * np.pi * 70 * te) * np.exp(-te / 0.05) * 0.02
        i0 = int((st - 0.12) * SR)
        if i0 + n < N:
            thumps[i0:i0 + n] += v
    amb_l = wind_l + cic + murmur + hand + thumps + moto * 0.7 + bell[:, 0] + birds[:, 0]
    amb_r = wind_r + np.roll(cic, int(0.02 * SR)) + murmur + hand + thumps + moto + bell[:, 1] + birds[:, 1]
    return np.stack([amb_l, amb_r], 1)


def main() -> int:
    tl = timeline()
    json.dump(tl, open(Path(C.BUILD) / "timeline.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # 原生音轨
    nat = np.zeros((N, 2))
    src_dir = Path(C.BUILD) / "audio_src"
    native_gain = []
    for i, s in enumerate(C.SHOTS):
        clip = Path(C.CLIPS) / f"{s['clip']}.mp4"
        if not clip.exists():
            raise SystemExit(f"片段缺失：{clip}")
        w = load_wav(extract_audio(clip, src_dir / f"{s['clip']}.wav"))
        w = w[:int(CLIP_SEC * SR)]
        rms0 = float(np.sqrt(np.mean(w ** 2)) + 1e-9)
        # 各镜头原生音效电平差异很大（S02 只有 0.003），统一抬到 ~0.045，最多放大 10 倍
        gain = float(np.clip(0.045 / rms0, 0.35, 10.0))
        w = envelope(w * gain, 0.2, 0.25)
        i0 = int(STARTS[i] * SR)
        i1 = min(N, i0 + len(w))
        nat[i0:i1] += w[:i1 - i0]
        native_gain.append(dict(id=s["id"], rms_in=round(rms0, 4), gain=round(gain, 2),
                                rms_out=round(rms0 * gain, 4)))

    amb = bed()
    amb += rng.normal(0, 1, (N, 2)) * 0.0015     # 底噪
    # 台词
    voice = np.zeros((N, 2))
    tts_report = []
    for ln in tl["tts"]:
        p = Path(C.AUDIO) / "lines" / f"{ln['id']}.wav"
        if not p.exists():
            raise SystemExit(f"台词缺失：{p}")
        sr, x = wavfile.read(p)
        x = x.astype(np.float64) / 32768.0
        if x.ndim > 1:
            x = x[:, 0]
        x = x * ln["gain"] / 0.1
        i0 = int(ln["at"] * SR)
        i1 = min(N, i0 + len(x))
        voice[i0:i1, 0] += x[:i1 - i0]
        voice[i0:i1, 1] += x[:i1 - i0]
        tts_report.append(dict(ln, dur=round(len(x) / SR, 3)))

    mix = nat + amb + voice
    # 片头 0.4s / 片尾 0.5s 淡入淡出
    fi = int(0.4 * SR)
    mix[:fi] *= np.linspace(0, 1, fi)[:, None]
    fo = int((C.END_BLACK + 0.5) * SR)
    mix[-fo:] *= np.linspace(1, 0, fo)[:, None]
    raw_peak = float(np.max(np.abs(mix)))
    mix = np.tanh(mix * 1.01) * 0.95
    mix = mix / max(1.0, float(np.max(np.abs(mix))) / 0.89)

    wavfile.write(Path(C.AUDIO) / "mix.wav", SR, (mix * 32767).astype(np.int16))
    report = dict(total=round(N / SR, 3), raw_peak=round(raw_peak, 3),
                  native_rms=native_gain, tts=tts_report)
    json.dump(report, open(Path(C.BUILD) / "audio_report.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print("mix ->", Path(C.AUDIO) / "mix.wav")
    return 0


if __name__ == "__main__":
    sys.exit(main())
