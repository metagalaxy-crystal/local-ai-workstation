#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""样例公共配置：统一解析路径，便于整体迁移到另一台电脑。

所有路径都可用环境变量覆盖，默认值对应当前机器的布局：

    MODEL_ROOT   d:\\models\\models       模型根目录（gguf / safetensors 都在这）
    LLAMA_DIR    d:\\models\\llama.cpp    llama.cpp 源码与编译产物目录
    COMFY_DIR    d:\\models\\ComfyUI      ComfyUI 目录
    OUTPUT_ROOT  d:\\models\\output       所有样例产物的输出根目录
    COMFY_HOST   http://127.0.0.1:8188    ComfyUI 服务地址
    SAMPLE_PY    d:\\models\\.venv\\Scripts\\python.exe  独立模型（TTS/质检/ASR）用解释器

迁移步骤：目标机器上保持同样的目录布局，只需按需设置上面 4 个路径类环境变量；
若布局完全一致，则一行都不用改。
"""
from __future__ import annotations

import os
from pathlib import Path


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default))


MODELS_ROOT = _env_path("MODEL_ROOT", r"d:\models\models")
LLAMA_DIR = _env_path("LLAMA_DIR", r"d:\models\llama.cpp")
COMFY_DIR = _env_path("COMFY_DIR", r"d:\models\ComfyUI")
OUTPUT_ROOT = _env_path("OUTPUT_ROOT", r"d:\models\output")
COMFY_HOST = os.environ.get("COMFY_HOST", "http://127.0.0.1:8188")

# llama-server 可执行文件（本机为 MSVC Release 构建；其它平台可指向 llama-server / llama-server.exe）
LLAMA_SERVER = Path(os.environ.get(
    "LLAMA_SERVER",
    str(LLAMA_DIR / "build" / "bin" / "Release" / "llama-server.exe")))

# 需要 transformers / funasr 等重依赖的样例用这个解释器
SAMPLE_PYTHON = os.environ.get("SAMPLE_PY", r"d:\models\.venv\Scripts\python.exe")

# ComfyUI 环境自带的 python（若用 uv 管理则可用 "uv run python"）
COMFY_PYTHON = os.environ.get("COMFY_PY", "python")


def model_path(relative: str) -> Path:
    """把注册表里的相对路径（允许正斜杠）解析成绝对路径。"""
    return MODELS_ROOT / relative.replace("\\", "/")


def out_dir(*parts: str) -> Path:
    """输出目录 = OUTPUT_ROOT/<组>/<案例>，不存在则自动创建。"""
    d = OUTPUT_ROOT.joinpath(*[p for p in parts if p])
    d.mkdir(parents=True, exist_ok=True)
    return d


def human_size(path: Path) -> str:
    """给日志用的可读体积。"""
    try:
        n = path.stat().st_size
    except OSError:
        return "缺失"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"
