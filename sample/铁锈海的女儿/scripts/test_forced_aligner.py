#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 Qwen3-ForcedAligner-0.6B 独立调用（方案 B）
用项目内已知 ground-truth 文本的 TTS 音频做字级时间戳对齐测试。
"""
import torch
from qwen_asr import Qwen3ForcedAligner

MODEL_DIR = r"d:\models\models\audio\Qwen3-ForcedAligner-0.6B"
SPEECH_DIR = r"d:\models\sample\铁锈海的女儿\06_compare\speech"

# (音频文件, ground-truth 文本)
CASES = [
    ("line1_father.wav", "好看吗？"),
    ("line2_girl.wav", "好看。"),
    ("line3_father.wav", "记住这个颜色，以后就见不到了。"),
]


def main():
    model = Qwen3ForcedAligner.from_pretrained(
        MODEL_DIR,
        dtype=torch.bfloat16,
        device_map="cuda:0",
    )

    for wav, text in CASES:
        audio = f"{SPEECH_DIR}\\{wav}"
        results = model.align(audio=audio, text=text, language="Chinese")
        print(f"\n=== {wav} ===")
        print(f"ground truth: {text}")
        for seg in results[0]:
            print(f"  {seg.text}\t{seg.start_time:.3f}s -> {seg.end_time:.3f}s")


if __name__ == "__main__":
    main()
