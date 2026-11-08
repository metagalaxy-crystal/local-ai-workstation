#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FunASR + Qwen3-ASR 对白转写 + 说话人分离（design.md 10.3 方案 A）。

手动三段式流水线（绕过 FunASR 1.4.16 不完整的 distribute_spk）:
  1. silero-VAD 分句 + Qwen3-ASR-0.6B 逐段转写 -> 每段 start/end/text
  2. CAM++ 对每个 VAD 段提说话人 embedding     -> [N, 192]
  3. sklearn KMeans / 层次聚类 分配 speaker     -> 合并输出

可选第 4 步（--align）：Qwen3-ForcedAligner-0.6B 字级对齐（qwen-asr 包独立调用，
绕开 FunASR 不透传 forced_aligner 的缺陷）:
  - 段内静音 >= --split-gap（默认 0.5s）处切分，子段重提 embedding 归最近聚类
    中心，修正长段内两人交替发言被整段误判的情况（已用合成合并段验证：
    父句+0.5s 静音+女句可正确切开并各归其父/女孩说话人）
  - JSON 写入字级时间戳（words 字段）
  - SRT 按句末标点/--max-line 智能断行
  注：silero-vad 本身对 >=0.3s 静音已很敏感，段内切分是兜底安全网。

与 diarize_transcribe.py（sherpa-onnx 路线，已作废留档）并列。

用法:
  python diarize_transcribe_funasr.py <音频> [--srt out.srt] [--json out.json]
      [--speakers 2] [--device cuda|cpu] [--model Qwen/Qwen3-ASR-0.6B]
      [--align] [--split-gap 0.8] [--max-line 24]
