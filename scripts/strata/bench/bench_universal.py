#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云端 Strata / 本地模型 普适性能对比测试。

测试维度（与具体业务无关）：
  T0 速度探针   固定提示词 256 tok，测纯生成速度
  T1 中文写作   命题散文（速度 + 人工评分）
  T2 数学推理   鸡兔同笼（自动判对错：鸡23/兔12）
  T3 代码生成   top_k_frequent 函数（自动提取代码并真实运行验证）
  T4 长文摘要   约1500字文章 → 摘要+要点（速度 + 人工评分）
  T5 知识问答   3 道常识题（自动判对错）
  T6 多模态     图片描述（仅支持视觉的端点，Strata 已开启）

用法:
  python bench_universal.py --preset strata            # 云端 Strata
  python bench_universal.py --preset deepseek          # 本地 DeepSeek-R1-8B（需先起 8092）
  python bench_universal.py --preset lfm               # 本地 LFM2.5-8B（需先起 8091）
  python bench_universal.py --host x --port y --key k --label 自定义 --skip-mm
  python bench_universal.py --preset lfm24b --lang en    # 英文基准（结果存 docs\bench_results/<label>_en/）

结果:
  docs\bench_results/<label>/  原始输出全文 + summary.json（耗时/tok/s/自动判分）
"""
from __future__ import annotations
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

RESULTS_ROOT = Path(r"D:\models\docs\bench_results")

PRESETS = {
    "strata":   dict(host="10.203.239.162", port=8082,
                     key=os.environ.get("STRATA_API_KEY", ""), effort="low"),
    "lfm":      dict(host="127.0.0.1", port=8091, key=None),
    "nanbeige": dict(host="127.0.0.1", port=8090, key=None, no_think=True),
    "qwen35b":  dict(host="127.0.0.1", port=8093, key=None, no_think=True),
    "qwen25vl": dict(host="127.0.0.1", port=8094, key=None),
    "minicpm":  dict(host="127.0.0.1", port=8095, key=None),
}

# 多模态测试图片（蒸汽朋克场景图，来自文生图实测产物）
MM_IMAGE = Path(r"D:\models\sample\铁锈海的女儿\08_image_pipeline\outputs\zimage_t2i_710895999_zimage_t2i_00001_.png")

LONG_ARTICLE = """
丝绸之路是古代连接中国与中亚、西亚乃至地中海各国的贸易与文化交流通道总称。它得名于19世纪德国地理学家李希霍芬，因中国丝绸是这条通道上最具代表性的商品而得名。狭义上的丝绸之路通常指西汉张骞通西域后开辟的陆上通道，起点为长安（今西安），经河西走廊、塔里木盆地，翻越帕米尔高原，通往大宛、大夏、安息等国，最终抵达罗马帝国的东方行省。

丝绸之路的意义远不止于商品交换。通过这条通道，中国的造纸术、印刷术、火药和指南针逐渐传向西方，深刻改变了世界文明的进程；而葡萄、苜蓿、石榴、胡麻、胡桃等作物，以及佛教、祆教、景教等宗教和音乐、舞蹈、绘画等艺术形式也源源传入中原，极大地丰富了汉唐宋时期的物质生活与精神生活。唐代是丝绸之路的鼎盛时期，长安城中有数以万计的胡商、僧侣和留学生，胡旋舞、羯鼓、葡萄酒成为都市风尚，唐诗中留下了大量描写西域风情的名句。

除了陆上通道，海上丝绸之路同样繁荣。自唐宋起，中国东南沿海的广州、泉州、明州（宁波）等港口与东南亚、印度、阿拉伯半岛乃至东非保持着密切的航运往来，瓷器、茶叶取代丝绸成为主要出口商品，因此海上丝路又被称为"陶瓷之路"。元代泉州港被誉为"东方第一大港"，摩洛哥旅行家伊本·白图泰曾盛赞其繁华。

明代以后，由于海禁政策、政治重心东移以及奥斯曼帝国阻断传统商路等因素，陆上丝绸之路逐渐衰落。然而它留下的遗产——敦煌莫高窟的壁画与藏经洞、撒马尔罕的造纸作坊、威尼斯的中国瓷器——至今仍在诉说那段横跨欧亚的千年交流史。2014年，"丝绸之路：长安—天山廊道的路网"被列入联合国教科文组织世界遗产名录，成为首个由多国联合申报成功的遗产项目。
"""


LONG_ARTICLE_EN = """
The Silk Road is the name given to the network of trade and cultural-exchange routes that in ancient times connected China with Central Asia, Western Asia and eventually the Mediterranean. It owes its name to the 19th-century German geographer Ferdinand von Richthofen, who coined the term because Chinese silk was the most representative commodity carried along these routes. In the narrow sense, the Silk Road usually refers to the overland route opened after the Han-dynasty envoy Zhang Qian travelled to the Western Regions: it began at Chang'an (present-day Xi'an), crossed the Hexi Corridor and the Tarim Basin, climbed the Pamir Plateau, and reached Dayuan, Daxia and Parthia before arriving at the eastern provinces of the Roman Empire.

