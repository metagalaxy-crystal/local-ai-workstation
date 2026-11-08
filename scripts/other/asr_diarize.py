#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语音转写 + 说话人分离样例（FunASR 版，可移植）。

用途
    对一段音频做"语音转写 + 说话人分离"：
      1) silero-VAD 切分语音段；
      2) Qwen3-ASR-0.6B 逐段转写；
      3) cam++ 提取每段说话人 embedding，KMeans/层次聚类分配说话人；
      4) --align 时用 Qwen3-ForcedAligner-0.6B 出字级时间戳，并在段内静音处
         细化说话人（修正长段内两人交替发言被整段误判的情况）。

依赖
    funasr / torch / torchaudio / soundfile / numpy / scikit-learn / qwen_asr
    （本机环境 d:\\models\\.venv 已全部安装）

示例命令
    # 基础：转写 + 2 人分离，输出到默认目录
    python asr_diarize.py dialogue.wav

    # 指定说话人数 / 输出路径
    python asr_diarize.py dialogue.wav --speakers 3 --out-dir out_dir

    # 启用字级对齐（更细的说话人切换与字级时间戳）
    python asr_diarize.py dialogue.wav --align --split-gap 0.5 --max-line 24

环境变量
    MODEL_ROOT   模型根目录，默认 d:\\models\\models（可用环境变量覆盖以迁移到别的机器）
    输出目录默认取 MODEL_ROOT 同级目录下的 output/other/asr/，也可用 --out-dir 指定。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径解析
# ---------------------------------------------------------------------------
DEFAULT_MODEL_ROOT = r"d:\models\models"

# 模型按名称扁平存放在 audio/ 下，用注册表 key + 本地路径加载
DEFAULT_MODEL = "Qwen/Qwen3-ASR-0.6B"
VAD_MODEL = "silero_vad"          # silero-vad 对短静音分段比 fsmn-vad 更敏感
SPK_MODEL = "cam++"

# --language 缩写 -> ForcedAligner 需要的语言名
LANG_NAME_MAP = {
    "zh": "Chinese", "en": "English", "yue": "Cantonese", "ja": "Japanese",
    "ko": "Korean", "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese", "ru": "Russian", "es": "Spanish",
}
PUNCT = "，。！？；：、…,.!?;:"
SENT_END = "。！？…!?"


def model_root() -> Path:
    return Path(os.environ.get("MODEL_ROOT", DEFAULT_MODEL_ROOT))


def output_dir() -> Path:
    """默认输出目录：<MODEL_ROOT 同级>/output/other/asr/。"""
    base = Path(os.environ.get("OUTPUT_ROOT", str(model_root().parent / "output")))
    return base / "other" / "asr"


def fmt_ts(ms: float) -> str:
    ms = int(round(ms))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def cluster_embeddings(embs, n_speakers: int):
    """对说话人 embedding 聚类，返回 label 数组。"""
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering, KMeans

    embs = np.asarray(embs)
    if len(embs) <= 1:
        return [0] * len(embs)
    if n_speakers and n_speakers > 0:
        km = KMeans(n_clusters=min(n_speakers, len(embs)), n_init=10, random_state=0)
        return km.fit_predict(embs).tolist()
    # 自动聚类：层次聚类 + 余弦距离阈值
    ac = AgglomerativeClustering(
        n_clusters=None, metric="cosine", linkage="average", distance_threshold=0.3)
    return ac.fit_predict(embs).tolist()


def cluster_centers(embs, labels):
    """各说话人标签的归一化均值中心，用于子段最近中心分配。"""
    import numpy as np

    embs = np.asarray(embs, dtype=np.float32)
    norm = embs / (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-8)
    centers = {}
    for lab in sorted(set(labels)):
        c = norm[[i for i, l in enumerate(labels) if l == lab]].mean(axis=0)
        centers[lab] = c / (np.linalg.norm(c) + 1e-8)
    return centers


def nearest_center(emb, centers) -> int:
    import numpy as np

    emb = emb / (np.linalg.norm(emb) + 1e-8)
    return max(centers, key=lambda k: float(np.dot(emb, centers[k])))


def attach_punct(text, items):
    """把原文标点挂回对齐字序列（aligner 输出已去标点）。"""
    plain = [c for c in text if not c.isspace() and c not in PUNCT]
    if len(plain) != len(items):
        return items, False
    out, i = [], 0
    for ch in text:
        if ch.isspace():
            continue
        if ch in PUNCT:
            if out:
                out[-1]["ch"] += ch
            continue
        out.append({"ch": ch, "start": items[i]["start"], "end": items[i]["end"]})
        i += 1
    return out, True


def split_at_gaps(items, gap_thr: float):
    """在字间静音 >= gap_thr 秒处切开，返回 [items, ...]。"""
    parts, cur = [], [items[0]]
    for prev, it in zip(items, items[1:]):
        if it["start"] - prev["end"] >= gap_thr:
            parts.append(cur)
            cur = []
        cur.append(it)
    parts.append(cur)
    return parts


