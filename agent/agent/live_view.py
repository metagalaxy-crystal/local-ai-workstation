# -*- coding: utf-8 -*-
"""浏览器实时画面：通过 CDP screencast 读取 Playwright 页面帧。

Playwright 的同步 API 只能在创建它的线程里用，WebUI 又在另一个线程，所以这里不碰
Playwright 对象，而是让 Chromium 额外开一个调试端口（--remote-debugging-port），
用 WebSocket 直接订阅 ``Page.screencastFrame``：

- 低开销：JPEG 质量 55、最长边 960px、everyNthFrame=2（只发变化帧）
- 浏览器没开/端口不通时 ``available()`` 为 False，前端自动退回 2 秒截图轮询

对外只有三个函数：``configure`` / ``available`` / ``latest`` / ``ensure``。
"""
from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
import urllib.request

_frame: bytes = b""
_stamp: float = 0.0
_lock = threading.Lock()

_port: int = 9223
_started = False
_stop = threading.Event()
_check_at: float = 0.0
_check_ok: bool = False


def configure(cfg) -> None:
    global _port
    try:
        _port = int(cfg.get("tools.browser.live_port", 9223))
    except Exception:
        _port = 9223


def latest() -> tuple[bytes, float]:
    with _lock:
        return _frame, _stamp


def available() -> bool:
    """1 秒缓存，避免前端每次请求都去问 CDP。"""
    global _check_at, _check_ok
    if time.time() - _check_at < 1.0:
        return _check_ok
    _check_at = time.time()
    _check_ok = _page_target() is not None
    return _check_ok


def _page_target() -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{_port}/json/list", timeout=0.8) as r:
            targets = json.load(r)
    except Exception:
        return None
    for t in targets:
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            return t
    return None


def ensure() -> None:
    """懒启动后台帧订阅线程（进程内只起一次）。"""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True).start()


def _loop() -> None:
    while not _stop.is_set():
        target = _page_target()
        if not target:
            time.sleep(1.0)
            continue
        try:
            asyncio.run(_screencast(target["webSocketDebuggerUrl"]))
        except Exception:
            time.sleep(1.0)  # 浏览器关掉/页面跳转后重连


async def _screencast(ws_url: str) -> None:
    """订阅变化帧 + 每秒补一张截图（headless 静止时 screencast 不出帧）。"""
    import websockets

    global _frame, _stamp
    async with websockets.connect(ws_url, max_size=16 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
        await ws.send(json.dumps({"id": 2, "method": "Page.startScreencast", "params": {
            "format": "jpeg", "quality": 55, "maxWidth": 960, "maxHeight": 540,
            "everyNthFrame": 2}}))
        cap_id, ack_id = 1000, 50000
        next_cap = time.monotonic()
        while not _stop.is_set():
            if time.monotonic() >= next_cap:
                cap_id += 1
                await ws.send(json.dumps({"id": cap_id, "method": "Page.captureScreenshot",
                                          "params": {"format": "jpeg", "quality": 55}}))
                next_cap = time.monotonic() + 1.0
            try:
                raw = await asyncio.wait_for(
                    ws.recv(), timeout=max(0.05, next_cap - time.monotonic()))
            except asyncio.TimeoutError:
                continue
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if msg.get("method") == "Page.screencastFrame":
                p = msg.get("params") or {}
                try:
                    data = base64.b64decode(p.get("data") or "")
                    session = int(p.get("sessionId") or 1)
                except Exception:
                    continue
                with _lock:
                    _frame = data
                    _stamp = time.time()
                ack_id += 1
                await ws.send(json.dumps({"id": ack_id, "method": "Page.screencastFrameAck",
                                          "params": {"sessionId": session}}))
            elif isinstance(msg.get("id"), int) and msg["id"] >= 1000:
                data = (msg.get("result") or {}).get("data")
                if data:
                    try:
                        blob = base64.b64decode(data)
                    except Exception:
                        continue
                    with _lock:
                        _frame = blob
                        _stamp = time.time()
