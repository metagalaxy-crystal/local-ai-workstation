import asyncio, json, os, subprocess
import edge_tts

VOICE = "zh-CN-YunyangNeural"
RATE = "-6%"
PITCH = "-3Hz"

LINES = [
    "天色渐暗，天地园缩在街角，一边热闹，一边冷清。",
    "枯藤缠绕的小道，通向园中唯一的白花岗岩圆亭。",
    "我迈步进入，没有人注意到我。",
    "石子隐约铺出岔路，像循着某种规律，好似阵法。",
    "抬头，圆形的玻璃顶，铁支架上满是精细的花纹。",
    "玻璃好似并不存在。“虚无”跳进我的脑海。",
    "天地园，链接天地，直通人间：亭上是天界，树墙后是地狱，另一头是人间。",
    "人间水晶般完美，安静到一声啼哭，是唯一的声音。",
    "地狱并不可怕，它就是我们的生活：求而不得。",
    "而天堂最悲苦：神明看惯疾苦，世界只是一张碎裂的纸。",
    "二〇二二年三月六日，夜幕降临时。",
]

BASE = r"d:\models\sample\天地源\天地源_video"
FFMPEG = r"C:\Program Files\EVCapture\ffmpeg.exe"
OUT = os.path.join(BASE, "audio")


async def synth(i, text):
    mp3 = os.path.join(OUT, f"line{i:02d}.mp3")
    wav = os.path.join(OUT, f"line{i:02d}.wav")
    com = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH)
    await com.save(mp3)
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", mp3,
                    "-ar", "48000", "-ac", "1", wav], check=True)
    return wav


async def main():
    tasks = [synth(i + 1, t) for i, t in enumerate(LINES)]
    await asyncio.gather(*tasks)
    from scipy.io import wavfile
    durs = []
    for i in range(len(LINES)):
        sr, data = wavfile.read(os.path.join(OUT, f"line{i+1:02d}.wav"))
        durs.append(round(len(data) / sr, 3))
    with open(os.path.join(BASE, "build", "lines.json"), "w", encoding="utf-8") as f:
        json.dump({"voice": VOICE, "lines": LINES, "durations": durs}, f, ensure_ascii=False, indent=1)
    print(list(zip(range(1, len(LINES) + 1), durs)), "total", round(sum(durs), 2))

asyncio.run(main())
