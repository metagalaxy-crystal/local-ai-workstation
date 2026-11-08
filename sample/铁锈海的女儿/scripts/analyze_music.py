#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MOSS-Music-8B 音乐理解测试（design.md 10.2 BGM 质检闭环）。

4-bit NF4 量化加载，8GB VRAM 可运行。
用法: python analyze_music.py <音频> [--prompt "描述这段音乐的情绪、风格、配器"]
"""
import argparse
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import soundfile as sf
import torch

MODEL_DIR = r"D:\models\models\music\MOSS-Music-8B"


def load_audio16k(path: str) -> np.ndarray:
    wav, sr = sf.read(path, dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    if sr != 16000:
        import torchaudio
        wav_t = torch.from_numpy(wav).unsqueeze(0)
        wav_t = torchaudio.functional.resample(wav_t, sr, 16000)
        wav = wav_t.squeeze(0).numpy().astype("float32")
    return wav.astype(np.float32)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--prompt", default="请描述这段音乐的情绪、风格、配器和整体氛围。",
                    help="提问内容")
    ap.add_argument("--max-new-tokens", type=int, default=512)
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.exists():
        print(f"音频不存在: {audio}", file=sys.stderr)
        return 1

    import importlib.util
    import sys
    import types
    from transformers import AutoProcessor

    # 创建虚拟包以支持 modeling 里的相对导入
    pkg_name = "moss_music_pkg"
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [MODEL_DIR]
    sys.modules[pkg_name] = pkg

    def _load(name):
        spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.{name}", str(Path(MODEL_DIR) / f"{name}.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"{pkg_name}.{name}"] = mod
        spec.loader.exec_module(mod)
        return mod

    config_mod = _load("configuration_moss_music")
    MossMusicConfig = config_mod.MossMusicConfig

    # 修复：configuration 未把 audio_config 从 dict 转成对象
    # 用 AttrDict（dict 子类，支持属性访问且可 JSON 序列化）
    class AttrDict(dict):
        def __getattr__(self, key):
            try:
                return self[key]
            except KeyError:
                raise AttributeError(key)
        def __setattr__(self, key, value):
            self[key] = value

    _orig_init = MossMusicConfig.__init__
    def _patched_init(self, audio_config=None, **kwargs):
        if isinstance(audio_config, dict):
            audio_config = AttrDict(audio_config)
        _orig_init(self, audio_config=audio_config, **kwargs)
    MossMusicConfig.__init__ = _patched_init

    modeling = _load("modeling_moss_music")
    MossMusicModel = modeling.MossMusicModel

    print(f"load model (4-bit NF4): {MODEL_DIR}")
    model = MossMusicModel.from_pretrained(
        MODEL_DIR,
        trust_remote_code=True,
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
        device_map="auto",
    )
    processor = AutoProcessor.from_pretrained(MODEL_DIR, trust_remote_code=True)
    print(f"model device: {next(model.parameters()).device}")

    wav = load_audio16k(str(audio))
    print(f"audio: {len(wav)/16000:.1f}s @16kHz")

    inputs = processor(text=args.prompt, audios=[wav], return_tensors="pt")
    # processor 不返回 audio_input_mask，需手动构建：标记音频占位 token 位置
    inputs["audio_input_mask"] = (inputs["input_ids"] == processor.audio_token_id)
    # mel 默认 bfloat16，但音频编码器卷积层是 float16，统一转 float16
    if "audio_data" in inputs:
        inputs["audio_data"] = inputs["audio_data"].to(torch.float16)
    inputs = {k: v.to(model.device) if isinstance(v, torch.Tensor) else v
              for k, v in inputs.items()}

    print(f"generate (max_new_tokens={args.max_new_tokens})...")
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=args.max_new_tokens,
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
            repetition_penalty=1.1,
        )
    # 去掉 prompt 部分
    input_len = inputs["input_ids"].shape[1]
    gen_ids = out[0][input_len:]
    text = processor.decode(gen_ids, skip_special_tokens=True)
    print("\n=== MOSS-Music 分析结果 ===")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
