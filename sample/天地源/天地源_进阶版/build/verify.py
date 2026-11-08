# -*- coding: utf-8 -*-
"""成片自检：响度稳定性、声源与镜头的对位、旁白入点。"""
import json, os
import numpy as np
from scipy.io import wavfile

B = r"d:\models\sample\天地源\天地源_进阶版"
SR = 48000
tl = json.load(open(os.path.join(B, "build", "timeline.json"), encoding="utf-8"))
STARTS, DURS, NARR = tl["starts"], tl["durs"], tl["narr_at"]

sr, d = wavfile.read(os.path.join(B, "audio", "mix.wav"))
x = d.astype(np.float64) / 32768.0
n = int(2.0 * SR)
rms = np.sqrt(np.mean(x[:len(x) // n * n].reshape(-1, n, 2) ** 2, axis=1)).mean(axis=1)
db = 20 * np.log10(rms + 1e-9)
print("全长 %.1fs  2s-RMS: min %.1f  max %.1f  极差 %.1f dB" %
      (len(x) / SR, db.min(), db.max(), db.max() - db.min()))

# 每个镜头窗口内的平均响度，确认没有突然的“忽大忽小”
print("\n镜头窗口响度：")
for i in range(len(STARTS)):
    a, b = int(STARTS[i] * SR), int((STARTS[i] + DURS[i]) * SR)
    seg = x[a:b]
    r = np.sqrt(np.mean(seg ** 2))
    print("  S%02d  %5.2f dBFS  %5.2fs" % (i + 1, 20 * np.log10(r + 1e-9), DURS[i]))

# 声源是否落在该落的镜头
print("\n声源对位（原始 stem 的场内/场外对比，>12 dB 视为对位明确）：")
checks = {"fire": [8], "paper": [9], "steps": [1, 2], "glass": [2, 4, 5],
          "crystal": [6], "insects": [0, 10], "drips": [0]}
for name, idxs in checks.items():
    _, sd = wavfile.read(os.path.join(B, "audio", "stems", name + ".wav"))
    s = sd.astype(np.float64)
    vals = []
    for i in range(len(STARTS)):
        a, b = int(STARTS[i] * SR), min(len(s), int((STARTS[i] + DURS[i]) * SR))
        vals.append(float(np.sqrt(np.mean(s[a:b] ** 2) + 1e-12)))
    inl = np.mean([vals[i] for i in idxs])
    out = np.mean([vals[i] for i in range(len(vals)) if i not in idxs]) + 1e-12
    print(f"  {name:8s} 命中镜头 {['S%02d' % (i+1) for i in idxs]}  "
          f"场内 {20*np.log10(inl+1e-12):6.1f} dB / 场外 {20*np.log10(out):6.1f} dB "
          f"→ 对比 {20*np.log10(inl/out):5.1f} dB")

print("\n旁白存在性（句内 RMS 相对句前留白，应 > 10 dB）：")
for i in range(len(STARTS)):
    a0, a1 = int((NARR[i] + 0.3) * SR), int((NARR[i] + tl["speech"][i] - 0.2) * SR)
    b0, b1 = int(max(0, NARR[i] - 0.8) * SR), int((NARR[i] - 0.2) * SR)
    rin = np.sqrt(np.mean(x[a0:a1] ** 2))
    rout = np.sqrt(np.mean(x[b0:b1] ** 2))
    print("  S%02d 句内 %5.1f dBFS  句前 %5.1f dBFS  差 %4.1f dB" %
          (i + 1, 20 * np.log10(rin + 1e-9), 20 * np.log10(rout + 1e-9),
           20 * np.log10(rin / (rout + 1e-9))))

print("\n旁白入点：", ", ".join(f"S{i+1}@{NARR[i]:.2f}s" for i in range(len(NARR))))
