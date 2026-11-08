#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键下载《铁锈海的女儿》视频生成工作流所需的全部模型文件。

支持：
- 自动跳过已下载完成的文件（用 HEAD 获取 Content-Length 比对）
- 断点续传（Range 请求，写到 ab 模式追加）
- 失败重试（最多 10 次后跳过下一项）
- 详细日志：stdout + 06_compare/download_all.log

清单（按 ComfyUI extra_model_paths.yaml 映射位置）：
  - Wan2.2-TI2V-5B-Q8_0.gguf                        5.4GB   QuantStack
  - Wan2.2_VAE.safetensors                           1.4GB   QuantStack
  - umt5-xxl-encoder-Q5_K_M.gguf                     4.1GB   city96
  - minimax_h3_fl2va_pruned_int8_convrot.safetensors 19.5GB  Comfy-Org  ← 重点
  - minimax_h3_fl2va_pruned_w6a8.safetensors          16GB    Comfy-Org
  - minimax_h3_video_vae_fp16.safetensors            5.2GB   Comfy-Org
  - minimax_h3_audio_vae_fp32.safetensors            605MB   Comfy-Org
  - qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors     15.7GB  Comfy-Org

镜像源：hf-mirror.com（中国大陆访问稳定，偶尔断连会自动重试）
"""
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

MIRROR = "https://hf-mirror.com"

# 顺序：重点项放前面，万一中途想中断也优先拿到关键文件
MODELS = [
    {
        "name": "MiniMax H3 pruned int8 convrot (重点)",
        "url": f"{MIRROR}/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        "dest": r"D:\models\models\video\MiniMax-H3\diffusion_models\minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        "size_gb": 19.53,
    },
    {
        "name": "MiniMax H3 pruned w6a8",
        "url": f"{MIRROR}/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_fl2va_pruned_w6a8.safetensors",
        "dest": r"D:\models\models\video\MiniMax-H3\diffusion_models\minimax_h3_fl2va_pruned_w6a8.safetensors",
        "size_gb": 16.0,
    },
    {
        "name": "MiniMax H3 video VAE fp16",
        "url": f"{MIRROR}/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_fp16.safetensors",
        "dest": r"D:\models\models\video\MiniMax-H3\vae\minimax_h3_video_vae_fp16.safetensors",
        "size_gb": 5.21,
    },
    {
        "name": "MiniMax H3 audio VAE fp32",
        "url": f"{MIRROR}/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors",
        "dest": r"D:\models\models\video\MiniMax-H3\vae\minimax_h3_audio_vae_fp32.safetensors",
        "size_gb": 0.605,
    },
    {
        "name": "qwen3vl-32b minimax nvfp4 awq",
        "url": f"{MIRROR}/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        "dest": r"D:\models\models\video\MiniMax-H3\encoder\qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        "size_gb": 15.7,
    },
    {
        "name": "Wan2.2-TI2V-5B Q8 GGUF",
        "url": f"{MIRROR}/QuantStack/Wan2.2-TI2V-5B-GGUF/resolve/main/Wan2.2-TI2V-5B-Q8_0.gguf",
        "dest": r"D:\models\models\video\Wan2.2-TI2V-5B\Wan2.2-TI2V-5B-Q8_0.gguf",
        "size_gb": 5.4,
    },
    {
        "name": "Wan2.2 VAE",
        "url": f"{MIRROR}/QuantStack/Wan2.2-TI2V-5B-GGUF/resolve/main/VAE/Wan2.2_VAE.safetensors",
        "dest": r"D:\models\models\video\Wan2.2-TI2V-5B\Wan2.2_VAE.safetensors",
        "size_gb": 1.4,
    },
    {
        "name": "UMT5-XXL encoder Q5_K_M",
        "url": f"{MIRROR}/city96/umt5-xxl-encoder-gguf/resolve/main/umt5-xxl-encoder-Q5_K_M.gguf",
        "dest": r"D:\models\models\encoder\umt5-xxl\umt5-xxl-encoder-Q5_K_M.gguf",
        "size_gb": 4.15,
    },
]

LOG = Path(r"D:\models\sample\铁锈海的女儿\06_compare\download_all.log")


def fmt_size(b):
    if b >= 1024 ** 3:
        return f"{b/1024**3:.2f}GB"
    if b >= 1024 ** 2:
        return f"{b/1024**2:.2f}MB"
    if b >= 1024:
        return f"{b/1024:.2f}KB"
    return f"{b}B"


def log_line(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_remote_size(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "curl/8.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(r.headers.get("Content-Length", 0))
    except Exception as e:
        log_line(f"  HEAD 失败: {e}")
        return 0


def download_one(model: dict) -> int:
    """返回 0=成功/已完成，1=放弃跳过"""
    name = model["name"]
    url = model["url"]
    dest = Path(model["dest"])
    log_line(f"=== [{name}] ===")
    log_line(f"  URL: {url}")
    log_line(f"  目标: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    have = dest.stat().st_size if dest.exists() else 0
    if have:
        log_line(f"  本地已存在: {fmt_size(have)}")

    total = get_remote_size(url)
    if total:
        log_line(f"  远程大小: {fmt_size(total)}")
        if have >= total:
            log_line(f"  已完成，跳过")
            return 0
    else:
        log_line(f"  无法获取 Content-Length，继续尝试下载")

    headers = {"User-Agent": "curl/8.0"}
    if have:
        headers["Range"] = f"bytes={have}-"
        log_line(f"  从 {fmt_size(have)} 续传")

    retries = 0
    while retries <= 10:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                mode = "ab" if have else "wb"
                last_log = time.time()
                last_bytes = have
                with dest.open(mode) as f:
                    while True:
                        chunk = r.read(1024 * 1024)  # 1MB
                        if not chunk:
                            break
                        f.write(chunk)
                        have += len(chunk)
                        now = time.time()
                        if now - last_log >= 10:
                            speed = (have - last_bytes) / (now - last_log)
                            pct = (have / total * 100) if total else 0
                            log_line(
                                f"  {fmt_size(have)}/{fmt_size(total) if total else '?'} "
                                f"({pct:.1f}%) {fmt_size(speed)}/s"
                            )
                            last_log = now
                            last_bytes = have
            log_line(f"  下载完成: {fmt_size(dest.stat().st_size)}")
            return 0
        except urllib.error.HTTPError as e:
            if e.code == 416:  # Range Not Satisfiable
                log_line(f"  Range 错误(已下载完成?): {e}")
                return 0
            log_line(f"  HTTP 错误 {e.code}: {e.reason}")
            retries += 1
            if retries > 10:
                log_line(f"  重试 {retries} 次仍失败，跳过")
                return 1
            time.sleep(5)
            have = dest.stat().st_size if dest.exists() else 0
            if have:
                headers["Range"] = f"bytes={have}-"
            else:
                headers.pop("Range", None)
        except Exception as e:
            log_line(f"  异常: {e}")
            retries += 1
            if retries > 10:
                return 1
            time.sleep(5)
            have = dest.stat().st_size if dest.exists() else 0
            if have:
                headers["Range"] = f"bytes={have}-"
    return 1


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    log_line(f"========== 一键下载开始，共 {len(MODELS)} 个文件 ==========")
    results = []
    for i, m in enumerate(MODELS, 1):
        log_line(f"--- [{i}/{len(MODELS)}] ---")
        try:
            rc = download_one(m)
            results.append((m["name"], rc))
        except Exception as e:
            log_line(f"  未捕获异常: {e}")
            results.append((m["name"], 1))

    log_line("========== 总结 ==========")
    ok = sum(1 for _, rc in results if rc == 0)
    fail = sum(1 for _, rc in results if rc != 0)
    for name, rc in results:
        status = "OK" if rc == 0 else "FAIL"
        log_line(f"  [{status}] {name}")
    log_line(f"完成: {ok} OK / {fail} FAIL")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
