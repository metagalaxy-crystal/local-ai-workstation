# -*- coding: utf-8 -*-
r"""ACE-Step 本地配乐：主氛围床 76s + 高潮层 40s（D 小调，电影氛围）。
用法： python scripts\gen_music.py [--force]
产物： music\bgm_main.* / bgm_climax.* + music\music_report.json
"""
import argparse, json, os, sys, time
from pathlib import Path

sys.path.insert(0, r"D:\models\scripts")
sys.path.insert(0, r"D:\models\scripts\comfyui")
from comfy_client import ComfyClient, load_workflow  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from v3_config import MUSIC  # noqa: E402

WF = Path(r"D:\models\scripts\comfyui\acestep\workflow.json")
HOST = "http://127.0.0.1:8188"

TRACKS = {
    "bgm_main": dict(
        tags="cinematic, ambient, piano, strings pad, slow, melancholic, atmospheric, film score, reverb, minimal",
        duration=76, bpm=66, keyscale="D minor", seed=901, steps=30),
    "bgm_climax": dict(
        tags="cinematic, strings, intense, emotional, slow build, film score, epic, drums, swelling",
        duration=40, bpm=66, keyscale="D minor", seed=902, steps=30),
}


def gen(name, cfg, client, force):
    out = Path(MUSIC) / f"{name}.flac"
    if (out.exists() or (Path(MUSIC) / f"{name}.mp3").exists()) and not force:
        print(f"[skip] {name}")
        return
    wf = load_workflow(WF)
    meta = wf["_meta"]
    enc = wf[meta["encode"]]["inputs"]
    enc["tags"] = cfg["tags"]
    if "duration" in enc:                       # 编码节点的时长也要同步，否则只生成 30s
        enc["duration"] = float(cfg["duration"])
    wf[meta["latent"]]["inputs"]["seconds"] = cfg["duration"]
    # 时长相关的显式字段（不同版本节点字段名不同，尽量都写）
    for k in ("duration", "seconds"):
        if k in wf[meta["latent"]]["inputs"]:
            wf[meta["latent"]]["inputs"][k] = cfg["duration"]
    wf[meta["sampler"]]["inputs"].update({"seed": cfg["seed"], "steps": cfg["steps"]})
    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") == "EmptyAceStepLatentAudio":
            node["inputs"]["seconds"] = cfg["duration"]
        if isinstance(node, dict) and "bpm" in node.get("inputs", {}):
            node["inputs"]["bpm"] = cfg["bpm"]
        if isinstance(node, dict) and "keyscale" in node.get("inputs", {}):
            node["inputs"]["keyscale"] = cfg["keyscale"]
    for fix in client.resolve_model_names(wf):
        print("# 校正", fix)
    t0 = time.time()
    pid = client.submit(wf)
    print(f"# 提交 {pid}  {name} {cfg['duration']}s bpm={cfg['bpm']}", flush=True)
    outs = client.wait(pid, on_tick=lambda s: print(f"  …{name} {s:.0f}s", flush=True))
    saved = client.fetch_outputs(outs, Path(MUSIC))
    got = None
    for f in saved:
        if str(f).lower().endswith((".flac", ".wav", ".mp3", ".ogg")):
            dst = Path(MUSIC) / f"{name}{Path(f).suffix}"
            os.replace(f, dst)
            got = dst
    dt = time.time() - t0
    print(f"[ok] {got}  {dt:.0f}s", flush=True)
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--timeout", type=int, default=3600)
    opt = ap.parse_args()
    client = ComfyClient(HOST, timeout=opt.timeout)
    done = {}
    for name, cfg in TRACKS.items():
        done[name] = str(gen(name, cfg, client, opt.force))
    json.dump({k: dict(file=v, **TRACKS[k]) for k, v in done.items()},
              open(Path(MUSIC) / "music_report.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
