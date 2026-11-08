# -*- coding: utf-8 -*-
"""时间轴：由旁白实际时长推导每个镜头时长、起点、旁白入点。

规则：镜头时长 = LEAD + 本句旁白 + TAIL；镜头之间用 XFADE 叠化，
      因此 starts[i] = sum(durs[:i]) - i * XFADE。
产出：build\\timeline.json
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import BASE, BUILD, SHOTS, XFADE, LEAD, TAIL

rep = json.load(open(os.path.join(BUILD, "tts_report.json"), encoding="utf-8"))
speech = [l["dur"] for l in rep["lines"]]
assert len(speech) == len(SHOTS) == len(LEAD) == len(TAIL)

durs = [round(LEAD[i] + speech[i] + TAIL[i], 3) for i in range(len(speech))]
starts = [round(sum(durs[:i]) - i * XFADE, 3) for i in range(len(durs))]
narr_at = [round(starts[i] + LEAD[i], 3) for i in range(len(durs))]
total = round(starts[-1] + durs[-1], 3)

# 每个镜头的动态素材实际时长（以文件为准），用于决定慢放倍率
import cv2

def clip_len(path):
    if not os.path.exists(path):
        return 0.0
    cap = cv2.VideoCapture(path)
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    cap.release()
    return round(n / fps, 2)

clips = {}
for s in SHOTS:
    p = os.path.join(BASE, "clips", (s["clip"] + ".mp4") if s["clip"] else "__none__")
    clips[s["key"]] = clip_len(p)

ratio = {s["key"]: round(durs[i] / clips[s["key"]], 2) if clips[s["key"]] else None
         for i, s in enumerate(SHOTS)}

data = dict(fps=24, xfade=XFADE, durs=durs, starts=starts, narr_at=narr_at,
            total=total, speech=speech, clip_seconds=clips, slow_ratio=ratio)
json.dump(data, open(os.path.join(BUILD, "timeline.json"), "w", encoding="utf-8"), indent=1)

for i, s in enumerate(SHOTS):
    print(f"{s['key']} dur={durs[i]:5.2f} start={starts[i]:5.2f} narr={narr_at[i]:5.2f} "
          f"clip={clips[s['key']]:4.2f}s slow={ratio[s['key']]}")
print("total", total, "s")
