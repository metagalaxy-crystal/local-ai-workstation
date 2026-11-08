# -*- coding: utf-8 -*-
"""天地源 · 电影版（v3）—— 全局配置：全本地流水线（Z-Image 生图 / MiniMax-H3 生视频 /
VoxCPM2 旁白 / ACE-Step 配乐 / numpy 音效 / OpenCV 电影化合成）

注：原 TTS 链路为 MOSS-TTS，已统一迁移至 VoxCPM2（保留本配置作为历史记录）。
"""
import os

BASE = r"d:\models\sample\天地源\天地源_电影版"
IMG = os.path.join(BASE, "images")
CLIPS = os.path.join(BASE, "clips")
AUDIO = os.path.join(BASE, "audio")
LINES = os.path.join(AUDIO, "lines")
STEMS = os.path.join(AUDIO, "stems")
MUSIC = os.path.join(BASE, "music")
BUILD = os.path.join(BASE, "build")
OUT = os.path.join(BASE, "out")

FFMPEG = r"C:\Program Files\EVCapture\ffmpeg.exe"
FFPROBE = r"C:\Program Files\EVCapture\ffprobe.exe"

FPS = 24
W, H = 1920, 1080          # 交付画幅（含遮幅黑边）
SCOPE_H = 804              # 2.39:1  Cinemascope 有效画面高度
XFADE = 0.72

# 本地生成规格
IMG_RES = "1344x576"       # Z-Image 关键帧（2.33:1）
CLIP_RES = "1120x480"      # H3 i2v（同宽高比，32 的倍数）
CLIP_STEPS = 20

# TTS：VoxCPM2（原 MOSS-TTS 已下线，模型与调用脚本已删除）
VOXCPM_DIR = r"D:\models\models\audio\VoxCPM2"
# 参考音：v2 的 Yunxi 试音样本（仅作声纹参考，合成全部本地完成）
VOXCPM_REF = r"d:\models\sample\天地源\天地源_进阶版\tts_test\zh-CN-YunxiNeural.wav"
VOXCPM_SR = 48000

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

# place 决定环境音推子场景；cam 是摄影机运动描述（写进 i2v 提示词）
SHOTS = [
    dict(key="S01", img="shot01", clip="s01", line=1, place="out",
         cam="缓慢推近", fog=0.14),
    dict(key="S02", img="shot02", clip="s02", line=2, place="path",
         cam="沿小道缓慢前移", fog=0.16),
    dict(key="S03", img="shot03", clip="s03", line=3, place="pavilion",
         cam="缓慢推进", fog=0.08),
    dict(key="S04", img="shot04", clip="s04", line=4, place="pavilion",
         cam="低位缓慢横移掠过地面", fog=0.06),
    dict(key="S05", img="shot05", clip="s05", line=5, place="pavilion",
         cam="缓慢上摇推近穹顶", fog=0.03),
    dict(key="S06", img="shot06", clip="s06", line=6, place="pavilion",
         cam="极缓慢推近玻璃", fog=0.02),
    dict(key="S07", img="shot07", clip="s07", line=7, place="three",
         cam="沿光柱缓慢升起", fog=0.13),
    dict(key="S08", img="shot08", clip="s08", line=8, place="world",
         cam="缓慢横移", fog=0.10),
    dict(key="S09", img="shot09", clip="s09", line=9, place="hell",
         cam="缓慢跟随背影前行", fog=0.07),
    dict(key="S10", img="shot10", clip="s10", line=10, place="heaven",
         cam="缓慢推进", fog=0.09),
    dict(key="S11", img="shot11", clip="s11", line=11, place="out",
         cam="缓慢拉远", fog=0.15),
]

LINE_MOOD = ["calm", "lift", "calm", "low", "calm", "void", "low",
             "calm", "low", "low", "void"]
LEAD = [1.55, 0.95, 0.80, 0.90, 0.85, 0.90, 1.00, 0.95, 1.00, 1.05, 1.20]
TAIL = [1.30, 1.05, 0.95, 1.05, 1.00, 1.10, 1.35, 1.10, 1.15, 1.30, 3.20]