def split_lines(words, max_chars: int):
    """字幕断行：句末标点必断；超过 max_chars 时在任意标点处断。"""
    lines, cur = [], []
    for w in words:
        cur.append(w)
        t = "".join(x["text"] for x in cur)
        if t and (t[-1] in SENT_END or (len(t) >= max_chars and t[-1] in PUNCT)):
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    return [(l[0]["start"], l[-1]["end"], "".join(x["text"] for x in l)) for l in lines]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="FunASR + Qwen3-ASR 语音转写与说话人分离（可移植样例）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("audio", help="输入音频路径（建议 16k/单声道，其他会自动重采样）")
    ap.add_argument("--out-dir", default=None, help="输出目录；默认写入默认输出目录")
    ap.add_argument("--json", default=None, help="JSON 输出路径；默认写入 <out-dir>/<stem>.json")
    ap.add_argument("--srt", default=None, help="SRT 输出路径；默认写入 <out-dir>/<stem>.srt")
    ap.add_argument("--speakers", type=int, default=2,
                    help="预设说话人数（双人对白=2）；0 表示自动聚类")
    ap.add_argument("--language", default="zh", help="转写语言（zh/en/yue/ja...）")
    ap.add_argument("--device", default=None, help="cuda / cpu；默认自动选择")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help="ASR 模型 ID 或本地目录名（可切 Qwen/Qwen3-ASR-1.7B）")
    ap.add_argument("--model-path", default=None,
                    help="ASR 本地模型路径；默认 <MODEL_ROOT>/audio/Qwen3-ASR-0.6B")
    ap.add_argument("--vad-model", default=VAD_MODEL, help="VAD 模型（silero_vad / fsmn-vad）")
    ap.add_argument("--spk-model-path", default=None,
                    help="cam++ 声纹模型路径；默认 <MODEL_ROOT>/audio/campplus")
    ap.add_argument("--align", action="store_true",
                    help="启用 ForcedAligner 字级对齐：段内说话人细化 + 字级时间戳")
    ap.add_argument("--aligner-path", default=None,
                    help="ForcedAligner 模型路径；默认 <MODEL_ROOT>/audio/Qwen3-ForcedAligner-0.6B")
    ap.add_argument("--split-gap", type=float, default=0.5,
                    help="段内静音 >= 该秒数时切分说话人（默认 0.5）")
    ap.add_argument("--max-line", type=int, default=24, help="SRT 单条字幕最大字数")
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.exists():
        print(f"[FAIL] 音频不存在: {audio}", file=sys.stderr)
        return 1

    root = model_root()
    model_path = args.model_path or str(root / "audio" / "Qwen3-ASR-0.6B")
    spk_model_path = args.spk_model_path or str(root / "audio" / "campplus")
    aligner_path = args.aligner_path or str(root / "audio" / "Qwen3-ForcedAligner-0.6B")

    out_dir = Path(args.out_dir) if args.out_dir else output_dir()
    json_path = Path(args.json) if args.json else out_dir / f"{audio.stem}.json"
    srt_path = Path(args.srt) if args.srt else out_dir / f"{audio.stem}.srt"

    import numpy as np
    import soundfile as sf
    import torch
    from funasr import AutoModel

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")

    # 1) VAD：单独切分语音段
    print(f"[INFO] load VAD: {args.vad_model}", flush=True)
    vad_model = AutoModel(model=args.vad_model, hub="ms",
                          disable_pbar=True, disable_update=True)

    # 2) ASR：Qwen3-ASR，不挂 vad/spk（避免 FunASR 内部 distribute_spk 报错）
    print(f"[INFO] load ASR: model={args.model}  path={model_path}  device={device}", flush=True)
    asr_model = AutoModel(
        model=args.model, model_path=model_path,
        device=device, dtype="bf16",
        disable_pbar=True, disable_update=True, trust_remote_code=True,
    )

    # 3) 说话人 embedding 模型（cam++）
    print(f"[INFO] load SPK: {SPK_MODEL}  path={spk_model_path}", flush=True)
    spk_model = AutoModel(model=SPK_MODEL, model_path=spk_model_path, device=device,
                          disable_pbar=True, disable_update=True)

    # 读原始音频（统一重采样到 16k 单声道）
    wav, sr = sf.read(str(audio), dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1).astype("float32")
    if sr != 16000:
        import torchaudio
        wav_t = torch.from_numpy(np.ascontiguousarray(wav)).unsqueeze(0)
        wav = torchaudio.functional.resample(wav_t, sr, 16000).squeeze(0).numpy().astype("float32")
        sr = 16000

    print(f"[INFO] vad segment: {audio}", flush=True)
    vad_res = vad_model.generate(input=wav, fs=sr)
    segments = vad_res[0].get("value") or []      # [[start_ms, end_ms], ...]
    print(f"[INFO] vad segments: {len(segments)}", flush=True)

    # 对每个 VAD 段：ASR 转写 + cam++ 提 embedding
    embs, valid_segs = [], []
    for start_ms, end_ms in segments:
        i0 = int(start_ms / 1000 * sr)
        i1 = int(end_ms / 1000 * sr)
        chunk = wav[i0:i1]
        if len(chunk) < sr // 10:                 # 跳过 <0.1s
            continue
        r = asr_model.generate(input=chunk, fs=sr, language=args.language)
        text = (r[0].get("text") or "").strip()
        if not text:
            continue
        sr2 = spk_model.generate(input=chunk, fs=sr)
        emb = sr2[0].get("spk_embedding")
        if emb is None:
            continue
        if hasattr(emb, "detach"):
            emb = emb.detach().cpu().numpy()
        embs.append(np.asarray(emb).reshape(-1))
        valid_segs.append((start_ms / 1000.0, end_ms / 1000.0, text))

    print(f"[INFO] valid segments: {len(valid_segs)}", flush=True)
    if not valid_segs:
        print("[FAIL] 无有效语音段", file=sys.stderr)
        return 1

    labels = cluster_embeddings(embs, args.speakers)
    out = []

    if args.align:
        # 4) 可选：ForcedAligner 字级对齐，细化段内说话人 + 字级时间戳
        from qwen_asr import Qwen3ForcedAligner

        lang_name = LANG_NAME_MAP.get(args.language, args.language)
        print(f"[INFO] load Aligner: {aligner_path}", flush=True)
        aligner = Qwen3ForcedAligner.from_pretrained(
            aligner_path,
            dtype=torch.bfloat16 if device == "cuda" else torch.float32,
            device_map="cuda:0" if device == "cuda" else device,
        )
        centers = cluster_centers(embs, labels)
        for (start, end, text), spk in zip(valid_segs, labels):
            chunk = wav[int(start * sr):int(end * sr)]
            try:
                res = aligner.align(audio=(chunk, sr), text=text, language=lang_name)
                items = [{"ch": s.text, "start": start + s.start_time, "end": start + s.end_time}
                         for s in res[0]]
            except Exception as e:
                print(f"[WARN] align failed @ {start:.2f}s: {e}", flush=True)
                items = []
            if not items:
                out.append({"start": start, "end": end, "text": text,
                            "speaker": f"SPEAKER_{int(spk):02d}"})
                continue
            items, _ = attach_punct(text, items)
            to_words = lambda part: [{"text": x["ch"], "start": round(x["start"], 3),
                                      "end": round(x["end"], 3)} for x in part]
            parts = split_at_gaps(items, args.split_gap)
            if len(parts) == 1:
                out.append({"start": start, "end": end, "text": text,
                            "speaker": f"SPEAKER_{int(spk):02d}",
                            "words": to_words(items)})
                continue
            # 段内有明显静音：逐子段重提 embedding，归最近说话人中心
            for part in parts:
                p_start, p_end = part[0]["start"], part[-1]["end"]
                p_text = "".join(x["ch"] for x in part)
                p_spk = spk
                p_chunk = wav[int(p_start * sr):int(p_end * sr)]
                if len(p_chunk) >= sr // 10:
                    r2 = spk_model.generate(input=p_chunk, fs=sr)
                    p_emb = r2[0].get("spk_embedding")
                    if p_emb is not None:
                        if hasattr(p_emb, "detach"):
                            p_emb = p_emb.detach().cpu().numpy()
                        p_spk = nearest_center(np.asarray(p_emb).reshape(-1), centers)
                out.append({"start": p_start, "end": p_end, "text": p_text,
                            "speaker": f"SPEAKER_{int(p_spk):02d}",
                            "words": to_words(part)})
    else:
        for (start, end, text), spk in zip(valid_segs, labels):
            out.append({"start": start, "end": end, "text": text,
                        "speaker": f"SPEAKER_{int(spk):02d}"})

    for s in out:
        print(f"[{s['speaker']}] {s['start']:7.2f} -> {s['end']:7.2f}  {s['text']}")

    # SRT：有字级时间戳时按标点断行，否则整段一条
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(srt_path, "w", encoding="utf-8") as f:
        idx = 0
        for s in out:
            lines = split_lines(s["words"], args.max_line) if s.get("words") \
                else [(s["start"], s["end"], s["text"])]
            for ls, le, lt in lines:
                idx += 1
                f.write(f"{idx}\n{fmt_ts(ls * 1000)} --> {fmt_ts(le * 1000)}\n"
                        f"[{s['speaker']}] {lt}\n\n")
    print(f"[OK] SRT: {srt_path}")

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] JSON: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
