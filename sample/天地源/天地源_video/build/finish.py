import json, os, re, subprocess, sys

BASE = r"d:\models\sample\天地源\天地源_video"
FF = r"C:\Program Files\EVCapture\ffmpeg.exe"
mix = os.path.join(BASE, "audio", "mix.wav")
master = os.path.join(BASE, "audio", "master.wav")

r = subprocess.run([FF, "-hide_banner", "-i", mix, "-af",
                    "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
                    "-f", "null", "-"], capture_output=True, text=True)
txt = r.stderr
m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", txt, re.S)
data = json.loads(m.group(0))
print(data)
args = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={data['input_i']}:"
        f"measured_TP={data['input_tp']}:measured_LRA={data['input_lra']}:"
        f"measured_thresh={data['input_thresh']}:offset={data['target_offset']}:linear=true")
subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", "-i", mix, "-af", args,
                "-ar", "48000", master], check=True)
print("master written")

out = os.path.join(BASE, "天地源_短片.mp4")
subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error",
                "-i", os.path.join(BASE, "build", "video_noaudio.mp4"),
                "-i", master, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart", out], check=True)
print("muxed", out, round(os.path.getsize(out) / 1e6, 1), "MB")
