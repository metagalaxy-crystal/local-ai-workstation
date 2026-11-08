#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 ComfyUI history 拉取每个 prompt 的执行时间账本。

用法:
  uv run python scripts/collect_timebook.py
  uv run python scripts/collect_timebook.py --ids prompt_id1 prompt_id2

输出:
  04_wan22/_timebook.json      —— Wan2.2 各镜头时间账本
  05_minimax_h3/_timebook.json —— MiniMax H3 各镜头时间账本
  06_compare/timebook_all.md   —— Markdown 汇总表（人读）

数据源说明:
  - ComfyUI /history/<prompt_id> 中的 status.messages 给出 start_time/end_time/execution_time
  - ComfyUI 主日志按 "Prompt executed in X seconds" 切段，每段对应一个完成的 prompt
    再从段内匹配 KSampler 进度条 (\d+/\d+ [..., X.XXs/it])，得到单步均值
  - 因此对未完成或仍在跑的 prompt，单步均值取最近一段进度（近似）
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

HOST = "http://127.0.0.1:8188"
ROOT = Path(r"D:\models\sample\铁锈海的女儿")
COMFY_OUT = Path(r"D:\models\ComfyUI\output\story_video")
COMFY_LOG = Path(r"C:\Users\junsheng\AppData\Local\Temp\trae-agent-toolhost\jobs\job-948ada3e01ac4132b58d19a2a004d5b4\output.log")

SUBMIT_GLOBS = {
    "wan22": ROOT / "04_wan22" / "_batch_submit_*.json",
    "minimax_h3": ROOT / "05_minimax_h3" / "_batch_submit_*.json",
}

SH_DESC = {
    1: "灰炉镇远景建立镜头",
    2: "幼年玛莲坐父亲肩头看蓝海",
    3: "蓝色海面特写(铜壳机械蜻蜓)",
    4: "父亲侧脸低语特写",
    5: "时间流逝延时转场",
    6: "成年玛莲独自站悬崖边",
}


def load_submissions() -> list[dict]:
    items = []
    for model, glob_path in SUBMIT_GLOBS.items():
        for p in sorted(glob_path.parent.glob(glob_path.name)):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
                for sid, pid in rec.get("submitted", []):
                    shot_n = int(sid.split("_")[1])
                    items.append({
                        "model": model, "shot_id": sid, "shot_n": shot_n,
                        "prompt_id": pid, "res": rec.get("res"),
                        "length": rec.get("length", 73),
                        "seed": rec.get("seed", 42),
                        "desc": SH_DESC.get(shot_n, ""),
                        "submit_file": p.name,
                    })
            except Exception as e:
                print(f"[WARN] 读 {p} 失败: {e}", file=sys.stderr)
    by_pid = {}
    for it in items:
        by_pid[it["prompt_id"]] = it
    return list(by_pid.values())


def fetch_history(prompt_id: str) -> dict:
    try:
        with urllib.request.urlopen(f"{HOST}/history/{prompt_id}", timeout=10) as r:
            data = json.loads(r.read())
        return data.get(prompt_id, {})
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}"}
    except Exception as e:
        return {"_error": str(e)}


def split_log_by_prompt(text: str) -> list[dict]:
    """按 'got prompt' 和 'Prompt executed in X seconds' 切日志段。

    返回每段的: {prompt_marker: 'got_prompt_index', sampler_progress: [(step,total,sec_per_it)],
                vae_tiled: bool, oom_msgs: [...], prompt_executed_secs: float}
    顺序与日志时间一致。
    """
    segments = []
    # 找所有 "got prompt" 行的位置（每个 prompt 提交时打一行，可能带 ANSI 颜色码）
    got_prompt_indices = [m.start() for m in re.finditer(r"got prompt", text)]
    if not got_prompt_indices:
        return segments
    # 在每两段之间截取
    bounds = got_prompt_indices + [len(text)]
    for i in range(len(got_prompt_indices)):
        seg = text[bounds[i]:bounds[i+1]]
        info = {"got_prompt_index": i, "sampler_progress": [],
                "vae_tiled": False, "oom_msgs": [], "prompt_executed_secs": None}
        # 单步均值
        prog = re.findall(
            r"(\d+)%\|.*?\|\s*(\d+)/(\d+)\s*\[([\d:]+)<([\d:]+),\s*([\d.]+)s/it", seg)
        if prog:
            last = prog[-1]
            info["sampler_progress"] = {
                "step": int(last[1]), "total": int(last[2]),
                "sec_per_it": float(last[5])
            }
        info["vae_tiled"] = "tiled" in seg.lower()
        oom = re.findall(r"(OOM[^.\n]*[.\n])", seg)
        info["oom_msgs"] = oom[-2:] if oom else []
        execs = re.findall(r"Prompt executed in ([\d.]+) seconds", seg)
        if execs:
            info["prompt_executed_secs"] = float(execs[-1])
        segments.append(info)
    return segments


