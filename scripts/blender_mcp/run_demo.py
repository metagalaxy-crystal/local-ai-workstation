"""Blender Lab 官方 MCP 样例：用 MCP 客户端驱动 Blender 生成「火花猫」。

链路：本脚本 --MCP/stdio--> blender-mcp --TCP(9876)--> Blender 插件

用法：
    python d:\\models\\scripts\\blender_mcp\\run_demo.py
    python d:\\models\\scripts\\blender_mcp\\run_demo.py --no-auto-start   # 不自动拉起 Blender

前置条件：Blender 已打开（插件会自动在 127.0.0.1:9876 起桥接服务），
或使用 --auto-start 以无界面方式拉起（默认开启）。
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_EXE = r"d:\models\tools\mcp-servers\blender_mcp_lab\mcp\.venv\Scripts\blender-mcp.exe"
BLENDER_EXE = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
HOST, PORT = "127.0.0.1", 9876


def bridge_alive(timeout=1.0):
    """检测 Blender 插件桥接端口是否在线。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((HOST, PORT)) == 0


def start_bridge(wait_seconds=25):
    """无界面拉起 Blender 并启动桥接服务（仅当端口未监听时）。"""
    print("[demo] 端口 %d 未监听，正在以无界面方式启动 Blender 桥接 ..." % PORT)
    subprocess.Popen(
        [BLENDER_EXE, "-b", "--online-mode", "--command", "blender_mcp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if bridge_alive():
            print("[demo] 桥接已就绪：%s:%d" % (HOST, PORT))
            return True
        time.sleep(0.5)
    raise RuntimeError("等待 Blender 桥接超时，请手动打开 Blender 后重试")


class MCPClient:
    """最小 stdio MCP 客户端（仅依赖标准库）。"""

    def __init__(self, command):
        self.proc = subprocess.Popen(
            [command], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1,
        )
        self.next_id = 1

    def _send(self, payload):
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def _read(self):
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read()
            raise RuntimeError("MCP 服务端无响应，stderr=%s" % err[:800])
        return json.loads(line)

    def initialize(self):
        self._send({"jsonrpc": "2.0", "id": self.next_id, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "spark-cat-demo", "version": "1.0"}}})
        resp = self._read()
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        return resp.get("result", {}).get("serverInfo", {})

    def list_tools(self):
        self._send({"jsonrpc": "2.0", "id": self.next_id, "method": "tools/list", "params": {}})
        resp = self._read()
        self.next_id += 1
        return resp["result"]["tools"]

    def call_tool(self, name, arguments):
        self._send({"jsonrpc": "2.0", "id": self.next_id, "method": "tools/call",
                    "params": {"name": name, "arguments": arguments}})
        resp = self._read()
        self.next_id += 1
        if "error" in resp:
            raise RuntimeError("工具调用失败：%s" % json.dumps(resp["error"], ensure_ascii=False))
        return resp["result"]

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Blender MCP 火花猫样例")
    parser.add_argument("--code", default=os.path.join(HERE, "spark_cat.py"),
                        help="送入 Blender 执行的 Python 脚本")
    parser.add_argument("--no-auto-start", action="store_true",
                        help="端口未监听时不自动拉起 Blender")
    args = parser.parse_args()

    if not bridge_alive():
        if args.no_auto_start:
            sys.exit("Blender 桥接未启动：请先打开 Blender（插件自带自动启动），再重跑本脚本")
        start_bridge()

    with open(args.code, encoding="utf-8") as fh:
        code = fh.read()

    client = MCPClient(MCP_EXE)
    try:
        info = client.initialize()
        tools = client.list_tools()
        print("[demo] 已连接 %s %s，工具 %d 个" %
              (info.get("name"), info.get("version"), len(tools)))
        print("[demo] 调用 execute_blender_code 构建场景（渲染约需数十秒）...")
        started = time.time()
        payload = client.call_tool("execute_blender_code", {"code": code})
        elapsed = time.time() - started
    finally:
        client.close()

    structured = payload.get("structuredContent") or {}
    text = payload["content"][0]["text"] if payload.get("content") else ""
    print("[demo] 耗时 %.1fs" % elapsed)
    print("[demo] 返回：%s" % json.dumps(structured, ensure_ascii=False)[:400])
    if text and "error" in text.lower():
        print("[demo] 原始输出：%s" % text[:400])
    print("[demo] 产物：d:\\models\\output\\blender_mcp\\spark_cat.png / spark_cat.blend")


if __name__ == "__main__":
    main()
