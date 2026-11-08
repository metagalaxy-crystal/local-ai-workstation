#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""编译后自检：验证 llama-cli 在 Blackwell sm_120 上能跑，无 'no kernel image'。

用法: uv run python scripts/llama_cpp/smoke_test.py
"""
import subprocess
import sys
from pathlib import Path

LLAMA_BIN = Path(r"D:\models\llama.cpp\build\bin\Release")
LLAMA_CLI = LLAMA_BIN / "llama-cli.exe"
LLAMA_SERVER = LLAMA_BIN / "llama-server.exe"

# 自检优先用已存在的 GGUF（models\text\ 里现成的）
TEST_MODELS = [
    r"D:\models\models\text\Qwen3.6-35B-A3B\Qwen3.6-35B-A3B-Q4_K_M.gguf",
    r"D:\models\models\text\LFM2-24B-A2B\LFM2-24B-A2B-Q4_K_M.gguf",
    r"D:\models\models\text\DeepSeek-R1-0528-Qwen3-8B\DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf",
]


def run(cmd: list[str], timeout: int = 300) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def main() -> int:
    print("=== llama.cpp 构建自检 ===\n", flush=True)

    if not LLAMA_CLI.exists():
        print(f"[FAIL] 未找到 {LLAMA_CLI}", file=sys.stderr)
        print("请先完成 cmake --build。", file=sys.stderr)
        return 1

    # 1) 版本
    code, out = run([str(LLAMA_CLI), "--version"], timeout=20)
    print("版本: " + out.strip())

    # 2) GPU / 驱动
    try:
        smi = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15)
        print("GPU : " + smi.stdout.strip())
    except Exception as e:
        print(f"nvidia-smi 不可用: {e}")

    # 3) 关键 flag 支持情况（--cpu-moe 是否可用）
    code, out = run([str(LLAMA_SERVER), "--help"], timeout=30)
    has_cpu_moe = "cpu-moe" in out
    print(f"\nllama-server --cpu-moe 支持: {'是' if has_cpu_moe else '否（serve.py 将回退 -ot experts.*=cpu）'}")

    # 4) 快速 CUDA 内核自检：用 llama-bench --list-devices（秒级，无需加载大模型）
    #    初始化 CUDA 时会打印 compute capability；若 sm_120 内核缺失会报 no kernel image
    bench = LLAMA_BIN / "llama-bench.exe"
    if bench.exists():
        print("\n--- CUDA 内核自检 (llama-bench --list-devices) ---", flush=True)
        code, out = run([str(bench), "--list-devices"], timeout=60)
        print(out.strip())
        low = out.lower()
        if "no kernel image" in low:
            print("\n[FAIL] 检测到 'no kernel image' —— sm_120 内核未正确生成。", file=sys.stderr)
            return 2
        if "compute capability" in low and "12.0" in out:
            print("\n[PASS] CUDA 后端初始化成功，compute capability 12.0 (sm_120) 内核可用。")
            return 0
        if code != 0:
            print(f"\n[WARN] llama-bench 退出码非 0: {code}", file=sys.stderr)
            return 3
        print("\n[WARN] 未在输出中确认 compute capability 12.0，请人工核对上面输出。",
              file=sys.stderr)
        return 3

    # 回退：无 llama-bench 时，用现成模型跑 8 token（-ngl 1 触发 CUDA，大模型较慢）
    model = next((m for m in TEST_MODELS if Path(m).exists()), None)
    if not model:
        print("\n[SKIP] 无 llama-bench 且无可用 GGUF，跳过推理自检。", file=sys.stderr)
        return 0
    print(f"\n用 {Path(model).name} 跑 8 token (-ngl 1, 大模型较慢)...")
    cmd = [str(LLAMA_CLI), "-m", model, "-p", "你好", "-n", "8", "-ngl", "1"]
    print("  " + " ".join(cmd), flush=True)
    code, out = run(cmd, timeout=600)
    print(out[-1500:])
    if "no kernel image" in out.lower():
        print("\n[FAIL] 检测到 'no kernel image' —— sm_120 内核未正确生成。", file=sys.stderr)
        return 2
    if code != 0:
        print(f"\n[WARN] 推理退出码非 0: {code}", file=sys.stderr)
        return 3
    print("\n[PASS] 自检通过，CUDA 内核在 sm_120 上可用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
