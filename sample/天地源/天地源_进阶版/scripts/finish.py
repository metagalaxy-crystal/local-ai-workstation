# -*- coding: utf-8 -*-
"""母带与封装：两遍 loudnorm 到 -16 LUFS / TP -1.5，再与画面合成成片。

运行：python scripts\\finish.py
产出：out\\天地源_进阶版_短片.mp4
"""
import json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import BASE, BUILD, AUDIO, OUT, FFMPEG

mix = os.path.join(AUDIO, "mix.wav")
master = os.path.join(AUDIO, "master.wav")
video = os.path.join(BUILD, "video_noaudio.mp4")
out = os.path.join(OUT, "天地源_进阶版_短片.mp4")

r = subprocess.run([FFMPEG, "-hide_banner", "-i", mix, "-af",
                    "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
                    "-f", "null", "-"], capture_output=True, text=True)
m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
data = json.loads(m.group(0))
print({k: data[k] for k in ("input_i", "input_tp", "input_lra", "input_thresh")})

args = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={data['input_i']}:"
        f"measured_TP={data['input_tp']}:measured_LRA={data['input_lra']}:"
        f"measured_thresh={data['input_thresh']}:offset={data['target_offset']}:linear=true")
subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", mix, "-af", args,
                "-ar", "48000", master], check=True)
print("master written")

subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                "-i", video, "-i", master, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart", out], check=True)
print("muxed", out, round(os.path.getsize(out) / 1e6, 1), "MB")
