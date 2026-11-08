# -*- coding: utf-8 -*-
"""通用文生图测试脚本：加载工作流 JSON → 解析模型文件名 → 提交 → 保存出图与指标。
工作流 JSON 顶层可含 "_meta": {"positive": "<node_id>", "negative": "<node_id>",
"sampler": "<node_id>", "latent": "<node_id>"}（提交前会被剥离）。
"""
import argparse, json, sys, time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from test_t2i import http_json, resolve_name, VramPoller  # noqa: E402

OUT_DIR = HERE / "outputs"
RESULT_DIR = HERE / "results"


def run(workflow_path, host="127.0.0.1:8188", prompt=None, negative=None,
        width=None, height=None, seed=None, steps=None, cfg=None,
        sampler=None, scheduler=None, prefix=None, timeout=1800):
    wf = json.loads(Path(workflow_path).read_text(encoding="utf-8"))
    meta = wf.pop("_meta", {})

    for node in wf.values():
        ct, inp = node["class_type"], node["inputs"]
        if ct in ("UNETLoader", "UnetLoaderGGUF"):
            inp["unet_name"] = resolve_name(ct, "unet_name", inp["unet_name"].replace("\\", "/").split("/")[-1], host)
        elif ct in ("CLIPLoader", "CLIPLoaderGGUF"):
            inp["clip_name"] = resolve_name(ct, "clip_name", inp["clip_name"].replace("\\", "/").split("/")[-1], host)
        elif ct == "VAELoader":
            inp["vae_name"] = resolve_name(ct, "vae_name", inp["vae_name"].replace("\\", "/").split("/")[-1], host)

    if prompt is not None:
        pnode = wf[meta["positive"]]
        pnode["inputs"]["text" if pnode["class_type"] == "CLIPTextEncode" else "prompt"] = prompt
    if negative is not None and meta.get("negative"):
        nnode = wf[meta["negative"]]
        nnode["inputs"]["text" if nnode["class_type"] == "CLIPTextEncode" else "prompt"] = negative
    if seed is None:
        seed = int(time.time() * 1000) % (2**31)
    if steps is not None:
        wf[meta["sampler"]]["inputs"]["steps"] = steps
    if cfg is not None:
        wf[meta["sampler"]]["inputs"]["cfg"] = cfg
    if sampler is not None:
        wf[meta["sampler"]]["inputs"]["sampler_name"] = sampler
    if scheduler is not None:
        wf[meta["sampler"]]["inputs"]["scheduler"] = scheduler
    wf[meta["sampler"]]["inputs"]["seed"] = seed
    if width:
        wf[meta["latent"]]["inputs"]["width"] = width
    if height:
        wf[meta["latent"]]["inputs"]["height"] = height
    if prefix:
        for node in wf.values():
            if node["class_type"] == "SaveImage":
                node["inputs"]["filename_prefix"] = prefix

    t0 = time.time()
    with VramPoller() as vram:
        pid = http_json(f"http://{host}/prompt", {"prompt": wf, "client_id": "gen_image"})["prompt_id"]
        print(f"已提交 prompt_id={pid} seed={seed}")
        deadline = time.time() + timeout
        while time.time() < deadline:
            hist = http_json(f"http://{host}/history/{pid}")
            if pid in hist:
                entry = hist[pid]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                    raise RuntimeError(f"执行出错: {json.dumps(msgs, ensure_ascii=False)[:2000]}")
                if entry.get("outputs"):
                    break
            time.sleep(1.5)
        else:
            raise TimeoutError("等待出图超时")
        elapsed, peak = time.time() - t0, vram.peak

    images = []
    import urllib.request, urllib.parse
    for node_out in hist[pid]["outputs"].values():
        for img in node_out.get("images", []):
            q = urllib.parse.urlencode(img)
            with urllib.request.urlopen(f"http://{host}/view?{q}", timeout=120) as r:
                data = r.read()
            dest = OUT_DIR / f"{prefix or 'gen'}_{seed}_{img['filename']}"
            dest.write_bytes(data)
            images.append(str(dest))
            print(f"已保存: {dest}")

    result = {"workflow": Path(workflow_path).name,
              "prompt": wf[meta["positive"]]["inputs"].get("prompt") or wf[meta["positive"]]["inputs"].get("text", ""),
              "negative": ((wf[meta["negative"]]["inputs"].get("prompt") or wf[meta["negative"]]["inputs"].get("text", "")) if meta.get("negative") else ""),
              "seed": seed, "steps": wf[meta["sampler"]]["inputs"]["steps"], "cfg": wf[meta["sampler"]]["inputs"]["cfg"],
              "width": wf[meta["latent"]]["inputs"]["width"], "height": wf[meta["latent"]]["inputs"]["height"],
              "elapsed_sec": round(elapsed, 1), "vram_peak_mb": peak, "images": images}
    dest = RESULT_DIR / f"{prefix or 'gen'}_{seed}.json"
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"耗时 {elapsed:.1f}s | 显存峰值 {peak} MB | 结果: {dest}")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--prompt")
    ap.add_argument("--negative")
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--steps", type=int)
    ap.add_argument("--cfg", type=float)
    ap.add_argument("--sampler")
    ap.add_argument("--scheduler")
    ap.add_argument("--prefix")
    ap.add_argument("--host", default="127.0.0.1:8188")
    args = ap.parse_args()
    run(args.workflow, host=args.host, prompt=args.prompt, negative=args.negative,
        width=args.width, height=args.height, seed=args.seed, steps=args.steps,
        cfg=args.cfg, sampler=args.sampler, scheduler=args.scheduler, prefix=args.prefix)
