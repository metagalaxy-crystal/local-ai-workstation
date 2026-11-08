# -*- coding: utf-8 -*-
"""旁白合成（进阶版）：分句韵律 + 自然停顿 + 近场话筒处理。

与 v1 的差别：
  1. 整句不再一次合成，而是切成小句，每句单独给 rate / pitch / volume，
     让语调有起伏、有轻重，而不是一条平线。
  2. 句内按标点插入长短不一的换气停顿（0.18~0.42s），避免“机关枪”。
  3. 每句做近场话筒链：高通 85Hz → 2.6kHz 存在感提升 → 温和压缩 → 短混响。
  4. 所有小句按语音 RMS 归一，彻底解决“声音忽大忽小”。

运行：python scripts\build_tts.py
产出：audio\lines\line01.wav .. line11.wav，build\tts_report.json
"""
import asyncio, hashlib, json, os, subprocess, sys
import numpy as np
from scipy import signal
from scipy.io import wavfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import BASE, AUDIO, LINES, BUILD, FFMPEG, VOICE, LINE_MOOD

SR = 48000
TXT = {
    1: "天色渐暗，天地园缩在街角，一边热闹，一边冷清。",
    2: "枯藤缠绕的小道，通向园中唯一的白花岗岩圆亭。",
    3: "我迈步进入，没有人注意到我。",
    4: "石子隐约铺出岔路，像循着某种规律，好似阵法。",
    5: "抬头，圆形的玻璃顶，铁支架上满是精细的花纹。",
    6: "玻璃好似并不存在。“虚无”跳进我的脑海。",
    7: "天地园，链接天地，直通人间：亭上是天界，树墙后是地狱，另一头是人间。",
    8: "人间水晶般完美，安静到一声啼哭，是唯一的声音。",
    9: "地狱并不可怕，它就是我们的生活：求而不得。",
    10: "而天堂最悲苦：神明看惯疾苦，世界只是一张碎裂的纸。",
    11: "二〇二二年三月六日，夜幕降临时。",
}

# 情绪 → (rate%, pitchHz, volume%)
MOOD = {
    "calm": (-6, -3, 0),
    "lift": (-2, 2, 2),
    "low": (-12, -6, -2),
    "void": (-17, -9, -6),
}
PAUSE = {"，": 0.24, "。": 0.40, "：": 0.32, "；": 0.36, "、": 0.20,
         "——": 0.30, "？": 0.38, "！": 0.30}
END = "，。：；！？、"


def split_clauses(text):
    """按标点切小句，标点保留在前一句尾部。返回 [(clause, pause_after), ...]"""
    out, cur, i = [], "", 0
    while i < len(text):
        ch = text[i]
        cur += ch
        if ch == "—" and text[i:i + 2] == "——":
            cur += "—"
            i += 1
            out.append((cur, PAUSE["——"]))
            cur = ""
        elif ch in END:
            out.append((cur, PAUSE.get(ch, 0.28)))
            cur = ""
        i += 1
    if cur.strip():
        out.append((cur, 0.0))
    # 最后一句后面不留标点停顿（整句之间由时间轴控制）
    return out


def jitter(seed, k, amp):
    h = hashlib.md5(f"{seed}-{k}".encode()).digest()
    return (h[0] / 255.0 - 0.5) * 2 * amp


async def synth_async(text, rate, pitch, vol, path):
    import edge_tts
    c = edge_tts.Communicate(text, VOICE, rate=f"{rate:+d}%",
                              pitch=f"{pitch:+d}Hz", volume=f"{vol:+d}%")
    await c.save(path)


def mp3_to_float(mp3):
    wav = mp3.replace(".mp3", ".tmp.wav")
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", mp3,
                    "-ac", "1", "-ar", str(SR), wav], check=True)
    _, d = wavfile.read(wav)
    os.remove(wav)
    return d.astype(np.float64) / 32768.0


def trim(x, thr=0.004):
    idx = np.where(np.abs(x) > thr)[0]
    if len(idx) < 10:
        return x
    a = max(0, idx[0] - int(0.02 * SR))
    b = min(len(x), idx[-1] + int(0.03 * SR))
    return x[a:b]