def parse_comfy_log() -> list[dict]:
    """整体切日志段，每段对应一个串行 prompt 的执行。"""
    try:
        text = COMFY_LOG.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    return split_log_by_prompt(text)


def extract_outputs(history: dict) -> list[dict]:
    outs = history.get("outputs", {})
    files = []
    for node_id, node_out in outs.items():
        vids = node_out.get("videos", [])
        for v in vids:
            files.append({
                "filename": v.get("filename"),
                "subfolder": v.get("subfolder", ""),
                "type": v.get("type", "output"),
            })
    return files


def find_output_file(model: str, shot_id: str) -> Path | None:
    prefix = f"{model}_{shot_id}"
    candidates = sorted(COMFY_OUT.glob(f"{prefix}*.mp4"))
    return candidates[0] if candidates else None


def fmt_or_none(val, fmt_str, none_str="—") -> str:
    if val is None:
        return none_str
    try:
        return fmt_str.format(val)
    except Exception:
        return none_str


def main() -> int:
    ap = argparse.ArgumentParser(description="时间账本采集")
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--out_md", default=str(ROOT / "06_compare" / "timebook_all.md"))
    args = ap.parse_args()

    items = load_submissions()
    if args.ids:
        want = set(args.ids)
        items = [it for it in items if it["prompt_id"] in want]
    if not items:
        print("[WARN] 没有找到提交记录", file=sys.stderr)
        return 1

    # 提前一次性切日志段
    log_segments = parse_comfy_log()
    print(f"日志切出 {len(log_segments)} 段（每段≈一个串行 prompt）")

    print(f"采集 {len(items)} 个 prompt 的时间账本...")
    rows = []
    for it in items:
        pid = it["prompt_id"]
        hist = fetch_history(pid)
        if "_error" in hist:
            print(f"  {it['model']} {it['shot_id']}: 拉取失败 {hist['_error']}", file=sys.stderr)
            continue
        st = hist.get("status", {})
        completed = st.get("completed", False)
        status_str = st.get("status_str", "")
        msgs = st.get("messages", [])
        exc = None
        start_ts = None
        end_ts = None
        execution_time = None
        for m in msgs:
            if isinstance(m, list) and len(m) >= 2 and isinstance(m[1], dict):
                tag = m[0]
                payload = m[1]
                if "exception_message" in payload:
                    exc = payload["exception_message"]
                if tag == "execution_start":
                    start_ts = payload.get("start_time")
                if tag in ("execution_success", "execution_cached", "execution_error"):
                    if end_ts is None or payload.get("end_time"):
                        end_ts = payload.get("end_time") or end_ts
                if "execution_time" in payload:
                    execution_time = payload["execution_time"]
        out_files = extract_outputs(hist)
        mp4_path = find_output_file(it["model"], it["shot_id"])
        mp4_size_mb = None
        if mp4_path and mp4_path.exists():
            mp4_size_mb = mp4_path.stat().st_size / 1024 / 1024
        total_secs = execution_time
        if total_secs is None and start_ts and end_ts:
            total_secs = end_ts - start_ts
        # 日志段匹配：当前 prompt 的 prompt_marker 索引
        # ComfyUI 按提交顺序串行处理，提交记录文件按时间排序，
        # 但我们不能保证提交记录顺序和 ComfyUI 处理顺序完全一致
        # 简化：用该 prompt 在 items 列表中的位置（按提交记录文件时间）作日志段索引
        idx = items.index(it)
        log_seg = log_segments[idx] if idx < len(log_segments) else {}
        sampler_progress = log_seg.get("sampler_progress")
        sampler_total = sampler_progress["total"] if sampler_progress else None
        sampler_step_avg = sampler_progress["sec_per_it"] if sampler_progress else None
        vae_tiled = log_seg.get("vae_tiled", False)
        oom_msgs = log_seg.get("oom_msgs", [])
        row = {
            "model": it["model"],
            "shot_id": it["shot_id"],
            "shot_n": it["shot_n"],
            "desc": it["desc"],
            "res": it["res"],
            "length": it["length"],
            "seed": it["seed"],
            "prompt_id": pid,
            "completed": completed,
            "status_str": status_str,
            "exception": exc,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "total_secs": total_secs,
            "sampler_steps_total": sampler_total,
            "sampler_step_secs_avg": sampler_step_avg,
            "vae_tiled_decoding": vae_tiled,
            "oom_messages": oom_msgs,
            "out_files": out_files,
            "mp4_path": str(mp4_path) if mp4_path else None,
            "mp4_size_mb": mp4_size_mb,
        }
        rows.append(row)
        status = "OK" if completed else ("FAIL" if exc else "running")
        print(f"  {it['model']:11s} {it['shot_id']} -> {status} "
              f"total={fmt_or_none(total_secs, '{:.0f}s')} "
              f"steps={sampler_total or '—'} "
              f"step_avg={fmt_or_none(sampler_step_avg, '{:.1f}s')} "
              f"tiled={vae_tiled} "
              f"size={fmt_or_none(mp4_size_mb, '{:.1f}MB')}")

    for model in ("wan22", "minimax_h3"):
        mrows = [r for r in rows if r["model"] == model]
        out_dir = ROOT / f"0{4 if model=='wan22' else 5}_{model}"
        out_dir.mkdir(parents=True, exist_ok=True)
        tb_path = out_dir / "_timebook.json"
        tb_path.write_text(
            json.dumps(mrows, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"  写出: {tb_path}")

    md = ["# 视频生成时间账本", "",
          f"采集时间: {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')} (Asia/Shanghai)",
          f"数据源: ComfyUI history @ {HOST} + 主日志（按 got prompt 切段）",
          "", "## Wan2.2 (1088x608x73 / 832x480x73, steps=20, cfg=3.5, euler/simple)", ""]
    md.append("| shot | 描述 | 分辨率 | 状态 | 总耗时(s) | 采样步数 | 单步均值(s) | VAE tiled | 输出文件 | 大小(MB) |")
    md.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted([r for r in rows if r["model"]=="wan22"], key=lambda x: x["shot_n"]):
        status = "OK" if r["completed"] else ("FAIL" if r["exception"] else "run")
        md.append("| {shot} | {desc} | {res} | {status} | {tot} | {steps} | {avg} | {tiled} | {fname} | {size} |".format(
            shot=r["shot_id"], desc=r["desc"], res=r["res"], status=status,
            tot=fmt_or_none(r["total_secs"], "{:.0f}"),
            steps=r["sampler_steps_total"] or "—",
            avg=fmt_or_none(r["sampler_step_secs_avg"], "{:.1f}"),
            tiled="是" if r["vae_tiled_decoding"] else "否",
            fname=Path(r["mp4_path"]).name if r["mp4_path"] else "—",
            size=fmt_or_none(r["mp4_size_mb"], "{:.1f}"),
        ))
    md += ["", "## MiniMax H3 (832x480x73 / 640x640x73, steps=24, cfg=1.0, euler/simple, T2VA)", ""]
    md.append("| shot | 描述 | 分辨率 | 状态 | 总耗时(s) | 采样步数 | 单步均值(s) | 音轨 | 输出文件 | 大小(MB) |")
    md.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted([r for r in rows if r["model"]=="minimax_h3"], key=lambda x: x["shot_n"]):
        status = "OK" if r["completed"] else ("FAIL" if r["exception"] else "run")
        md.append("| {shot} | {desc} | {res} | {status} | {tot} | {steps} | {avg} | 是(同步) | {fname} | {size} |".format(
            shot=r["shot_id"], desc=r["desc"], res=r["res"], status=status,
            tot=fmt_or_none(r["total_secs"], "{:.0f}"),
            steps=r["sampler_steps_total"] or "—",
            avg=fmt_or_none(r["sampler_step_secs_avg"], "{:.1f}"),
            fname=Path(r["mp4_path"]).name if r["mp4_path"] else "—",
            size=fmt_or_none(r["mp4_size_mb"], "{:.1f}"),
        ))
    md += ["", "## 异常记录", ""]
    errs = [r for r in rows if r["exception"]]
    if errs:
        for r in errs:
            md.append(f"- **{r['model']} {r['shot_id']}** ({r['prompt_id']}): {r['exception']}")
    else:
        md.append("（无异常）")
    if any(r["oom_messages"] for r in rows):
        md += ["", "## OOM 触发记录", ""]
        for r in rows:
            if r["oom_messages"]:
                md.append(f"- **{r['model']} {r['shot_id']}**: {r['oom_messages']}")
    md.append("")
    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"  写出: {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
