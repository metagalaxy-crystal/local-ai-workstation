#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速验证 VoxCPM2 参数调优能不能缓解"神神鬼鬼"问题"""
from __future__ import annotations
import os, sys, time, wave, hashlib
import numpy as np
from pathlib import Path

OUT = Path(r"d:\models\output\tts_param_test")
OUT.mkdir(parents=True, exist_ok=True)

from voxcpm import VoxCPM
print("[加载 VoxCPM2...]", flush=True)
model = VoxCPM.from_pretrained(
    r"d:\models\models\audio\VoxCPM2",
    load_denoiser=False, optimize=False, device="cuda",
)

# 容易翻车的3条
TESTS = [
    "哥哥你看！那边的小花好漂亮呀！",
    "嘿嘿嘿……你终于来了，我的小猎物。",
    "呜……为什么……为什么会变成这样……",
]

CASES = [
    ("默认",          dict(cfg_value=2.0,  inference_timesteps=10)),
    ("cfg=1.2 保守",  dict(cfg_value=1.2,  inference_timesteps=10)),
    ("cfg=1.5 稳",    dict(cfg_value=1.5,  inference_timesteps=10)),
    ("cfg=2.5 强",    dict(cfg_value=2.5,  inference_timesteps=10)),
    ("步=20 更准",    dict(cfg_value=2.0,  inference_timesteps=20)),
    ("最稳组合",      dict(cfg_value=1.5,  inference_timesteps=15)),
]

for text in TESTS:
    tag = hashlib.md5(text.encode("utf-8")).hexdigest()[:6]
    print(f"\n{'='*60}", flush=True)
    print(f"🔤 文本: {text}", flush=True)
    print(f"{'='*60}", flush=True)
    for name, kw in CASES:
        t0 = time.time()
        try:
            wav = model.generate(text=text, retry_badcase=True, **kw)
            dur = len(wav) / 48000
            fname = OUT / f"{tag}_{name.replace(' ', '_').replace('=', '_')}.wav"
            arr = np.asarray(wav).squeeze().astype(np.float32)
            data = (np.clip(arr, -1.0, 1.0) * 32767).astype("<i2").tobytes()
            with wave.open(str(fname), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000); w.writeframes(data)
            print(f"  ✅ {name:15s} | {time.time()-t0:5.1f}s | {dur:.2f}s | {fname.name}", flush=True)
        except Exception as e:
            print(f"  ❌ {name:15s} | {e}", flush=True)

print(f"\n📁 全部在 {OUT}", flush=True)
