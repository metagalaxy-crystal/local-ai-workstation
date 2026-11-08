#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动 llama-server 运行注册表里的任意文本 / 多模态模型（可控制全部参数）。

用法示例：
    python start_server.py --list                     # 列出可用模型 key
    python start_server.py nanbeige                   # 按注册表推荐参数启动
    python start_server.py deepseek-r1 --think on --think-budget 2048
    python start_server.py qwen36 --think off --ctx 8192 --n-cpu-moe 40
    python start_server.py minicpmv --kv-type q8_0 --dry-run   # 只打印命令不启动

参数覆盖优先级：命令行 > models.json 里的推荐值。
启动后可用 chat.py / vlm_test.py 发提示词（OpenAI 兼容接口）。
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "models.json"


def load_registry() -> dict:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def strip_flag(args: list[str], *flags: str) -> list[str]:
    """从参数表里删掉指定开关（含其值），用于命令行覆盖注册表默认值。"""
    out, i = [], 0
    while i < len(args):
        tok = args[i]
        if tok in flags:                      # -c 4096  /  --threads 6
            i += 2
            continue
        if any(tok.startswith(f + "=") for f in flags):
            i += 1
            continue
        out.append(tok)
        i += 1
    return out


def build_command(model: dict, opt: argparse.Namespace) -> tuple[list[str], list[str]]:
    """返回 (命令, 警告列表)。"""
    warns: list[str] = []
    cmd = [str(config.LLAMA_SERVER), "-m", str(config.model_path(model["gguf"]))]
    cmd += list(model.get("server_args", []))
    if model.get("mmproj"):
        cmd += ["-mm", str(config.model_path(model["mmproj"]))]

    # ---- 命令行覆盖 ----
    if opt.ctx is not None:
        cmd = strip_flag(cmd, "-c", "--ctx-size") + ["-c", str(opt.ctx)]
    if opt.ngl is not None:
        cmd = strip_flag(cmd, "-ngl", "--n-gpu-layers") + ["-ngl", str(opt.ngl)]
    if opt.threads is not None:
        cmd = strip_flag(cmd, "-t", "--threads") + ["-t", str(opt.threads)]
    if opt.kv_type:
        cmd = strip_flag(cmd, "-ctk", "-ctv", "--cache-type-k", "--cache-type-v")
        cmd += ["-ctk", opt.kv_type, "-ctv", opt.kv_type]
    if opt.n_cpu_moe is not None:
        cmd = strip_flag(cmd, "-ncmoe", "--n-cpu-moe") + ["--n-cpu-moe", str(opt.n_cpu_moe)]
    if opt.think:
        cmd = strip_flag(cmd, "-rea", "--reasoning") + ["-rea", opt.think]
    if opt.think_effort:
        cmd = strip_flag(cmd, "--reasoning-effort") + ["--reasoning-effort", opt.think_effort]
    if opt.think_budget is not None:
        cmd = strip_flag(cmd, "--reasoning-budget") + ["--reasoning-budget", str(opt.think_budget)]
    if opt.think_format:
        cmd = strip_flag(cmd, "--reasoning-format") + ["--reasoning-format", opt.think_format]

    cmd += ["--host", opt.host, "--port", str(opt.port)]
    if opt.alias:
        cmd = strip_flag(cmd, "--alias") + ["--alias", opt.alias]
    if opt.no_jinja:
        cmd = strip_flag(cmd, "--jinja", "--no-jinja") + ["--no-jinja"]
    for extra in opt.extra or []:
        cmd += shlex.split(extra)

    # ---- 存在性检查 ----
    if not config.LLAMA_SERVER.exists():
        warns.append(f"找不到 llama-server：{config.LLAMA_SERVER}（用 LLAMA_SERVER 环境变量指定路径）")
    for rel, label in ((model["gguf"], "主模型"), (model.get("mmproj"), "投影文件")):
        if rel and not config.model_path(rel).exists():
            warns.append(f"{label}不存在：{config.model_path(rel)}")
    return cmd, warns


def main() -> int:
    reg = load_registry()
    ap = argparse.ArgumentParser(description="llama-server 启动器（全参数可覆盖）")
    ap.add_argument("model", nargs="?", help=f"模型 key：{', '.join(reg)}")
    ap.add_argument("--list", action="store_true", help="列出注册表里的模型")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--alias", help="服务对外模型名（/v1/models 里显示）")
    ap.add_argument("--ctx", type=int, help="上下文长度 -c")
    ap.add_argument("--ngl", type=int, help="卸载到 GPU 的层数 -ngl")
    ap.add_argument("--threads", type=int, help="CPU 线程数 -t")
    ap.add_argument("--kv-type", help="KV cache 量化类型，如 q8_0 / q4_0（同时设 -ctk/-ctv）")
    ap.add_argument("--n-cpu-moe", type=int, dest="n_cpu_moe",
                    help="MoE 专家权重留在内存的层数（35B MoE 显存不够时用）")
    ap.add_argument("--think", choices=["on", "off", "auto"], help="思考模式开关 -rea")
    ap.add_argument("--think-effort", dest="think_effort", help="思考强度 default/low/medium/high")
    ap.add_argument("--think-budget", type=int, dest="think_budget",
                    help="思考 token 预算，-1 不限、0 立即结束")
    ap.add_argument("--think-format", dest="think_format", help="思考输出格式，如 deepseek")
    ap.add_argument("--no-jinja", action="store_true", help="禁用 jinja 模板引擎")
    ap.add_argument("--extra", action="append", help="追加任意原生参数，可多次：--extra \"--no-webui\"")
    ap.add_argument("--dry-run", action="store_true", help="只打印命令，不启动")
    opt = ap.parse_args()

    if opt.list or not opt.model:
        print("可用模型（key / 名称 / 擅长）")
        print("-" * 78)
        for key, m in reg.items():
            tag = {"支持": "思考", "可选": "思考?", "none": "非思考"}[m.get("thinking", "none")]
            mp = " +mmproj" if m.get("mmproj") else ""
            print(f"{key:12s} {m['name']:28s} [{tag}, {config.human_size(config.model_path(m['gguf']))}{mp}]")
            print(f"{'':12s} 擅长：{m['task']}")
        return 0

    model = reg.get(opt.model)
    if not model:
        print(f"未知模型 key：{opt.model}；用 --list 查看", file=sys.stderr)
        return 1

    cmd, warns = build_command(model, opt)
    print(f"# 模型：{model['name']}（{model['task']}）")
    print(f"# 思考模式：{model.get('thinking', 'none')}")
    for w in warns:
        print(f"# 警告：{w}", file=sys.stderr)
    print("# 命令：\n" + " ".join(shlex.quote(c) for c in cmd), flush=True)

    if opt.dry_run:
        return 0
    if warns and not config.LLAMA_SERVER.exists():
        return 1

    print(f"# 服务地址：http://127.0.0.1:{opt.port}（OpenAI 兼容：/v1/chat/completions）", flush=True)
    try:
        return subprocess.call(cmd, cwd=str(config.LLAMA_SERVER.parent))
    except KeyboardInterrupt:
        print("\n# 已停止")
        return 0


if __name__ == "__main__":
    sys.exit(main())
