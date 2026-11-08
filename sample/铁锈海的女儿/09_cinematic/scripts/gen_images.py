# -*- coding: utf-8 -*-
r"""Z-Image-Turbo 本地文生图：批量生成 9 张电影感关键帧。
用法： python scripts\gen_images.py [--only shot01] [--force]
产物： images\shotNN.png + images\shotNN.json（提示词/参数留档）
"""
import argparse, json, os, sys, time
from pathlib import Path

sys.path.insert(0, r"D:\models\scripts")
sys.path.insert(0, r"D:\models\scripts\comfyui")
from comfy_client import ComfyClient, load_workflow  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from txh_config import IMG, IMG_RES, BUILD  # noqa: E402

WF = Path(r"D:\models\scripts\comfyui\zimage\workflow.json")
JOBS = Path(__file__).parent / "jobs_img.json"
HOST = "http://127.0.0.1:8188"
NEG = "低画质，模糊，变形，文字，水印，过曝，卡通，CGI 感，人物畸形，多余肢体，面部崩坏"


def gen(name, prompt, seed, client, force):
    out = Path(IMG) / f"{name}.png"
    if out.exists() and not force:
        print(f"[skip] {name}")
        return
    wf = load_workflow(WF)
    meta = wf["_meta"]
    w, h = (int(x) for x in IMG_RES.split("x"))
    pos = wf[meta["positive"]]["inputs"]
    pos["prompt"] = prompt                      # TextEncodeZImageOmni 的字段名是 prompt
    if "text" in pos:
        pos["text"] = prompt
    neg = wf[meta["negative"]]["inputs"]
    neg["prompt"] = NEG
    if "text" in neg:
        neg["text"] = NEG
    wf[meta["latent"]]["inputs"].update({"width": w, "height": h})
    wf[meta["sampler"]]["inputs"].update({"seed": seed})
    for fix in client.resolve_model_names(wf):
        print("# 校正", fix)
    t0 = time.time()
    pid = client.submit(wf)
    print(f"# 提交 {pid}  {name} {w}x{h} seed={seed}", flush=True)
    outs = client.wait(pid, on_tick=lambda s: print(f"  …{name} {s:.0f}s", flush=True))
    saved = client.fetch_outputs(outs, Path(BUILD))
    for f in saved:
        if str(f).lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            os.replace(f, out)
    dt = time.time() - t0
    json.dump(dict(name=name, prompt=prompt, negative=NEG, res=IMG_RES, seed=seed,
                   prompt_id=pid, seconds=round(dt, 1), out=str(out)),
              open(Path(IMG) / f"{name}.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"[ok] {out}  {dt:.0f}s", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--timeout", type=int, default=1800)
    opt = ap.parse_args()
    jobs = json.load(open(JOBS, encoding="utf-8-sig"))
    client = ComfyClient(HOST, timeout=opt.timeout)
    for name, j in jobs.items():
        if opt.only and name != opt.only:
            continue
        gen(name, j["prompt"], j.get("seed", 42), client, opt.force)


if __name__ == "__main__":
    main()
