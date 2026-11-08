#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地模型 硬推理能力测试（与 bench_universal 区分开的独立测试）。

10 道题，全部有确定答案、自动判分。覆盖：多步数学、逻辑演绎、排序链、
直觉陷阱、概率、代码行为预测、日期推算、组合计数、规划、信息论称球。
判分规则：每题若干关键词组，组内 OR、组间 AND，命中即 ✓。
与主 bench 的差异：temperature 0.3（降低采样噪声），max_tokens 1500。

用法:
  python bench_reasoning.py --preset lfm24b
  python bench_reasoning.py --host 127.0.0.1 --port 8097 --label x

结果:
  docs\bench_results/<label>_reasoning/q01.txt … q10.txt + summary.json
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_universal import PRESETS, RESULTS_ROOT, chat, extract  # noqa: E402

SUFFIX = "请给出推理过程，并在最后一行明确写出最终答案。"

# (题号, 领域, 题目, 判分关键词组[组内OR/组间AND], 标准答案)
QUESTIONS = [
    ("q01", "多步数学",
     "一项工程，甲单独做12天完成，乙单独做18天完成。两人合作3天后甲离开，"
     "乙单独继续做剩余部分。问乙还需要几天才能完成？",
     [["10.5", "21/2", "10天半", "十点五"]], "10.5 天"),

    ("q02", "逻辑演绎",
     "甲、乙、丙三人中，骑士总说真话，无赖总说谎。甲说：“乙是无赖。”"
     "乙说：“丙是无赖。”丙说：“甲和乙都是无赖。”请推出三人的身份。",
     [["甲", "无赖"], ["乙", "骑士"], ["丙", "无赖"]], "甲无赖、乙骑士、丙无赖"),

    ("q03", "排序链",
     "A、B、C、D、E 五人赛跑。已知：A 在 B 之前到达；C 在 D 之后、E 之前到达；"
     "B 在 D 之前到达；E 不是第一名。请写出从先到后的完整名次。",
     [["A、B、D、C、E", "A,B,D,C,E", "A B D C E", "A→B→D→C→E",
       "A>B>D>C>E", "ABDCE", "A-B-D-C-E"]], "A、B、D、C、E（D 第三）"),

    ("q04", "直觉陷阱",
     "一根绳子和一个铁环共 110 元，绳子比铁环贵 100 元。问铁环多少钱？",
     [["5元", "5 元", "5块", "铁环为5", "铁环是5", "铁环5"]], "5 元（直觉答案 10 元是错的）"),

    ("q05", "概率",
     "袋中有 3 个红球和 2 个白球，不放回地摸出两个球。问两个都是红球的概率是多少？",
     [["3/10", "0.3", "30%", "十分之三", "frac{3}{10}", "3÷10",
       "3 × 1/10", "0.30"]], "3/10"),

    ("q06", "代码行为预测",
     "预测下面 Python 代码的输出（写出三行打印结果）：\n"
     "def f(a=[]):\n    a.append(len(a))\n    return a\n"
     "print(f())\nprint(f())\nprint(f([7]))",
     [["[0, 1]", "[0,1]"], ["[7, 1]", "[7,1]"]], "[0] / [0, 1] / [7, 1]（可变默认参数陷阱）"),

    ("q07", "日期推算",
     "已知 2026 年 1 月 1 日是星期四。问 2026 年 10 月 19 日是星期几？",
     [["星期一", "周一", "礼拜一", "Monday"]], "星期一"),

    ("q08", "组合计数",
     "平面上有 5 条直线，任意两条都相交，且任意三条不共点。"
     "问这些直线最多把平面分成多少个区域？",
     [["16"]], "16 个（公式 n(n+1)/2+1）"),

    ("q09", "规划",
     "农夫带狼、羊、白菜过河，船一次只能载农夫和一样东西。狼和羊不能单独相处，"
     "羊和白菜不能单独相处。问最少要渡河几个单程才能全部安全过河？",
     [["7个单程", "7 个单程", "7次", "7 次", "七次", "7趟", "7 趟",
       "7 个单程", "七个单程", "7 单程", "7次渡", "7 次渡",
       "7 one-way", "7 one way", "trips is 7", "is 7", "= 7",
       "7 crossings", "seven trips", "seven crossings", "is seven"]], "7 个单程"),

    ("q10", "信息论称球",
     "有 12 个外观相同的球，其中有一个重量与其他不同（不知是偏重还是偏轻）。"
     "用一架天平，最多称几次就一定能找出这个球？",
     [["3次", "3 次", "三次", "3趟"]], "3 次"),
]


def judge(text: str, groups: list[list[str]]) -> bool:
    # 归一化：窄不换行空格/不换行连字符等排版字符，避免关键词误判
    t = (text.replace("\u202f", " ").replace("\u00a0", " ")
             .replace("\u2011", "-").replace("\u2009", " "))
    return all(any(k in t for k in g) for g in groups)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", choices=list(PRESETS))
    ap.add_argument("--host"); ap.add_argument("--port", type=int)
    ap.add_argument("--key"); ap.add_argument("--label")
    args = ap.parse_args()

    cfg = dict(PRESETS.get(args.preset, {}))
    for k in ("host", "port", "key"):
        if getattr(args, k) is not None:
            cfg[k] = getattr(args, k)
    cfg.setdefault("host", "127.0.0.1"); cfg.setdefault("port", 8082)
    cfg.setdefault("key", None)
    label = args.label or args.preset or "custom"

    extra = {"temperature": 0.3}  # 推理测试降低采样噪声
    if cfg.get("no_think"):
        extra["chat_template_kwargs"] = {"enable_thinking": False}
    if cfg.get("effort"):
        extra["reasoning_effort"] = cfg["effort"]

    out_dir = RESULTS_ROOT / f"{label}_reasoning"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        with urllib.request.urlopen(
                f"http://{cfg['host']}:{cfg['port']}/health", timeout=8) as r:
            print(f"health: {r.read().decode()[:120]}")
    except Exception as e:
        print(f"[FAIL] 连不上 {cfg['host']}:{cfg['port']} —— {e}", file=sys.stderr)
        return 2

    P = lambda *a: print(*a, flush=True)
    results, n_ok = [], 0
    t_start = time.time()

    for qid, domain, q, groups, answer in QUESTIONS:
        prompt = f"{q}\n{SUFFIX}"
        try:
            resp, dt = chat(cfg["host"], cfg["port"], cfg["key"],
                            [{"role": "user", "content": prompt}], 1500, extra)
            text, usage = extract(resp)
        except Exception as e:
            text, dt, usage = f"[请求异常] {e}", 0.0, {}
        (out_dir / f"{qid}.txt").write_text(text, encoding="utf-8")
        ok = judge(text, groups)
        n_ok += ok
        ct = usage.get("completion_tokens", 0)
        r = {"q": qid, "domain": domain, "ok": ok,
             "wall_sec": round(dt, 1), "completion_tokens": ct,
             "tok_per_sec": round(ct / dt, 1) if dt > 0 else 0}
        results.append(r)
        P(f"[{qid}·{domain}] {'✓' if ok else '✗'} "
          f"{r['wall_sec']}s · {ct} tok · {r['tok_per_sec']} t/s")

    summary = {"label": label, "endpoint": f"{cfg['host']}:{cfg['port']}",
               "temperature": 0.3, "max_tokens": 1500,
               "score": f"{n_ok}/10", "total_sec": round(time.time() - t_start, 1),
               "time": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    P(f"\n总分 {n_ok}/10 | 总耗时 {summary['total_sec']}s → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
