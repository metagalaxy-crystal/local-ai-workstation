# -*- coding: utf-8 -*-
r"""质检：每个片段抽取 4 帧拼图 + 音频 RMS/峰值，输出 build\qc\qc_report.json"""
import json, subprocess, sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
import zwj_config as C

QC = Path(C.BUILD) / "qc"
QC.mkdir(parents=True, exist_ok=True)
rep = []
for s in C.SHOTS:
    mp4 = Path(C.CLIPS) / f"{s['clip']}.mp4"
    if not mp4.exists():
        rep.append(dict(id=s["id"], exists=False))
        continue
    tile = QC / f"{s['clip']}_tiles.png"
    subprocess.run([C.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(mp4),
                    "-vf", "select='eq(n\\,0)+eq(n\\,40)+eq(n\\,80)+eq(n\\,120)',scale=1088:-1,tile=2x2",
                    "-frames:v", "1", str(tile)], check=True)
    wav = QC / f"{s['clip']}_a.wav"
    subprocess.run([C.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(mp4),
                    "-vn", "-ac", "1", "-ar", "16000", str(wav)], check=True)
    x, sr = sf.read(wav, dtype="float32")
    rep.append(dict(id=s["id"], exists=True, dur=round(len(x) / sr, 3),
                    rms=round(float(np.sqrt(np.mean(x ** 2))), 4),
                    peak=round(float(np.max(np.abs(x))), 4),
                    tile=str(tile)))
json.dump(rep, open(QC / "qc_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(rep, ensure_ascii=False, indent=1))
