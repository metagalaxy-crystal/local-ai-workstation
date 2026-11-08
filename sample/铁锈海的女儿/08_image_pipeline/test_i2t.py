# -*- coding: utf-8 -*-
"""图生文测试：图片 base64 → llama-server OpenAI 兼容 API → VLM 回答"""
import argparse, base64, json, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
RESULT_DIR = HERE / "results"
RESULT_DIR.mkdir(exist_ok=True)


def ask_vlm(host, image_path, question, model="vlm", max_tokens=512, timeout=300):
    ext = Path(image_path).suffix.lstrip(".").lower()
    if ext == "jpg":
        ext = "jpeg"
    b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64}"}},
                {"type": "text", "text": question},
            ],
        }],
    }
    t0 = time.time()
    req = urllib.request.Request(f"http://{host}/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read())
    elapsed = time.time() - t0
    usage = resp.get("usage", {})
    answer = resp["choices"][0]["message"]["content"]
    return {"question": question, "image": str(image_path), "answer": answer,
            "elapsed_sec": round(elapsed, 2),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "tok_per_sec": round(usage.get("completion_tokens", 0) / elapsed, 2) if elapsed else None}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1:8081")
    ap.add_argument("--image", required=True)
    ap.add_argument("--question", default="请详细描述这张图片的内容。")
    ap.add_argument("--save", default=None, help="结果 JSON 保存路径")
    args = ap.parse_args()

    result = ask_vlm(args.host, args.image, args.question)
    print(f"耗时 {result['elapsed_sec']}s | 生成 {result['completion_tokens']} tok | "
          f"{result['tok_per_sec']} tok/s")
    print("-" * 40)
    print(result["answer"])
    if args.save:
        Path(args.save).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
