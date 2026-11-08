# -*- coding: utf-8 -*-
r"""MiniMax-H3 int8 图生视频：每个关键帧生成一个 124 帧（5.17s）镜头。

用法：
    python gen_clips.py --job S01        # 单个（含冒烟测试）
    python gen_clips.py --all            # 全部
    python gen_clips.py --job S01 --res 1120x480 --steps 20
产物：clips\sNN.mp4 + sNN.json；ComfyUI 原生音轨保留在 mp4 内
"""
from __future__ import annotations

import argparse, json, os, sys, time
from pathlib import Path

sys.path.insert(0, r"d:\models\scripts")
sys.path.insert(0, r"d:\models\scripts\comfyui")
from comfy_client import ComfyClient, load_workflow  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import zwj_config as C  # noqa: E402

WF = Path(r"d:\models\scripts\comfyui\minimax-h3\workflow_i2v.json")
HOST = "http://127.0.0.1:8188"


def run_one(shot, res, length, steps, seed, force, timeout):
    out_mp4 = Path(C.CLIPS) / f"{shot['clip']}.mp4"
    if out_mp4.exists() and not force:
        print(f"[skip] {out_mp4.name}")
        return
    wf = load_workflow(WF)
    meta = wf["_meta"]
    cond, snode = meta["cond"], meta["sampler"]
    w, h = (int(x) for x in (res or C.SRC_RES).lower().split("x"))
    L = length or C.CLIP_LEN
    S = steps or C.CLIP_STEPS
    wf[cond]["inputs"].update({"prompt": shot["clip_prompt"], "width": w, "height": h, "length": L})
    wf[snode]["inputs"].update({"steps": S, "seed": seed if seed is not None else shot["seed"]})
    wf["11"]["inputs"]["fps"] = C.FPS
    wf.pop(meta["last_frame"], None)
    wf[cond]["inputs"].pop("last_frame", None)

    client = ComfyClient(HOST, timeout=timeout)
    img = Path(shot["image"])
    if not img.is_absolute():
        img = Path(C.IMG) / img
    if not img.exists():
        raise SystemExit(f"关键帧缺失：{img}")
    wf[meta["first_frame"]]["inputs"]["image"] = client.upload_image(img)
    for fix in client.resolve_model_names(wf):
        print("# 校正", fix)
    t0 = time.time()
    pid = client.submit(wf)
    print(f"# 提交 {pid}  {shot['id']} {w}x{h} {L}帧 steps={S}", flush=True)
    outs = client.wait(pid, on_tick=lambda s: print(f"  …{shot['id']} {s:.0f}s", flush=True))
    saved = client.fetch_outputs(outs, Path(C.CLIPS))
    for f in saved:
        if str(f).lower().endswith(".mp4"):
            os.replace(f, out_mp4)
    dt = time.time() - t0
    json.dump(dict(id=shot["id"], image=shot["image"], prompt=shot["clip_prompt"],
                   res=f"{w}x{h}", length=L, steps=S, seed=wf[snode]["inputs"]["seed"],
                   prompt_id=pid, seconds=round(dt, 1), out=str(out_mp4)),
              open(Path(C.CLIPS) / f"{shot['clip']}.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"[ok] {out_mp4}  {dt:.0f}s", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--res")
    ap.add_argument("--length", type=int)
    ap.add_argument("--steps", type=int)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--image", help=r"覆盖首帧（如上一镜末帧），默认 images\shotNN.png")
    ap.add_argument("--timeout", type=int, default=7200)
    opt = ap.parse_args()
    todo = [s for s in C.SHOTS if not opt.job or s["id"] == opt.job]
    if not opt.job and not opt.all:
        print("可用镜头：" + ", ".join(s["id"] for s in C.SHOTS))
        return 0
    if opt.job and not todo:
        raise SystemExit(f"没有镜头 {opt.job}")
    for s in todo:
        if opt.image:
            s = dict(s, image=opt.image)
        run_one(s, opt.res, opt.length, opt.steps, opt.seed, opt.force, opt.timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
