# -*- coding: utf-8 -*-
"""端到端联动：Z-Image 生图 → 启动 VLM → 图生文分析 → 停止服务 → 保存结果
用法:
  python run_e2e.py                          # 默认 minicpm，全量显卡加载
  python run_e2e.py --vlm qwenvl --ngl 16    # 与 ComfyUI 共存时分层卸载
"""
import argparse, json, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from test_t2i import generate_image
from test_i2t import ask_vlm

RESULT_DIR = HERE / "results"
RESULT_DIR.mkdir(exist_ok=True)

DEFAULT_PROMPT = ("蒸汽朋克风格：一位十七岁少女站在锈迹斑斑的船头，海风吹动她的短发，"
                  "背景是铁锈色的海洋与巨型齿轮城市天际线，黄昏橙光，电影感构图，细节丰富")
EVAL_QUESTION = ("这是一张 AI 生成的故事分镜参考图。请回答：1) 画面主体是什么？"
                 "2) 画风与配色是否符合蒸汽朋克风格？3) 作为视频分镜，构图上有何改进建议？")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host-comfy", default="127.0.0.1:8188")
    ap.add_argument("--host-vlm", default="127.0.0.1:8081")
    ap.add_argument("--vlm", choices=["minicpm", "qwenvl"], default="minicpm")
    ap.add_argument("--ngl", type=int, default=999, help="VLM 显卡层数，与 ComfyUI 共存时调低如 16")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--width", type=int, default=1088)
    ap.add_argument("--height", type=int, default=608)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    report = {"vlm": args.vlm, "ngl": args.ngl}

    print("=" * 50)
    print("[1/3] Z-Image 文生图")
    t2i = generate_image(host=args.host_comfy, prompt=args.prompt,
                         width=args.width, height=args.height, seed=args.seed,
                         prefix=f"e2e_{args.vlm}")
    report["t2i"] = t2i
    image_path = t2i["images"][0]

    print("=" * 50)
    print(f"[2/3] 启动 VLM 服务 ({args.vlm}, ngl={args.ngl})")
    subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File",
                    str(HERE / "vlm_server.ps1"), "-Action", "start",
                    "-Vlm", args.vlm, "-Ngl", str(args.ngl)], check=True)
    try:
        print(f"      VLM 图生文分析")
        t0 = time.time()
        i2t = ask_vlm(args.host_vlm, image_path, EVAL_QUESTION)
        report["i2t"] = i2t
        print(f"耗时 {i2t['elapsed_sec']}s | {i2t['tok_per_sec']} tok/s")
        print("-" * 50)
        print(i2t["answer"])
    finally:
        subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File",
                        str(HERE / "vlm_server.ps1"), "-Action", "stop"])

    dest = RESULT_DIR / f"e2e_{args.vlm}_{t2i['seed']}.json"
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 50)
    print(f"端到端报告: {dest}")


if __name__ == "__main__":
    main()