"""
import argparse
import json
import sys
from pathlib import Path

# 模型按名称扁平存放在 models/audio/ 下，用注册表 key + 本地路径加载
DEFAULT_MODEL = "Qwen/Qwen3-ASR-0.6B"
DEFAULT_MODEL_PATH = r"D:\models\models\audio\Qwen3-ASR-0.6B"
# silero-vad 对短静音分段比 fsmn-vad 更敏感，适合对白场景
VAD_MODEL = "silero_vad"
SPK_MODEL = "cam++"
SPK_MODEL_PATH = r"D:\models\models\audio\campplus"
ALIGNER_PATH = r"D:\models\models\audio\Qwen3-ForcedAligner-0.6B"

# --language 缩写 -> aligner 需要的语言名
LANG_NAME_MAP = {
    "zh": "Chinese", "en": "English", "yue": "Cantonese", "ja": "Japanese",
    "ko": "Korean", "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese", "ru": "Russian", "es": "Spanish",
}
PUNCT = "，。！？；：、…,.!?;:"
SENT_END = "。！？…!?"


def fmt_ts(ms: float) -> str:
    ms = int(round(ms))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def cluster_embeddings(embs, n_speakers: int):
    """对说话人 embedding 聚类，返回 label 数组。"""
    import numpy as np
    from sklearn.cluster import KMeans, AgglomerativeClustering

    embs = np.asarray(embs)
    if len(embs) <= 1:
        return [0] * len(embs)
    if n_speakers and n_speakers > 0:
        # 说话人数已知，用 KMeans
        km = KMeans(n_clusters=min(n_speakers, len(embs)), n_init=10, random_state=0)
        return km.fit_predict(embs).tolist()
    # 自动聚类：层次聚类 + 余弦距离阈值
    ac = AgglomerativeClustering(
        n_clusters=None, metric="cosine", linkage="average", distance_threshold=0.3,
    )
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
    """把原文标点挂回对齐字序列（aligner 输出已去标点）。
    items: [{'ch','start','end'}, ...]，与 text 去标点后应等长。
    返回 (items, matched)；不匹配时原样返回，标点挂载失败不影响主流程。"""
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
    """字幕断行：句末标点必断；超过 max_chars 时在任意标点处断。
    words: [{'text','start','end'}, ...] -> [(start, end, text), ...]"""
    lines, cur = [], []
    for w in words:
        cur.append(w)
        t = "".join(x["text"] for x in cur)
        if t and (t[-1] in SENT_END or (len(t) >= max_chars and t[-1] in PUNCT)):
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    return [(l[0]["start"], l[-1]["end"], "".join(x["text"] for x in l))
            for l in lines]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--srt")
    ap.add_argument("--json")
    ap.add_argument("--speakers", type=int, default=2,
                    help="预设说话人数（双人对白=2）；0 表示自动聚类")
    ap.add_argument("--language", default="zh")
    ap.add_argument("--device", default=None, help="默认 cuda，无 GPU 时回退 cpu")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help="模型 ID 或本地目录（可切 Qwen/Qwen3-ASR-1.7B）")
    ap.add_argument("--align", action="store_true",
                    help="启用 Qwen3-ForcedAligner 字级对齐：段内说话人细化 + 字级时间戳")
    ap.add_argument("--aligner-path", default=ALIGNER_PATH)
    ap.add_argument("--split-gap", type=float, default=0.5,
                    help="段内静音 >= 该秒数时切分说话人（默认 0.5；实测说话人切换间隙可低至 0.5s）")
    ap.add_argument("--max-line", type=int, default=24,
                    help="SRT 单条字幕最大字数（默认 24）")
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.exists():
        print(f"音频不存在: {audio}", file=sys.stderr)
        return 1

    import numpy as np
    import soundfile as sf
    import torch
    from funasr import AutoModel

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")

    # 1) VAD：单独用 silero-vad 切分语音段（对短静音更敏感）
    print(f"load VAD: {VAD_MODEL}")
    vad_model = AutoModel(model=VAD_MODEL, hub="ms", disable_pbar=True, disable_update=True)

    # 2) ASR：Qwen3-ASR，不挂 vad/spk（避免 FunASR 内部 distribute_spk 报错）
    print(f"load ASR: model={args.model}  path={DEFAULT_MODEL_PATH}  device={device}")
    asr_model = AutoModel(
        model=args.model, model_path=DEFAULT_MODEL_PATH,
        device=device, dtype="bf16",
        disable_pbar=True, disable_update=True, trust_remote_code=True,
    )
    # 3) 说话人 embedding 模型（campplus）
    print(f"load SPK: {SPK_MODEL}  path={SPK_MODEL_PATH}")
    spk_model = AutoModel(
        model=SPK_MODEL, model_path=SPK_MODEL_PATH, device=device,
        disable_pbar=True, disable_update=True,
    )

    # 读原始音频（16k 单声道，供 ASR/campplus 切片）
    wav, sr = sf.read(str(audio), dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1).astype("float32")
    if sr != 16000:
        import torchaudio
        wav_t = torch.from_numpy(wav).unsqueeze(0)
        wav_t = torchaudio.functional.resample(wav_t, sr, 16000)
        wav = wav_t.squeeze(0).numpy().astype("float32")
        sr = 16000

    print(f"vad segment: {audio}")
    vad_res = vad_model.generate(input=wav, fs=sr)
    segments = vad_res[0].get("value") or []  # [[start_ms, end_ms], ...]
    print(f"vad segments: {len(segments)}")

    # 对每个 VAD 段：ASR 转写 + campplus 提 embedding
    embs = []
    valid_segs = []
    for start_ms, end_ms in segments:
        i0 = int(start_ms / 1000 * sr)
        i1 = int(end_ms / 1000 * sr)
        chunk = wav[i0:i1]
        if len(chunk) < sr // 10:  # 跳过 <0.1s
            continue
        # ASR 转写
        r = asr_model.generate(input=chunk, fs=sr, language=args.language)
        text = (r[0].get("text") or "").strip()
        if not text:
            continue
        # campplus 提 embedding
        sr2 = spk_model.generate(input=chunk, fs=sr)
        emb = sr2[0].get("spk_embedding")
        if emb is None:
            continue
        if hasattr(emb, "detach"):
            emb = emb.detach().cpu().numpy()
        embs.append(np.asarray(emb).reshape(-1))
        valid_segs.append((start_ms / 1000.0, end_ms / 1000.0, text))

    print(f"valid segments: {len(valid_segs)}")
    if not valid_segs:
        print("无有效语音段")
        return 1

    labels = cluster_embeddings(embs, args.speakers)
    out = []

    if args.align:
        # 4) 可选：ForcedAligner 字级对齐，细化段内说话人 + 字级时间戳
        from qwen_asr import Qwen3ForcedAligner

        lang_name = LANG_NAME_MAP.get(args.language, args.language)
        print(f"load Aligner: {args.aligner_path}")
        aligner = Qwen3ForcedAligner.from_pretrained(
            args.aligner_path,
            dtype=torch.bfloat16 if device == "cuda" else torch.float32,
            device_map="cuda:0" if device == "cuda" else device,
        )
        centers = cluster_centers(embs, labels)
        for (start, end, text), spk in zip(valid_segs, labels):
            chunk = wav[int(start * sr):int(end * sr)]
            try:
                res = aligner.align(audio=(chunk, sr), text=text, language=lang_name)
                items = [{"ch": s.text, "start": start + s.start_time,
                          "end": start + s.end_time} for s in res[0]]
            except Exception as e:
                print(f"align failed @ {start:.2f}s: {e}")
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

    if args.srt:
        with open(args.srt, "w", encoding="utf-8") as f:
            idx = 0
            for s in out:
                # 有字级时间戳时按标点断行，否则整段一条
                lines = split_lines(s["words"], args.max_line) if s.get("words") \
                    else [(s["start"], s["end"], s["text"])]
                for ls, le, lt in lines:
                    idx += 1
                    f.write(f"{idx}\n{fmt_ts(ls * 1000)} --> {fmt_ts(le * 1000)}\n"
                            f"[{s['speaker']}] {lt}\n\n")
        print(f"SRT: {args.srt}")
    if args.json:
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print(f"JSON: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
