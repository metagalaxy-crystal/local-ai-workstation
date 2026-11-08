#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一 TTS 入口：VoxCPM2，自动分句、参数调优、badcase 重试。

设计原则：
  - VoxCPM2 默认 cfg=1.5（保守稳定），避免"神神鬼鬼"
  - 长文本自动按标点分句 + 交叉淡入拼接
  - bad case 自动重试（音频异常短/静音过多）

用法:
    # 默认合成
    python tts_run.py --text "你好世界。" --out out.wav

    # 参考音频克隆
    python tts_run.py --text "你好世界。" --ref-audio ref.wav --out out.wav

    # Voice Design（纯文本描述音色，无需参考音频）
    python tts_run.py --text "(温柔女声，语速偏慢)你好世界。" --out out.wav
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import wave as _wave
from pathlib import Path

import numpy as np

BASE = Path(r"d:\models")
MODELS_DIR = BASE / "models"
OUT_DIR = BASE / "output" / "tts"

VOXCPM_DIR = MODELS_DIR / "audio" / "VoxCPM2"


# ---------------------------------------------------------------------------
# 分句
# ---------------------------------------------------------------------------
PUNCT_RE = re.compile(r"([。！？!?；;，,、\n\r])")


def split_sentences(text: str, max_chars: int = 40) -> list[str]:
    """按标点分句，单句超过 max_chars 再硬切。"""
    text = text.strip()
    if not text:
        return []

    # 按标点切，保留标点
    parts = PUNCT_RE.split(text)
    sentences, cur = [], ""
    for p in parts:
        cur += p
        cur = cur.strip()
        if cur and PUNCT_RE.fullmatch(p):
            sentences.append(cur)
            cur = ""
        elif len(cur) >= max_chars:
            sentences.append(cur)
            cur = ""
    if cur:
        sentences.append(cur)

    # 合并过短的句子
    merged, buf = [], ""
    for s in sentences:
        if len(buf) + len(s) <= max_chars:
            buf += s
        else:
            if buf:
                merged.append(buf)
            buf = s
    if buf:
        merged.append(buf)
    return merged or [text]


