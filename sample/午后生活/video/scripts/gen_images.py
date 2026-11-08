# -*- coding: utf-8 -*-
r"""Z-Image 关键帧：先生成角色定妆照，再以定妆照为参考图生成 6 张分镜图。

用法：
    python gen_images.py --char              # 只生成定妆照
    python gen_images.py --only S01          # 只生成某个镜头（自动先确保定妆照存在）
    python gen_images.py                     # 全部（定妆照 + 6 镜头）
产物：images\character.png、images\shotNN.png + 同名 json 留档
"""
from __future__ import annotations

import argparse, hashlib, json, os, sys, time
from pathlib import Path

sys.path.insert(0, r"d:\models\scripts")
sys.path.insert(0, r"d:\models\scripts\comfyui")
from comfy_client import ComfyClient, load_workflow  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import zwj_config as C  # noqa: E402

WF = Path(r"d:\models\scripts\comfyui\zimage\workflow.json")
HOST = "http://127.0.0.1:8188"


def fit_ref(src: Path, w: int, h: int, dest: Path) -> Path:
    """把参考图等比缩放进 w×h 画布（黑边居中），避免参考 latent 与目标尺寸不匹配。"""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    s = min(w / im.width, h / im.height)
    im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    canvas.paste(im, ((w - im.width) // 2, (h - im.height) // 2))
    canvas.save(dest)
    return dest


def build(w, h, prompt, seed, ref_image=None, client=None, auto_resize=True):
    wf = load_workflow(WF)
    wf["3"]["inputs"]["prompt"] = prompt
    wf["4"]["inputs"]["prompt"] = C.NEG
    wf["6"]["inputs"].update({"width": w, "height": h})
    wf["7"]["inputs"].update({"seed": seed, "steps": C.IMG_STEPS})
    wf["9"]["inputs"]["filename_prefix"] = "zwj"
    if ref_image is not None:
        wf["20"] = {"class_type": "LoadImage", "inputs": {"image": client.upload_image(ref_image)}}
        wf["3"]["inputs"]["image1"] = ["20", 0]
        wf["3"]["inputs"]["vae"] = ["5", 0]
        wf["3"]["inputs"]["auto_resize_images"] = auto_resize
    return wf


def run_one(client, name, prompt, res, seed, out_png, ref_image=None):
    w, h = (int(x) for x in res.lower().split("x"))
    auto_resize = True
    if ref_image is not None:
        src_hash = hashlib.md5(Path(ref_image).read_bytes()).hexdigest()[:10]
        fitted = Path(C.BUILD) / f"_ref_{w}x{h}_{src_hash}.png"
        if not fitted.exists():
            fit_ref(Path(ref_image), w, h, fitted)
        ref_image = fitted
        auto_resize = False
    wf = build(w, h, prompt, seed, ref_image, client, auto_resize)
    for fix in client.resolve_model_names(wf):
        print("# 校正", fix)
    t0 = time.time()
    pid = client.submit(wf)
    print(f"# 提交 {pid}  {name} {w}x{h} seed={seed}", flush=True)
    outs = client.wait(pid, on_tick=lambda s: print(f"  …{name} {s:.0f}s", flush=True))
    saved = client.fetch_outputs(outs, Path(C.BUILD))
    png = next((f for f in saved if str(f).lower().endswith((".png", ".jpg", ".webp"))), None)
    if png is None:
        raise SystemExit(f"{name} 未产出图片：{outs}")
    os.replace(png, out_png)
    dt = time.time() - t0
    json.dump(dict(name=name, prompt=prompt, negative=C.NEG, res=res, seed=seed,
                   reference=(str(ref_image) if ref_image else None),
                   prompt_id=pid, seconds=round(dt, 1), out=str(out_png)),
              open(out_png.with_suffix(".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"[ok] {out_png}  {dt:.0f}s", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--char", action="store_true", help="只生成定妆照")
    ap.add_argument("--only", help="只生成某个镜头，如 S01")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--ref-file", help=r"覆盖参考图（默认 images\character.png）")
    ap.add_argument("--no-ref", action="store_true", help="不用参考图，纯文生图（适合远景分镜）")
    ap.add_argument("--timeout", type=int, default=1800)
    opt = ap.parse_args()

    client = ComfyClient(HOST, timeout=opt.timeout)
    char_png = Path(C.IMG) / f"{C.CHAR_SHEET['name']}.png"
    if opt.ref_file:
        char_png = Path(opt.ref_file)
    if opt.no_ref:
        char_png = None

    if not opt.ref_file and not opt.no_ref and (not char_png.exists() or opt.char):
        run_one(client, "character", C.CHAR_SHEET["prompt"], C.CHAR_SHEET["res"],
                C.CHAR_SHEET["seed"], char_png)
    if opt.char:
        return 0
    if not opt.no_ref and not char_png.exists():
        raise SystemExit("定妆照缺失，无法做参考图生成")

    for s in C.SHOTS:
        if opt.only and s["id"] != opt.only:
            continue
        out = Path(C.IMG) / s["image"]
        if out.exists() and not opt.force:
            print(f"[skip] {out.name}")
            continue
        run_one(client, s["id"], s["img_prompt"], C.IMG_RES, s["seed"], out, ref_image=char_png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
