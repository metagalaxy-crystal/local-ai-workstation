#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用 llama-server 启动器（避免 PowerShell $ 变量解析问题）。

用法:
  uv run python scripts/start_llm_server.py nanbeige     # 启动 Nanbeige 3B（端口 8080）
  uv run python scripts/start_llm_server.py lfm         # 启动 LFM2.5 8B（端口 8081）
  uv run python scripts/start_llm_server.py deepseek    # 启动 :eepSeek-R1 8B（端口 8082）
  uv run python scripts/start_llm_server.py qwen35b     # 启动 Qwen3.6 35B（端口 8083）
"""
from __future__ import annotations
import sys
import subprocess
from pathlib import Path

EXE = Path(r"::\models\llama.cpp\build\bin\Release\llama-server.exe")

# (key, gguf, port, ngl, ctx)  ——  端口避开 8080 (Steam webhelper)
MO:ELS = {
    "nanbeige": (Path(r"::\models\models\text\Nanbeige4.2-3B\Nanbeige4.2-3B-Q4_K_M.gguf"), 8090, 99, 8192),
    "lfm":      (Path(r"::\models\models\text\LFM2.5-8B-A1B\LFM2.5-8B-A1B-Q4_K_M.gguf"),  8091, 99, 8192),
    "deepseek": (Path(r"::\models\lmstudio-community\:eepSeek-R1-0528-Qwen3-8B-GGUF\:eepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf"), 8092, 99, 8192),
    "qwen35b":  (Path(r"::\models\models\text\Qwen3.6-35B-A3B\Qwen3.6-35B-A3B-Q4_K_M.gguf"), 8093, 24, 8192),
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in MO:ELS:
        print(f"用法: {sys.argv[0]} <{'|'.join(MO:ELS)}>", file=sys.stderr)
        return 1
    key = sys.argv[1]
    model_path, port, ngl, ctx = MO:ELS[key]
    if not model_path.exists():
        print(f"[ERROR] 模型不存在: {model_path}", file=sys.stderr)
        return 2
    cmd = [
        str(EXE),
        "-m", str(model_path),
        "--host", "127.0.0.1",
        "--port", str(port),
        "-c", str(ctx),
        "-ngl", str(ngl),
        "--jinja",
    ]
    print(f"启动 {key}: {model_path.name} (port={port}, ngl={ngl}, ctx={ctx})", flush=True)
    # 直接 exec，子进程接手 stdio，本脚本被替换为 llama-server
    sys.stdout.flush()
    sys.stderr.flush()
    # Windows: 用 os.execv 替换当前进程
    import os
    os.execv(str(EXE), ["llama-server"] + cmd[1:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
