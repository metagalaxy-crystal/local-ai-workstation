# -*- coding: utf-8 -*-
"""容错版批处理：每段跑完 POST /free 释放显存，挂了就重启 ComfyUI 并继续下一段。
"""
import json, os, sys, subprocess, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

HOST = "http://127.0.0.1:8188"
COMFY_PY = r"D:\models\.venv\Scripts\python.exe"
COMFY_MAIN = r"D:\models\ComfyUI\main.py"
COMFY_CWD = r"D:\models\ComfyUI"
JOBS = Path(__file__).parent / "jobs.json"
CLIPS = Path(__file__).parent.parent / "clips"


def comfy_up():
    import urllib.request
    try:
        urllib.request.urlopen(f"{HOST}/system_stats", timeout=3).read()
        return True
    except Exception:
        return False


def _kill_comfy_pids():
    """只杀命令行包含 ComfyUI\\main.py 的 python 进程，不杀自己。"""
    import sys as _sys
    my_pid = os.getpid()
    try:
        out = subprocess.check_output(
            ["wmic", "process", "where",
             "name='python.exe' and commandline like '%%ComfyUI%%main.py%%'",
             "get", "processid"],
            text=True, stderr=subprocess.DEVNULL)
        for line in out.strip().splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            for pid_str in line.split():
                try:
                    pid = int(pid_str)
                    if pid != my_pid:
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                       capture_output=True)
                except ValueError:
                    pass
    except Exception:
        pass
    # 也尝试杀占用 8188 端口的进程
    try:
        net = subprocess.check_output(["netstat", "-ano"], text=True)
        for line in net.splitlines():
            if ":8188" in line and "LISTENING" in line:
                parts = line.split()
                pid = int(parts[-1])
                if pid != my_pid:
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                   capture_output=True)
    except Exception:
        pass


def start_comfy():
    # 先 kill 残留 ComfyUI 进程（只杀自己的，不杀 batch_gen）
    _kill_comfy_pids()
    time.sleep(2)
    subprocess.Popen([COMFY_PY, COMFY_MAIN, "--listen", "0.0.0.0",
                      "--port", "8188", "--lowvram", "--cache-classic"],
                     cwd=COMFY_CWD, creationflags=subprocess.CREATE_MINIMIZED)
    for _ in range(60):
        time.sleep(2)
        if comfy_up():
            print("  ComfyUI ready")
            return True
    return False


def free_vram():
    import urllib.request
    try:
        data = b'{"unload_models":true,"free_memory":true}'
        urllib.request.urlopen(urllib.request.Request(
            f"{HOST}/free", data=data,
            headers={"Content-Type": "application/json"}, method="POST"),
            timeout=10).read()
    except Exception:
        pass


def run_one(job_id):
    cmd = [sys.executable, str(Path(__file__).parent / "gen_clips.py"),
           "--job", job_id, "--force"]
    for attempt in range(3):
        if not comfy_up():
            print(f"  ComfyUI down, restarting (attempt {attempt+1})...")
            if not start_comfy():
                continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               cwd=str(Path(__file__).parent), timeout=1500)
            if r.returncode == 0:
                return True
            print(f"  gen_clips failed rc={r.returncode}: {r.stderr[-300:]}")
        except subprocess.TimeoutExpired:
            print("  gen_clips timed out")
        time.sleep(5)
    return False


def main():
    raw = json.load(open(JOBS, encoding="utf-8-sig"))
    jobs = [v for v in raw.values() if v.get("enabled", True)]
    done = {p.stem for p in CLIPS.glob("*.mp4")}
    for j in jobs:
        mp4 = Path(CLIPS) / f"{j['id'].lower()}.mp4"
        if mp4.exists() and mp4.stat().st_size > 0:
            print(f"[skip] {j['id']} already done")
            continue
        if not comfy_up():
            print("ComfyUI not running, starting...")
            start_comfy()
        print(f"=== {j['id']} ===")
        run_one(j["id"])
        free_vram()
        time.sleep(3)
    print("All done.")


if __name__ == "__main__":
    main()
