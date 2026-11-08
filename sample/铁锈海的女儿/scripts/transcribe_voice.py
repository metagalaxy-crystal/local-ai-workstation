#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qwen3-ASR + FunASR 语音转写：对白校验 + SRT 字幕导出（design.md 10.3）。

用法:
  python transcribe_voice.py <音频> [--srt out.srt] [--json out.json]
      [--reference "台本第一句
台本第二句"] [--language zh] [--model Qwen/Qwen3-ASR-0.6B]

模型: Qwen3-ASR-0.6B（bf16，显存 ≈4 GB），FSMN-VAD 负责长音频分句；
模型扁平存放在 models/audio/Qwen3-ASR-0.6B/ 和 models/audio/fsmn-vad/。
"""
import argparse
import difflib
import json
import sys
from pathlib import Path

DEFAULT_MODEL = "Qwen/Qwen3-ASR-0.6B"
DEFAULT_MODEL_PATH = r"D:\models\models\audio\Qwen3-ASR-0.6B"
VAD_MODEL = "fsmn-vad"
VAD_MODEL_PATH = r"D:\models\models\audio\fsmn-vad"


def fmt_ts(ms: float) -> str:
    ms = int(round(ms))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="HF 模型 ID 或本地模型目录")
    ap.add_argument("--language", default="zh")
    ap.add_argument("--device", default=None)
    ap.add_argument("--srt", help="导出 SRT 字幕路径")
    ap.add_argument("--json", help="导出分段 JSON 路径")
    ap.add_argument("--reference", help="台本文本（换行分句），与识别结果逐句比对")
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.exists():
        print(f"音频不存在: {audio}", file=sys.stderr)
        return 1

    import torch
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")

    from funasr import AutoModel

    print(f"load model: {args.model}  path={DEFAULT_MODEL_PATH}  device={device}")
    model = AutoModel(
        model=args.model,
        model_path=DEFAULT_MODEL_PATH,
        vad_model=VAD_MODEL,
        vad_model_path=VAD_MODEL_PATH,
        device=device,
        dtype="bf16",
        disable_pbar=True,
        disable_update=True,
    )

    res = model.generate(
        input=str(audio),
        language=args.language,
        sentence_timestamp=True,  # 无 punc 模型时按 VAD 段返回句子级时间戳
        batch_size_s=300,
    )

    sentence_info = res[0].get("sentence_info") or []
    segs = []
    for s in sentence_info:
        text = (s.get("text") or s.get("sentence") or "").strip()
        if not text:
            continue
        segs.append({"start": float(s["start"]) / 1000.0,
                     "end": float(s["end"]) / 1000.0,
                     "text": text})
    print(f"分段={len(segs)}")
    for i, s in enumerate(segs, 1):
        print(f"[{i}] {s['start']:7.2f} -> {s['end']:7.2f}  {s['text']}")

    if args.srt:
        with open(args.srt, "w", encoding="utf-8") as f:
            for i, s in enumerate(segs, 1):
                f.write(f"{i}\n{fmt_ts(s['start'] * 1000)} --> {fmt_ts(s['end'] * 1000)}\n"
                        f"{s['text']}\n\n")
        print(f"SRT: {args.srt}")
    if args.json:
        Path(args.json).write_text(
            json.dumps(segs, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON: {args.json}")

    if args.reference is not None:
        ref_lines = [l.strip() for l in args.reference.splitlines() if l.strip()]
        print("\n--- 台本比对 ---")
        for rl in ref_lines:
            best, ratio = None, 0.0
            for s in segs:
                r = difflib.SequenceMatcher(None, rl, s["text"]).ratio()
                if r > ratio:
                    best, ratio = s, r
            mark = "OK  " if ratio >= 0.8 else "MISS"
            shown = best["text"][:30] if best else "(无识别结果)"
            print(f"[{mark}] {ratio:.2f}  台本: {rl[:30]}  ->  识别: {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
