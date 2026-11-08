#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MOSS-Music-8B 音乐质检样例（可移植）。

用途
    对一段音频/音乐做理解式质检：输出调性、配器、情绪、风格、时长等分析文本。
    为适配 8GB 显存，模型以 4-bit NF4 量化加载。

依赖
    torch / transformers / bitsandbytes / soundfile / numpy
    （本机环境 d:\\models\\.venv 已全部安装；GPU 需支持 bnb 4bit）

示例命令
    # 基本用法（分析结果同时打印并写入默认输出目录）
    python music_qc.py song.wav

    # 自定义提问
    python music_qc.py song.wav --prompt "请描述这段音乐的调性、配器和情绪。"

    # 指定输出文件
    python music_qc.py song.wav --out result.txt

环境变量
    MODEL_ROOT   模型根目录，默认 d:\\models\\models（可用环境变量覆盖以迁移到别的机器）
    输出目录默认取 MODEL_ROOT 同级目录下的 output/other/music_qc/，也可用 --out 指定。
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import types
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# 路径解析
# ---------------------------------------------------------------------------
DEFAULT_MODEL_ROOT = r"d:\models\models"


def model_root() -> Path:
    return Path(os.environ.get("MODEL_ROOT", DEFAULT_MODEL_ROOT))


def music_model_dir() -> Path:
    return model_root() / "music" / "MOSS-Music-8B"


def output_dir() -> Path:
    """默认输出目录：<MODEL_ROOT 同级>/output/other/music_qc/。"""
    base = Path(os.environ.get("OUTPUT_ROOT", str(model_root().parent / "output")))
    return base / "other" / "music_qc"


def load_audio_16k(path: str):
    """读取音频并重采样到 16k 单声道。"""
    import numpy as np
    import soundfile as sf

    wav, sr = sf.read(path, dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    if sr != 16000:
        import torch
        import torchaudio
        wav_t = torch.from_numpy(np.ascontiguousarray(wav)).unsqueeze(0)
        wav = torchaudio.functional.resample(wav_t, sr, 16000).squeeze(0).numpy()
    return wav.astype(np.float32)


def load_model(model_dir: str):
    """按虚拟包方式加载本地 MOSS-Music 模型与 processor。

    修复点：
      1) modeling 内部使用相对导入，需通过虚拟包（__path__ 指向模型目录）加载；
      2) configuration 未把 audio_config(dict) 转成可属性访问对象，需打补丁。
    """
    import torch
    from transformers import AutoProcessor

    pkg_name = "moss_music_pkg"
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [model_dir]
    sys.modules[pkg_name] = pkg

    def _load(name):
        spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.{name}", str(Path(model_dir) / f"{name}.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"{pkg_name}.{name}"] = mod
        spec.loader.exec_module(mod)
        return mod

    config_mod = _load("configuration_moss_music")
    MossMusicConfig = config_mod.MossMusicConfig

    class AttrDict(dict):
        """支持属性访问的 dict，用于把 audio_config 由 dict 转成对象。"""

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

    print(f"[INFO] 加载模型 (4-bit NF4): {model_dir}", flush=True)
    model = MossMusicModel.from_pretrained(
        model_dir,
        trust_remote_code=True,
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
        device_map="auto",
    )
    processor = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True)
    print(f"[INFO] model device: {next(model.parameters()).device}", flush=True)
    return model, processor


def main() -> int:
    ap = argparse.ArgumentParser(
        description="MOSS-Music-8B 音乐质检（4bit NF4，可移植样例）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("audio", help="待分析音频路径（wav/mp3/flac 等）")
    ap.add_argument("--prompt", default="请描述这段音乐的情绪、风格、配器和整体氛围。",
                    help="提问内容")
    ap.add_argument("--out", default=None, help="分析文本输出路径；默认写入默认输出目录")
    ap.add_argument("--max-new-tokens", type=int, default=512)
    ap.add_argument("--temperature", type=float, default=0.7,
                    help="采样温度（避免复读可适当调低）")
    ap.add_argument("--top-p", type=float, default=0.9)
    ap.add_argument("--repetition-penalty", type=float, default=1.1,
                    help="重复惩罚，>1 抑制复读")
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.exists():
        print(f"[FAIL] 音频不存在: {audio}", file=sys.stderr)
        return 1
    if not music_model_dir().exists():
        print(f"[FAIL] 模型未下载: {music_model_dir()}", file=sys.stderr)
        return 3

    import torch

    model, processor = load_model(str(music_model_dir()))

    wav = load_audio_16k(str(audio))
    print(f"[INFO] audio: {len(wav) / 16000:.1f}s @16kHz", flush=True)

    inputs = processor(text=args.prompt, audios=[wav], return_tensors="pt")
    # processor 不返回 audio_input_mask，需手动构建（标记音频占位 token 位置）
    inputs["audio_input_mask"] = (inputs["input_ids"] == processor.audio_token_id)
    # mel 默认 bfloat16，但音频编码器卷积层为 float16，统一转 float16
    if "audio_data" in inputs:
        inputs["audio_data"] = inputs["audio_data"].to(torch.float16)
    inputs = {k: v.to(model.device) if isinstance(v, torch.Tensor) else v
              for k, v in inputs.items()}

    print(f"[INFO] generate (max_new_tokens={args.max_new_tokens})...", flush=True)
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=args.max_new_tokens,
            do_sample=True,
            temperature=args.temperature,
            top_p=args.top_p,
            repetition_penalty=args.repetition_penalty,
        )
    gen_ids = out[0][inputs["input_ids"].shape[1]:]
    text = processor.decode(gen_ids, skip_special_tokens=True)

    print("\n=== MOSS-Music 分析结果 ===")
    print(text)

    out_path = Path(args.out) if args.out else (output_dir() / f"{audio.stem}_qc.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"\n[OK] 结果已写入: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
