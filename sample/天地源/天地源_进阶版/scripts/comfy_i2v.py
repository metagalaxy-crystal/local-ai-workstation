# -*- coding: utf-8 -*-
"""本地 ComfyUI 图生视频执行器（MiniMax H3 int8 / i2v）。

依赖已跑通的 ComfyUI 服务与样例工作流：
    D:\\models\\scripts\\comfyui\\minimax-h3\\workflow_i2v.json
    D:\\models\\scripts\\comfyui\\comfy_client.py

用法：
    # 单镜头
    python scripts\\comfy_i2v.py --job S01
    # 全部
    python scripts\\comfy_i2v.py --all
    # 覆盖参数
    python scripts\\comfy_i2v.py --job S01 --length 73 --res 832x480 --steps 16

约定：
  * length 必须落在模型网格 17k+5（5/22/39/56/73/90/107/124…），73 帧 = 3.0s@24fps
  * 生成的 mp4 自带 H3 原生音轨，成片时会被丢弃（本片音效全部自制）
  * 每个镜头生成后写 clips\\<JOB>.json 记录提示词、参数、prompt_id、耗时，保证可重跑
"""
from __future__ import annotations

import argparse, json, os, sys, time
from pathlib import Path

BASE = Path(r"d:\models\sample\天地源\天地源_进阶版")
CLIPS = BASE / "clips"
IMAGES = BASE / "images"
JOBS = BASE / "scripts" / "jobs.json"

sys.path.insert(0, r"D:\models\scripts")
sys.path.insert(0, r"D:\models\scripts\comfyui")
from comfy_client import ComfyClient, ComfyError, load_workflow  # noqa: E402

WF = Path(r"D:\models\scripts\comfyui\minimax-h3\workflow_i2v.json")
HOST = "http://127.0.0.1:8188"


def run_one(job, length, res, steps, seed, force, timeout):
    out_mp4 = CLIPS / f"{job['id'].lower()}.mp4"
    if out_mp4.exists() and not force:
        print(f"[skip] {out_mp4.name} 已存在")
        return
    wf = load_workflow(WF)
    meta = wf["_meta"]
    cond, snode = meta["cond"], meta["sampler"]
    w, h = (int(x) for x in (res or job.get("res", "832x480")).lower().split("x"))
    L = length or job.get("length", 73)
    S = steps or job.get("steps", 16)
    wf[cond]["inputs"].update({"prompt": job["prompt"], "width": w, "height": h, "length": L})
    wf[snode]["inputs"].update({"steps": S, "seed": seed if seed is not None else job.get("seed", 42)})
    wf["11"]["inputs"]["fps"] = 24
    wf.pop(meta["last_frame"], None)
    wf[cond]["inputs"].pop("last_frame", None)

    client = ComfyClient(HOST, timeout=timeout)
    img = IMAGES / job["image"]
    uploaded = client.upload_image(img)
    wf[meta["first_frame"]]["inputs"]["image"] = uploaded
    for fix in client.resolve_model_names(wf):
        print("# 校正", fix)
    t0 = time.time()
    pid = client.submit(wf)
    print(f"# 提交 {pid}  {job['id']} {w}x{h} {L}帧 steps={S}", flush=True)
    outs = client.wait(pid, on_tick=lambda s: print(f"  …{job['id']} {s:.0f}s", flush=True))
    saved = client.fetch_outputs(outs, CLIPS)
    for f in saved:
        if str(f).lower().endswith(".mp4"):
            os.replace(f, out_mp4)
    dt = time.time() - t0
    json.dump(dict(id=job["id"], image=job["image"], prompt=job["prompt"], res=f"{w}x{h}",
                   length=L, steps=S, seed=wf[snode]["inputs"]["seed"], prompt_id=pid,
                   seconds=round(dt, 1), out=str(out_mp4)),
              open(CLIPS / f"{job['id'].lower()}.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"[ok] {out_mp4}  {dt:.0f}s", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--length", type=int)
    ap.add_argument("--res")
    ap.add_argument("--steps", type=int)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--timeout", type=int, default=7200)
    opt = ap.parse_args()
    raw = json.load(open(JOBS, encoding="utf-8-sig"))
    jobs = [v for v in raw.values() if v.get("enabled", True)]
    todo = [j for j in jobs if j["id"] == opt.job] if opt.job else jobs
    if not opt.job and not opt.all:
        print("可用镜头：" + ", ".join(j["id"] for j in jobs))
        return 0
    for j in todo:
        run_one(j, opt.length, opt.res, opt.steps, opt.seed, opt.force, opt.timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
