# -*- coding: utf-8 -*-
"""MCP stdio 客户端：把外部 MCP server 的工具挂进本地注册表。

配置（configs/agent.json）：
    "mcp_servers": [
      {"name": "playwright", "command": "node",
       "args": [".../node_modules/@playwright/mcp/cli.js", "--browser", "msedge", "--headless"],
       "enabled": true, "persistent": true, "timeout": 120}
    ]

每个远端工具注册为 mcp_<server>_<tool>，schema 原样透传。

两种会话模式：
  persistent=true   常驻子进程 + 常驻会话（浏览器这类有状态的 server 必须用）
  默认              「每次调用起一个会话」的短连接，省去长连接状态管理
"""
from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import threading
from typing import Any

import anyio

from .config import Config
from .tools.registry import ToolRegistry


def _tool_specs(result: Any) -> list[dict[str, Any]]:
    """把 list_tools 结果转成注册表用的 spec；兼容新旧 mcp SDK 字段名。"""
    return [
        {"name": t.name,
         "description": t.description or "",
         # 旧版 inputSchema，新版 input_schema
         "schema": getattr(t, "inputSchema", None)
         or getattr(t, "input_schema", None)
         or {"type": "object", "properties": {}}}
        for t in result.tools
    ]


def _content_text(result: Any) -> str:
    parts = []
    for block in result.content:
        text = getattr(block, "text", None)
        parts.append(text if text is not None else str(block))
    return "\n".join(parts) or "（无输出）"


def _list_tools(command: str, args: list[str], env: dict[str, str] | None,
                cwd: str | None = None) -> list[dict[str, Any]]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def _run():
        params = StdioServerParameters(command=command, args=args, env=env, cwd=cwd)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return _tool_specs(await session.list_tools())
    return anyio.run(_run)


def _call_tool(command: str, args: list[str], env: dict[str, str] | None,
               tool: str, arguments: dict[str, Any], cwd: str | None = None) -> str:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def _run():
        params = StdioServerParameters(command=command, args=args, env=env, cwd=cwd)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return _content_text(await session.call_tool(tool, arguments))
    return anyio.run(_run)


class PersistentServer:
    """常驻 stdio 会话：子进程和页面状态跨工具调用保持（浏览器类 MCP 用）。"""

    def __init__(self, name: str, command: str, args: list[str],
                 env: dict[str, str] | None, cwd: str | None = None,
                 startup_timeout: float = 120) -> None:
        self.name = name
        self.command, self.args, self.env, self.cwd = command, args, env, cwd
        self.tools: list[dict[str, Any]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._ready = threading.Event()
        self._error = ""
        self._thread = threading.Thread(target=self._run, name=f"mcp-{name}", daemon=True)
        self._thread.start()
        if not self._ready.wait(startup_timeout):
            raise RuntimeError(f"MCP server {name} 启动超时（{startup_timeout:.0f}s）")
        if self._error:
            raise RuntimeError(self._error)

    # ---- 后台线程：一个长生命周期协程守住 stdio 会话 ----
    def _run(self) -> None:
        try:
            anyio.run(self._serve)
        except BaseException as exc:  # noqa: BLE001 - 启动失败要回传给主线程
            self._error = f"{type(exc).__name__}: {exc}"
        finally:
            self._ready.set()

    async def _serve(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        params = StdioServerParameters(command=self.command, args=self.args,
                                       env=self.env, cwd=self.cwd)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self.tools = _tool_specs(await session.list_tools())
                self._ready.set()
                while True:
                    tool, arguments, future = await self._queue.get()
                    if tool is None:  # 关闭信号
                        return
                    try:
                        result = await session.call_tool(tool, arguments)
                        future.set_result(_content_text(result))
                    except Exception as exc:  # noqa: BLE001 - 交给调用方
                        future.set_exception(exc)

    def call(self, tool: str, arguments: dict[str, Any], timeout: float = 120) -> str:
        if self._loop is None or not self._loop.is_running() or self._queue is None:
            raise RuntimeError(f"MCP server {self.name} 已退出")
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (tool, arguments, future))
        return future.result(timeout=timeout)

    def close(self, timeout: float = 8.0) -> None:
        if self._loop is None or not self._loop.is_running() or self._queue is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, (None, None, None))
            self._thread.join(timeout=timeout)
        except Exception:  # noqa: BLE001 - 退出阶段尽力而为
            pass


def load_mcp_servers(cfg: Config, registry: ToolRegistry,
                     track: dict[str, tuple[list[str], "PersistentServer | None"]] | None = None,
                     only: set[str] | None = None) -> list[str]:
    """按配置挂载 MCP server，返回成功挂载的 server 名列表。

    track 用于记录每个 server 注册了哪些工具、持有哪些常驻会话（供动态卸载）。
    only 限定只挂载指定名字的 server（WebUI 单个启用）。
    """
    loaded: list[str] = []
    for server in cfg.get("mcp_servers", []) or []:
        if not server.get("enabled", True):
            continue
        name = server["name"]
        if only is not None and name not in only:
            continue
        command, args = server["command"], list(server.get("args", []))
        env = server.get("env")
        cwd = server.get("cwd")
        timeout = float(server.get("timeout", 60))
        session: PersistentServer | None = None
        try:
            if server.get("persistent"):
                session = PersistentServer(name, command, args, env, cwd=cwd,
                                           startup_timeout=float(server.get("startup_timeout", 120)))
                atexit.register(session.close)
                tools = session.tools
            else:
                tools = _list_tools(command, args, env, cwd)
        except Exception as exc:
            print(f"[mcp] server {name} 启动失败：{type(exc).__name__}: {exc}")
            continue

        registered: list[str] = []
        for tool in tools:
            def make_handler(tool_name: str, sess=session, cmd=command,
                             a=args, e=env, d=cwd, tmo=timeout) -> Any:
                def handler(**kwargs) -> str:
                    if sess is not None:
                        return sess.call(tool_name, kwargs, tmo)
                    return _call_tool(cmd, a, e, tool_name, kwargs, d)
                return handler
            spec_name = f"mcp_{name}_{tool['name']}"
            registry.tool(
                spec_name,
                f"[MCP:{name}] {tool['description']}",
                tool["schema"],
                timeout=timeout,
            )(make_handler(tool["name"]))
            registered.append(spec_name)
        if track is not None:
            track[name] = (registered, session)
        loaded.append(name)
    return loaded


def unmount_mcp_server(registry: ToolRegistry, name: str,
                       track: dict[str, tuple[list[str], "PersistentServer | None"]]) -> int:
    """卸载一个已挂载的 MCP server：注销工具 + 关闭常驻会话。"""
    names, session = track.pop(name, ([], None))
    if session is not None:
        session.close()
    return registry.unregister(names)
