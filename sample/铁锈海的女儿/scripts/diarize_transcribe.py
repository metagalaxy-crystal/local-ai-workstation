#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sherpa-onnx 对白转写 + 说话人分离（design.md 10.3 路线 v2）。

【2026-10-12 已作废，留档】sherpa-onnx 高层 diarization API 存在 pybind
绑定缺陷（1.12.40 / 1.13.8 的 OfflineSpeakerDiarizationResult 均未暴露
分段访问接口），路线放弃；最终方案改为 Qwen3-ASR + FunASR
（spk_model="funasr/campplus"），见 transcribe_voice.py。
相关模型与 pip 包已清理，本脚本不可直接运行，仅作排障记录保留。

流程: soundfile 解码 -> torchaudio 重采样16k -> sherpa-onnx diarization
      (pyannote-segmentation-3.0 onnx + 3dspeaker eres2netv2 嵌入 + FastClustering)
      -> 按说话人分段 -> SenseVoice-small int8 分段转写 -> SRT/JSON。
CPU 运行，无需 CUDA / ffmpeg；旧 whisperx+pyannote 路线已于 2026-10-12 废弃删除。

用法:
  python diarize_transcribe.py <音频> [--srt out.srt] [--json out.json] [--speakers 2]
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio

import sherpa_onnx

DIAR_DIR = Path(r"D:\models\models\audio\sherpa-diarization")
SEGMENTATION_ONNX = DIAR_DIR / "pyannote_segmentation_3_0" / "model.onnx"
EMBEDDING_ONNX = DIAR_DIR / "3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx"
EMBEDDING_SIZE = 71441526  # complete onnx size; partial downloads fall back to campplus
CAMPPLUS_ONNX = DIAR_DIR / "campplus_cn_en_common_200k.onnx"
SENSEVOICE_DIR = Path(r"D:\models\models\audio\sensevoice\sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17")


def load_audio16k(path: str) -> np.ndarray:
    """soundfile 解码 -> 16kHz 单声道 float32 numpy（不依赖 ffmpeg）。"""
    data, sr = sf.read(path, dtype="float32", always_2d=True)  # [T, C]
    wav = torch.from_numpy(data.T)  # [C, T]
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)
    if sr != 16000:
        wav = torchaudio.functional.resample(wav, sr, 16000)
    return wav.squeeze(0).numpy()


def build_diarization(num_speakers: int) -> sherpa_onnx.OfflineSpeakerDiarization:
    embedding = EMBEDDING_ONNX if (EMBEDDING_ONNX.is_file() and EMBEDDING_ONNX.stat().st_size == EMBEDDING_SIZE) else CAMPPLUS_ONNX
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(SEGMENTATION_ONNX),
            ),
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(embedding),
        ),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=num_speakers),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    return sherpa_onnx.OfflineSpeakerDiarization(config)


def build_recognizer() -> sherpa_onnx.OfflineRecognizer:
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(SENSEVOICE_DIR / "model.int8.onnx"),
        tokens=str(SENSEVOICE_DIR / "tokens.txt"),
        num_threads=2,
        language="zh",
        use_itn=True,
        decoding_method="greedy_search",
    )


def clean_text(t: str) -> str:
    """去掉 SenseVoice 输出中的 <|zh|><|NEUTRAL|><|Speech|> 等标记。"""
    return re.sub(r"<\|[^|]*\|>", "", t).strip()


def fmt_ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def merge_turns(turns, max_gap: float = 1.0):
    """合并同一说话人时间间隔小于 max_gap 的相邻段。"""
    merged = []
    for t in turns:
        if merged and merged[-1]["speaker"] == t["speaker"] and t["start"] - merged[-1]["end"] <= max_gap:
            merged[-1]["end"] = t["end"]
            merged[-1]["text"] += t["text"]
        else:
            merged.append(dict(t))
    return merged


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--srt")
    ap.add_argument("--json")
    ap.add_argument("--speakers", type=int, default=2)
    ap.add_argument("--no-merge", action="store_true", help="disable merging adjacent same-speaker turns")
    args = ap.parse_args()

    print(f"decode: {args.audio}")
    samples = load_audio16k(args.audio)
    print(f"audio: {len(samples)/16000:.1f}s @16kHz")

    print("diarize (cpu, pyannote-seg-3.0 + speaker embedding)...")
    sd = build_diarization(args.speakers)
    # sherpa-onnx 1.12.x returns numpy [N,3]: start_sample, end_sample, speaker_id
    segs = sd.process(samples)
    print(f"diarized: {len(segs)} turns")

    recognizer = build_recognizer()
    print("transcribe segments (SenseVoice int8)...")

    out = []
    for start_s, end_s, spk in segs:
        s_sec = float(start_s) / 16000.0
        e_sec = float(end_s) / 16000.0
        chunk = samples[int(start_s):int(end_s)]
        if len(chunk) < 1600:  # skip <0.1s blips
            continue
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, chunk)
        recognizer.decode_stream(stream)
        text = clean_text(stream.result.text)
        if not text:
            continue
        turn = {"start": s_sec, "end": e_sec,
                "text": text, "speaker": f"SPEAKER_{int(spk):02d}"}
        out.append(turn)
        print(f"[{turn['speaker']}] {turn['start']:7.2f} -> {turn['end']:7.2f}  {text}")

    if not args.no_merge:
        out = merge_turns(out)

    if args.srt:
        with open(args.srt, "w", encoding="utf-8") as f:
            for i, s in enumerate(out, 1):
                f.write(f"{i}\n{fmt_ts(s['start'])} --> {fmt_ts(s['end'])}\n[{s['speaker']}] {s['text']}\n\n")
        print(f"SRT: {args.srt}")
    if args.json:
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
