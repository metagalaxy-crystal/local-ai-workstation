# -*- coding: utf-8 -*-
"""Z-Image-Turbo 文生图测试：提交 ComfyUI 工作流 → 等待出图 → 记录耗时与显存峰值"""
import argparse, json, sys, threading, time, urllib.request, urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
OUT_DIR = HERE / "outputs"
RESULT_DIR = HERE / "results"
OUT_DIR.mkdir(exist_ok=True)
RESULT_DIR.mkdir(exist_ok=True)


def http_json(url, payload=None, timeout=30):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def resolve_name(node_class, field, suffix, host):
    """按后缀在 ComfyUI 可选列表中解析实际文件名"""
    info = http_json(f"http://{host}/object_info/{node_class}")
    options = info[node_class]["input"]["required"][field][0]
    for opt in options:
        if opt.replace("\\", "/").endswith(suffix):
            return opt
    print(f"[错误] {node_class}.{field} 找不到 {suffix}\n可选值: {options}", file=sys.stderr)
    sys.exit(1)


class VramPoller:
    """轮询 nvidia-smi 记录显存峰值（MB）"""

    def __init__(self, interval=0.5):
        self.interval = interval
        self.peak = 0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        import subprocess
        while not self._stop.is_set():
            try:
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    text=True, timeout=5)
                self.peak = max(self.peak, int(out.strip().splitlines()[0]))
            except Exception:
                pass
            self._stop.wait(self.interval)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join()


def generate_image(host="127.0.0.1:8188", prompt=None, width=1088, height=608,
                   seed=None, steps=8, cfg=1.0, sampler="euler", scheduler="simple",
                   prefix="zimage_t2i", timeout=900):
    wf = json.loads((HERE / "workflow_zimage_t2i_api.json").read_text(encoding="utf-8"))

    # 校验模型文件是否已被 ComfyUI 识别
    wf["1"]["inputs"]["unet_name"] = resolve_name("UnetLoaderGGUF", "unet_name",
                                                  "z-image-turbo-Q4_K_M.gguf", host)
    wf["2"]["inputs"]["clip_name"] = resolve_name("CLIPLoaderGGUF", "clip_name",
                                                  "Qwen_3_4b-Q6_K.gguf", host)
    wf["5"]["inputs"]["vae_name"] = resolve_name("VAELoader", "vae_name",
                                                 "vae/ae.safetensors", host)
    if prompt:
        wf["3"]["inputs"]["prompt"] = prompt
    if seed is None:
        seed = int(time.time() * 1000) % (2**31)
    wf["7"]["inputs"].update(seed=seed, steps=steps, cfg=cfg,
                             sampler_name=sampler, scheduler=scheduler)
    wf["6"]["inputs"].update(width=width, height=height)
    wf["9"]["inputs"]["filename_prefix"] = prefix

    t0 = time.time()
    with VramPoller() as vram:
        pid = http_json(f"http://{host}/prompt", {"prompt": wf, "client_id": "t2i_test"})["prompt_id"]
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
            time.sleep(1)
        else:
            raise TimeoutError("等待出图超时")
        elapsed = time.time() - t0
        peak = vram.peak

    images = []
    for node_out in hist[pid]["outputs"].values():
        for img in node_out.get("images", []):
            q = urllib.parse.urlencode(img)
            with urllib.request.urlopen(f"http://{host}/view?{q}", timeout=60) as r:
                data = r.read()
            dest = OUT_DIR / f"{prefix}_{seed}_{img['filename']}"
            dest.write_bytes(data)
            images.append(str(dest))
            print(f"已保存: {dest}")

    result = {"prompt": wf["3"]["inputs"]["prompt"], "seed": seed, "steps": steps, "cfg": cfg,
              "width": width, "height": height, "elapsed_sec": round(elapsed, 2),
              "vram_peak_mb": peak, "images": images}
    dest = RESULT_DIR / f"t2i_{seed}.json"
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"耗时 {elapsed:.1f}s | 显存峰值 {peak} MB | 结果: {dest}")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1:8188")
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--width", type=int, default=1088)
    ap.add_argument("--height", type=int, default=608)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--cfg", type=float, default=1.0)
    ap.add_argument("--prefix", default="zimage_t2i")
    args = ap.parse_args()
    generate_image(host=args.host, prompt=args.prompt, width=args.width, height=args.height,
                   seed=args.seed, steps=args.steps, cfg=args.cfg, prefix=args.prefix)