Its significance went far beyond the exchange of goods. Papermaking, printing, gunpowder and the compass gradually travelled westward along this route and profoundly changed the course of world civilization, while grapes, alfalfa, pomegranates, sesame and walnuts, together with Buddhism and other religions and with music, dance and painting, flowed eastward into the Central Plains and greatly enriched both the material and the spiritual life of the Han, Tang and Song periods. The Tang dynasty was the heyday of the Silk Road: tens of thousands of Sogdian merchants, monks and foreign students lived in Chang'an, and the Sogdian whirling dance, the jiegu drum and grape wine became urban fashions, leaving a wealth of verses about the Western Regions in Tang poetry.

Besides the overland route, the maritime Silk Road was equally prosperous. From the Tang and Song dynasties onward, the ports of Guangzhou, Quanzhou and Mingzhou (Ningbo) on China's southeastern coast maintained close shipping links with Southeast Asia, the Indian subcontinent, the Arabian Peninsula and even East Africa. Porcelain and tea replaced silk as the main exports, which is why the maritime route is also called the "Porcelain Road". In the Yuan dynasty the Moroccan traveller Ibn Battuta praised Quanzhou as the greatest port in the East.

After the Ming dynasty the overland Silk Road declined, owing to the maritime ban, the eastward shift of political power and the Ottoman Empire's blocking of the traditional trade routes. Yet the heritage it left behind — the murals and the library cave of the Mogao Caves at Dunhuang, the paper-making workshops of Samarkand, the Chinese porcelain of Venice — still testifies to a thousand years of exchange across Eurasia. In 2014 the "Silk Roads: the Routes Network of Chang'an–Tianshan Corridor" was inscribed on the UNESCO World Heritage List, the first such project jointly nominated by several countries.
"""

# 测试项提示词：中文集为原有内容（保持不动），英文集用于 --lang en
PROMPTS = {
    "zh": {
        "t0": "用中文详细介绍丝绸之路上流通的主要商品与文化交流。",
        "t1": "以《秋天的第一场雨》为题写一篇 300 字左右的散文。直接输出正文。",
        "t2": "鸡兔同笼，共有 35 个头，94 条腿。问鸡和兔各有多少只？请给出计算过程。",
        "t3": "用 Python 写一个函数 top_k_frequent(nums, k)，返回整数列表中出现频率最高的 k 个数，"
              "按频率从高到低排序（频率相同按数值升序）。只输出函数代码，不要解释。",
        "t4_lead": "阅读下面这篇文章，用 100 字以内写一段摘要，再列出 3 个关键要点。",
        "t5": [("《红楼梦》的作者是谁？成书于哪个朝代？", ["曹雪芹", "清"]),
               ("光在真空中的传播速度大约是每秒多少公里？", ["30万", "300000", "3×10"]),
               ("HTTP 协议中 404 状态码表示什么？", ["不存在", "未找到", "not found"])],
        "t6": "详细描述这张图片：场景内容、人物（如有）、构图、色调氛围。",
        "t7a": '写一个 150 字以内的微小说，开头必须是："她在第十四次重生后，决定不再救他。"'
               "要求有意外转折。直接输出正文。",
        "t7b": "为一款帮助老年人学习使用智能手机的 App 起 3 个名字，"
               "每个名字用一句话解释创意。直接输出列表。",
        "article": LONG_ARTICLE,
    },
    "en": {
        "t0": "Describe in detail the main goods traded along the Silk Road and the cultural exchanges it enabled.",
        "t1": "Write an essay of about 300 words titled 'The First Rain of Autumn'. Output the essay text only.",
        "t2": "A farmer keeps chickens and rabbits. There are 35 heads and 94 legs in total. "
              "How many chickens and how many rabbits are there? Show your calculation.",
        "t3": "Write a Python function top_k_frequent(nums, k) that returns the k most frequent integers "
              "in the list, sorted by frequency from high to low (ties broken by ascending value). "
              "Output only the function code, no explanation.",
        "t4_lead": "Read the article below, then write a summary in no more than 100 words, "
                   "followed by 3 key points.",
        "t5": [("Who wrote the novel 'Pride and Prejudice'? In which century was it first published?",
                ["austen"]),
               ("What is the speed of light in a vacuum, in kilometres per second?",
                ["300,000", "300000", "299,792", "3×10", "3x10"]),
               ("What does the HTTP 404 status code mean?",
                ["not found", "notfound", "does not exist", "doesn't exist", "no such"])],
        "t6": "Describe this image in detail: the scene, any figures, the composition, and the colour and mood.",
        "t7a": 'Write a micro-fiction of no more than 150 words. The opening sentence must be exactly: '
               '"After her fourteenth rebirth, she decided not to save him again." '
               "Include an unexpected twist. Output only the story.",
        "t7b": "Suggest 3 names for an app that helps elderly people learn to use smartphones. "
               "Explain the idea behind each name in one sentence. Output only the list.",
        "article": LONG_ARTICLE_EN,
    },
}


def chat(host: str, port: int, key: str | None, messages: list,
         max_tokens: int, extra: dict | None = None) -> tuple[dict, float]:
    payload = {"model": "bench", "messages": messages,
               "temperature": 0.7, "max_tokens": max_tokens, "stream": False}
    if extra:
        payload.update(extra)
    req = urllib.request.Request(
        f"http://{host}:{port}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1800) as r:
        resp = json.loads(r.read())
    return resp, time.time() - t0


def extract(resp: dict) -> tuple[str, dict]:
    msg = resp.get("choices", [{}])[0].get("message", {})
    text = msg.get("content", "") or msg.get("reasoning_content", "") or ""
    usage = resp.get("usage", {})
    return text, usage


def run_test(name: str, cfg: dict, messages: list, max_tokens: int,
             out_dir: Path) -> dict:
    resp, dt = chat(cfg["host"], cfg["port"], cfg["key"], messages,
                    max_tokens, cfg.get("extra"))
    text, usage = extract(resp)
    ct = usage.get("completion_tokens", 0)
    (out_dir / f"{name}.txt").write_text(text, encoding="utf-8")
    return {"test": name, "wall_sec": round(dt, 1),
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": ct,
            "tok_per_sec": round(ct / dt, 1) if dt > 0 else 0}


def verify_code(text: str) -> tuple[bool, str]:
    """提取并真实运行生成的 top_k_frequent，验证正确性。"""
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    code = m.group(1) if m else text
    harness = code + "\n\n" + (
        "assert top_k_frequent([1,1,1,2,2,3], 2) == [1,2]\n"
        "assert top_k_frequent([5,5,4,4,4,6,7], 2) == [4,5]\n"
        "assert top_k_frequent([9], 1) == [9]\n"
        "print('PASS')\n")
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as f:
        f.write(harness)
        path = f.name
    try:
        r = subprocess.run([sys.executable, path], capture_output=True,
                           text=True, timeout=30)
        ok = "PASS" in r.stdout
        return ok, "" if ok else (r.stderr.strip()[-300:] or r.stdout[-300:])
    except Exception as e:
        return False, str(e)
    finally:
        Path(path).unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", choices=list(PRESETS))
    ap.add_argument("--host"); ap.add_argument("--port", type=int)
    ap.add_argument("--key"); ap.add_argument("--label")
    ap.add_argument("--effort", default=None)
    ap.add_argument("--skip-mm", action="store_true", help="跳过多模态测试")
    ap.add_argument("--tests", default=None,
                    help="只跑指定测试，逗号分隔，如 t6,t7；默认全跑")
    ap.add_argument("--lang", choices=["zh", "en"], default="zh",
                    help="提示词语言：zh=中文基准（默认），en=英文基准")
    args = ap.parse_args()
    L = PROMPTS[args.lang]
    wanted = set(args.tests.split(",")) if args.tests else None
    def want(t: str) -> bool:
        return wanted is None or t in wanted

    cfg = dict(PRESETS.get(args.preset, {}))
    for k in ("host", "port", "key"):
        if getattr(args, k) is not None:
            cfg[k] = getattr(args, k)
    cfg.setdefault("host", "127.0.0.1"); cfg.setdefault("port", 8082)
    cfg.setdefault("key", None)
    label = args.label or args.preset or "custom"
    extra = {}
    effort = args.effort or cfg.get("effort")
    if effort:
        extra["reasoning_effort"] = effort
    if cfg.get("no_think"):
        extra["chat_template_kwargs"] = {"enable_thinking": False}
    cfg["extra"] = extra

    out_dir = RESULTS_ROOT / (label if args.lang == "zh" else f"{label}_en")
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        req = urllib.request.Request(f"http://{cfg['host']}:{cfg['port']}/health")
        if cfg["key"]:
            req.add_header("Authorization", f"Bearer {cfg['key']}")
        with urllib.request.urlopen(req, timeout=8) as r:
            print(f"health: {r.read().decode()[:160]}")
    except Exception as e:
        print(f"[FAIL] 连不上 {cfg['host']}:{cfg['port']} —— {e}", file=sys.stderr)
        return 2

    results = []
    P = lambda *a: print(*a, flush=True)

    # T0 速度探针（2 次）
    if want("t0"):
        P("\n[T0] 速度探针 ...")
        speeds = []
        for i in range(2):
            r = run_test(f"t0_probe_{i+1}", cfg,
                         [{"role": "user", "content": L["t0"]}], 256, out_dir)
            speeds.append(r["tok_per_sec"]); P(f"  第{i+1}次 {r['tok_per_sec']} tok/s")
        results.append({"test": "t0_probe", "tok_per_sec_median": sorted(speeds)[0]})

    # T1 中文写作
    if want("t1"):
        P("[T1] 中文写作 ...")
        r = run_test("t1_writing", cfg,
                     [{"role": "user", "content": L["t1"]}], 900, out_dir)
        P(f"  {r['wall_sec']}s | {r['tok_per_sec']} tok/s"); results.append(r)

    # T2 数学推理
    if want("t2"):
        P("[T2] 数学推理 ...")
        r = run_test("t2_math", cfg,
                     [{"role": "user", "content": L["t2"]}], 1024, out_dir)
        txt = (out_dir / "t2_math.txt").read_text(encoding="utf-8")
        r["auto_correct"] = ("23" in txt) and ("12" in txt)
        P(f"  {r['wall_sec']}s | 答案自动判定: {'✓' if r['auto_correct'] else '✗'}"); results.append(r)

    # T3 代码生成（真实运行验证）
    if want("t3"):
        P("[T3] 代码生成 ...")
        r = run_test("t3_code", cfg,
                     [{"role": "user", "content": L["t3"]}], 900, out_dir)
        ok, err = verify_code((out_dir / "t3_code.txt").read_text(encoding="utf-8"))
        r["auto_correct"] = ok
        if not ok:
            r["error"] = err
        P(f"  {r['wall_sec']}s | 代码运行验证: {'✓ PASS' if ok else '✗ ' + err[:80]}"); results.append(r)

    # T4 长文摘要
    if want("t4"):
        P("[T4] 长文摘要 ...")
        r = run_test("t4_summary", cfg,
                     [{"role": "user", "content":
                       f"{L['t4_lead']}\n\n{L['article']}"}], 900, out_dir)
        P(f"  {r['wall_sec']}s | prompt={r['prompt_tokens']} | {r['tok_per_sec']} tok/s"); results.append(r)

    # T5 知识问答
    if want("t5"):
        P("[T5] 知识问答 ...")
        qs = L["t5"]
        n_ok = 0
        for i, (q, keys) in enumerate(qs, 1):
            r = run_test(f"t5_qa_{i}", cfg, [{"role": "user", "content": q}], 512, out_dir)
            txt = (out_dir / f"t5_qa_{i}.txt").read_text(encoding="utf-8").lower()
            hit = any(k.lower() in txt for k in keys)
            n_ok += hit
            P(f"  Q{i}: {'✓' if hit else '✗'} ({r['wall_sec']}s)")
        results.append({"test": "t5_qa", "correct": f"{n_ok}/3"})

    # T6 多模态
    if want("t6") and not args.skip_mm:
        if not MM_IMAGE.exists():
            P(f"[T6] 跳过（测试图不存在: {MM_IMAGE}）")
        else:
            P("[T6] 多模态（图片描述）...")
            b64 = base64.b64encode(MM_IMAGE.read_bytes()).decode()
            try:
                r = run_test("t6_vision", cfg,
                             [{"role": "user", "content": [
                                 {"type": "image_url", "image_url":
                                  {"url": f"data:image/png;base64,{b64}"}},
                                 {"type": "text", "text": L["t6"]}]}],
                             800, out_dir)
                P(f"  {r['wall_sec']}s | {r['tok_per_sec']} tok/s"); results.append(r)
            except urllib.error.HTTPError as e:
                P(f"  多模态调用失败: HTTP {e.code} {e.read().decode(errors='replace')[:150]}")

    # T7 创造力（微小说 + 创意命名，人工评分）
    if want("t7"):
        P("[T7a] 创造力·微小说 ...")
        r = run_test("t7a_microfiction", cfg,
                     [{"role": "user", "content": L["t7a"]}], 1200, out_dir)
        P(f"  {r['wall_sec']}s | {r['tok_per_sec']} tok/s"); results.append(r)
        P("[T7b] 创造力·创意命名 ...")
        r = run_test("t7b_naming", cfg,
                     [{"role": "user", "content": L["t7b"]}], 800, out_dir)
        P(f"  {r['wall_sec']}s | {r['tok_per_sec']} tok/s"); results.append(r)

    summary = {"label": label, "endpoint": f"{cfg['host']}:{cfg['port']}",
               "extra": extra, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
               "results": results}
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    P(f"\n结果已保存 → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