# ---------------------------------------------------------------------------
# 音频工具
# ---------------------------------------------------------------------------
def write_wav_16bit(path: Path | str, wav_np: np.ndarray, sr: int) -> None:
    arr = np.asarray(wav_np).squeeze().astype(np.float32)
    data = (np.clip(arr, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    with _wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(data)


def crossfade_concat(chunks: list[np.ndarray], sr: int, fade_ms: int = 30,
                     silence_ms: int = 80) -> np.ndarray:
    """多段拼接 + 交叉淡入淡出 + 句间短静音。"""
    if not chunks:
        return np.array([], dtype=np.float32)
    fade_n = int(sr * fade_ms / 1000)
    sil_n = int(sr * silence_ms / 1000)
    sil = np.zeros(sil_n, dtype=np.float32)

    out = chunks[0].astype(np.float32)
    for c in chunks[1:]:
        c = c.astype(np.float32)
        # crossfade 尾部
        if fade_n > 0 and len(out) > fade_n and len(c) > fade_n:
            fade_out = np.linspace(1, 0, fade_n, dtype=np.float32)
            fade_in = np.linspace(0, 1, fade_n, dtype=np.float32)
            out[-fade_n:] = out[-fade_n:] * fade_out + c[:fade_n] * fade_in
            out = np.concatenate([out, sil, c[fade_n:]])
        else:
            out = np.concatenate([out, sil, c])
    return out


def is_bad_audio(wav: np.ndarray, sr: int) -> bool:
    """粗检 bad case：全静音 / 过短 / 幅值异常低。"""
    if wav.size < sr * 0.3:  # <0.3s
        return True
    peak = float(np.max(np.abs(wav))) if wav.size else 0
    if peak < 0.01:  # 几乎静音
        return True
    rms = float(np.sqrt(np.mean(wav.astype(np.float32) ** 2))) if wav.size else 0
    if rms < 0.005:
        return True
    return False


# ---------------------------------------------------------------------------
# 模型 Runner
# ---------------------------------------------------------------------------
class VoxCPMRunner:
    def __init__(self, device: str | None = None,
                 cfg_value: float = 1.5, inference_timesteps: int = 10):
        if device is None:
            device = "cuda"
        self.cfg_value = cfg_value
        self.inference_timesteps = inference_timesteps
        from voxcpm import VoxCPM
        print(f"[VoxCPM2] 加载 (cfg={cfg_value}, steps={inference_timesteps})...", flush=True)
        try:
            self.model = VoxCPM.from_pretrained(
                str(VOXCPM_DIR), load_denoiser=False, optimize=False, device=device)
        except Exception as e:
            print(f"[VoxCPM2] CUDA 失败 ({e})，回退 CPU", flush=True)
            self.model = VoxCPM.from_pretrained(
                str(VOXCPM_DIR), load_denoiser=False, optimize=False, device="cpu")
        print("[VoxCPM2] ✅ 就绪", flush=True)
        self.sr = 48000

    def synthesize(self, text: str, ref_audio: str | None = None,
                   max_retries: int = 2) -> tuple[np.ndarray, int]:
        kwargs = dict(
            text=text,
            cfg_value=self.cfg_value,
            inference_timesteps=self.inference_timesteps,
            retry_badcase=True,
        )
        if ref_audio:
            kwargs["reference_wav_path"] = ref_audio

        last_wav = None
        for attempt in range(max_retries + 1):
            wav = self.model.generate(**kwargs)
            if not is_bad_audio(wav, self.sr):
                return wav, self.sr
            last_wav = wav
            if attempt < max_retries:
                print(f"  [VoxCPM2] badcase，重试 {attempt+1}/{max_retries}", flush=True)
        print(f"  [VoxCPM2] ⚠️ {max_retries} 次重试仍 badcase，返回最后一次", flush=True)
        return last_wav if last_wav is not None else np.zeros(self.sr, dtype=np.float32), self.sr


# ---------------------------------------------------------------------------
# 高层入口
# ---------------------------------------------------------------------------
_RUNNERS: dict[str, VoxCPMRunner] = {}


def get_runner(**kwargs) -> VoxCPMRunner:
    """懒加载 runner，同名参数复用。"""
    key = "voxcpm"
    if key not in _RUNNERS:
        _RUNNERS[key] = VoxCPMRunner(**kwargs)
    return _RUNNERS[key]


def tts(text: str, out_path: str | Path,
        ref_audio: str | None = None,
        cfg_value: float | None = None,
        inference_timesteps: int | None = None) -> Path:
    """统一 TTS 入口（VoxCPM2）。自动分句 + 拼接 + badcase 重试。

    Args:
        text: 要合成的文本；可用括号包裹音色描述做 Voice Design，如 "(温柔女声)你好"
        out_path: 输出 wav 路径
        ref_audio: 参考音频（克隆音色）
        cfg_value: cfg_value，覆盖默认 1.5
        inference_timesteps: 推理步数，覆盖默认 10

    Returns:
        输出文件路径
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    runner_kw = {}
    if cfg_value is not None:
        runner_kw["cfg_value"] = cfg_value
    if inference_timesteps is not None:
        runner_kw["inference_timesteps"] = inference_timesteps
    runner = get_runner(**runner_kw)

    sentences = split_sentences(text)
    print(f"📝 分句: {len(sentences)} 段", flush=True)
    for i, s in enumerate(sentences, 1):
        print(f"  [{i}] {s}", flush=True)

    t0 = time.time()
    chunks: list[np.ndarray] = []
    for i, s in enumerate(sentences, 1):
        t1 = time.time()
        wav, sr = runner.synthesize(s, ref_audio=ref_audio)
        chunks.append(wav)
        print(f"  ✅ [{i}/{len(sentences)}] {len(wav)/sr:.2f}s | {time.time()-t1:.1f}s",
              flush=True)

    if len(chunks) == 1:
        final_wav, final_sr = chunks[0], runner.sr
    else:
        final_wav = crossfade_concat(chunks, runner.sr)
        final_sr = runner.sr

    write_wav_16bit(out_path, final_wav, final_sr)
    dur = len(final_wav) / final_sr
    total = time.time() - t0
    print(f"\n🎉 完成: {out_path} | {dur:.2f}s 音频 | {total:.1f}s 总耗时 | RTF {total/dur:.2f}",
          flush=True)
    return out_path


# ===========================================================================
# CLI
# ===========================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="VoxCPM2 统一 TTS 入口")
    ap.add_argument("--text", required=True, help="合成文本；括号包裹音色描述可 Voice Design")
    ap.add_argument("--out", default=None, help="输出路径，默认自动命名")
    ap.add_argument("--ref-audio", default=None, help="参考音频用于克隆")
    ap.add_argument("--cfg", type=float, default=None,
                    help="cfg_value，默认 1.5（保守稳定）")
    ap.add_argument("--steps", type=int, default=None,
                    help="inference_timesteps，默认 10")
    args = ap.parse_args()

    if args.out is None:
        import hashlib
        tag = hashlib.md5(args.text.encode("utf-8")).hexdigest()[:6]
        args.out = str(OUT_DIR / f"voxcpm_{tag}.wav")

    try:
        tts(args.text, args.out, ref_audio=args.ref_audio,
            cfg_value=args.cfg, inference_timesteps=args.steps)
    except Exception as e:
        print(f"❌ 失败: {e}", file=sys.stderr, flush=True)
        import traceback; traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
