# -*- coding: utf-8 -*-
"""天地源 · 进阶版 —— 全局配置（所有路径、分镜、参数集中在这里）"""
import os

BASE = r"d:\models\sample\天地源\天地源_进阶版"
IMG = os.path.join(BASE, "images")
CLIPS = os.path.join(BASE, "clips")
AUDIO = os.path.join(BASE, "audio")
LINES = os.path.join(AUDIO, "lines")
STEMS = os.path.join(AUDIO, "stems")
BUILD = os.path.join(BASE, "build")
OUT = os.path.join(BASE, "out")

FFMPEG = r"C:\Program Files\EVCapture\ffmpeg.exe"
FFPROBE = r"C:\Program Files\EVCapture\ffprobe.exe"

FPS = 24
W, H = 1920, 1080
PW, PH = 3840, 2160          # 超采样工作底板
XFADE = 0.72                 # 镜头之间的叠化时长（秒）

# 旁白音色
VOICE = "zh-CN-YunxiNeural"

# line: 对应旁白句子序号（1..11）
# clip: clips 目录中的动态素材名（None = 静态关键帧 + 程序化氛围）
# clip_dur: 生成片段的原始时长，用于决定播放速率
# motion: 片段不足时的兜底运镜强度 (z0, z1)
SHOTS = [
    dict(key="S01", img="shot01", clip="s01", clip_dur=8.0, line=1,
         z=(1.000, 1.030), c0=(0.500, 0.500), c1=(0.535, 0.500),
         fog=0.14, wind=1.00, place="out"),
    dict(key="S02", img="shot02", clip="s02", clip_dur=8.0, line=2,
         z=(1.000, 1.022), c0=(0.500, 0.520), c1=(0.500, 0.500),
         fog=0.16, wind=0.95, place="path"),
    dict(key="S03", img="shot03", clip="s03", clip_dur=6.0, line=3,
         z=(1.000, 1.030), c0=(0.500, 0.500), c1=(0.520, 0.492),
         fog=0.08, wind=0.55, place="pavilion"),
    dict(key="S04", img="shot04", clip="s04", clip_dur=6.0, line=4,
         z=(1.000, 1.055), c0=(0.500, 0.500), c1=(0.520, 0.505),
         fog=0.06, wind=0.55, place="pavilion"),
    dict(key="S05", img="shot05", clip="s05", clip_dur=6.0, line=5,
         z=(1.000, 1.028), c0=(0.500, 0.500), c1=(0.512, 0.492),
         fog=0.03, wind=0.40, place="pavilion"),
    dict(key="S06", img="shot06", clip="s06", clip_dur=6.0, line=6,
         z=(1.000, 1.050), c0=(0.500, 0.500), c1=(0.500, 0.480),
         fog=0.02, wind=0.35, place="pavilion"),
    dict(key="S07", img="shot07_1", clip="s07", clip_dur=10.0, line=7,
         z=(1.000, 1.026), c0=(0.500, 0.500), c1=(0.545, 0.505),
         fog=0.13, wind=0.80, place="three"),
    dict(key="S08", img="shot08", clip="s08", clip_dur=6.0, line=8,
         z=(1.000, 1.060), c0=(0.500, 0.540), c1=(0.500, 0.500),
         fog=0.10, wind=0.30, place="world"),
    dict(key="S09", img="shot09", clip="s09", clip_dur=6.0, line=9,
         z=(1.000, 1.024), c0=(0.500, 0.500), c1=(0.500, 0.485),
         fog=0.07, wind=0.50, place="hell"),
    dict(key="S10", img="shot10", clip="s10", clip_dur=6.0, line=10,
         z=(1.000, 1.030), c0=(0.500, 0.500), c1=(0.520, 0.492),
         fog=0.09, wind=0.85, place="heaven"),
    dict(key="S11", img="shot11", clip="s11", clip_dur=6.0, line=11,
         z=(1.000, 1.042), c0=(0.500, 0.500), c1=(0.500, 0.500),
         fog=0.15, wind=1.05, place="out"),
]

# 每句旁白的情绪/停顿脚本：mode 决定基础语速与音高偏移
#   calm   — 平稳叙述
#   low    — 压低、放慢（沉重、虚无）
#   lift   — 略提、稍快（引入、递进）
#   void   — 很慢、很轻（三界、结尾）
LINE_MOOD = ["calm", "lift", "calm", "low", "calm", "void", "low",
             "calm", "low", "low", "void"]

# 镜头分配给的旁白之外，句子前后的呼吸时间（秒）
LEAD = [1.55, 0.95, 0.80, 0.90, 0.85, 0.90, 1.00, 0.95, 1.00, 1.05, 1.20]
TAIL = [1.30, 1.05, 0.95, 1.05, 1.00, 1.10, 1.35, 1.10, 1.15, 1.30, 3.20]

