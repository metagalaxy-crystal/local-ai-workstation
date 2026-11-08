# -*- coding: utf-8 -*-
"""铁锈海的女儿 · 第一节 电影版 v2 —— 全局配置
改进要点：
  1. 声线：父亲=Yunjian→降调+失真→沧桑；成年玛莲=Yunxi→降速+混响→疲惫低沉；
     七岁玛莲=XiaoXiao→升调+高频→清亮童声（与成年版明显区分）
  2. TTS 参数：更保守，贴近参考音自然度（原 MOSS-TTS，现迁移至 VoxCPM2）
  3. 取消光流慢放，直接用 H3 原始片段时长
  4. i2v 提示词加入明确的人像微动作（眨眼/呼吸/嘴唇/头发/表情）
"""
import os

BASE = r"d:\models\sample\铁锈海的女儿\09_cinematic"
IMG = os.path.join(BASE, "images")
CLIPS = os.path.join(BASE, "clips")
AUDIO = os.path.join(BASE, "audio")
LINES_DIR = os.path.join(AUDIO, "lines")
STEMS = os.path.join(AUDIO, "stems")
MUSIC = os.path.join(BASE, "music")
BUILD = os.path.join(BASE, "build")
OUT = os.path.join(BASE, "out")

FFMPEG = r"C:\Program Files\EVCapture\ffmpeg.exe"
FFPROBE = r"C:\Program Files\EVCapture\ffprobe.exe"

FPS = 24
W, H = 1920, 1080
SCOPE_H = 804
XFADE = 0.60
END_CARD = 2.8

IMG_RES = "1344x576"
CLIP_RES = "1120x480"
CLIP_STEPS = 20
CLIP_LEN = 124             # 17k+5, 124/24 = 5.17s；渲染时尾部重复补足镜头时长

# ========== 三声部参考音 ==========
# TTS 引擎：VoxCPM2（原 MOSS-TTS 已下线）
VOXCPM_DIR = r"D:\models\models\audio\VoxCPM2"
VOXCPM_SR = 48000
_TTS_REF = r"d:\models\sample\天地源\天地源_进阶版\tts_test"
VOICES = {
    # 成年玛莲（29岁疲惫内心独白）：云希做基底 → 降速+低频提升+混响
    "narrator": os.path.join(_TTS_REF, "zh-CN-YunxiNeural.wav"),
    # 父亲（35岁锅炉工沧桑沙哑）：云健做基底 → 降调+低通+失真
    "father":   os.path.join(_TTS_REF, "zh-CN-YunjianNeural.wav"),
    # 七岁玛莲（清亮好奇童声）：晓晓 → 升调+高频
    "girl":     os.path.join(_TTS_REF, "zh-CN-XiaoxiaoNeural.wav"),
}

# ========== 声部修饰参数（v2 新增） ==========
# (tape_ratio=变速, eq_low=低频提升dB, eq_high=高频切除dB, lp_cut=低通截止Hz,
#  reverb_wet=混响湿声%, distort=失真量, gain=增益归一)
VOICE_CHAR = {
    "narrator": (0.92, 3.0, 5.0, 3800, 0.18, 0.00, 0.110),  # 疲惫低沉，像在回忆
    "father":   (0.88, 4.0, 4.5, 3000, 0.12, 0.08, 0.100),  # 沧桑沙哑，锅炉工
    "girl":     (1.06, 0.0, -2.0, 8000, 0.05, 0.00, 0.100), # 清亮好奇，童声
}

# TTS 生成参数（VoxCPM2；原 MOSS-TTS 参数已下线）
TTS_GEN = dict(cfg_value=1.5, inference_timesteps=10)

# ========== 旁白结构（分句更自然，不再硬编码停顿） ==========
# 文本里直接写自然停顿点："……" 表示长停顿，"嗯" 之类的不要
LINES = {
    1: [("玛莲·艾德斯坦记得……铁锈海还叫蓝海的那一天。", "narrator", "")],
    2: [("那年她七岁，父亲把她扛在肩头，站在灰炉镇外的悬崖上。这是她第一次离开家旅行。", "narrator", "")],
    3: [("海风灌进她的领口，咸腥里夹着一种她说不上来的清冽。海是蓝的，像玻璃一样的蓝。", "narrator", "")],
    4: [("阳光碎在海面上，碎成千万片银子，晃得她眯起眼睛。", "narrator", "")],
    5: [("好看吗？", "father", "cloth"),
        ("父亲问。", "narrator", ""),
        ("好看。", "girl", "bright"),
        ("她说。", "narrator", "")],
    6: [("记住这个颜色。", "father", "cloth"),
        ("父亲的声音从她头顶传下来，闷闷的，像隔着一层布。", "narrator", ""),
        ("以后就……见不到了。", "father", "cloth")],
    7: [("她当时不懂。她觉得，海就是深蓝色的。这是常识。", "narrator", "")],
    8: [("二十九岁的玛莲，站在同一块悬崖上。脚下是锈红色的海水，赤潮像一张巨大的腐烂的毯子，一直铺到天际线。", "narrator", "")],
    9: [("她记不清小时候的味道，也记不清当时的颜色。唯一记得的……是父亲说的那句话。", "narrator", "")],
}

TXT = {i: "".join(seg[0] for seg in segs) for i, segs in LINES.items()}

# place 场景决定环境音推子；cam=摄影机运动（写进 i2v 提示词）
SHOTS = [
    dict(key="S01", img="shot01", clip="s01", line=1, place="town",
         cam="从悬崖缓慢下降并推向远处海面", fog=0.12),
    dict(key="S02", img="shot02", clip="s02", line=2, place="cliff",
         cam="极缓慢推近父女背影", fog=0.05),
    dict(key="S03", img="shot03", clip="s03", line=3, place="cliff",
         cam="缓慢向右横移", fog=0.03),
    dict(key="S04", img="shot04", clip="s04", line=4, place="cliff",
         cam="极缓慢推近女孩面部", fog=0.02),
    dict(key="S05", img="shot05", clip="s05", line=5, place="cliff",
         cam="固定机位轻微呼吸感", fog=0.02),
    dict(key="S06", img="shot06", clip="s06", line=6, place="cliff",
         cam="缓慢拉远", fog=0.06),
    dict(key="S07", img="shot07", clip="s07", line=7, place="trans",
         cam="固定机位延时流逝", fog=0.10),
    dict(key="S08", img="shot08", clip="s08", line=8, place="rust",
         cam="缓慢推近玛莲", fog=0.14),
    dict(key="S09", img="shot09", clip="s09", line=9, place="rust",
         cam="缓慢拉远并升高", fog=0.16),
]

# 取消光流慢放后，镜头时长 = 原始片段时长(5.17s) + 前后空镜缓冲
# LEAD 是镜头开始时旁白还没出声的空白时间（让画面先有呼吸）
# TAIL 是旁白结束后画面继续走的时间（让情绪沉落）
LINE_MOOD = ["calm", "calm", "lift", "lift", "calm", "low", "low", "low", "void"]
# 每镜头固定时长（不用光流拉长，统一给 6.0s；原始片段 5.17s 占满后前后补黑）
SHOT_FIXED_SEC = 6.00

DIP = [0, 0, 0, 0, 0, 0.30, 0.20, 0, 0]
INTENSITY = [0.45, 0.55, 0.50, 0.55, 0.60, 0.72, 0.78, 0.90, 0.50]

TITLE = "铁锈海的女儿"
SUBTITLE = "第一节 · 蓝海"
