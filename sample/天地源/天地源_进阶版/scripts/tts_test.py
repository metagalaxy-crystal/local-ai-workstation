# -*- coding: utf-8 -*-
r"""音色试音：同一句话用多个 edge-tts 中文音色合成，量化“表现力”后择优。

指标：
  f0_std   基频标准差（半音）——越大说明语调起伏越丰富
  rms_dyn  能量动态范围（dB）——越大说明轻重变化越明显
  rate     语速（字/秒）——过快会显得播音腔
  pause    句内停顿占比
输出：tts_test\metrics.json + 每个音色的 wav
"""
import asyncio, json, os, subprocess, sys
import numpy as np
from scipy import signal
from scipy.io import wavfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import BASE, FFMPEG

TEST = os.path.join(BASE, "tts_test")
VOICES = ["zh-CN-YunxiNeural", "zh-CN-XiaoxiaoNeural", "zh-CN-YunjianNeural",
          "zh-CN-YunyangNeural", "zh-CN-XiaoyiNeural"]
SENT = "玻璃好似并不存在。“虚无”跳进我的脑海。"
TXT = os.path.join(TEST, "sent.txt")
open(TXT, "w", encoding="utf-8").write(SENT)
SR = 48000


async def synth(voice, mp3):
    import edge_tts
    c = edge_tts.Communicate(SENT, voice, rate="-4%", pitch="-2Hz")
    await c.save(mp3)


def to_wav(mp3, wav):
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", mp3,
                    "-ac", "1", "-ar", str(SR), wav], check=True)


def f0_track(x, sr=SR):
    win, hop = int(0.040 * sr), int(0.010 * sr)
    lo, hi = int(sr / 380), int(sr / 70)
    out = []
    for i in range(0, len(x) - win, hop):
        fr = x[i:i + win].astype(np.float64)
        fr = fr - fr.mean()
        if np.sqrt(np.mean(fr ** 2)) < 0.006:
            continue
        ac = np.correlate(fr, fr, "full")[win - 1:]
        ac /= (ac[0] + 1e-9)
        seg = ac[lo:hi]
        k = int(np.argmax(seg)) + lo
        if ac[k] > 0.42:
            out.append(sr / k)
    return np.array(out)


def analyse(wav):
    sr, d = wavfile.read(wav)
    x = d.astype(np.float64) / 32768.0
    idx = np.where(np.abs(x) > 0.004)[0]
    x = x[idx[0]:idx[-1]] if len(idx) else x
    f0 = f0_track(x, sr)
    semi = 12 * np.log2(f0 / np.median(f0) + 1e-9) if len(f0) else np.array([0.0])
    # 能量动态：把语音段切成 50ms 块，取块 RMS 的 10%~90% 分位差
    n = int(0.050 * sr)
    rms = np.array([np.sqrt(np.mean(x[i:i + n] ** 2)) for i in range(0, len(x) - n, n)])
    rms = rms[rms > 0.004]
    dyn = 20 * np.log10(np.percentile(rms, 90) / (np.percentile(rms, 10) + 1e-9)) if len(rms) else 0
    voiced = np.mean(np.abs(x) > 0.004)
    return dict(f0_std=round(float(np.std(semi)), 2), f0_med=round(float(np.median(f0)), 1),
                rms_dyn=round(float(dyn), 1), pause=round(float(1 - voiced), 3),
                dur=round(len(x) / sr, 2), rate=round(len(SENT) / (len(x) / sr), 2))


res = {}
for v in VOICES:
    mp3 = os.path.join(TEST, v + ".mp3")
    wav = os.path.join(TEST, v + ".wav")
    asyncio.run(synth(v, mp3))
    to_wav(mp3, wav)
    m = analyse(wav)
    res[v] = m
    print(v, m, flush=True)

json.dump(res, open(os.path.join(TEST, "metrics.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("done")
