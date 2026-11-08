#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地模型 编程能力专项测试。5 道题全部真实运行验证，自动判分。

任务覆盖：算法实现 / 类设计 / 调试纠错 / 解析 / 动态规划。
与主 bench T3（单函数）的区别：难度上调、需要多函数协作或类设计、
含"模型必须读懂并修复别人的 bug"与防贪心捷径的测试用例。

判分：提取模型输出中的 Python 代码块（优先最后一个 ``` 块，
其次从 def/class 行截取，兜底全文），拼接 harness 真实运行。

用法:
  python bench_coding.py --preset ornith
结果:
  docs\bench_results/<label>_coding/t1..t5.txt + summary.json
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_universal import PRESETS, RESULTS_ROOT, chat, extract  # noqa: E402

# (题号, 领域, 题目, harness 代码)
TASKS = [
    ("t1", "算法实现",
     "用 Python 实现函数 merge(intervals)，输入区间列表（元素为 [start, end]，"
     "输入不保证有序），合并所有重叠区间，返回按起点升序排列的结果列表。"
     "只输出代码，不要解释。",
     """
assert merge([[1,3],[2,6],[8,10],[15,18]]) == [[1,6],[8,10],[15,18]]
assert merge([[1,4],[4,5]]) == [[1,5]]
assert merge([]) == []
assert merge([[5,7],[1,2]]) == [[1,2],[5,7]]
assert merge([[1,10],[2,3],[4,5],[11,12]]) == [[1,10],[11,12]]
print('PASS')
"""),

    ("t2", "类设计",
     "用 Python 实现 LRUCache 类，构造参数 capacity，方法 get(key)（不存在返回 -1）"
     "和 put(key, value)，两种操作都必须 O(1)。只输出代码，不要解释。",
     """
c = LRUCache(2)
c.put(1, 1)
c.put(2, 2)
assert c.get(1) == 1
c.put(3, 3)
assert c.get(2) == -1
c.put(4, 4)
assert c.get(1) == -1
assert c.get(3) == 3
assert c.get(4) == 4
print('PASS')
"""),

    ("t3", "调试纠错",
     "下面的 binary_search 有 bug：某些输入会死循环，某些输入返回错误结果。"
     "请修复它，输出修复后的完整函数（保持函数签名不变）。只输出代码。\n"
     "```python\n"
     "def binary_search(arr, target):\n"
     "    lo, hi = 0, len(arr) - 1\n"
     "    while lo < hi:\n"
     "        mid = (lo + hi) // 2\n"
     "        if arr[mid] == target:\n"
     "            return mid\n"
     "        elif arr[mid] < target:\n"
     "            lo = mid\n"
     "        else:\n"
     "            hi = mid\n"
     "    return -1\n"
     "```",
     """
assert binary_search([1,3,5,7,9], 5) == 2
assert binary_search([1,3,5,7,9], 1) == 0
assert binary_search([1,3,5,7,9], 9) == 4
assert binary_search([1,3,5,7,9], 4) == -1
assert binary_search([2], 2) == 0
assert binary_search([2], 5) == -1
print('PASS')
"""),

    ("t4", "解析转换",
     "用 Python 实现函数 roman_to_int(s)，把罗马数字字符串转为整数"
     "（s 范围 1-3999，输入保证合法）。只输出代码，不要解释。",
     """
assert roman_to_int('III') == 3
assert roman_to_int('IV') == 4
assert roman_to_int('IX') == 9
assert roman_to_int('LVIII') == 58
assert roman_to_int('MCMXCIV') == 1994
print('PASS')
"""),

    ("t5", "动态规划",
     "用 Python 实现函数 min_coins(coins, amount)，返回凑出 amount 所需的最少"
     "硬币数（每种硬币数量无限）；无法凑出返回 -1，amount 为 0 返回 0。"
     "只输出代码，不要解释。",
     """
assert min_coins([1,2,5], 11) == 3
assert min_coins([2], 3) == -1
assert min_coins([1], 0) == 0
assert min_coins([186,419,83,408], 6249) == 20
print('PASS')
"""),
]


def extract_code(text: str) -> tuple[str, str]:
    """返回 (代码, 提取方式)。优先最后一个 ``` 块，其次 def/class 行截取，兜底全文。"""
    blocks = re.findall(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    if blocks:
        return blocks[-1].strip(), "code_block" + ("(多个取最后)" if len(blocks) > 1 else "")
    m = re.search(r"^\s*(?:def |class |import |from )", text, re.MULTILINE)
    if m:
        code = text[m.start():].strip()
        # 去掉代码后混入的散文行（以中文标点结尾）
        lines = code.splitlines()
        while lines and lines[-1].rstrip().endswith(("。", "：", "，", "；", "！", "？")):
            lines.pop()
        return "\n".join(lines).strip(), "def_line"
    return text.strip(), "whole_text"


def run_code(code: str, harness: str) -> tuple[bool, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as f:
        f.write(code + "\n\n" + harness)
        path = f.name
    try:
        r = subprocess.run([sys.executable, path], capture_output=True,
                           text=True, timeout=30)
        ok = "PASS" in r.stdout
        return ok, "" if ok else (r.stderr.strip()[-250:] or r.stdout[-250:])
    except Exception as e:
        return False, str(e)
    finally:
        Path(path).unlink(missing_ok=True)


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

    extra = {"temperature": 0.3}
    if cfg.get("no_think"):
        extra["chat_template_kwargs"] = {"enable_thinking": False}
    if cfg.get("effort"):
        extra["reasoning_effort"] = cfg["effort"]

    out_dir = RESULTS_ROOT / f"{label}_coding"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        with urllib.request.urlopen(
                f"http://{cfg['host']}:{cfg['port']}/health", timeout=8) as r:
            print(f"health: {r.read().decode()[:120]}")
    except Exception as e:
        print(f"[FAIL] 连不上 {cfg['host']}:{cfg['port']} —— {e}", file=sys.stderr)
        return 2

    P = lambda *a: print(*a, flush=True)
    results, n_ok, n_extract_fail = [], 0, 0
    t_start = time.time()

    for qid, domain, prompt, harness in TASKS:
        try:
            resp, dt = chat(cfg["host"], cfg["port"], cfg["key"],
                            [{"role": "user", "content": prompt}], 2000, extra)
            text, usage = extract(resp)
        except Exception as e:
            text, dt, usage = f"[请求异常] {e}", 0.0, {}
        (out_dir / f"{qid}.txt").write_text(text, encoding="utf-8")
        code, how = extract_code(text)
        if how == "whole_text":
            n_extract_fail += 1
        ok, err = run_code(code, harness)
        n_ok += ok
        ct = usage.get("completion_tokens", 0)
        r = {"t": qid, "domain": domain, "ok": ok, "extract": how,
             "wall_sec": round(dt, 1), "completion_tokens": ct,
             "tok_per_sec": round(ct / dt, 1) if dt > 0 else 0}
        if not ok:
            r["error"] = err
        results.append(r)
        P(f"[{qid}·{domain}] {'✓' if ok else '✗'} ({how}) "
          f"{r['wall_sec']}s · {ct} tok")
        if err:
            P(f"    err: {err[:100]}")

    summary = {"label": label, "endpoint": f"{cfg['host']}:{cfg['port']}",
               "temperature": 0.3, "max_tokens": 2000,
               "score": f"{n_ok}/5", "extract_fail": n_extract_fail,
               "total_sec": round(time.time() - t_start, 1),
               "time": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    P(f"\n总分 {n_ok}/5 | 总耗时 {summary['total_sec']}s → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