def vocal_chain(x):
    """近场人声处理：高通 + 存在感 + 压缩 + 短混响"""
    sos = signal.butter(2, 85, btype="high", fs=SR, output="sos")
    y = signal.sosfilt(sos, x)
    # presence: 2.5kHz 附近 +2.5dB（用一带通叠加实现）
    sos_p = signal.butter(2, [2200, 3400], btype="band", fs=SR, output="sos")
    y = y + 0.55 * signal.sosfilt(sos_p, y)
    # 存在的齿音软化：6.5kHz 以上轻衰减
    sos_s = signal.butter(2, 6500, btype="high", fs=SR, output="sos")
    y = y - 0.28 * signal.sosfilt(sos_s, y)
    # 温和压缩（3:1，阈值 -26dBFS，5ms/120ms）
    env = np.abs(y)
    atk = np.exp(-1.0 / (0.005 * SR))
    rel = np.exp(-1.0 / (0.120 * SR))
    e = signal.lfilter([1 - atk], [1, -atk], env)
    e = signal.lfilter([1 - rel], [1, -rel], e)
    e = np.maximum(e, 1e-6)
    db = 20 * np.log10(e)
    over = np.maximum(db + 26.0, 0.0)
    gain_db = -over * (1 - 1 / 3.0)
    g = 10 ** (gain_db / 20.0)
    g = np.clip(g, 0.25, 1.0)
    gf = np.convolve(g, np.ones(64) / 64, "same")
    y = y * gf
    # 短混响（0.55s，-20dB）
    rng = np.random.default_rng(3)
    n = int(0.55 * SR)
    ir = rng.normal(0, 1, n) * np.exp(-np.arange(n) / (0.13 * SR))
    ir[0] = 1.0
    ir /= np.sqrt(np.sum(ir ** 2))
    w = signal.fftconvolve(y, ir)[:len(y)]
    y = y * 0.92 + w * 0.10
    return y


def breath(dur=0.16, amp=0.010, seed=0):
    """极轻的换气声：带通的短噪声，两端淡入淡出"""
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    x = rng.normal(0, 1, n)
    sos = signal.butter(2, [420, 1800], btype="band", fs=SR, output="sos")
    x = signal.sosfilt(sos, x)
    x /= (np.max(np.abs(x)) + 1e-9)
    env = np.sin(np.pi * np.arange(n) / n) ** 2
    return x * env * amp


report = {"voice": VOICE, "mood": MOOD, "lines": []}
total_txt = 0.0
for ln in range(1, 12):
    text = TXT[ln]
    mood = LINE_MOOD[ln - 1]
    rate, pitch, vol = MOOD[mood]
    clauses = split_clauses(text)
    pieces = []
    cl_report = []
    t_cursor = 0.0
    for k, (cl, pause) in enumerate(clauses):
        # 句内递降：越靠后的分句，音高略低、语速略慢，像把话收住
        prog = k / max(len(clauses) - 1, 1)
        r = rate + int(round(-1.6 * prog + jitter(ln, k, 1.2)))
        p = pitch + int(round(-1.8 * prog + jitter(ln, k + 99, 1.0)))
        v = vol + int(round(-1.0 * prog))
        mp3 = os.path.join(LINES, f"c{ln:02d}_{k+1:02d}.mp3")
        asyncio.run(synth_async(cl, r, p, v, mp3))
        x = trim(mp3_to_float(mp3))
        os.remove(mp3)
        rms = np.sqrt(np.mean(x ** 2)) + 1e-9
        x = x * (0.105 / rms)
        x = np.clip(x, -0.95, 0.95)
        f = int(0.008 * SR)
        x[:f] *= np.linspace(0, 1, f)
        x[-f:] *= np.linspace(1, 0, f)
        pieces.append(x)
        cl_report.append(dict(text=cl, start=round(t_cursor, 3),
                              dur=round(len(x) / SR, 3), rate=r, pitch=p,
                              clause_pause=pause))
        t_cursor += len(x) / SR
        if pause > 0:
            gap = int(pause * SR)
            g = np.zeros(gap)
            # 长停顿里偶尔加一次极轻的换气，避免机械感
            if pause >= 0.34 and (ln + k) % 3 == 0:
                br = breath(amp=0.008, seed=ln * 10 + k)
                g[:len(br)] += br[:len(g)] if len(br) <= len(g) else br[:len(g)]
            pieces.append(g)
            t_cursor += pause
    y = np.concatenate(pieces)
    y = vocal_chain(y)
    y = y / (np.max(np.abs(y)) + 1e-9) * 0.89
    out = os.path.join(LINES, f"line{ln:02d}.wav")
    wavfile.write(out, SR, (y * 32767).astype(np.int16))
    report["lines"].append(dict(line=ln, mood=mood, text=text,
                                dur=round(len(y) / SR, 3), clauses=cl_report))
    total_txt += len(y) / SR
    print(f"line{ln:02d} {mood:5s} {len(y)/SR:5.2f}s  {text}", flush=True)

json.dump(report, open(os.path.join(BUILD, "tts_report.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("total speech", round(total_txt, 2), "s")
