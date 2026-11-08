FPS = 24
W, H = 1920, 1080
PW, PH = 3840, 2160          # supersampled working plate
OVERLAP = 0.62               # dissolve length between shots
BASE = r"d:\models\sample\天地源\天地源_video"

SHOTS = [
    dict(img="shot01", line=1, z=(1.015, 1.075), c0=(0.52, 0.50), c1=(0.60, 0.50), fog=0.13),
    dict(img="shot02", line=2, z=(1.10, 1.005), c0=(0.50, 0.52), c1=(0.50, 0.50), fog=0.14),
    dict(img="shot03", line=3, z=(1.005, 1.065), c0=(0.50, 0.50), c1=(0.575, 0.475), fog=0.10),
    dict(img="shot04", line=4, z=(1.11, 1.025), c0=(0.44, 0.55), c1=(0.50, 0.50), fog=0.09),
    dict(img="shot05", line=5, z=(1.13, 1.03), c0=(0.50, 0.47), c1=(0.50, 0.42), fog=0.05),
    dict(img="shot06", line=6, z=(1.01, 1.095), c0=(0.50, 0.50), c1=(0.50, 0.455), fog=0.05),
    dict(img="shot07_1", line=7, z=(1.075, 1.005), c0=(0.50, 0.50), c1=(0.635, 0.505), fog=0.12),
    dict(img="shot08", line=8, z=(1.095, 1.01), c0=(0.50, 0.545), c1=(0.50, 0.50), fog=0.11),
    dict(img="shot09", line=9, z=(1.02, 1.09), c0=(0.50, 0.50), c1=(0.51, 0.535), fog=0.10),
    dict(img="shot10", line=10, z=(1.035, 1.095), c0=(0.50, 0.54), c1=(0.49, 0.475), fog=0.0),
    dict(img="shot11", line=11, z=(1.085, 1.005), c0=(0.455, 0.50), c1=(0.50, 0.50), fog=0.13),
]
