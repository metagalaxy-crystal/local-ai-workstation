#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用修好的判分规则对已生成的 _reasoning 输出重新判分，更新 summary.json。
不重跑模型，只重读 q*.txt。"""
from __future__ import annotations
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_reasoning import QUESTIONS, judge

RESULTS = Path(r"D:\models\docs\bench_results")

for d in sorted(RESULTS.glob("*_reasoning")):
    if not (d / "summary.json").exists():
        continue
    summary = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    n_ok = 0
    for qid, domain, q, groups, answer in QUESTIONS:
        f = d / f"{qid}.txt"
        ok = judge(f.read_text(encoding="utf-8"), groups) if f.exists() else False
        n_ok += ok
        for r in summary["results"]:
            if r.get("q") == qid:
                r["ok"] = ok
    old = summary.get("score")
    summary["score"] = f"{n_ok}/10"
    summary["rejudged"] = True
    (d / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{d.name:22s} {old} -> {summary['score']}" +
          ("  (有修正)" if old != summary["score"] else ""))
