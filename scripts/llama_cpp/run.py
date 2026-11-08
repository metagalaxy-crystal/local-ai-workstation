#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llama_cpp 样例统一入口（便于 .bat / shell 一行转调）。

    python run.py list
    python run.py start nanbeige
    python run.py chat -p "你好"
    python run.py vlm --image D:\\pic.png
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUBS = {"list": "start_server.py", "start": "start_server.py",
        "chat": "chat.py", "vlm": "vlm_test.py"}


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] not in SUBS:
        print(__doc__)
        return 1
    script = SUBS[argv[0]]
    rest = argv[1:]
    if argv[0] == "list":
        rest = ["--list"]
    return subprocess.call([sys.executable, str(HERE / script)] + rest)


if __name__ == "__main__":
    sys.exit(main())
