# -*- coding: utf-8 -*-
"""本地模型服务编排：按任务需要启动 / 停止 LLM 与 ComfyUI。

背景：工作站显存只有 8GB，ComfyUI（约 8GB）、语音脚本、大对话模型三者互斥，
所以重型多模型流水线必须由编排层在节点间切换服务，而不是全部常驻。

- 模型注册表：scripts/llama_cpp/models.json（key → gguf/启动参数/用途）
- 启动命令统一走 `uv run python scripts/...`（与手工启动方式一致）
- 就绪探测：LLM 轮询 /v1/models 直到 alias 出现；ComfyUI 轮询 /system_stats
- 停止：优先 terminate 自己启动的进程；不是本进程树启动的按端口找 PID 后 taskkill
- 全程写日志 output/agent/services.log，UI 可回看切换过程
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import psutil

from .config import Config

LLM_PORT = 8080
COMFY_PORT = 8188
EMBED_PORT = 8081
RERANK_PORT = 8082


def _http_json(url: str, timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def _port_alive(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def kill_port(port: int) -> list[int]:
    """结束监听指定端口的进程树，返回被杀掉的 PID 列表。"""
    killed: list[int] = []
    try:
        conns = psutil.net_connections(kind="inet")
    except Exception:
        return killed
    pids = {c.pid for c in conns
            if c.laddr and c.laddr.port == port and c.status == "LISTEN" and c.pid}
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=15)
        killed.append(pid)
    return killed


class ServiceManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        scripts_dir = Path(cfg.get("tools.scripts_dir", "d:/models/scripts"))
        self.root = scripts_dir.parent  # d:/models
        self.registry_path = scripts_dir / "llama_cpp" / "models.json"
        self.log_path = cfg.path("paths.output_root") / "services.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._procs: dict[str, subprocess.Popen] = {}

    # ------------------------------------------------------------------ 注册表
    def models(self) -> list[dict]:
        """注册表中的模型列表，附带当前是否在线。"""
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        active = self.llm_status().get("model")
        out = []
        for key, item in data.items():
            if key.startswith("_") or item.get("role") in ("embed", "rerank", "router"):
                continue  # embed/rerank/router 是后端服务，不属于对话模型切换列表
            out.append({
                "key": key,
                "name": item.get("name", key),
                "task": item.get("task", ""),
                "desc": item.get("desc", ""),
                "active": key == active,
            })
        return out

    # ------------------------------------------------------------------ 状态
    def llm_status(self) -> dict:
        data = _http_json(f"http://127.0.0.1:{LLM_PORT}/v1/models")
        if not data:
            return {"online": False, "model": None, "port": LLM_PORT}
        ids = [m.get("id", "") for m in data.get("data", [])]
        return {"online": True, "model": ids[0] if ids else None,
                "models": ids, "port": LLM_PORT}

    def comfy_status(self) -> dict:
        data = _http_json(f"http://127.0.0.1:{COMFY_PORT}/system_stats")
        return {"online": bool(data), "port": COMFY_PORT}

    def status(self) -> dict:
        """四路探测并发执行，总耗时 ≈ 最慢的一路（而不是串行相加）。"""
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            f_llm = pool.submit(self.llm_status)
            f_comfy = pool.submit(self.comfy_status)
            f_embed = pool.submit(_port_alive, EMBED_PORT)
            f_rerank = pool.submit(_port_alive, RERANK_PORT)
            return {
                "llm": f_llm.result(),
                "comfy": f_comfy.result(),
                "embed": {"online": f_embed.result(), "port": EMBED_PORT},
                "rerank": {"online": f_rerank.result(), "port": RERANK_PORT},
            }

    # ------------------------------------------------------------------ 资源预算
    def gpu_memory(self) -> dict:
        """显存占用：psutil 看不到显存，必须走 nvidia-smi（结果缓存 3 秒）。"""
        now = time.time()
        cache = getattr(self, "_gpu_cache", None)
        if cache and now - getattr(self, "_gpu_ts", 0.0) < 3:
            return cache
        smi = shutil.which("nvidia-smi") or (
            "C:/Windows/System32/nvidia-smi.exe"
            if Path("C:/Windows/System32/nvidia-smi.exe").exists() else None)
        data: dict = {"known": False}
        if smi:
            try:
                out = subprocess.run(
                    [smi, "--query-gpu=memory.total,memory.used,memory.free",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10)
                fields = (out.stdout or "").strip().splitlines()[0].split(",")
                total, used, free = (int(float(v)) for v in fields[:3])
                data = {"known": True, "total_mb": total, "used_mb": used, "free_mb": free}
            except Exception:
                data = {"known": False}
        self._gpu_cache, self._gpu_ts = data, now
        return data

    def ram_status(self) -> dict:
        vm = psutil.virtual_memory()
        return {"known": True, "total_mb": int(vm.total / 1048576),
                "used_mb": int(vm.used / 1048576),
                "free_mb": int(vm.available / 1048576)}

    def check_budget(self, vram_mb: int = 0, ram_mb: int = 0) -> dict:
        """重型服务启动前的准入检查；指标读不到时放行，不能因探测失败卡死主流程。"""
        self._gpu_ts = 0.0  # 刚停过服务，必须现读显存，不能用 3 秒缓存里的旧值
        gpu, ram = self.gpu_memory(), self.ram_status()
        vram_free = gpu.get("free_mb")
        ram_free = ram.get("free_mb")
        vram_ok = (not gpu.get("known")) or (vram_free or 0) >= vram_mb
        ram_ok = (not ram.get("known")) or (ram_free or 0) >= ram_mb
        msg = ""
        if not vram_ok:
            msg = f"显存不足：需 {vram_mb}MB，当前空闲 {vram_free}MB（共 {gpu.get('total_mb')}MB）"
        if not ram_ok:
            msg = (msg + "；" if msg else "") + \
                f"内存不足：需 {ram_mb}MB，当前可用 {ram_free}MB"
        return {"ok": vram_ok and ram_ok, "checked": bool(gpu.get("known") or ram.get("known")),
                "need_vram_mb": vram_mb, "vram_free_mb": vram_free,
                "need_ram_mb": ram_mb, "ram_free_mb": ram_free, "msg": msg}

    # ------------------------------------------------------------------ LLM
    def ensure_llm(self, key: str, timeout: float = 600) -> dict:
        """确保指定模型在 :8080 上服务；当前跑的是别的模型就先换掉。"""
        with self._lock:
            cur = self.llm_status()
            if cur["online"] and cur.get("model") == key:
                return {"ok": True, "msg": f"{key} 已在线"}
            if cur["online"]:
                self._log(f"切换模型：{cur.get('model')} → {key}")
                self._stop_llm_locked()
            cmd = self._uv_cmd(f"scripts/llama_cpp/start_server.py {key} --alias {key}")
            if not cmd:
                return {"ok": False, "msg": "找不到 uv，无法启动模型服务"}
            self._log(f"启动模型 {key}: {' '.join(cmd)}")
            self._spawn("llm", cmd)
            ok, msg = self._wait_llm(key, timeout)
            self._log(f"{key} 就绪" if ok else f"{key} 启动失败: {msg}")
            return {"ok": ok, "msg": msg}

    def stop_llm(self) -> dict:
        with self._lock:
            return self._stop_llm_locked()

    def _stop_llm_locked(self) -> dict:
        killed = self._stop_proc("llm")
        if _port_alive(LLM_PORT):  # 端口没监听就不必做 psutil 全表扫描（文本步骤会频繁调用）
            killed += kill_port(LLM_PORT)
        if killed:
            self._log(f"停止 LLM（pid {killed}），等待端口释放")
            for _ in range(30):
                if not _port_alive(LLM_PORT):
                    break
                time.sleep(1)
        return {"ok": True, "msg": f"已停止（pid {killed}）" if killed else "本就不在运行"}

    def _wait_llm(self, key: str, timeout: float) -> tuple[bool, str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.llm_status()
            if st["online"] and st.get("model") == key:
                return True, f"{key} 已就绪"
            proc = self._procs.get("llm")
            if proc and proc.poll() is not None:
                return False, f"进程提前退出（code={proc.returncode}），详见 services.log"
            time.sleep(2)
        return False, f"等待就绪超时（{int(timeout)}s）"

    # ------------------------------------------------------------------ ComfyUI
    def ensure_comfy(self, timeout: float = 300) -> dict:
        with self._lock:
            if self.comfy_status()["online"]:
                return {"ok": True, "msg": "ComfyUI 已在线"}
            cmd = self._uv_cmd("scripts/comfyui/start_comfyui.py")
            if not cmd:
                return {"ok": False, "msg": "找不到 uv，无法启动 ComfyUI"}
            self._log(f"启动 ComfyUI: {' '.join(cmd)}")
            self._spawn("comfy", cmd)
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self.comfy_status()["online"]:
                    self._log("ComfyUI 就绪")
                    return {"ok": True, "msg": "ComfyUI 已就绪"}
                proc = self._procs.get("comfy")
                if proc and proc.poll() is not None:
                    return {"ok": False, "msg": f"ComfyUI 进程提前退出（code={proc.returncode}）"}
                time.sleep(2)
            return {"ok": False, "msg": f"ComfyUI 启动超时（{int(timeout)}s）"}

    def stop_comfy(self) -> dict:
        with self._lock:
            killed = self._stop_proc("comfy")
            if _port_alive(COMFY_PORT):
                killed += kill_port(COMFY_PORT)
            if killed:
                self._log(f"停止 ComfyUI（pid {killed}）")
            return {"ok": True, "msg": f"已停止（pid {killed}）" if killed else "本就不在运行"}

    # ------------------------------------------------------------------ Embed / Rerank（CPU 小服务）
    def ensure_embed(self, timeout: float = 120) -> dict:
        return self._ensure_aux("embed", EMBED_PORT, timeout)

    def stop_embed(self) -> dict:
        return self._stop_aux("embed", EMBED_PORT)

    def ensure_rerank(self, timeout: float = 120) -> dict:
        return self._ensure_aux("rerank", RERANK_PORT, timeout)

    def stop_rerank(self) -> dict:
        return self._stop_aux("rerank", RERANK_PORT)

    def _ensure_aux(self, key: str, port: int, timeout: float) -> dict:
        with self._lock:
            if _port_alive(port):
                return {"ok": True, "msg": f"{key} 已在线"}
            cmd = self._uv_cmd(
                f"scripts/llama_cpp/start_server.py {key} --alias {key} --port {port}")
            if not cmd:
                return {"ok": False, "msg": "找不到 uv，无法启动"}
            self._log(f"启动 {key}: {' '.join(cmd)}")
            self._spawn(key, cmd)
            deadline = time.time() + timeout
            while time.time() < deadline:
                if _port_alive(port):
                    self._log(f"{key} 就绪（:{port}）")
                    return {"ok": True, "msg": f"{key} 已就绪"}
                proc = self._procs.get(key)
                if proc and proc.poll() is not None:
                    return {"ok": False,
                            "msg": f"{key} 进程提前退出（code={proc.returncode}），详见 services.log"}
                time.sleep(1)
            return {"ok": False, "msg": f"{key} 启动超时（{int(timeout)}s）"}

    def _stop_aux(self, key: str, port: int) -> dict:
        with self._lock:
            killed = self._stop_proc(key) + kill_port(port)
            if killed:
                self._log(f"停止 {key}（pid {killed}）")
            return {"ok": True, "msg": f"已停止（pid {killed}）" if killed else "本就不在运行"}

    # ------------------------------------------------------------------ 内部
    def _uv_cmd(self, script_args: str) -> list[str] | None:
        uv = shutil.which("uv") or shutil.which("uv.exe")
        if not uv:
            return None
        return [uv, "run", "python"] + script_args.split()

    def _spawn(self, name: str, cmd: list[str]) -> None:
        log_fh = self.log_path.open("a", encoding="utf-8")
        proc = subprocess.Popen(
            cmd, cwd=str(self.root),
            stdout=log_fh, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        self._procs[name] = proc

    def _stop_proc(self, name: str) -> list[int]:
        proc = self._procs.pop(name, None)
        if not proc or proc.poll() is not None:
            return []
        pid = proc.pid
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=15)
        return [pid]

    def _log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
        try:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass

    def log_tail(self, n: int = 50) -> list[str]:
        if not self.log_path.exists():
            return []
        try:
            lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        return lines[-n:]

    def close(self) -> None:
        """不杀服务进程（服务独立于 UI 生命周期），仅清理句柄引用。"""
        self._procs.clear()
