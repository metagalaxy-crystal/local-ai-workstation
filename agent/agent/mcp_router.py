# -*- coding: utf-8 -*-
"""按任务内容自动挑选并挂载 MCP server。

设计：
  - 初始不挂载任何 MCP（configs/agent.json 里 enabled 全为 false），启动更轻、上下文更干净
  - 执行任务前按关键词命中需要的 server，命中即挂载；挂载后常驻复用，
    但受 schema 预算约束（mcp.schema_budget_chars）：超预算自动卸载闲置的自动挂载项
  - 在调度视角里，MCP 调用等价于一个 CPU 节点：stdio 子进程，不占显存，
    可以与 GPU 上的 LLM 步骤同时进行（见 调度架构方案.md）
"""
from __future__ import annotations

import json
import threading

from .config import Config
from .mcp_client import load_mcp_servers, unmount_mcp_server
from .tools.registry import ToolRegistry

# 关键词 → MCP。顺序即优先级；同一条任务最多自动挂 2 个，避免上下文被工具清单挤爆
_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("deckcraft", ("ppt", "幻灯片", "演示文稿", "演示稿", "课件", "汇报材料", "pptx", "幻灯")),
    ("wordcraft", ("word文档", "docx", "写文档", "报告", "简历", "合同", "说明书", "公文")),
    ("gridcraft", ("excel", "xlsx", "表格", "工作表", "数据表", "台账")),
    ("pdfcraft", ("pdf", "合并文档", "拆分文档", "pdf表单", "扫描件")),
    ("photocraft", ("修图", "抠图", "图层", "psd", "photoshop", "调色", "换背景")),
    ("vectorcraft", ("矢量", "illustrator", "ai文件", "logo", "图标设计", "svg插画")),
    ("designcraft", ("排版", "画册", "宣传册", "海报", "出版物", "indesign")),
    ("effectcraft", ("动效", "特效", "关键帧", "after effects", "片头动画")),
    ("figcraft", ("原型", "ui设计", "界面设计", "figma", "组件库", "交互稿")),
    ("filmcraft", ("视频剪辑", "剪辑", "字幕", "premiere", "时间线", "转场")),
    ("soundcraft", ("音频", "混音", "录音", "降噪", "pro tools", "配乐")),
    ("lightcraft", ("照片库", "相册", "raw", "lightroom", "照片管理")),
    ("cadcraft", ("cad", "图纸", "工程图", "autocad", "dxf", "三维建模")),
    ("blender", ("blender", "3d建模", "几何节点", "blend文件")),
    ("playwright", ("浏览器", "网页", "打开网站", "爬取", "抓取", "http://", "https://",
                    "网页截图", "登录网站")),
]

MAX_AUTO = 2

# 未显式传入 track 时的兜底记录（CLI 场景）
_TRACK: dict[str, tuple[list[str], object]] = {}
_lock = threading.Lock()


def pick(task: str) -> list[str]:
    """按任务文本挑出需要挂载的 MCP 名字（最多 MAX_AUTO 个）。"""
    low = (task or "").lower()
    hits = [name for name, keys in _RULES if any(k in low for k in keys)]
    return hits[:MAX_AUTO]


def auto_mount(cfg: Config, registry: ToolRegistry, task: str,
               track: dict | None = None) -> list[str]:
    """按任务自动挂载需要的 MCP，返回本次新挂载的 server 名。已挂载的不会重复启动。

    挂载后做 schema 预算检查：本地模型上下文有限（默认 16K），工具清单每轮都随
    prompt 重发，超限就把「非本任务需要、且配置里 enabled=false（即自动挂载的）」
    的 server 按挂载先后卸载，手动启用的不动。
    """
    names = pick(task)
    entries = [s for s in (cfg.get("mcp_servers", []) or []) if isinstance(s, dict)]
    book = _TRACK if track is None else track
    mounted: list[str] = []
    with _lock:
        for name in names:
            if name in book:
                continue  # 已挂载，直接复用
            entry = next((s for s in entries if s.get("name") == name), None)
            if entry is None:
                continue  # 配置里没有这个 server，跳过
            # 配置里 enabled 是 false，挂载用的副本要强制置 True
            single = Config({"mcp_servers": [dict(entry, enabled=True)]}, cfg.source)
            if load_mcp_servers(single, registry, track=book):
                mounted.append(name)
        pruned = _prune_over_budget(cfg, registry, book, keep=set(names))
    if pruned:
        print(f"[mcp] schema 超预算，已卸载闲置 server：{', '.join(pruned)}", flush=True)
    return mounted


def _schema_chars(registry: ToolRegistry) -> int:
    """注册表里 MCP 工具的 schema 总字符数（本地工具很小，不计）。"""
    total = 0
    for sch in registry.schemas():
        if sch.get("function", {}).get("name", "").startswith("mcp_"):
            total += len(json.dumps(sch, ensure_ascii=False))
    return total


def close_all(track: dict | None = None) -> None:
    """退出时关掉所有常驻 MCP 会话（顺带杀掉子进程），避免留下孤儿进程。

    只发关闭信号、最多等数秒；即使某个 server 的调用还卡着也不阻塞退出。
    """
    book = _TRACK if track is None else track
    with _lock:
        items = list(book.values())
        book.clear()
    for _names, session in items:
        try:
            if session is not None:
                session.close(timeout=3.0)
        except Exception:  # noqa: BLE001 - 退出阶段尽力而为
            pass


def _prune_over_budget(cfg: Config, registry: ToolRegistry, book: dict,
                       keep: set[str]) -> list[str]:
    """超预算时卸载最老的自动挂载 server（不动 keep 与配置里手动启用的）。"""
    budget = int(cfg.get("mcp.schema_budget_chars", 6000) or 0)
    if budget <= 0:
        return []
    enabled_manual = {s.get("name") for s in (cfg.get("mcp_servers", []) or [])
                      if isinstance(s, dict) and s.get("enabled")}
    pruned: list[str] = []
    while _schema_chars(registry) > budget:
        victim = next((n for n in book if n not in keep and n not in enabled_manual), None)
        if victim is None:
            break  # 剩下的都是本任务要的或手动启用的，超预算也认
        unmount_mcp_server(registry, victim, book)
        pruned.append(victim)
    return pruned
