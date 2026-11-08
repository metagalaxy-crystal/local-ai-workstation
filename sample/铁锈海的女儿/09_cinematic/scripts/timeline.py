# -*- coding: utf-8 -*-
"""v2 时间轴：不用光流重定时，直接用 H3 原始片段时长 + 固定过渡。
每个镜头时长 = SHOT_FIXED_SEC（6.0s），片段 5.17s 在中间前后各补黑 0.415s。
产出：build\\timeline.json
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from txh_config import BUILD, SHOTS, XFADE, SHOT_FIXED_SEC, END_CARD

import cv2

def clip_len(path):
    if not os.path.exists(path):
        return 0.0
    cap = cv2.VideoCapture(path)
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    cap.release()
    return round(n / fps, 2)

rep = json.load(open(os.path.join(BUILD, "tts_report.json"), encoding="utf-8"))
speech = [l.get("dur") or l["seconds"] for l in rep["lines"]]

# 固定时长策略：每个镜头 6.0s（或用片段实际时长+缓冲，取最大）
fixed_durs = [SHOT_FIXED_SEC] * len(SHOTS)
# 如果旁白太长，自动拉长对应镜头时长
for i, sp in enumerate(speech):
    need = sp + 0.90      # 前 0.45s + 旁白 + 后 0.45s
    if need > fixed_durs[i]:
        fixed_durs[i] = round(need + 0.30, 2)

durs = fixed_durs
starts = [round(sum(durs[:i]) - i * XFADE, 3) for i in range(len(durs))]
# 旁白在镜头开始后 0.45s 入
narr_at = [round(starts[i] + 0.45, 3) for i in range(len(durs))]
total = round(starts[-1] + durs[-1] + END_CARD, 3)

clips = {}
for s in SHOTS:
    p = os.path.join(os.path.dirname(BUILD) + os.sep + "clips", s["clip"] + ".mp4")
    clips[s["key"]] = clip_len(p)

data = dict(fps=24, xfade=XFADE, end_card=END_CARD, durs=durs, starts=starts,
            narr_at=narr_at, total=total, speech=speech, clip_seconds=clips,
            strategy="fixed_6s_plus_buffer")
json.dump(data, open(os.path.join(BUILD, "timeline.json"), "w", encoding="utf-8"), indent=1)

for i, s in enumerate(SHOTS):
    print(f"{s['key']} dur={durs[i]:5.2f} start={starts[i]:5.2f} narr={narr_at[i]:5.2f} "
          f"clip={clips[s['key']]:4.2f}s")
print("total", total, "s (片尾卡", END_CARD, "s)")
