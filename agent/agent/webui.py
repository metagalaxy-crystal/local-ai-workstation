# -*- coding: utf-8 -*-
"""自研 WebUI（:8088）：任务聊天 + 多模型流水线编排 + 系统监视一体化。

页面结构：
  顶部    资源监视条（CPU / 内存 / 显存 / GPU 利用率，2s 轮询）+ 主题切换（默认浅色）
  左侧    任务列表（新建/删除/设置工作目录）、服务面板（LLM 模型切换、ComfyUI 启停、
          embed/rerank 状态）、已安装 MCP 插件列表
  中间    模型运行图（流水线步骤条）+ 消息流（每个模型的输入输出、工具卡片、token chip）
  底部    对话输入 + 附件上传 + 「发送」（普通对话）/「规划执行」（多模型流水线）

API：
  GET  /                        页面
  GET  /api/sessions            任务列表
  GET  /api/session/<id>        {session, messages, usage}
  POST /api/session/new         {title?, workspace?}
  POST /api/session/delete      {session_id}
  POST /api/session/workspace   {session_id, workspace}
  POST /api/chat                {session_id, message} → 同步普通对话
  POST /api/plan_run            {session_id, message, model_key?} → {run_id} 后台流水线
  GET  /api/run_status          ?run_id= 或 ?session_id=
  POST /api/run_cancel          {run_id}
  GET  /api/resources           CPU/RAM/VRAM/GPU 采样
  GET  /api/services            各服务在线状态 + 服务日志尾巴
  POST /api/service             {action: start_llm|stop_llm|start_comfy|stop_comfy|start_embed|stop_embed|start_rerank|stop_rerank, key?}
  GET  /api/models              模型注册表 + 当前在线
  GET  /api/mcp                 已安装 MCP 插件
  GET  /api/files               ?session_id= 任务工作目录内可预览的产出文件
  GET  /api/file                ?session_id=&path= 读取工作目录内文件（防目录穿越）
  POST /api/upload              multipart 附件，存会话工作区 uploads/
"""
from __future__ import annotations

import json
import mimetypes
import re
import shutil
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import Config
from .llm import LLMClient, LLMError
from .loop import AgentLoop, Callbacks
from .memory.store import SessionStore
from .orchestrator import PlannedRunner
from .scheduler import Scheduler, SchedulerRunner
from .services import ServiceManager
from .tools import build_registry, scope
from .trace import Trace, sample_resources

_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>本地模型工作站</title>
<style>
  :root {
    --bg:#f4f6f9; --panel:#ffffff; --panel2:#eef1f5; --border:#dfe3ea;
    --text:#1f2329; --dim:#6b7280; --accent:#2563eb; --accent-t:#ffffff;
    --ok:#16a34a; --err:#dc2626; --warn:#d97706; --chip:#e8edf4; --tool:#f8fafc;
  }
  [data-theme="dark"] {
    --bg:#1a1b26; --panel:#16161e; --panel2:#1f2335; --border:#2f344d;
    --text:#c0caf5; --dim:#565f89; --accent:#7aa2f7; --accent-t:#1a1b26;
    --ok:#9ece6a; --err:#f7768e; --warn:#e0af68; --chip:#2f344d; --tool:#1a1b26;
  }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family:system-ui,"Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text);
         height:100vh; display:flex; flex-direction:column; overflow:hidden; }
  button { cursor:pointer; font-family:inherit; }
  /* ---------- 顶部资源条 ---------- */
  #topbar { height:42px; background:var(--panel); border-bottom:1px solid var(--border);
            display:flex; align-items:center; gap:14px; padding:0 14px; flex-shrink:0; }
  #topbar .brand { font-weight:600; font-size:14px; color:var(--accent); }
  .res-chip { font-size:12px; color:var(--dim); background:var(--chip); padding:3px 10px;
              border-radius:10px; white-space:nowrap; }
  .res-chip b { color:var(--text); font-weight:600; }
  #topbar .spacer { flex:1; }
  #theme-btn { background:var(--chip); border:1px solid var(--border); color:var(--text);
               border-radius:6px; padding:4px 10px; font-size:12px; }
  /* ---------- 布局 ---------- */
  #layout { flex:1; display:flex; min-height:0; }
  #sidebar { width:280px; background:var(--panel); border-right:1px solid var(--border);
             overflow-y:auto; padding:10px; flex-shrink:0; }
  .side-sec { margin-bottom:16px; }
  .side-sec h3 { font-size:12px; color:var(--dim); margin-bottom:6px; text-transform:uppercase; letter-spacing:.5px; }
  .task-item { padding:7px 9px; border-radius:6px; cursor:pointer; font-size:13px; position:relative; }
  .task-item:hover, .task-item.active { background:var(--panel2); }
  .task-item .ttl { font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .task-item .ws { font-size:11px; color:var(--dim); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .task-item .del { position:absolute; right:6px; top:6px; color:var(--dim); border:none; background:none; font-size:13px; display:none; }
  .task-item:hover .del { display:block; }
  .task-item .del:hover { color:var(--err); }
  .mini-btn { width:100%; padding:6px; border:1px solid var(--border); background:var(--panel2);
              color:var(--text); border-radius:6px; font-size:12px; margin-top:6px; }
  .svc-row { display:flex; align-items:center; gap:6px; font-size:12px; padding:4px 2px; }
  .dot { width:8px; height:8px; border-radius:50%; background:var(--dim); flex-shrink:0; }
  .dot.on { background:var(--ok); }
  .dot.off { background:var(--err); }
  .svc-row .name { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .svc-btn { border:1px solid var(--border); background:var(--panel2); color:var(--text);
             border-radius:5px; padding:2px 8px; font-size:11px; }
  .model-item { font-size:12px; padding:5px 6px; border-radius:5px; display:flex; gap:6px; align-items:center; }
  .model-item.active { background:var(--chip); }
  .model-item .mname { flex:1; }
  .model-item .mtask { color:var(--dim); font-size:11px; display:block; }
  .mcp-item { font-size:12px; padding:3px 6px; color:var(--dim); }
  .mcp-row { display:flex; align-items:center; gap:6px; font-size:12px; padding:3px 2px; }
  .mcp-row .name { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .mcp-row .st { font-size:10.5px; color:var(--dim); white-space:nowrap; }
  .mcp-row .peer { font-size:10px; color:var(--dim); background:var(--chip);
    border-radius:9px; padding:1px 6px; white-space:nowrap; }
  #svc-log { font-size:10px; color:var(--dim); background:var(--tool); border:1px solid var(--border);
             border-radius:6px; padding:5px; max-height:110px; overflow-y:auto; white-space:pre-wrap; }
  /* ---------- 主区 ---------- */
  #main { flex:1; display:flex; flex-direction:column; min-width:0; }
  #planbar { background:var(--panel); border-bottom:1px solid var(--border); padding:8px 14px;
             display:none; align-items:center; gap:6px; flex-wrap:wrap; flex-shrink:0; }
  #planbar .pstep { font-size:12px; padding:4px 10px; border-radius:12px; background:var(--chip);
                    color:var(--dim); border:1px solid var(--border); }
  #planbar .pstep.running { border-color:var(--warn); color:var(--warn); }
  #planbar .pstep.done { border-color:var(--ok); color:var(--ok); }
  #planbar .pstep.err { border-color:var(--err); color:var(--err); }
  #planbar .pstep.clickable:hover { border-color:var(--accent); color:var(--accent); }
  #planbar .pstep.sel { border-color:var(--accent); color:var(--accent);
                        box-shadow:inset 0 0 0 1px var(--accent); }
  #planbar .parrow { color:var(--dim); font-size:11px; }
  #planbar .ptokens { margin-left:auto; font-size:11px; color:var(--dim); }
  #cancel-run { border:1px solid var(--err); color:var(--err); background:none; border-radius:10px;
                padding:3px 10px; font-size:11px; }
  #planbar .pexpand { border:1px solid var(--border); background:var(--panel2); color:var(--text);
                      border-radius:10px; padding:3px 10px; font-size:11px; }
  /* ---------- 运行图展开视图 ---------- */
  #runexpand { display:none; background:var(--panel); border-bottom:1px solid var(--border);
               padding:10px 14px 12px; flex-shrink:0; max-height:40vh; overflow-y:auto; }
  #runexpand.show { display:block; }
  .re-head { display:flex; align-items:center; gap:10px; font-size:11px; color:var(--dim); margin-bottom:8px; }
  .re-head .ttl { font-weight:600; color:var(--text); font-size:12px; }
  .re-head .legend { margin-left:auto; display:flex; gap:12px; }
  .re-head .legend span { display:inline-flex; align-items:center; gap:4px; }
  .re-grid { display:grid; grid-template-columns:1.15fr 1.1fr 1fr 1fr; gap:10px; align-items:start; }
  .re-col { border:1px dashed var(--border); border-radius:10px; padding:8px 9px 4px; min-width:0; }
  .re-col > h4 { font-size:12px; font-weight:600; }
  .re-col > .sub { font-size:10.5px; color:var(--dim); margin:1px 0 7px; }
  .re-item { background:var(--panel); border:1px solid var(--border); border-radius:7px;
             padding:5px 8px; margin-bottom:5px; }
  .re-item .nm { font-size:12px; font-weight:600; display:flex; align-items:center; gap:6px;
                 line-height:1.35; word-break:break-word; }
  .re-item .cap { font-size:10.5px; color:var(--dim); margin-top:2px; line-height:1.35;
                  word-break:break-word; }
  .re-item .v { font-size:18px; font-weight:600; margin-top:2px; line-height:1.2; }
  .re-item.task .nm { font-weight:600; max-height:2.7em; overflow:hidden; }
  .re-item.pending { border-style:dashed; background:transparent; }
  .re-item.pending .nm { color:var(--dim); font-weight:400; }
  .re-item.clickable { cursor:pointer; }
  .re-item.clickable:hover { border-color:var(--accent); }
  .re-item.sel { border-color:var(--accent); box-shadow:inset 0 0 0 1px var(--accent); }
  .re-item .tok { font-size:13px; font-weight:600; color:var(--accent); margin-right:5px; }
  /* 细分节点：每个步骤内部的推理轮次 / 工具调用 */
  .re-subs { margin-top:5px; border-top:1px dashed var(--border); padding-top:4px; }
  .re-sub-row { display:flex; align-items:center; gap:6px; font-size:10.5px;
    color:var(--dim); padding:2px 4px; border-radius:5px; cursor:pointer; }
  .re-sub-row:hover { background:var(--hover, rgba(0,0,0,.04)); }
  .re-sub-row .k { flex-shrink:0; opacity:.75; }
  .re-sub-row .n { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis;
    white-space:nowrap; color:var(--text); }
  .re-sub-row .m { flex-shrink:0; font-variant-numeric:tabular-nums; }
  .re-sub-row.ok .m { color:var(--ok); }
  .re-sub-row.err .m { color:var(--warn); }
  .re-sub-row.run .m { color:var(--warn); }
  .re-sub-row.idle { cursor:default; }
  .re-sub-row.sel { box-shadow:inset 0 0 0 1px var(--accent); border-radius:4px; }
  .re-sub2 { font-size:10.5px; color:var(--dim); margin:6px 0 4px; }
  .re-dot { width:6px; height:6px; border-radius:50%; background:var(--ok); flex-shrink:0; }
  .re-dot.run { background:var(--warn); }
  .re-dot.err { background:var(--err); }
  .re-dot.idle { background:transparent; border:1px dashed var(--dim); }
  .re-bar { height:4px; border-radius:3px; background:var(--panel2); overflow:hidden;
            display:flex; margin-top:7px; }
  .re-bar i { height:100%; display:block; }
  @media (max-width:1120px) { .re-grid { grid-template-columns:1fr 1fr; } }
  #messages { flex:1; overflow-y:auto; padding:14px 16px; }
  .msg { margin-bottom:10px; padding:9px 13px; border-radius:8px; max-width:82%; white-space:pre-wrap;
         word-break:break-word; font-size:14px; }
  .msg.user { background:var(--accent); color:var(--accent-t); margin-left:auto; }
  .msg.assistant { background:var(--panel); border:1px solid var(--border); }
  .msg.assistant.live { border-color:var(--accent); }
  .msg.assistant.live::after { content:'▌'; color:var(--accent); animation:blink 1s infinite; }
  @keyframes blink { 50% { opacity:0; } }
  .msg .stats { font-size:11px; color:var(--dim); margin-top:5px; }
  .msg.thinking { background:var(--tool); border:1px dashed var(--border); border-left:3px solid var(--warn);
                  color:var(--dim); font-size:12px; max-width:92%; cursor:pointer;
                  display:flex; align-items:center; gap:8px; }
  .msg.thinking:hover { color:var(--text); border-color:var(--warn); }
  .msg.thinking .th-h { color:var(--warn); font-weight:600; }
  .msg.thinking .th-num { margin-left:auto; font-size:11px; flex-shrink:0; }
  /* ---------- 可折叠的操作步骤 ---------- */
  .step { background:var(--tool); border:1px solid var(--border); border-radius:8px;
          margin-top:5px; font-size:12px; max-width:92%; align-self:flex-start; width:92%;
          display:flex; align-items:center; gap:7px; padding:5px 9px; cursor:pointer; }
  .step:hover { border-color:var(--accent); }
  .step .st-ico { width:6px; height:6px; border-radius:50%; background:var(--ok); flex-shrink:0; }
  .step.running .st-ico { background:var(--warn); animation:st-pulse 1s ease-in-out infinite; }
  .step.fail .st-ico { background:var(--err); }
  @keyframes st-pulse { 50% { opacity:.25; } }
  .step .st-name { font-weight:600; white-space:nowrap; }
  .step .st-args { color:var(--dim); overflow:hidden; text-overflow:ellipsis;
                   white-space:nowrap; flex:1; min-width:0; }
  .step .st-meta { color:var(--dim); font-size:11px; white-space:nowrap; }
  .step .st-view { font-size:10.5px; color:var(--accent); border:1px solid var(--accent);
                   background:none; border-radius:10px; padding:1px 7px; flex-shrink:0; }
  /* ---------- 运行中实时状态条 ---------- */
  #livestatus { display:none; background:var(--panel); border-top:1px solid var(--border);
                padding:6px 14px 9px; flex-shrink:0; font-size:11.5px; color:var(--dim);
                position:relative; }
  #livestatus.show { display:block; }
  #livestatus .ls-row { display:flex; align-items:center; gap:8px; min-width:0; }
  #livestatus .ls-spin { width:10px; height:10px; border-radius:50%; border:2px solid var(--border);
                         border-top-color:var(--accent); animation:spin .8s linear infinite; flex-shrink:0; }
  @keyframes spin { to { transform:rotate(360deg); } }
  #livestatus .ls-phase { color:var(--text); font-weight:600; overflow:hidden;
                          text-overflow:ellipsis; white-space:nowrap; }
  #livestatus .ls-note { color:var(--dim); white-space:nowrap; }
  #livestatus .ls-meta { margin-left:auto; white-space:nowrap; }
  #livestatus .ls-bar { position:absolute; left:0; right:0; bottom:0; height:2px; overflow:hidden;
                        background:var(--panel2); }
  #livestatus .ls-bar i { position:absolute; width:32%; height:100%; background:var(--accent);
                          animation:ls-slide 1.4s ease-in-out infinite; }
  @keyframes ls-slide { 0% { left:-32%; } 100% { left:100%; } }
  .ev { margin-bottom:8px; padding:7px 11px; border-radius:7px; font-size:12px; max-width:92%;
        background:var(--tool); border:1px solid var(--border); border-left:3px solid var(--accent); color:var(--text); }
  .ev.svc { border-left-color:var(--warn); color:var(--dim); }
  .ev.ok { border-left-color:var(--ok); }
  .ev.err { border-left-color:var(--err); }
  .ev .tk { color:var(--dim); font-size:11px; }
  .usage-line { font-size:11px; color:var(--dim); margin-bottom:10px; }
  /* ---------- 底部输入 ---------- */
  #composer { background:var(--panel); border-top:1px solid var(--border); padding:10px 14px; flex-shrink:0; }
  #attach-chip { font-size:11px; color:var(--dim); margin-bottom:5px; display:none; }
  #composer-row { display:flex; gap:8px; }
  #input { flex:1; padding:9px 12px; border-radius:7px; border:1px solid var(--border);
           background:var(--bg); color:var(--text); font-size:14px; resize:none; height:40px; font-family:inherit; }
  .cbtn { padding:0 16px; border-radius:7px; border:none; font-size:13px; }
  #send { background:var(--accent); color:var(--accent-t); }
  #plan-run { background:var(--panel2); color:var(--accent); border:1px solid var(--accent); }
  #attach { background:var(--panel2); color:var(--text); border:1px solid var(--border); }
  .cbtn:disabled { opacity:.5; cursor:not-allowed; }
  /* ---------- 右侧预览 ---------- */
  #preview { width:400px; min-width:320px; border-left:1px solid var(--border);
             background:var(--panel); display:flex; flex-direction:column; flex-shrink:0; }
  #pv-bar { display:flex; gap:6px; padding:8px; border-bottom:1px solid var(--border); align-items:center; }
  .pv-tab { border:1px solid var(--border); background:var(--panel2); color:var(--dim);
            border-radius:6px; padding:4px 12px; font-size:12px; }
  .pv-tab.active { color:var(--accent); border-color:var(--accent); background:var(--panel); font-weight:600; }
  #pv-urlbar { display:none; gap:6px; padding:8px; border-bottom:1px solid var(--border); }
  #pv-browser-empty { position:absolute; inset:0; display:none; align-items:center; justify-content:center;
                      color:var(--dim); font-size:12px; padding:24px; text-align:center; line-height:1.7; }
  #pv-url { flex:1; padding:5px 8px; border:1px solid var(--border); border-radius:6px;
            background:var(--bg); color:var(--text); font-size:12px; min-width:0; }
  #pv-body { flex:1; position:relative; background:var(--bg); min-height:0; }
  #pv-body iframe, #pv-body img, #pv-body video, #pv-body audio {
            position:absolute; inset:0; width:100%; height:100%; border:none;
            object-fit:contain; background:var(--bg); }
  #pv-body audio { height:56px; top:auto; bottom:12px; }
  #pv-body img.live { cursor:zoom-in; }
  /* ---------- 浏览器画面放大（全屏浮层） ---------- */
  #pv-zoom { display:none; position:fixed; inset:0; background:rgba(15,17,26,.78); z-index:60;
             align-items:center; justify-content:center; }
  #pv-zoom.show { display:flex; }
  #pv-zoom-body { position:relative; width:94vw; height:90vh; background:var(--bg);
                  border-radius:10px; overflow:hidden; }
  #pv-zoom-body img { position:absolute; inset:0; width:100%; height:100%;
                      object-fit:contain; cursor:zoom-out; }
  #pv-zoom .pv-zoom-btn { position:fixed; right:24px; top:20px; z-index:61;
      border:1px solid var(--border); background:var(--panel); color:var(--text);
      border-radius:8px; padding:7px 16px; font-size:13px; }
  #pv-zoom .pv-zoom-btn:hover { border-color:var(--accent); color:var(--accent); }
  #pv-empty { position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
              color:var(--dim); font-size:12px; padding:24px; text-align:center; }
  #pv-files-wrap { height:32%; max-height:260px; min-height:150px; border-top:1px solid var(--border);
                   overflow-y:auto; padding:6px 8px; flex-shrink:0; }
  #pv-files-wrap h4 { font-size:11px; color:var(--dim); margin:6px 0 3px; }
  .pv-sandbox { font-size:11px; color:var(--dim); margin-bottom:2px; }
  .pv-sandbox b { color:var(--accent); font-weight:600; }
  .pv-file { font-size:12px; padding:4px 6px; border-radius:5px; display:flex; gap:6px; cursor:pointer; }
  .pv-file:hover { background:var(--chip); }
  .pv-file .fname { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .pv-file .fsize { color:var(--dim); font-size:11px; flex-shrink:0; }
  #pv-custom { position:absolute; inset:0; overflow:auto; display:none; background:var(--bg); }
  #pv-custom.show { display:block; }
  #pv-custom .pv-doc { padding:12px 14px; font-size:12.5px; line-height:1.6; color:var(--text); }
  #pv-custom h3 { font-size:14px; margin:0 0 6px; }
  #pv-custom h4 { font-size:11px; color:var(--dim); margin:12px 0 4px; letter-spacing:.4px; }
  #pv-custom pre { white-space:pre-wrap; word-break:break-word; background:var(--panel2);
                  border:1px solid var(--border); border-radius:6px; padding:8px;
                  font-size:11.5px; font-family:ui-monospace,Consolas,monospace; overflow:auto; }
  #pv-custom textarea { width:100%; height:54vh; background:var(--bg); color:var(--text);
                        border:1px solid var(--border); border-radius:6px; padding:8px;
                        font:12px/1.55 ui-monospace,Consolas,monospace; resize:vertical; }
  .pv-actions { display:flex; gap:6px; margin:8px 0; align-items:center; }
  /* ---------- 左侧知识库 ---------- */
  .kb-master { display:flex; align-items:center; gap:6px; font-size:12px; color:var(--dim);
               padding:2px 2px 7px; cursor:pointer; }
  .kb-cat { margin-bottom:4px; }
  .kb-head { display:flex; align-items:center; gap:6px; font-size:12px; padding:3px 2px; cursor:pointer; }
  .kb-head input { margin:0; }
  .kb-head .dot-c { width:5px; height:5px; border-radius:50%; background:var(--accent); }
  .kb-head .cnt { color:var(--dim); font-size:10.5px; margin-left:auto; }
  .kb-files { margin:1px 0 4px 21px; }
  .kb-file { font-size:11.5px; color:var(--dim); padding:2px 4px; border-radius:4px;
             display:flex; gap:4px; cursor:pointer; }
  .kb-file .fname { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .kb-file:hover { background:var(--chip); color:var(--text); }
  .kb-file .del { margin-left:auto; border:none; background:none; color:var(--err);
                  opacity:.5; padding:0 2px; }
  .kb-file .del:hover { opacity:1; }
  .kb-hint { font-size:10.5px; color:var(--dim); padding:2px 2px; }
  #pv-show { position:fixed; right:0; top:45%; z-index:50; writing-mode:vertical-rl;
             padding:10px 5px; border:1px solid var(--border); border-right:none; border-radius:6px 0 0 6px;
             background:var(--panel); color:var(--dim); font-size:12px; }
</style>
</head>
<body>
<div id="topbar">
  <span class="brand">本地模型工作站</span>
  <span class="res-chip">CPU <b id="r-cpu">-</b></span>
  <span class="res-chip">内存 <b id="r-ram">-</b></span>
  <span class="res-chip">显存 <b id="r-vram">-</b></span>
  <span class="res-chip">GPU <b id="r-gpu">-</b></span>
  <span class="spacer"></span>
  <button id="theme-btn" onclick="toggleTheme()">深色模式</button>
</div>
<div id="layout">
  <aside id="sidebar">
    <div class="side-sec">
      <h3>任务</h3>
      <div id="session-list"></div>
      <button class="mini-btn" onclick="newSession()">+ 新建任务</button>
      <button class="mini-btn" id="mem-btn" style="display:none" onclick="consolidateMemory()">整理记忆</button>
    </div>
    <div class="side-sec">
      <h3>全局知识库</h3>
      <label class="kb-master"><input type="checkbox" id="kb-master" onchange="kbSelChanged()">
        发送对话时引用全局知识库</label>
      <div id="kb-list"></div>
      <div class="kb-hint">勾选门类；只有勾选并开启时才注入对话</div>
      <div style="display:flex;gap:6px;margin-top:6px">
        <button class="mini-btn" style="margin-top:0" onclick="kbNewCategory()">+ 门类</button>
        <button class="mini-btn" style="margin-top:0" onclick="kbNewFile()">+ 文件</button>
      </div>
    </div>
    <div class="side-sec">
      <h3>模型服务</h3>
      <div class="svc-row"><span class="dot" id="d-llm"></span><span class="name" id="llm-name">LLM</span>
        <button class="svc-btn" onclick="svc('stop_llm')">停</button></div>
      <div id="model-list"></div>
      <div class="svc-row"><span class="dot" id="d-comfy"></span><span class="name">ComfyUI</span>
        <button class="svc-btn" onclick="svc('start_comfy')">起</button>
        <button class="svc-btn" onclick="svc('stop_comfy')">停</button></div>
      <div class="svc-row"><span class="dot" id="d-embed"></span><span class="name">Embed :8081</span>
        <button class="svc-btn" onclick="svc('start_embed')">起</button>
        <button class="svc-btn" onclick="svc('stop_embed')">停</button></div>
      <div class="svc-row"><span class="dot" id="d-rerank"></span><span class="name">Rerank :8082</span>
        <button class="svc-btn" onclick="svc('start_rerank')">起</button>
        <button class="svc-btn" onclick="svc('stop_rerank')">停</button></div>
      <div id="svc-log"></div>
    </div>
    <div class="side-sec">
      <h3>MCP 插件</h3>
      <div id="mcp-list"></div>
    </div>
    <div class="side-sec">
      <h3>定时任务</h3>
      <div class="svc-row"><span class="name">调度器</span>
        <button class="svc-btn" id="sched-toggle" onclick="schedToggle()">…</button></div>
      <div id="sched-list"></div>
      <input id="sched-text" placeholder="任务内容，如：汇总今天的 token 用量"
        style="width:100%;margin-top:8px;padding:7px 9px;border-radius:6px;border:1px solid var(--border);background:var(--panel);color:var(--text);font-size:12px">
      <div style="display:flex;gap:6px;margin-top:6px">
        <select id="sched-type" onchange="schedTypeHint()"
          style="flex:1;padding:6px;border-radius:6px;border:1px solid var(--border);background:var(--panel);color:var(--text);font-size:12px">
          <option value="daily">每天定点</option><option value="once">一次性</option><option value="interval">间隔循环</option>
        </select>
        <input id="sched-time" placeholder="HH:MM"
          style="width:100px;padding:6px;border-radius:6px;border:1px solid var(--border);background:var(--panel);color:var(--text);font-size:12px">
      </div>
      <button class="mini-btn" style="width:100%;margin-top:6px" onclick="schedAdd()">添加定时任务</button>
    </div>
  </aside>
  <div id="main">
    <div id="planbar"></div>
    <div id="runexpand"></div>
    <div id="messages"></div>
    <div id="livestatus"></div>
    <div id="composer">
      <div id="attach-chip"></div>
      <div id="composer-row">
        <button class="cbtn" id="attach" onclick="document.getElementById('file').click()">附件</button>
        <input type="file" id="file" style="display:none" onchange="uploadFile(this)">
        <textarea id="input" placeholder="输入任务，Enter 发送 / Shift+Enter 换行"
          onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}"></textarea>
        <button class="cbtn" id="send" onclick="send()">发送</button>
        <button class="cbtn" id="plan-run" onclick="planRun()">规划执行</button>
      </div>
    </div>
  </div>
  <div id="preview">
    <div id="pv-bar">
      <button id="pv-tab-files" class="pv-tab active" onclick="pvTab('files')">文件</button>
      <button id="pv-tab-browser" class="pv-tab" onclick="pvTab('browser')">浏览器</button>
      <span style="flex:1"></span>
      <button class="mini-btn" style="width:auto" onclick="togglePreview(false)">收起</button>
    </div>
    <div id="pv-urlbar">
      <input id="pv-url" placeholder="输入网址回车，在内嵌浏览器预览"
        onkeydown="if(event.key==='Enter')pvGo()">
      <button class="mini-btn" style="width:auto" onclick="pvGo()">打开</button>
      <button class="mini-btn" style="width:auto" onclick="pvLive()">刷新截图</button>
    </div>
    <div id="pv-body">
      <div id="pv-empty">浏览器预览<br>点击消息里的「详情」或下方文件，在这里查看</div>
      <div id="pv-browser-empty">暂无浏览器截图<br>模型打开网页/搜索时会自动切到这里</div>
      <iframe id="pv-frame" style="display:none" sandbox="allow-scripts allow-same-origin"></iframe>
      <img id="pv-img" style="display:none" alt="" onclick="pvZoom(true)">
      <video id="pv-vid" style="display:none" controls></video>
      <audio id="pv-aud" style="display:none" controls></audio>
      <div id="pv-custom"></div>
    </div>
    <div id="pv-files-wrap">
      <div class="pv-sandbox">工作目录：沙箱 <b id="pv-sandbox">-</b></div>
      <h4>任务输入</h4>
      <div id="pv-inputs"></div>
      <h4>任务产出</h4>
      <div id="pv-files"></div>
    </div>
  </div>
  <button id="pv-show" style="display:none" onclick="togglePreview(true)">◀ 预览</button>
</div>
<div id="pv-zoom" onclick="pvZoom(false)">
  <div id="pv-zoom-body" onclick="event.stopPropagation()"></div>
  <button class="pv-zoom-btn" onclick="pvZoom(false)">缩小</button>
</div>
<script>
let currentSession = null;
let historyMsgs = [];
let activeRun = null;
let runPoll = null;
let attachedPath = null;
let expandOpen = false;   // 运行图展开模式（框图视图）
let expandTip = null;     // 选中的子节点：`${runId}:${i}:c${k}` / `${runId}:${i}:r${k}`
let expandSel = null;     // 展开视图主选中的大步骤：`${runId}:${i}`
let expandSels = null;    // 多步骤同时展开（点工具 chip 时聚合所有相关步骤）：Set
let expandCallName = '';  // 选中的工具名：展开视图里所有同名调用行一起高亮
let expandScroll = false; // 下一次展开视图渲染后，把选中节点滚进可视区
let sessionUsage = {prompt:0, completion:0};  // 整个任务的历史累计（不含正在跑的 run）

/* ---------- 主题 ---------- */
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  document.getElementById('theme-btn').textContent = t === 'dark' ? '浅色模式' : '深色模式';
  localStorage.setItem('theme', t);
}
function toggleTheme() {
  applyTheme(localStorage.getItem('theme') === 'dark' ? 'light' : 'dark');
}
applyTheme(localStorage.getItem('theme') || 'light');

/* ---------- 任务 ---------- */
async function loadSessions() {
  const r = await fetch('/api/sessions');
  const data = await r.json();
  document.getElementById('session-list').innerHTML = data.map(s => {
    const t = (s.title || '').trim() || '未命名任务';
    return `<div class="task-item ${s.id===currentSession?'active':''}" onclick="selectSession('${s.id}')">
      <div class="ttl" title="${esc(t)}">${esc(t)}</div>
      <div class="ws">沙箱 ${esc(s.sandbox || s.id)}</div>
      <button class="del" onclick="event.stopPropagation();delSession('${s.id}')">×</button>
    </div>`;
  }).join('');
  document.getElementById('mem-btn').style.display = currentSession ? 'block' : 'none';
}
async function selectSession(id) {
  currentSession = id;
  loadSessions();
  const r = await fetch(`/api/session/${id}`);
  const data = await r.json();
  historyMsgs = data.messages || [];
  renderMessages();
  const u = (data.usage && data.usage[0]) || {};
  sessionUsage = {prompt: u.prompt_tokens || 0, completion: u.completion_tokens || 0};
  if (data.usage && data.usage.length) {
    appendUsage(`本任务累计：${u.runs} 次运行 · prompt ${u.prompt_tokens||0} · completion ${u.completion_tokens||0} tokens`);
  }
  const rr = await fetch(`/api/run_status?session_id=${id}`);
  const run = await rr.json();
  activeRun = (run && run.id) ? run : null;
  renderRun(); renderThinking(); renderLive();
  // 只给进行中的 run 开轮询——完成态开了也会在第一次回调里停掉，还会误触发重复重载
  if (activeRun && activeRun.status === 'running') startRunPoll();
  loadFiles();
}
async function newSession() {
  // 空白任务不落库：只清空界面进入草稿态，首次发送时后端才真正创建会话
  currentSession = null;
  sessionUsage = {prompt:0, completion:0};
  historyMsgs = []; activeRun = null;
  renderMessages(); renderRun(); renderThinking(); renderLive();
  if (typeof renderDraft === 'function') renderDraft();
  loadSessions(); loadFiles();
}
async function delSession(id) {
  if (!confirm('删除该任务及其全部消息，并清空对应沙箱目录？')) return;
  await fetch('/api/session/delete', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({session_id:id})});
  if (currentSession === id) {
    currentSession = null; historyMsgs = []; activeRun = null;
    renderMessages(); renderRun(); renderThinking(); renderLive(); loadFiles();
  }
  loadSessions();
}

/* ---------- 消息渲染 ---------- */
function esc(s){ const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML; }
function enc(s){ return encodeURIComponent(String(s||'')).replace(/'/g, '%27'); }
function renderMessages() {
  const box = document.getElementById('messages');
  box.innerHTML = '';
  pendingSteps = [];  // 重绘后旧的步骤节点已脱离 DOM，避免 tool_result 配对到幽灵节点
  for (const m of historyMsgs) {
    if (m.role === 'user') appendMsg('user', m.content);
    else if (m.role === 'assistant' && m.content) appendMsg('assistant', m.content);
    else if (m.role === 'tool') appendEv('tool', m.name, true, (m.content||'').split('\n')[0].slice(0,150));
  }
  box.scrollTop = box.scrollHeight;
}
function appendMsg(role, text, stats) {
  const box = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.textContent = text;
  if (stats) { const s=document.createElement('div'); s.className='stats'; s.textContent=stats; div.appendChild(s); }
  box.appendChild(div); box.scrollTop = box.scrollHeight;
}
function appendUsage(text) {
  const box = document.getElementById('messages');
  const div = document.createElement('div'); div.className='usage-line'; div.textContent=text;
  box.appendChild(div);
}
function appendEv(kind, title, ok, text) {
  const box = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = `ev ${kind} ${ok===true?'ok':ok===false?'err':''}`;
  div.textContent = `[${title}] ${text||''}`;
  box.appendChild(div); box.scrollTop = box.scrollHeight;
  return div;
}
/* ---------- 可折叠操作步骤（工具调用） ---------- */
const TOOL_LABEL = {
  read_file:'读取文件', write_file:'写入文件', edit_file:'编辑文件', apply_patch:'修改文件',
  list_dir:'列目录', list_files:'列目录', shell:'执行命令', run_shell:'执行命令',
  search:'联网搜索', web_search:'联网搜索', browser:'浏览器操作', browse:'浏览器操作',
  rag_search:'检索记忆', comfy:'生成图像/视频', tts_speak:'语音合成', asr:'语音识别',
  schedule:'定时任务', memory_consolidate:'整理记忆'
};
let pendingSteps = [];
function toolLabel(name) { return TOOL_LABEL[name] || (name || '工具'); }
function fmtMs(ms) {
  if (ms == null || !isFinite(ms)) return '';
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}
function appendStep(name, argsText) {
  const box = document.getElementById('messages');
  const d = document.createElement('div');
  d.className = 'step running';
  d.dataset.tool = name || '';
  d.dataset.args = String(argsText || '');
  const oneLine = String(argsText || '').replace(/\s+/g, ' ').slice(0, 80);
  d.innerHTML = `<span class="st-ico"></span>`
    + `<span class="st-name">${esc(toolLabel(name))}</span>`
    + `<span class="st-args">${esc(oneLine || '（无参数）')}</span>`
    + `<span class="st-meta">运行中…</span>`
    + `<button class="st-view" onclick="openStep(this)">详情</button>`;
  box.appendChild(d); box.scrollTop = box.scrollHeight;
  pendingSteps.push(d);
  return d;
}
function finishStep(el, ok, ms, text) {
  el.classList.remove('running');
  el.classList.add(ok ? 'ok' : 'fail');
  el.dataset.ok = ok ? '1' : '0';
  el.dataset.ms = (ms == null) ? '' : String(ms);
  el.dataset.result = String(text || '');
  el.querySelector('.st-meta').textContent =
    `${ok ? '成功' : '失败'}${ms != null ? ' · ' + fmtMs(ms) : ''}`;
}
function finalizeSteps() {
  for (const el of pendingSteps) {
    if (!el.classList.contains('running')) continue;
    el.classList.remove('running');
    el.querySelector('.st-meta').textContent = '已结束（未收到结果）';
    if (!el.dataset.result) el.dataset.result = '(运行结束时仍未返回结果)';
  }
  pendingSteps = [];
}
/* 步骤详情 → 右侧预览，不再在对话框里撑开大段文字 */
function openStep(btn) {
  const el = btn.closest('.step');
  if (!el) return;
  pvDetail(toolLabel(el.dataset.tool), el.dataset.args,
           el.dataset.result || '（执行中…）', el.dataset.ok !== '0', el.dataset.ms);
}

/* ---------- 流水线渲染 ---------- */
function autoBrowserTab() {
  // 出现浏览器/搜索类工具时，自动切到「浏览器」标签并开始实时截图（每个运行只切一次）
  if (!activeRun || !activeRun.events || pvAutoRun === activeRun.id) return;
  const hit = activeRun.events.some(ev =>
    (ev.kind === 'tool_call' || ev.kind === 'tool_args') &&
    /browser|playwright|screenshot|navigate|web_search|web_fetch|fetch_url|open_url/i
      .test(ev.name || ev.tool || ''));
  if (!hit) return;
  pvAutoRun = activeRun.id;
  if (document.getElementById('preview').style.display === 'none') togglePreview(true);
  pvLive();  // 直接连实时画面；浏览器还没起就自动退回截图轮询
}
function renderRun() {
  const bar = document.getElementById('planbar');
  const panel = document.getElementById('runexpand');
  if (!activeRun || !activeRun.id) {
    bar.style.display='none';
    panel.className = ''; panel.innerHTML = '';
    return;
  }
  bar.style.display = 'flex';
  autoBrowserTab();
  const isChat = activeRun.plan && activeRun.plan.kind === 'chat';
  let html = '';
  if (isChat) {
    // 对话运行图：从事件流推导节点（决策 → 模型切换 → 对话执行 → 工具 → 收尾）
    const nodes = [];
    let llmSeen = false, llmDone = false;
    for (const ev of activeRun.events || []) {
      if (ev.kind === 'decision') nodes.push({label:'◆ ' + esc(ev.key || '决策'), st:'done'});
      else if (ev.kind === 'service') nodes.push({label:esc((ev.msg||'').slice(0,16)), st: ev.ok===false?'err':'done'});
      else if (ev.kind === 'round') llmSeen = true;
      else if (ev.kind === 'tool_call') {
        // 同名工具连续调用折叠成 ⚒ name ×N，避免长任务把步骤条撑爆
        const lastTool = [...nodes].reverse().find(n => n.tool);
        if (lastTool && lastTool.tool === ev.name && lastTool.st !== 'running') {
          lastTool.n = (lastTool.n || 1) + 1;
          lastTool.label = '⚒ ' + esc(ev.name || '') + ' ×' + lastTool.n;
          lastTool.st = 'running';
        } else {
          nodes.push({label:'⚒ ' + esc(ev.name||''), st:'running', tool:ev.name});
        }
      }
      else if (ev.kind === 'tool_result') {
        const n = [...nodes].reverse().find(n => n.st === 'running' && n.tool === ev.name);
        if (n) n.st = ev.ok ? 'done' : 'err';
      }
      else if (ev.kind === 'answer') {
        llmDone = true;
        nodes.push({label: ev.status === 'done' ? '✔ 完成'
                      : '✖ ' + esc(RUN_STATUS_CN[ev.status] || ev.status || ''),
                    st: ev.status === 'done' ? 'done' : 'err'});
      }
      else if (ev.kind === 'error') { llmDone = true; nodes.push({label:'✖ 错误', st:'err'}); }
    }
    if (llmSeen || (activeRun.status === 'running' && nodes.length))
      nodes.splice(1, 0, {label:'◉ 对话 ' + esc(activeRun.model_key || ''), st: llmDone ? 'done' : 'running', chat:true});
    // 当前选中的子调用 → 运行条上对应的工具 chip 同步高亮
    let selToolName = expandCallName || '';
    if (!selToolName && expandTip) {
      const parts = String(expandTip).split(':');
      const st = stepStats(activeRun).find(x => String(x.i) === parts[1]);
      const ck = (parts[2] || '').match(/^c(\d+)$/);
      if (st && ck && st.calls[+ck[1]]) selToolName = st.calls[+ck[1]].name;
    }
    // 工具/对话节点可点：都同步打开展开视图并定位到对应节点
    html = nodes.map(n => n.chat
      ? `<span class="pstep ${n.st} clickable" style="cursor:pointer" `
        + `onclick="pvChat()" title="点击查看每轮推理与用量">${n.label}</span>`
      : n.tool
      ? `<span class="pstep ${n.st} clickable${selToolName === n.tool ? ' sel' : ''}" style="cursor:pointer" `
        + `data-tool="${esc(n.tool)}" onclick="pvTool(this.dataset.tool)" `
        + `title="点击查看该工具的逐次调用明细">${n.label}</span>`
      : `<span class="pstep ${n.st}">${n.label}</span>`
    ).join('<span class="parrow">→</span>');
  } else {
    const steps = (activeRun.plan && activeRun.plan.steps) || [];
    const stMap = {};
    for (const ev of activeRun.events || []) {
      if (ev.kind === 'step_start') stMap[ev.i] = 'running';
      if (ev.kind === 'step_done') stMap[ev.i] = ev.ok ? 'done' : 'err';
    }
    html = steps.map((s, i) =>
      `<span class="pstep clickable ${stMap[i]||''}" style="cursor:pointer" `
      + `onclick="pvStep(${i})" title="点击查看本步骤明细">${i+1}. ${esc(s.goal.slice(0,18))}·${esc(s.tool)}</span>`
    ).join('<span class="parrow">→</span>');
  }
  html += `<span class="ptokens" title="整个任务累计（含历史运行）；本次 ${activeRun.prompt_tokens||0}+${activeRun.completion_tokens||0}">任务 tokens ${taskTokens()}</span>`;
  if (currentSession) html += `<button onclick="showRunHistory()" title="回看本任务历次运行及其 token">◷ 历史</button>`;
  if (activeRun.status === 'running' && !isChat) html += `<button id="cancel-run" onclick="cancelRun()">取消</button>`;
  html += `<button class="pexpand" onclick="toggleExpand()">${expandOpen ? '收起 ▴' : '展开 ▾'}</button>`;
  bar.innerHTML = html;
  renderExpand();
}

/* ---------- 运行图 · 展开视图（框图：任务 / 模型 / 步骤 / tokens） ---------- */
function toggleExpand() { expandOpen = !expandOpen; renderRun(); }

/* 整个任务的累计 token（历史运行 + 正在跑的这次） */
function taskTokens() {
  const live = (activeRun && activeRun.status === 'running')
    ? (activeRun.prompt_tokens || 0) + (activeRun.completion_tokens || 0) : 0;
  return (sessionUsage.prompt || 0) + (sessionUsage.completion || 0) + live;
}

/* ---------- 历史运行：运行图已落库，可回看任意一次 ---------- */
async function showRunHistory() {
  if (!currentSession) return;
  let runs = [];
  try {
    const r = await fetch(`/api/run_list?session_id=${currentSession}`);
    runs = await r.json();
  } catch (e) { runs = []; }
  if (!Array.isArray(runs) || !runs.length) {
    pvCustom('<h3>◷ 历史运行</h3><div style="font-size:12px;color:var(--dim)">暂无已保存的运行记录。</div>');
    return;
  }
  const rows = runs.map(x => {
    const tok = (x.prompt_tokens || 0) + (x.completion_tokens || 0);
    const st = x.status === 'done' ? '完成' : (x.status === 'running' ? '进行中' : '中止');
    const cls = x.status === 'done' ? 'ok' : (x.status === 'running' ? 'run' : 'err');
    const cur = activeRun && activeRun.id === x.run_id;
    const row = `<div class="re-sub-row ${cls}" style="cursor:pointer${cur ? ';box-shadow:inset 0 0 0 1px var(--accent)' : ''}" `
      + `onclick="loadRun('${x.run_id}')" title="回看这次运行的完整运行图">`
      + `<span class="k">${esc((x.started_at || x.updated_at || '').slice(5, 16))}</span>`
      + `<span class="n">${esc(x.task || '(无任务描述)')}</span>`
      + `<span class="m">${st} · ${tok} tok</span></div>`;
    // 报错留档：历史里直接能看到失败原因，不用点进去翻事件
    const errLine = x.error
      ? `<div style="padding:0 8px 6px;font-size:11px;color:#ff9a9a;line-height:1.4">⚠ ${esc(x.error)}</div>`
      : '';
    return `<div>${row}${errLine}</div>`;
  }).join('');
  const sum = runs.reduce((a, x) => a + (x.prompt_tokens || 0) + (x.completion_tokens || 0), 0);
  pvCustom(`<h3>◷ 历史运行（${runs.length}）</h3>
    <div style="font-size:11px;color:var(--dim)">本任务累计 ${sum} tok（prompt + completion）。`
    + `点击任一运行回看当时的运行图与逐节点 token。</div>
    <h4>运行记录</h4><div class="re-subs">${rows}</div>`);
}

async function loadRun(runId) {
  const r = await fetch(`/api/run_status?run_id=${runId}`);
  const run = await r.json();
  if (!run || !run.id) return;
  if (runPoll) { clearInterval(runPoll); runPoll = null; }
  activeRun = run;
  expandSel = null;
  expandTip = null;
  expandSels = null;
  expandCallName = '';
  renderRun(); renderExpand(); renderThinking(); renderLive(); renderDraft();
  if (run.status === 'running') startRunPoll();  // 历史运行静默展示，不轮询
}
async function refreshUsage() {
  if (!currentSession) return;
  try {
    const r = await fetch(`/api/usage?session_id=${currentSession}`);
    const u = (await r.json())[0] || {};
    sessionUsage = {prompt: u.prompt_tokens || 0, completion: u.completion_tokens || 0};
  } catch (e) { /* 下次刷新再补 */ }
}

const RUN_STATUS_CN = {running:'运行中', done:'已完成', error:'失败', cancelled:'已取消',
  max_rounds:'轮数用完（未完成）', empty_answer:'空回答（上下文占满，未完成）',
  llm_error:'模型调用失败', time_budget:'超时中止', token_budget:'token 用尽中止',
  interrupted:'中断'};
function runStatusCls(st) {
  return st === 'running' ? 'run' : st === 'done' ? '' : st === 'cancelled' ? 'idle' : 'err';
}
function runElapsed(run) {
  if (!run.started_at) return '';
  const t0 = new Date(String(run.started_at).replace(' ', 'T')).getTime();
  const t1 = run.finished_at ? new Date(String(run.finished_at).replace(' ', 'T')).getTime() : Date.now();
  if (!isFinite(t0) || !isFinite(t1)) return '';
  const s = Math.max(0, Math.round((t1 - t0) / 1000));
  return s >= 60 ? `${Math.floor(s/60)}m${String(s%60).padStart(2,'0')}s` : `${s}s`;
}
/* 事件流 → 模型/工具/轮次/token 汇总（token 总量以 run 累计值为准） */
function summarizeRun(run) {
  const out = {models:new Map(), tools:new Map(), rounds:0, prompt:0, completion:0,
               decision:'', errors:0, toolCalls:0};
  let cur = run.model_key || '';
  const modelOf = k => {
    k = k || '（未知模型）';
    if (!out.models.has(k)) out.models.set(k, {key:k, rounds:0, prompt:0, completion:0});
    return out.models.get(k);
  };
  const toolOf = n => {
    n = n || '未知工具';
    if (!out.tools.has(n)) out.tools.set(n, {name:n, n:0, ok:0, err:0, ms:0, brief:''});
    return out.tools.get(n);
  };
  if (cur) modelOf(cur);
  for (const ev of run.events || []) {
    if (ev.kind === 'decision') {
      out.decision = ev.msg || ('模型选择 → ' + (ev.key || ''));
      if (ev.key) { cur = ev.key; modelOf(cur); }
    } else if (ev.kind === 'service' && ev.action === 'switch_llm' && ev.ok !== false) {
      if (ev.model) { cur = ev.model; modelOf(cur); }
    } else if (ev.kind === 'round') {
      out.rounds = Math.max(out.rounds, ev.i || 0);
      const m = modelOf(cur); m.rounds = Math.max(m.rounds, ev.i || 0);
    } else if (ev.kind === 'llm') {
      out.prompt += ev.prompt || 0; out.completion += ev.completion || 0;
      const m = modelOf(cur);
      m.prompt += ev.prompt || 0; m.completion += ev.completion || 0;
      m.rounds = Math.max(m.rounds, ev.i || 0);
    } else if (ev.kind === 'tool_call') {
      out.toolCalls++; toolOf(ev.name || ev.tool).n++;
    } else if (ev.kind === 'tool_result') {
      const t = toolOf(ev.name || ev.tool);
      t.n = Math.max(t.n, t.ok + t.err);
      if (ev.ok) t.ok++; else { t.err++; out.errors++; }
      t.ms += ev.ms || 0; t.brief = ev.brief || t.brief;
    } else if (ev.kind === 'error') {
      out.errors++;
    }
  }
  out.prompt = run.prompt_tokens || out.prompt;
  out.completion = run.completion_tokens || out.completion;
  out.total = out.prompt + out.completion;
  return out;
}
/* 事件流 → 每个「大步骤」的用量与动作（对话按轮次，流水线按计划步骤） */
function stepStats(run) {
  const isChat = run.plan && run.plan.kind === 'chat';
  const out = [];
  const byI = new Map();
  const ensure = (i, label, tool) => {
    const key = (i == null) ? 0 : i;
    if (!byI.has(key)) {
      byI.set(key, {i:key, label: label || (isChat ? '执行' : `步骤 ${key + 1}`),
                    tool: tool || '', status:'', prompt:0, completion:0, ms:0,
                    calls:[], rounds:[], brief:'', error:''});
      out.push(byI.get(key));
    }
    const rec = byI.get(key);
    if (label) rec.label = label;
    if (tool) rec.tool = tool;
    return rec;
  };
  if (!isChat) {
    ((run.plan && run.plan.steps) || []).forEach((st, i) =>
      ensure(i, `${i + 1}. ${String(st.goal || '').slice(0, 22)}`, st.tool));
  }
  for (const ev of run.events || []) {
    if (ev.kind === 'round') {
      if (ev.i != null && isChat) ensure(ev.i, `第 ${ev.i} 轮`);
    } else if (ev.kind === 'step_start') {
      // 验收节点用大序号（>=1000），单独命名，别显示成"第 1001 步"
      const lab = ev.tool === 'verify'
        ? (ev.i > 1000 ? `验收 · 第 ${ev.i - 999} 次` : '验收')
        : `${(ev.i || 0) + 1}. ${String(ev.goal || '').slice(0, 22)}`;
      ensure(ev.i, lab, ev.tool).status = 'running';
    } else if (ev.kind === 'tokens' || ev.kind === 'llm') {
      const r = ensure(ev.i, null);
      r.prompt += ev.prompt || 0;
      r.completion += ev.completion || 0;
      // 细分节点：本轮推理的 token 用量，供展开视图逐轮展示
      r.rounds.push({i: ev.i, p: ev.prompt || 0, c: ev.completion || 0});
    } else if (ev.kind === 'tool_call') {
      ensure(ev.i, null).calls.push(
        {name: ev.name || ev.tool || '工具', args: ev.args || '', ok: null, ms: 0, text: ''});
    } else if (ev.kind === 'tool_result') {
      const r = ensure(ev.i, null);
      const name = ev.name || ev.tool || '工具';
      const hit = [...r.calls].reverse().find(x => x.name === name && x.ok === null);
      // 只补结果相关字段，别把 tool_call 记下的参数覆盖掉
      const rec = {ok: ev.ok, ms: ev.ms || 0, text: ev.text || ev.brief || ''};
      if (hit) Object.assign(hit, rec); else r.calls.push({name, args: '', ...rec});
    } else if (ev.kind === 'step_done') {
      const r = ensure(ev.i, null);
      r.status = ev.ok === false ? 'err' : 'done';
      r.ms = ev.ms || r.ms;
      r.brief = ev.brief || r.brief;
    } else if (ev.kind === 'error') {
      const r = ensure(ev.i, null);
      r.status = 'err';
      r.error = ev.msg || '';
    }
  }
  // 对话没有 step_start/done：按是否有 token / 调用判定状态
  for (const r of out) {
    if (!r.status) r.status = (r.prompt || r.completion || r.calls.length) ? 'done' : 'idle';
  }
  out.sort((a, b) => a.i - b.i);
  return out;
}
function trimText(s, n) {
  s = String(s || '');
  return s.length > n ? s.slice(0, n) + '\n…（已截断）' : s;
}
/* 点某个大步骤 → 预览明细 + 展开视图同步选中（自动展开该步的子节点） */
function pvStep(i) {
  const run = activeRun;
  if (!run) return;
  const key = `${run.id}:${i}`;
  if (expandSel === key && !expandTip && !expandCallName && !expandSels) {  // 再点一次：收起子节点
    expandSel = null; renderRun(); return;
  }
  const st = stepStats(run).find(x => x.i === i);
  if (!st) return;
  expandSel = key;
  expandTip = null;
  expandSels = null;
  expandCallName = '';
  expandOpen = true;       // 预览联动：点步骤时展开视图必须打开并高亮这一步
  expandScroll = true;
  renderRun();             // 重绘运行条 + 展开视图（选中态、子节点）
  const tok = st.prompt + st.completion;
  const status = st.status === 'running' ? '进行中' : st.status === 'err' ? '失败'
               : st.status === 'done' ? '完成' : '未开始';
  const calls = st.calls.length ? st.calls.map(c => {
    const okTag = c.ok === null ? '进行中' : c.ok ? '成功' : '失败';
    return `▸ ${c.name} · ${okTag}${c.ms ? ' · ' + fmtMs(c.ms) : ''}`
      + (c.args ? `\n  参数：${trimText(c.args, 200)}` : '')
      + (c.text ? `\n  结果：${trimText(c.text, 500)}` : '');
  }).join('\n\n') : '（本步骤没有工具调用）';
  pvCustom(`<h3>${esc(st.label)}</h3>
    <div style="font-size:11px;color:var(--dim)">${status}${st.ms ? ' · 用时 ' + fmtMs(st.ms) : ''}`
    + ` · tokens ${tok}（prompt ${st.prompt} + completion ${st.completion}）</div>`
    + `<h4>目标 / 工具</h4><div>${esc(st.tool || '模型直接推理，无外部工具')}</div>`
    + `<h4>调用明细</h4><pre>${esc(calls)}</pre>`
    + (st.brief ? `<h4>产出摘要</h4><pre>${esc(trimText(st.brief, 400))}</pre>` : '')
    + (st.error ? `<h4>错误</h4><pre>${esc(trimText(st.error, 400))}</pre>` : ''));
}

/* 点某个工具调用节点 → 只看这一次调用；展开视图同步选中该子节点 */
function pvCall(i, k) {
  const run = activeRun;
  if (!run) return;
  const st = stepStats(run).find(x => x.i === i);
  const c = st && st.calls[k];
  if (!c) return;
  expandSel = `${run.id}:${i}`;
  expandTip = `${run.id}:${i}:c${k}`;
  expandSels = null;
  expandCallName = '';
  expandOpen = true;
  expandScroll = true;
  renderRun();
  const okTag = c.ok === null ? '进行中' : c.ok ? '成功' : '失败';
  pvCustom(`<h3>${esc(c.name)}</h3>
    <div style="font-size:11px;color:var(--dim)">${esc(st.label)} · ${okTag}`
    + `${c.ms ? ' · 用时 ' + fmtMs(c.ms) : ''}</div>`
    + `<h4>参数</h4><pre>${esc(c.args || '（未记录参数）')}</pre>`
    + `<h4>结果</h4><pre>${esc(c.text || '（还没有返回结果）')}</pre>`
    + `<h4>步骤上下文</h4><div style="font-size:11px;color:var(--dim)">`
    + `tokens ${st.prompt + st.completion}（prompt ${st.prompt} + completion ${st.completion}）`
    + `${st.ms ? ' · 步骤用时 ' + fmtMs(st.ms) : ''}</div>`);
}

/* 点某一轮推理 → 预览本轮 token 构成；展开视图同步选中 */
function pvRound(i, k) {
  const run = activeRun;
  if (!run) return;
  const st = stepStats(run).find(x => x.i === i);
  const r = st && st.rounds[k];
  if (!r) return;
  expandSel = `${run.id}:${i}`;
  expandTip = `${run.id}:${i}:r${k}`;
  expandSels = null;
  expandCallName = '';
  expandOpen = true;
  expandScroll = true;
  renderRun();
  pvCustom(`<h3>推理 · 第 ${r.i || 1} 轮</h3>
    <div style="font-size:11px;color:var(--dim)">${esc(st.label)} · 本轮 tokens ${r.p + r.c}`
    + `（prompt ${r.p} + completion ${r.c}）</div>`
    + `<h4>所属步骤</h4><div>${esc(st.tool || '模型直接推理，无外部工具')}</div>`
    + `<h4>步骤累计</h4><div style="font-size:11px;color:var(--dim)">`
    + `tokens ${st.prompt + st.completion} · ${st.calls.length} 次工具调用`
    + `${st.ms ? ' · 用时 ' + fmtMs(st.ms) : ''}</div>`);
}

/* 点顶部工具 chip（如 ⚒ web_search ×5）→ 该工具的汇总：次数/成败/耗时 + 逐次调用入口 */
function pvTool(name) {
  const run = activeRun;
  if (!run) return;
  const steps = stepStats(run);
  const hits = [];
  for (const st of steps)
    st.calls.forEach((c, k) => { if (c.name === name) hits.push({st, k, c}); });
  if (!hits.length) {
    pvCustom(`<h3>⚒ ${esc(name)}</h3><div style="font-size:12px;color:var(--dim)">本次运行还没有该工具的调用记录。</div>`);
    return;
  }
  const okN = hits.filter(h => h.c.ok === true).length;
  const errN = hits.filter(h => h.c.ok === false).length;
  // 展开视图同步：把该工具出现过的所有步骤都展开，并高亮这些步骤里的同名调用行
  const stepIdx = [...new Set(hits.map(h => h.st.i))];
  expandSels = new Set(stepIdx.map(i => `${run.id}:${i}`));
  expandSel = `${run.id}:${stepIdx[0]}`;
  expandTip = null;
  expandCallName = name;
  expandOpen = true;
  expandScroll = true;
  renderRun();
  const ms = hits.reduce((a, h) => a + (h.c.ms || 0), 0);
  // 同一调用所在步骤只计一次 token
  const uniqSteps = [...new Map(hits.map(h => [h.st.i, h.st])).values()];
  const tok = uniqSteps.reduce((a, st) => a + st.prompt + st.completion, 0);
  const rounds = uniqSteps.reduce((a, st) => a + st.rounds.length, 0);
  const rows = hits.map((h, idx) => {
    const okTag = h.c.ok === null ? '进行中' : h.c.ok ? '成功' : '失败';
    const cls = h.c.ok === null ? 'run' : h.c.ok ? 'ok' : 'err';
    return `<div class="re-sub-row ${cls}" style="cursor:pointer" `
      + `onclick="pvCall(${h.st.i},${h.k})" title="点击查看这次调用的完整参数与结果">`
      + `<span class="k">#${idx + 1}</span>`
      + `<span class="n">${esc(h.st.label)}</span>`
      + `<span class="m">${okTag}${h.c.ms ? ' · ' + fmtMs(h.c.ms) : ''}</span></div>`;
  }).join('');
  pvCustom(`<h3>⚒ ${esc(name)}</h3>
    <div style="font-size:11px;color:var(--dim)">共 ${hits.length} 次调用 · 成功 ${okN} · 失败 ${errN}`
    + `${ms ? ' · 总耗时 ' + fmtMs(ms) : ''}`
    + ` · 涉及 ${uniqSteps.length} 个步骤 / ${rounds} 轮推理 · tokens ${tok}</div>`
    + `<h4>逐次调用（点击查看参数与结果）</h4><div class="re-subs">${rows}</div>`);
}

/* 点运行条上的「◉ 对话」→ 展开视图列出每一轮推理及其工具与用量 */
function pvChat() {
  const run = activeRun;
  if (!run) return;
  const steps = stepStats(run);
  expandSels = new Set(steps.map(st => `${run.id}:${st.i}`));
  expandSel = steps.length ? `${run.id}:${steps[0].i}` : null;
  expandTip = null;
  expandCallName = '';
  expandOpen = true;
  expandScroll = true;
  renderRun();
  if (!steps.length) {
    pvCustom(`<h3>◉ 对话执行</h3><div style="font-size:12px;color:var(--dim)">还没有推理轮次。</div>`);
    return;
  }
  const rows = steps.map(st => {
    const acts = st.calls.length ? st.calls.map(c => '⚒ ' + c.name).join(' / ') : '无工具';
    return `<div class="re-sub-row" style="cursor:pointer" onclick="pvStep(${st.i})" title="点击定位到这一轮">`
      + `<span class="k">${esc(st.label)}</span>`
      + `<span class="n">${esc(acts)}</span>`
      + `<span class="m">${st.prompt + st.completion} tok</span></div>`;
  }).join('');
  const s = summarizeRun(run);
  pvCustom(`<h3>◉ 对话执行</h3>
    <div style="font-size:11px;color:var(--dim)">${esc(run.model_key || '未知模型')} · ${s.rounds} 轮推理`
    + ` · tokens ${s.total}（prompt ${s.prompt} + completion ${s.completion}）`
    + `${s.errors ? ' · 失败 ' + s.errors + ' 次' : ''}</div>`
    + `<h4>逐轮明细（点击定位到展开视图）</h4><div class="re-subs">${rows}</div>`);
}

function renderExpand() {
  const panel = document.getElementById('runexpand');
  if (!activeRun || !expandOpen) {
    panel.className = ''; panel.innerHTML = ''; expandScroll = false; return;
  }
  const run = activeRun;
  const s = summarizeRun(run);
  const isChat = run.plan && run.plan.kind === 'chat';
  const stCls = runStatusCls(run.status);
  const elapsed = runElapsed(run);
  const dot = (c) => `<span class="re-dot ${c||''}"></span>`;
  const item = (nm, cap, opts) => {
    opts = opts || {};
    return `<div class="re-item${opts.pending ? ' pending' : ''}${opts.cls ? ' ' + opts.cls : ''}">`
      + `<div class="nm">${opts.dot ? dot(opts.dot) : ''}${nm}</div>`
      + (cap ? `<div class="cap">${cap}</div>` : '') + `</div>`;
  };

  /* ① 任务概述 */
  const statusItem = item(
    dot(stCls) + esc(RUN_STATUS_CN[run.status] || run.status || '-'),
    `运行 ${esc(run.id)} · ${isChat ? '对话执行' : '流水线'}${elapsed ? ' · 用时 ' + elapsed : ''}`
    + (run.started_at ? ' · ' + esc(run.started_at) : ''));
  const taskItem = item(esc((run.task || '（未记录任务）').slice(0, 90)),
    `${esc(run.model_key || '未选模型')} · 会话 ${esc((run.session_id || '').slice(0,8))}`,
    {cls:'task', dot:stCls});

  /* ② 模型调度 */
  let modelItems = '';
  if (s.decision) modelItems += item(dot('') + '决策', esc(s.decision));
  const modelList = [...s.models.values()];
  modelItems += modelList.map(m => {
    const tok = m.prompt + m.completion;
    const cap = m.rounds
      ? `轮次 ${m.rounds} · prompt ${m.prompt} + completion ${m.completion} = ${tok}`
      : (tok ? `prompt ${m.prompt} + completion ${m.completion} = ${tok}` : '待调用');
    return item(dot(m.rounds || tok ? '' : 'idle') + esc(m.key), cap,
                {pending: !(m.rounds || tok)});
  }).join('');
  if (!modelItems) modelItems = item('尚未选择模型', '等待决策', {pending:true});

  /* ③ 步骤与工具（每个大步骤可点，明细进右侧预览） */
  const steps = stepStats(run);
  const selKey = `${run.id}:`;
  const stepDot = st => st.status === 'err' ? 'err' : st.status === 'running' ? 'run'
                       : st.status === 'idle' ? 'idle' : '';
  const stepCap = st => {
    const tok = st.prompt + st.completion;
    const names = [...new Set(st.calls.map(c => c.name).filter(Boolean))];
    return [st.tool && !names.length ? st.tool : names.join(' / '),
            tok ? tok + ' tok' : '', st.ms ? fmtMs(st.ms) : '']
      .filter(Boolean).join(' · ') || '未开始';
  };
  // 细分节点：把大步骤拆成「推理轮次」和「每次工具调用」，都可单独点击看明细，
  // 并在展开视图里高亮当前选中的子节点
  const subRows = st => {
    const rows = [];
    st.rounds.forEach((r, k) => {
      const sel = expandTip === selKey + st.i + ':r' + k;
      rows.push(`<div class="re-sub-row clickable${sel ? ' sel' : ''}" `
        + `title="点击查看本轮 token 构成" style="cursor:pointer" `
        + `onclick="event.stopPropagation();pvRound(${st.i},${k})">`
        + `<span class="k">推理</span>`
        + `<span class="n">第 ${r.i || 1} 轮</span>`
        + `<span class="m">${r.p}+${r.c} tok</span></div>`);
    });
    st.calls.forEach((c, k) => {
      const okTag = c.ok === null ? '进行中' : c.ok ? '成功' : '失败';
      const cls = c.ok === null ? 'run' : c.ok ? 'ok' : 'err';
      const sel = expandTip === selKey + st.i + ':c' + k
               || (!!expandCallName && c.name === expandCallName);
      rows.push(`<div class="re-sub-row clickable ${cls}${sel ? ' sel' : ''}" title="点击查看这次调用的参数与结果"`
        + ` onclick="event.stopPropagation();pvCall(${st.i},${k})">`
        + `<span class="k">工具</span>`
        + `<span class="n">${esc(c.name)}</span>`
        + `<span class="m">${okTag}${c.ms ? ' · ' + fmtMs(c.ms) : ''}</span></div>`);
    });
    if (!rows.length) rows.push(`<div class="re-sub-row idle"><span class="k">状态</span>`
      + `<span class="n">无工具调用</span><span class="m">模型直接推理</span></div>`);
    return `<div class="re-subs">${rows.join('')}</div>`;
  };
  // 子节点默认折叠：只展示选中步骤的推理/工具明细，不再一次全铺开
  const collapsedHint = st => {
    const nR = st.rounds.length, nC = st.calls.length;
    if (!nR && !nC) return '';
    return `<div style="font-size:11px;color:var(--dim);padding:2px 6px">`
      + `▸ ${nR} 轮推理 · ${nC} 次工具，点击展开</div>`;
  };
  const selStep = (st) => expandSel === selKey + st.i
    || (!!expandSels && expandSels.has(selKey + st.i));
  const toolItems = steps.length
    ? steps.map(st => {
        const isSel = selStep(st);
        return `<div class="re-item clickable${isSel ? ' sel' : ''}" `
          + `onclick="pvStep(${st.i})" title="点击查看本步骤明细 / 再点收起">`
          + `<div class="nm">${dot(stepDot(st))}${esc(st.label)}</div>`
          + `<div class="cap">${esc(stepCap(st))}</div>`
          + (isSel ? subRows(st) : collapsedHint(st)) + `</div>`;
      }).join('')
    : item('暂无步骤', '模型直接回答，或不依赖工具', {pending:true});

  /* ④ token 消耗：本次累计 + 每个大步骤用量 */
  const total = s.total || 0;
  const pPct = total ? Math.round(100 * s.prompt / total) : 0;
  const tokenRows = steps.filter(st => st.prompt + st.completion).slice(0, 10).map(st => {
    const t = st.prompt + st.completion;
    const pct = total ? Math.max(3, Math.round(100 * t / total)) : 0;
    return `<div class="re-item clickable${selStep(st) ? ' sel' : ''}"`
      + ` onclick="pvStep(${st.i})" title="点击查看明细">`
      + `<div class="nm"><span class="tok">${t}</span>`
      + `<span style="font-size:11px;color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(st.label)}</span></div>`
      + `<div class="re-bar"><i style="width:${pct}%;background:var(--accent)"></i></div></div>`;
  }).join('');
  const tokenItems =
    `<div class="re-item"><div class="nm">${dot('')}本次运行</div>`
    + `<div class="v">${total}</div>`
    + `<div class="cap">prompt ${s.prompt} + completion ${s.completion}</div>`
    + (total ? `<div class="re-bar"><i style="width:${pPct}%;background:var(--accent)"></i>`
             + `<i style="width:${100-pPct}%;background:var(--ok)"></i></div>` : '')
    + `</div>`
    + (tokenRows ? `<div class="re-sub2">按大步骤</div>` + tokenRows : '')
    + item(dot('') + `${s.rounds} 轮 · ${s.toolCalls || [...s.tools.values()].reduce((a,t)=>a+t.n,0)} 次工具`,
           s.errors ? `失败 ${s.errors} 次${elapsed ? ' · 用时 ' + elapsed : ''}`
                    : `无失败${elapsed ? ' · 用时 ' + elapsed : ''}`);

  panel.className = 'show';
  const keepScroll = panel.scrollTop;
  panel.innerHTML =
    `<div class="re-head"><span class="ttl">模型运行图 · 展开视图</span>`
    + `<span>运行 #${esc(run.id)} · ${esc(RUN_STATUS_CN[run.status] || run.status || '')}</span>`
    + `<span class="legend"><span>${dot('')}已发生</span><span>${dot('run')}进行中</span>`
    + `<span>${dot('err')}失败</span><span>${dot('idle')}未发生</span></span></div>`
    + `<div class="re-grid">`
    + `<section class="re-col"><h4>任务概述</h4><div class="sub">目标 · 状态 · 耗时</div>`
      + taskItem + statusItem + `</section>`
    + `<section class="re-col"><h4>模型调度</h4><div class="sub">决策 · 轮次 · 各自用量</div>`
      + modelItems + `</section>`
    + `<section class="re-col"><h4>步骤与工具</h4><div class="sub">点步骤看右侧明细</div>`
      + toolItems + `</section>`
    + `<section class="re-col"><h4>Token 消耗</h4><div class="sub">本次 ${total} · 任务累计 ${taskTokens()}</div>`
      + tokenItems + `</section>`
    + `</div>`;
  panel.scrollTop = keepScroll;
  // 由点击触发的重绘：把刚选中的节点滚进可视区（轮询重绘不触发，避免页面乱跳）
  if (expandScroll) {
    expandScroll = false;
    const pick = panel.querySelector('.re-sub-row.sel') || panel.querySelector('.re-item.sel');
    if (pick) pick.scrollIntoView({block: 'nearest', behavior: 'smooth'});
  }
}
function renderRunEvents() {
  if (!activeRun) return;
  for (const ev of activeRun.events || []) {
    if (ev._shown) continue; ev._shown = true;
    if (ev.kind === 'phase') appendEv('svc', '阶段', undefined, ev.msg);
    else if (ev.kind === 'decision') appendEv('svc', '决策', true, ev.msg);
    else if (ev.kind === 'round') appendEv('svc', '推理', undefined, ev.msg);
    else if (ev.kind === 'reasoning') appendEv('svc', '思考', undefined, ev.msg);
    else if (ev.kind === 'llm') appendEv('svc', 'token', undefined, ev.msg);
    else if (ev.kind === 'service') appendEv('svc', '服务', ev.ok, `${ev.action} ${ev.model||''} ${ev.msg||''}`);
    else if (ev.kind === 'step_start') appendEv('svc', `步骤${ev.i+1}`, undefined, `${ev.goal} [${ev.tool}]`);
    else if (ev.kind === 'tool_call') appendStep(ev.name || ev.tool, ev.args);
    else if (ev.kind === 'tool_args') appendStep(ev.tool, ev.args);
    else if (ev.kind === 'tool_result') {
      const name = ev.name || ev.tool;
      let el = null;
      for (let k = pendingSteps.length - 1; k >= 0; k--) {
        if (pendingSteps[k].classList.contains('running') && pendingSteps[k].dataset.tool === name) {
          el = pendingSteps[k]; break;
        }
      }
      if (!el) el = appendStep(name, '(参数未记录)');
      finishStep(el, ev.ok, ev.ms, ev.text || ev.brief);
    }
    else if (ev.kind === 'tokens') appendEv('svc', 'token', undefined, `步骤${ev.i+1}: prompt ${ev.prompt} + completion ${ev.completion}`);
    else if (ev.kind === 'step_done') { if (!ev.ok) appendEv('tool', `步骤${ev.i+1}`, false, ev.brief); }
    else if (ev.kind === 'error') { finalizeSteps(); appendEv('tool', '错误', false, ev.msg); }
    else if (ev.kind === 'done') { finalizeSteps(); appendEv('tool', '完成', true, `${ev.msg}，共 ${ev.prompt_tokens}+${ev.completion_tokens} tokens`); }
    else if (ev.kind === 'cancelled') { finalizeSteps(); appendEv('tool', '已取消', false, ev.msg); }
    else if (ev.kind === 'answer') {
      // 对话收尾：最终回复 + 统计（活气泡的使命到此结束）
      finalizeSteps();
      const stats = `轮数 ${ev.rounds||0} · tokens ${(ev.prompt_tokens||0)+(ev.completion_tokens||0)} · ${ev.status||''}`;
      appendMsg('assistant', ev.msg || '', stats);
      renderDraft();
    }
  }
}
/* 流式草稿：运行中把 run.draft 渲染成末尾的活气泡，随轮询逐段变长 */
function renderDraft() {
  const box = document.getElementById('messages');
  let live = document.getElementById('live-draft');
  const txt = (activeRun && activeRun.status === 'running') ? (activeRun.draft || '') : '';
  if (!txt) { if (live) live.remove(); return; }
  if (!live) {
    live = document.createElement('div');
    live.id = 'live-draft';
    live.className = 'msg assistant live';
  }
  live.textContent = txt;
  box.appendChild(live);  // 始终挪到末尾，保证新事件不会插到它后面
  box.scrollTop = box.scrollHeight;
}
/* 思考过程：只留一行摘要，点击进右侧预览看全文 */
let thinkText = '';
function renderThinking() {
  const box = document.getElementById('messages');
  let el = document.getElementById('live-thinking');
  const txt = (activeRun && activeRun.thinking) || '';
  if (!txt) { if (el) el.remove(); return; }
  thinkText = txt;
  if (!el) {
    el = document.createElement('div');
    el.id = 'live-thinking';
    el.className = 'msg thinking';
    el.onclick = pvThinking;
    el.innerHTML = '<span class="th-h">💭 思考过程</span><span class="th-num"></span>';
  }
  el.classList.toggle('live', !!(activeRun && activeRun.status === 'running'));
  el.querySelector('.th-num').textContent = `${txt.length} 字 · 点击查看`;
  const draft = document.getElementById('live-draft');
  box.insertBefore(el, draft || null);
  box.scrollTop = box.scrollHeight;
}
/* 运行中实时状态：阶段名 + 本阶段耗时 + 静默时长 + token + 不确定进度条 */
let liveSig = '', liveAt = 0, liveDraftLen = 0, liveThinkLen = 0;
function evClock(ts) {
  const p = String(ts || '').split(':').map(Number);
  if (p.length < 2 || !isFinite(p[0])) return 0;
  const d = new Date(); d.setHours(p[0], p[1] || 0, p[2] || 0, 0);
  return d.getTime();
}
function currentPhase(run) {
  const evs = run.events || [];
  for (let i = evs.length - 1; i >= 0; i--) {
    const e = evs[i];
    const step = (e.i != null) ? `步骤 ${e.i + 1}` : '';
    switch (e.kind) {
      case 'phase': return e.msg || '进行中…';
      case 'decision': return '决策：选到 ' + (e.key || '模型');
      case 'service':
        if (e.action === 'ensure_llm' || e.action === 'switch_llm')
          return `加载模型 ${e.model || ''}（切换服务中）`;
        return e.msg || e.action || '服务切换';
      case 'round': return `第 ${e.i} 轮推理`;
      case 'reasoning': return `第 ${e.i || ''} 轮 · 模型思考中`;
      case 'llm': return `第 ${e.i} 轮结束，决定下一步`;
      case 'tool_call': return `执行工具 ${e.name || e.tool || ''}（等待返回）`;
      case 'tool_args': return `准备工具 ${e.tool || ''} 参数`;
      case 'tool_result': return `工具 ${e.name || e.tool || ''} 已返回，继续推理`;
      case 'tokens': return `${step || '步骤'} 产出 token`;
      case 'step_start': return `${step}：${(e.goal || '').slice(0, 18)}`;
      case 'step_done': return `${step} ${e.ok ? '完成' : '失败'}`;
      case 'answer': return '生成最终回复';
      case 'error': return '出错：' + (e.msg || '').slice(0, 40);
    }
  }
  return '准备中…';
}
function renderLive() {
  const el = document.getElementById('livestatus');
  const running = activeRun && activeRun.status === 'running';
  if (!running) { el.className = ''; el.innerHTML = ''; el._built = false; return; }
  if (!el._built) {
    el.innerHTML = '<div class="ls-row"><span class="ls-spin"></span>'
      + '<span class="ls-phase"></span><span class="ls-note"></span>'
      + '<span class="ls-meta"></span></div><div class="ls-bar"><i></i></div>';
    el._built = true;
  }
  const evs = activeRun.events || [];
  const last = evs[evs.length - 1] || {};
  const draftLen = (activeRun.draft || '').length;
  const thinkLen = (activeRun.thinking || '').length;
  const sig = evs.length + '|' + (last.ts || '') + '|' + (last.kind || '');
  if (sig !== liveSig || draftLen !== liveDraftLen || thinkLen !== liveThinkLen) {
    liveSig = sig; liveDraftLen = draftLen; liveThinkLen = thinkLen;
    liveAt = Date.now();
  }
  const now = Date.now();
  const sincePhase = Math.max(0, Math.round((now - (evClock(last.ts) || liveAt || now)) / 1000));
  const silent = Math.max(0, Math.round((now - (liveAt || now)) / 1000));
  const tokens = (activeRun.prompt_tokens || 0) + (activeRun.completion_tokens || 0);
  el.className = 'show';
  el.querySelector('.ls-phase').textContent = currentPhase(activeRun);
  el.querySelector('.ls-note').textContent = thinkLen ? `思考 ${thinkLen} 字`
    : draftLen ? `已输出 ${draftLen} 字` : '尚无文字输出';
  el.querySelector('.ls-meta').textContent =
    `本阶段 ${sincePhase}s · 静默 ${silent}s · tokens ${tokens}`;
}
async function planRun() {
  const text = document.getElementById('input').value.trim();
  if (!text) return;
  if (attachedPath) { /* 附件路径随消息带上 */ }
  document.getElementById('input').value = '';
  appendMsg('user', text);
  setBusy(true);
  const r = await fetch('/api/plan_run', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({session_id: currentSession, message: text + (attachedPath?`\n[附件] ${attachedPath}`:'')})});
  const data = await r.json();
  attachedPath = null; document.getElementById('attach-chip').style.display='none';
  if (data.session_id && !currentSession) {
    currentSession = data.session_id; sessionUsage = {prompt:0, completion:0}; loadSessions();
  }
  if (data.route) appendEv('svc', '路由器', true, `→ ${data.route.key}：${data.route.reason||''}`);
  if (data.run_id) {
    activeRun = {id:data.run_id, events:[], status:'running'};
    startRunPoll();
  } else {
    appendMsg('assistant', data.error || '启动失败');
    setBusy(false);
  }
}
function startRunPoll() {
  if (runPoll) clearInterval(runPoll);
  if (!activeRun) return;
  runPoll = setInterval(async () => {
    if (!activeRun) { clearInterval(runPoll); return; }
    const r = await fetch(`/api/run_status?run_id=${activeRun.id}`);
    const run = await r.json();
    if (!run || !run.id) return;
    run.events = run.events.map(e => { e._shown = false; return e; });
    const ekey = e => e.ts + e.kind + (e.i||'') + ((e.msg||e.brief||e.args||'')+'').slice(0,20);
    const shown = new Set();
    for (const e of (activeRun.events||[])) if (e._shown) shown.add(ekey(e));
    for (const e of run.events) if (shown.has(ekey(e))) e._shown = true;
    activeRun = run;
    renderRun(); renderRunEvents(); renderDraft(); renderThinking(); renderLive();
    if (run.status !== 'running') {
      clearInterval(runPoll); runPoll = null; setBusy(false);
      loadSessions();  // 后台自动起的 AI 标题也该刷新了
      loadFiles();     // 产出列表刷新，新文件出现在右下角
      refreshUsage().then(() => renderRun());  // 右上角任务 tokens 计入本次
      renderDraft();   // 清掉活气泡（answer 事件已渲染最终回复）
      renderThinking(); renderLive();
      // 流水线完成 → 重载会话把各步产出的助手消息刷进消息流；
      // 对话不重载（answer 事件已带最终回复，重载反而丢事件现场）
      const isChat = run.plan && run.plan.kind === 'chat';
      if (currentSession && !isChat) selectSession(currentSession);
    }
  }, 800);
}
async function cancelRun() {
  if (!activeRun) return;
  await fetch('/api/run_cancel', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({run_id: activeRun.id})});
}

/* ---------- 普通对话（异步：事件流实时可见） ---------- */
async function send() {
  const input = document.getElementById('input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  let full = text + (attachedPath ? `\n[附件] ${attachedPath}` : '');
  attachedPath = null; document.getElementById('attach-chip').style.display='none';
  appendMsg('user', text);
  setBusy(true);
  try {
    const r = await fetch('/api/chat', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({session_id: currentSession, message: full, kb: kbSelected()})});
    const data = await r.json();
    if (data.session_id && !currentSession) {
      currentSession = data.session_id; sessionUsage = {prompt:0, completion:0}; loadSessions();
    }
    if (data.run_id) {
      activeRun = {id:data.run_id, events:[], status:'running'};
      startRunPoll();
    } else {
      appendMsg('assistant', data.error || '启动失败');
      setBusy(false);
    }
  } catch (e) {
    appendMsg('assistant', '请求失败: ' + e.message);
    setBusy(false);
  }
}
function setBusy(b) {
  document.getElementById('send').disabled = b;
  document.getElementById('plan-run').disabled = b;
}

/* ---------- 附件 ---------- */
async function uploadFile(input) {
  if (!input.files.length) return;
  const fd = new FormData();
  fd.append('session_id', currentSession || '');
  fd.append('file', input.files[0]);
  const r = await fetch('/api/upload', {method:'POST', body: fd});
  const data = await r.json();
  if (data.ok) {
    attachedPath = data.path;
    const chip = document.getElementById('attach-chip');
    chip.style.display = 'block';
    chip.textContent = '已上传：' + data.path;
  } else {
    alert('上传失败: ' + (data.error||''));
  }
  input.value = '';
}

/* ---------- 资源 / 服务 / 模型 / MCP ---------- */
async function refreshResources() {
  try {
    const r = await fetch('/api/resources');
    const d = await r.json();
    document.getElementById('r-cpu').textContent = d.cpu + '%';
    document.getElementById('r-ram').textContent = `${d.ram_used}/${d.ram_total}G`;
    document.getElementById('r-vram').textContent =
      d.vram_used !== undefined ? `${(d.vram_used/1024).toFixed(1)}/${(d.vram_total/1024).toFixed(1)}G` : 'N/A';
    document.getElementById('r-gpu').textContent = d.gpu_util !== undefined ? d.gpu_util + '%' : 'N/A';
  } catch (e) {}
}
async function refreshServices() {
  try {
    const r = await fetch('/api/services');
    const d = await r.json();
    setDot('d-llm', d.llm.online);
    document.getElementById('llm-name').textContent = 'LLM: ' + (d.llm.model || '离线');
    setDot('d-comfy', d.comfy.online);
    setDot('d-embed', d.embed.online);
    setDot('d-rerank', d.rerank.online);
    if (d.log && d.log.length) document.getElementById('svc-log').textContent = d.log.join('\n');
  } catch (e) {}
}
function setDot(id, on) {
  const el = document.getElementById(id);
  el.className = 'dot ' + (on ? 'on' : 'off');
}
async function loadModels() {
  const r = await fetch('/api/models');
  const data = await r.json();
  document.getElementById('model-list').innerHTML = data.map(m =>
    `<div class="model-item ${m.active?'active':''}">
      <div class="mname">${esc(m.name)}<span class="mtask">${esc(m.task)}</span></div>
      ${m.active ? '' : `<button class="svc-btn" onclick="svc('start_llm','${m.key}')">切换</button>`}
    </div>`).join('');
}
async function svc(action, key) {
  await fetch('/api/service', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({action, key})});
  setTimeout(refreshServices, 800);
  setTimeout(loadModels, 800);
}
async function loadMcp() {
  const r = await fetch('/api/mcp');
  const data = await r.json();
  const el = document.getElementById('mcp-list');
  if (!Array.isArray(data) || !data.length) {
    el.innerHTML = '<div class="mcp-item">（未安装）</div>';
    return;
  }
  el.innerHTML = data.map(m => {
    const dot = m.mounted ? 'on' : (m.enabled ? 'off' : '');
    // 扫描项不可启停，状态直接用后端给的说明，绝不显示"启用中"
    const st = m.mounted ? `已挂载 ${m.tools} 工具`
      : (m.source === 'scan' ? (m.note || '已安装')
        : (m.enabled ? '启用中…' : (m.note || '未启用')));
    const peer = m.peer ? `<span class="peer" title="对标 ${esc(m.peer)}">${esc(m.peer)}</span>` : '';
    const btn = m.source === 'config'
      ? `<button class="svc-btn" data-mcp="${esc(m.name)}" data-en="${m.enabled ? 1 : 0}">${m.enabled ? '停用' : '启用'}</button>`
      : '';
    return `<div class="mcp-row"><span class="dot ${dot}"></span>
      <span class="name" title="${esc(m.name)}">${esc(m.name)}</span>${peer}
      <span class="st">${esc(st)}</span>${btn}</div>`;
  }).join('');
  el.querySelectorAll('[data-mcp]').forEach(b => {
    b.onclick = () => toggleMcp(b.dataset.mcp, b.dataset.en !== '1');
  });
}
async function toggleMcp(name, enabled) {
  const r = await fetch('/api/mcp/toggle', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({name, enabled})});
  const d = await r.json();
  if (!d.ok) alert(d.msg || '操作失败');
  loadMcp();
}

async function consolidateMemory() {
  if (!currentSession) return;
  if (!confirm('把该任务归档的历史片段蒸馏成记忆卡（MEMORY.md）？需要 LLM 与 Embed 在线。')) return;
  const r = await fetch('/api/memory/consolidate', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({session_id: currentSession})});
  const d = await r.json();
  alert(d.msg || (d.ok ? '完成' : '失败'));
}

/* ---------- 全局知识库（左侧管理 + 勾选注入） ---------- */
let kbData = {categories: []};
let kbSel = new Set();
let kbEditTarget = null;
function kbMasterOn() {
  const el = document.getElementById('kb-master');
  return !!(el && el.checked);
}
function kbSelected() {
  return kbMasterOn() ? Array.from(kbSel) : [];
}
function kbSelChanged() {
  localStorage.setItem('kbMaster', kbMasterOn() ? '1' : '');
  const list = document.getElementById('kb-list');
  if (list) list.style.opacity = kbMasterOn() ? 1 : .5;
}
async function loadKb() {
  try {
    const r = await fetch('/api/kb');
    kbData = await r.json();
  } catch (e) { return; }
  try {
    const saved = JSON.parse(localStorage.getItem('kbCats') || '[]');
    if (Array.isArray(saved)) kbSel = new Set(saved);
  } catch (e) {}
  const list = document.getElementById('kb-list');
  list.innerHTML = kbData.categories.map((c, ci) => `
    <div class="kb-cat">
      <label class="kb-head">
        <input type="checkbox" ${kbSel.has(c.name) ? 'checked' : ''} onchange="kbToggle(${ci}, this)">
        <span class="dot-c"></span><span>${esc(c.name)}</span>
        <span class="cnt">${c.files.length}</span>
      </label>
      <div class="kb-files">${c.files.map((f, fi) =>
        `<div class="kb-file" onclick="kbOpenFile(${ci}, ${fi})">
          <span class="fname">${esc(f.name)}</span>
          <button class="del" onclick="event.stopPropagation();kbDeleteFile(${ci}, ${fi})">×</button>
        </div>`).join('') || '<div class="kb-hint">（空）</div>'}
      </div>
    </div>`).join('') || '<div class="kb-hint">（暂无门类，点「+ 门类」新建）</div>';
  list.style.opacity = kbMasterOn() ? 1 : .5;
}
function kbToggle(ci, el) {
  const c = kbData.categories[ci];
  if (!c) return;
  if (el.checked) kbSel.add(c.name); else kbSel.delete(c.name);
  localStorage.setItem('kbCats', JSON.stringify(Array.from(kbSel)));
}
function kbOpenFile(ci, fi) {
  const c = kbData.categories[ci];
  const f = c && c.files[fi];
  if (!f) return;
  fetch(`/api/kb/read?category=${encodeURIComponent(c.name)}&name=${encodeURIComponent(f.name)}`)
    .then(r => r.json())
    .then(d => kbShowEditor(c.name, f.name, d.content || ''))
    .catch(() => kbShowEditor(c.name, f.name, ''));
}
function kbShowEditor(cat, name, content) {
  kbEditTarget = {cat, name};
  pvCustom(`<h3>📚 ${esc(cat)} / ${esc(name)}</h3>
    <textarea id="kb-editor">${esc(content || '')}</textarea>
    <div class="pv-actions">
      <button class="mini-btn" style="width:auto;margin-top:0" onclick="kbSaveCurrent()">保存</button>
      <span id="kb-save-note" style="font-size:11px;color:var(--dim)">memory/knowledge/${esc(cat)}/</span>
    </div>`);
}
async function kbSaveCurrent() {
  if (!kbEditTarget) return;
  const box = document.getElementById('kb-editor');
  if (!box) return;
  const r = await fetch('/api/kb/save', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({category: kbEditTarget.cat, name: kbEditTarget.name, content: box.value})});
  const d = await r.json();
  const note = document.getElementById('kb-save-note');
  if (d.ok) {
    kbEditTarget = {cat: d.category, name: d.name};
    if (note) note.textContent = '已保存';
    loadKb();
  } else if (note) note.textContent = d.msg || '保存失败';
}
function kbNewCategory() {
  const name = prompt('新门类名称（如 工作规则 / 项目知识 / 全局记忆）');
  if (!name || !name.trim()) return;
  fetch('/api/kb/category', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name: name.trim()})})
    .then(r => r.json()).then(d => { if (!d.ok) alert(d.msg || '创建失败'); loadKb(); });
}
function kbNewFile() {
  if (!kbData.categories.length) { alert('请先新建一个门类'); return; }
  const names = kbData.categories.map(c => c.name);
  const cat = prompt('归档到哪个门类？\n' + names.join(' / '), names[0]);
  if (!cat) return;
  const name = prompt('文件名（.md / .txt）', '新知识.md');
  if (!name) return;
  kbShowEditor(cat.trim(), name.trim(), '');
}
async function kbDeleteFile(ci, fi) {
  const c = kbData.categories[ci];
  const f = c && c.files[fi];
  if (!f || !confirm(`删除知识文件「${f.name}」？`)) return;
  await fetch('/api/kb/delete', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({category: c.name, name: f.name})});
  loadKb();
}

// ---- 右侧预览：文件 / 浏览器 两个标签 ----
let pvLiveTimer = null;
let pvTabCur = 'files';
let pvAutoRun = null;  // 已经自动切过浏览器标签的运行
function pvStopLive() {
  if (pvLiveTimer) { clearInterval(pvLiveTimer); pvLiveTimer = null; }
  const img = document.getElementById('pv-img');
  const src = img && img.getAttribute('src');
  if (src && src.indexOf('/api/live') === 0) img.removeAttribute('src');  // 断开 MJPEG 长连接
}
// 浏览器画面放大：把同一个 <img> 节点搬进全屏浮层（MJPEG 连接不断开，不重复占带宽）
let pvZoomed = false;
function pvZoom(on) {
  const overlay = document.getElementById('pv-zoom');
  const img = document.getElementById('pv-img');
  if (on) {
    if (pvTabCur !== 'browser' || img.style.display === 'none' || !img.getAttribute('src')) return;
    img.classList.remove('live');
    document.getElementById('pv-zoom-body').appendChild(img);
    overlay.classList.add('show');
    pvZoomed = true;
  } else if (pvZoomed) {
    document.getElementById('pv-body').insertBefore(img, document.getElementById('pv-vid'));
    overlay.classList.remove('show');
    img.classList.add('live');
    pvZoomed = false;
  }
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') pvZoom(false); });
function pvClear() {
  pvStopLive();
  const frame = document.getElementById('pv-frame'),
        img = document.getElementById('pv-img'),
        vid = document.getElementById('pv-vid'),
        aud = document.getElementById('pv-aud'),
        empty = document.getElementById('pv-empty');
  img.classList.remove('live');
  frame.style.display = 'none'; img.style.display = 'none';
  vid.style.display = 'none'; aud.style.display = 'none';
  vid.pause(); aud.pause();
  document.getElementById('pv-custom').classList.remove('show');
  document.getElementById('pv-browser-empty').style.display = 'none';
  empty.style.display = 'flex';
}
function pvTab(which) {
  const prev = pvTabCur;
  pvTabCur = which;
  document.getElementById('pv-tab-files').classList.toggle('active', which === 'files');
  document.getElementById('pv-tab-browser').classList.toggle('active', which === 'browser');
  document.getElementById('pv-urlbar').style.display = which === 'browser' ? 'flex' : 'none';
  document.getElementById('pv-files-wrap').style.display = which === 'files' ? 'block' : 'none';
  if (which === 'browser') {
    if (!pvLiveTimer) pvLive();
  } else {
    pvStopLive();
    if (prev === 'browser') pvClear();
  }
}
function pvLive() {
  // 优先看 CDP 实时画面（MJPEG），浏览器没开/流中断时自动退回 2 秒截图轮询
  pvTabCur = 'browser';
  document.getElementById('pv-urlbar').style.display = 'flex';
  document.getElementById('pv-files-wrap').style.display = 'none';
  document.getElementById('pv-tab-files').classList.remove('active');
  document.getElementById('pv-tab-browser').classList.add('active');
  const img = document.getElementById('pv-img');
  const hint = document.getElementById('pv-browser-empty');
  pvStopLive();
  img.style.display = 'block';
  img.classList.add('live');  // 浏览器画面可点击放大
  const fallback = () => {
    pvStopLive();
    img.onerror = null;
    hint.innerHTML = '暂无实时画面<br>浏览器未运行时改为每 2 秒截图';
    img.onerror = () => { img.style.display = 'none'; hint.style.display = 'flex'; };
    img.onload = () => { hint.style.display = 'none'; };
    img.src = '/api/preview?t=' + Date.now();
    pvLiveTimer = setInterval(() => { img.src = '/api/preview?t=' + Date.now(); }, 2000);
  };
  img.onerror = () => fallback();  // /api/live 503 或长连接被浏览器关掉
  img.onload = () => { hint.style.display = 'none'; };
  img.src = '/api/live?t=' + Date.now();
}
function togglePreview(on) {
  document.getElementById('preview').style.display = on ? 'flex' : 'none';
  document.getElementById('pv-show').style.display = on ? 'none' : 'block';
  localStorage.setItem('preview', on ? 'on' : 'off');
  if (!on) pvStopLive();
  if (on) loadFiles();
}
function pvShow(which, src) {
  pvStopLive();
  const frame = document.getElementById('pv-frame'),
        img = document.getElementById('pv-img'),
        vid = document.getElementById('pv-vid'),
        aud = document.getElementById('pv-aud'),
        empty = document.getElementById('pv-empty');
  document.getElementById('pv-custom').classList.remove('show');
  document.getElementById('pv-browser-empty').style.display = 'none';
  empty.style.display = 'none';
  frame.style.display = which === 'frame' ? 'block' : 'none';
  img.style.display = which === 'img' ? 'block' : 'none';
  vid.style.display = which === 'vid' ? 'block' : 'none';
  aud.style.display = which === 'aud' ? 'block' : 'none';
  if (which !== 'vid') vid.pause();
  if (which !== 'aud') aud.pause();
  if (which === 'frame') { frame.src = src; vid.removeAttribute('src'); aud.removeAttribute('src'); }
  else if (which === 'img') { img.src = src; vid.removeAttribute('src'); aud.removeAttribute('src'); }
  else if (which === 'vid') { vid.src = src; img.removeAttribute('src'); }
  else if (which === 'aud') { aud.src = src; img.removeAttribute('src'); }
  if (document.getElementById('preview').style.display === 'none') togglePreview(true);
}
/* 右上方自定义面板：步骤详情 / 思考过程 / 知识库编辑都走这里 */
function pvCustom(html) {
  if (pvTabCur !== 'files') pvTab('files');  // 详情类内容归「文件」标签
  const c = document.getElementById('pv-custom');
  c.innerHTML = `<div class="pv-doc">${html}</div>`;
  c.classList.add('show');
  ['pv-empty','pv-frame','pv-img','pv-vid','pv-aud'].forEach(id => {
    document.getElementById(id).style.display = 'none';
  });
  document.getElementById('pv-browser-empty').style.display = 'none';
  document.getElementById('pv-vid').pause();
  document.getElementById('pv-aud').pause();
  if (document.getElementById('preview').style.display === 'none') togglePreview(true);
}
function pvDetail(name, args, result, ok, ms) {
  const tag = ok ? '<span style="font-size:11px;color:var(--ok)">成功</span>'
                 : '<span style="font-size:11px;color:var(--err)">失败</span>';
  pvCustom(`<h3>${esc(name)} ${tag}</h3>
    ${ms ? `<div style="font-size:11px;color:var(--dim)">耗时 ${fmtMs(Number(ms))}</div>` : ''}
    <h4>参数</h4><pre>${esc(args || '(无参数)')}</pre>
    <h4>结果</h4><pre>${esc(result || '(无输出)')}</pre>`);
}
function pvThinking() {
  pvCustom(`<h3>💭 思考过程</h3>
    <div style="font-size:11px;color:var(--dim);margin-bottom:6px">${thinkText.length} 字</div>
    <pre>${esc(thinkText)}</pre>`);
}
function pvGo() {
  let url = document.getElementById('pv-url').value.trim();
  if (!url) return;
  if (!/^https?:\/\//i.test(url) && !url.startsWith('/')) url = 'http://' + url;
  pvShow('frame', url);
}
function pvFile(rel, kind) {
  if (!currentSession) return;
  if (pvTabCur !== 'files') pvTab('files');  // 文件预览归「文件」标签
  document.getElementById('pv-img').onerror = null;  // 普通图片预览不要误触发「浏览器截图」空态
  document.getElementById('pv-img').classList.remove('live');  // 文件图片不提供放大手势
  // t= 时间戳：同一文件重新生成后再点，能强制刷新，不会停在旧内容上
  const url = `/api/file?session_id=${currentSession}&path=${encodeURIComponent(rel)}&t=${Date.now()}`;
  if (kind === 'file') {
    pvCustom(`<h3>📦 ${esc(rel.split('/').pop())}</h3>
      <div style="font-size:12px;color:var(--dim)">该类型不支持内嵌预览，可下载后本地打开。</div>
      <div class="pv-actions">
        <a class="mini-btn" style="width:auto;margin-top:0;padding:6px 12px;text-align:center"
           href="${esc(url)}" download>下载文件</a></div>`);
    return;
  }
  pvShow(kind === 'image' ? 'img' : kind === 'audio' ? 'aud'
         : kind === 'video' ? 'vid' : 'frame', url);
}
function fmtSize(n) {
  return n > 1048576 ? (n / 1048576).toFixed(1) + 'M' : Math.max(1, Math.round(n / 1024)) + 'K';
}
const FILE_ICON = {image: '🖼', video: '🎬', audio: '🔊', html: '🌐', pdf: '📕',
                   text: '📄', doc: '📘', file: '📦'};
function fileRows(list, emptyText) {
  if (!list || !list.length) return `<div class="pv-file" style="cursor:default;color:var(--dim)">${emptyText}</div>`;
  return list.map(f =>
    `<div class="pv-file" onclick="pvFile(decodeURIComponent('${enc(f.rel)}'), '${f.kind}')">
      <span>${FILE_ICON[f.kind] || '📄'}</span>
      <span class="fname" title="${esc(f.rel)}">${esc(f.name)}</span>
      <span class="fsize">${fmtSize(f.size)}</span>
    </div>`).join('');
}
async function loadFiles() {
  const out = document.getElementById('pv-files');
  const inp = document.getElementById('pv-inputs');
  const sb = document.getElementById('pv-sandbox');
  if (!currentSession) {
    out.innerHTML = ''; inp.innerHTML = ''; sb.textContent = '-';
    return;
  }
  try {
    const r = await fetch(`/api/files?session_id=${currentSession}`);
    const d = await r.json();
    sb.textContent = d.sandbox || currentSession.slice(0, 10);
    inp.innerHTML = fileRows(d.inputs, '（暂无输入；附件上传后存到沙箱 uploads/）');
    out.innerHTML = fileRows(d.outputs, '（暂无产出文件）');
  } catch (e) { /* 忽略，下轮再刷 */ }
}
setInterval(loadFiles, 8000);

// ---- 定时任务 ----
let schedOn = true;
async function loadSched() {
  const r = await fetch('/api/schedule');
  const d = await r.json();
  schedOn = d.enabled;
  document.getElementById('sched-toggle').textContent = d.enabled ? '暂停' : '恢复';
  document.getElementById('sched-list').innerHTML = d.tasks.length ? d.tasks.map(t => `
    <div class="mcp-item" style="opacity:${t.enabled?1:.45}">
      <div style="display:flex;justify-content:space-between;gap:6px">
        <span style="flex:1">${esc(t.task)}</span>
        ${t.enabled ? `<span style="cursor:pointer;color:var(--dim)" onclick="schedCancel('${t.id}')">×</span>` : '<span style="color:var(--dim)">已停用</span>'}
      </div>
      <div style="font-size:11px;color:var(--dim);margin-top:2px">${esc(t.desc)} · 已跑 ${t.run_count} 次${t.last_run ? ' · 上次 ' + t.last_run.slice(5,16) : ''}</div>
    </div>`).join('') : '<div class="mcp-item">（暂无定时任务）</div>';
}
function schedTypeHint() {
  const t = document.getElementById('sched-type').value;
  document.getElementById('sched-time').placeholder =
    t === 'daily' ? 'HH:MM' : t === 'once' ? 'YYYY-MM-DD HH:MM' : '间隔秒数';
}
async function schedAdd() {
  const task = document.getElementById('sched-text').value.trim();
  if (!task) { alert('请输入任务内容'); return; }
  const st = document.getElementById('sched-type').value;
  const tv = document.getElementById('sched-time').value.trim();
  const body = {task, schedule_type: st};
  if (st === 'daily') body.daily_time = tv || '09:00';
  else if (st === 'once') body.run_at = tv;
  else body.interval_seconds = parseInt(tv) || 3600;
  const r = await fetch('/api/schedule/add', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const d = await r.json();
  if (!d.ok) { alert(d.msg || '添加失败'); return; }
  document.getElementById('sched-text').value = '';
  document.getElementById('sched-time').value = '';
  loadSched();
}
async function schedCancel(id) {
  await fetch('/api/schedule/cancel', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({id})});
  loadSched();
}
async function schedToggle() {
  await fetch('/api/schedule/toggle', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({enabled: !schedOn})});
  loadSched();
}

document.getElementById('kb-master').checked = localStorage.getItem('kbMaster') === '1';
loadSessions(); loadModels(); loadMcp(); loadSched(); schedTypeHint(); loadKb();
if (localStorage.getItem('preview') === 'off') togglePreview(false);
refreshResources(); refreshServices();
setInterval(refreshResources, 2000);
setInterval(refreshServices, 5000);
setInterval(loadModels, 8000);
setInterval(loadSched, 10000);
setInterval(renderLive, 500);  // 状态条本地走秒：后端静默时也能看出没卡死
</script>
</body>
</html>"""


def _graph_from_trace(run_id: str, session_id: str, evs: list[dict]) -> dict | None:
    """把 trace.jsonl 的事件翻译成前端运行图结构（字段对齐 PlannedRunner.emit）。

    用于给「运行图落库」上线之前的历史运行补档；trace 没有原始回复正文，
    因此补一条说明性的 answer 事件，并如实标注 token 与失败状态。
    """
    start = next((e for e in evs if e.get("kind") == "run_start"), {})
    end = next((e for e in reversed(evs) if e.get("kind") == "run_end"), {})
    raw_status = str(end.get("status") or "")
    status = {"ok": "done", "llm_error": "error"}.get(raw_status, raw_status or "interrupted")
    round_no = 0
    events: list[dict] = []
    prompt_tokens = completion_tokens = 0
    for e in sorted(evs, key=lambda x: x.get("ts") or 0):
        kind = e.get("kind")
        if kind == "round":
            round_no = int(e.get("round") or round_no + 1)
            events.append({"kind": "round", "i": round_no, "ts": e.get("ts")})
        elif kind == "llm":
            r = int(e.get("round") or round_no)
            p, c = int(e.get("prompt") or 0), int(e.get("completion") or 0)
            prompt_tokens += p
            completion_tokens += c
            events.append({"kind": "llm", "i": r, "prompt": p, "completion": c,
                           "ms": int(e.get("ms") or 0),
                           "msg": f"第 {r} 轮：prompt {p} + completion {c}",
                           "ts": e.get("ts")})
        elif kind == "tool_call":
            events.append({"kind": "tool_call", "i": round_no,
                           "name": e.get("name") or "",
                           "args": str(e.get("args") or ""), "ts": e.get("ts")})
        elif kind == "tool_result":
            brief = str(e.get("brief") or "")
            events.append({"kind": "tool_result", "i": round_no,
                           "name": e.get("name") or "", "ok": bool(e.get("ok")),
                           "brief": brief[:120], "text": brief,
                           "ms": int(e.get("ms") or 0), "ts": e.get("ts")})
    if not events:
        return None
    events.append({"kind": "answer",
                   "msg": f"（历史运行由 trace 还原：{len(events)} 个事件；原始回复正文未留档）",
                   "status": status,
                   "prompt_tokens": prompt_tokens,
                   "completion_tokens": completion_tokens})
    started_ts = float(start.get("ts") or (evs[0].get("ts") if evs else 0) or 0)
    started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started_ts)) if started_ts else ""
    finished = (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(end["ts"])))
                if end.get("ts") else "")
    return {
        "id": run_id, "session_id": session_id, "task": start.get("task") or "",
        "model_key": "",
        "status": "interrupted" if status == "running" else status,
        "plan": start.get("plan") or {"kind": "chat", "steps": []},
        "events": events,
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
        "started_at": started, "finished_at": finished,
        "draft": "", "thinking": "",
    }


class WebUI:
    def __init__(self, cfg: Config, port: int = 8088, registry=None, mcp=None):
        self.cfg = cfg
        self.port = port
        from . import live_view
        live_view.configure(cfg)  # 实时画面与浏览器工具必须用同一个 CDP 端口
        self._registry = registry  # 外部传入则复用（CLI+WebUI 共用一个注册表，MCP 只挂一次）
        self._mcp: dict[str, tuple[list[str], object]] = mcp if mcp is not None else {}
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._loop: AgentLoop | None = None
        self._llm: LLMClient | None = None
        self._store: SessionStore | None = None
        self._services: ServiceManager | None = None
        self._runner: PlannedRunner | None = None
        self._sched: Scheduler | None = None
        self._sched_runner: SchedulerRunner | None = None
        self._lock = threading.Lock()
        self._exec_lock = threading.Lock()  # 聊天与流水线互斥，保护 scope.WORKSPACE
        self._last_switch_ts = 0.0  # 上次模型切换时间，路由冷却期用

    def _ensure_all(self) -> None:
        with self._lock:
            if self._loop is None:
                self._store = SessionStore(self.cfg.path("paths.db"))
                self._llm = LLMClient(self.cfg)
                registry = self._registry or build_registry(self.cfg)
                if self._registry is None and self.cfg.get("mcp_servers"):
                    from .mcp_client import load_mcp_servers
                    loaded = load_mcp_servers(self.cfg, registry, track=self._mcp)
                    if loaded:
                        print(f"[mcp] 已挂载：{', '.join(loaded)}", flush=True)
                self._services = ServiceManager(self.cfg)
                trace = Trace(self.cfg.path("paths.trace"))  # 对话与流水线共用一份（互斥执行，不冲突）
                self._runner = PlannedRunner(
                    self.cfg, registry, self._store, self._services, self._exec_lock,
                    trace=trace)
                self._runner.mcp_track = self._mcp  # 自动挂载复用同一份挂载记录
                self._loop = AgentLoop(
                    self.cfg, self._llm, registry, store=self._store,
                    callbacks=Callbacks(), stream=True,  # 流式：回复逐 token 进草稿，前端实时可见
                    trace=trace)  # 对话 run 也落 trace，看板可回放
                self._loop.mcp_track = self._mcp
                self._loop.services = self._services  # 验收模型与执行模型不同时真切
                # 内置调度器：WebUI 即定时任务的管理入口
                self._sched = Scheduler(
                    self.cfg.path("paths.db").parent / "scheduled_tasks.json")
                self._sched_runner = SchedulerRunner(self._sched, self._exec_scheduled)
                self._sched_runner.start()
                self._recover_runs()

    def _recover_runs(self) -> None:
        """启动恢复：上次没跑完的 run 标为中断；再从 trace 回填老运行图。"""
        if not self._store:
            return
        try:
            fixed = self._store.close_stale_runs()
            fixed += self._store.mark_stale_run_graphs()
            if fixed:
                print(f"[run_graph] 已标记 {fixed} 个上次未结束的运行", flush=True)
        except Exception as exc:
            print(f"[run_graph] 清理陈旧运行失败：{exc}", flush=True)
        try:
            self._backfill_run_graphs()
        except Exception as exc:
            print(f"[run_graph] 历史回填失败：{exc}", flush=True)

    def _backfill_run_graphs(self) -> None:
        """运行图落库上线前的老任务：从 trace.jsonl 还原事件、token 与失败状态。"""
        path = self.cfg.path("paths.trace")
        if not path.exists():
            return
        groups: dict[str, list[dict]] = {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(line)
            except Exception:
                continue
            groups.setdefault(str(ev.get("run") or ""), []).append(ev)
        known = self._store.run_graph_ids()
        added = 0
        for run_id, evs in groups.items():
            if not run_id or run_id in known:
                continue
            start = next((e for e in evs if e.get("kind") == "run_start"), None)
            if not start:
                continue
            sid = str(start.get("session_id") or "")
            if not sid:
                task = str(start.get("task") or "")
                sid = self._store.session_for_run_task(
                    task, float(start.get("ts") or 0)) or \
                    self._store.session_by_user_message(
                        task, float(start.get("ts") or 0))
            if not sid:
                continue
            payload = _graph_from_trace(run_id, sid, evs)
            if not payload:
                continue
            self._store.save_run_graph(run_id, sid, payload,
                                       updated_at=payload.get("started_at") or None)
            added += 1
        if added:
            print(f"[run_graph] 已从 trace 回填 {added} 个历史运行", flush=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> bool:
        if self._server is not None:
            return True
        try:
            server = _Server(("127.0.0.1", self.port), _Handler)
        except OSError:
            return False
        server.webui = self  # type: ignore[attr-defined]
        server.daemon_threads = True
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        # 预加载默认 LLM：后台线程起主模型，不阻塞 WebUI 就绪
        if bool(self.cfg.get("llm.preload", True)):
            threading.Thread(target=self._preload_llm, daemon=True).start()
        # 清掉历史遗留的空白会话（没有任何消息与运行记录）
        cutoff = time.strftime("%Y-%m-%d %H:%M:%S")
        threading.Thread(target=self._purge_empty_sessions, args=(cutoff,), daemon=True).start()
        return True

    def _purge_empty_sessions(self, cutoff: str) -> None:
        """空白会话不保存：只清理启动前遗留的、从未产生消息/运行的会话及空沙箱。"""
        try:
            self._ensure_all()
            store = self._store
            if store is None:
                return
            for row in store.list_sessions(limit=500):
                if str(row.get("created_at") or "") >= cutoff:
                    continue  # 本次启动后新建的不算历史遗留，留给当前交互
                sid = row["id"]
                if store.load_messages(sid) or store.usage_summary(sid):
                    continue
                self.delete_session(sid)
        except Exception:
            pass  # 清理失败不影响启动

    def _preload_llm(self) -> None:
        try:
            self._ensure_all()
            key = self.cfg.get("llm.model", "")
            if key:
                self._services.ensure_llm(key)
        except Exception:
            pass  # 预加载失败不致命，面板可手动切换

    def stop(self) -> None:
        # 先关常驻 MCP 会话（杀子进程），否则退出后 deckcraft 之类的进程会留在后台
        try:
            from .mcp_router import close_all
            close_all(self._mcp)
        except Exception:
            pass
        if self._server:
            try:
                if getattr(self, "_thread", None) is not None and self._thread.is_alive():
                    self._server.shutdown()
            finally:
                self._server.server_close()
                self._server = None
                self._thread = None
        if self._sched_runner:
            try:
                self._sched_runner.stop()
            finally:
                self._sched_runner = None
        if self._store:
            try:
                self._store.close()
            finally:
                self._store = None
        self._loop = None
        self._llm = None
        self._runner = None
        self._services = None

    # ------------------------------------------------------------------ 会话
    def list_sessions(self) -> list[dict]:
        self._ensure_all()
        assert self._store is not None
        out = self._store.list_sessions()
        for s in out:
            s["workspace"] = self._ensure_sandbox(s)
            s["sandbox"] = Path(s["workspace"]).name
            s["title"] = self._short_title(s.get("title") or "")
        return out

    def session_detail(self, session_id: str) -> dict:
        self._ensure_all()
        assert self._store is not None
        return {
            "session": self._store.get_session(session_id),
            "messages": self._store.load_messages(session_id),
            "usage": self._store.usage_summary(session_id),
        }

    def session_usage(self, session_id: str) -> list[dict]:
        """任务累计用量（只读账本，给右上角 tokens 用，不拉全量消息）。"""
        self._ensure_all()
        assert self._store is not None
        return self._store.usage_summary(session_id)

    # ------------------------------------------------------------------ 沙箱
    def _sandbox_base(self) -> Path:
        return self.cfg.path("paths.workspace")

    def _ensure_sandbox(self, sess: dict) -> str:
        """每个任务一个独立沙箱：memory/workspace/<session_id>/；老任务自动补建。"""
        assert self._store is not None
        sid = sess.get("id") or ""
        base = self._sandbox_base().resolve()
        ws = (sess.get("workspace") or "").strip()
        if not ws or Path(ws).resolve() == base:
            ws = str(base / sid)
            self._store.set_workspace(sid, ws)
        Path(ws).mkdir(parents=True, exist_ok=True)
        return ws

    @staticmethod
    def _short_title(text: str, limit: int = 16) -> str:
        """把长标题压成一句话小标题（不额外调模型）。"""
        t = " ".join((text or "").split())
        if len(t) <= limit:
            return t
        for i, ch in enumerate(t[:limit]):
            if ch in "，,。.;；!！?？:：、":
                return t[:i]
        return t[:limit - 1] + "…"

    def new_session(self, title: str, workspace: str) -> dict:
        self._ensure_all()
        assert self._store is not None
        title = self._short_title(title.strip())
        sid = self._store.create_session(title=title, workspace=workspace.strip())
        ws = self._ensure_sandbox(self._store.get_session(sid) or {"id": sid})
        return {"session_id": sid, "workspace": ws, "sandbox": Path(ws).name}

    def delete_session(self, session_id: str) -> dict:
        self._ensure_all()
        assert self._store is not None
        sess = self._store.get_session(session_id) or {}
        ws = Path(sess["workspace"]) if sess.get("workspace") else None
        self._store.delete_session(session_id)
        # 删任务 = 删沙箱；只清理 workspace 基目录内的目录，避免误删用户自定义目录
        if ws and ws.exists():
            try:
                r = ws.resolve()
                base = self._sandbox_base().resolve()
                r.relative_to(base)
                if r != base:
                    shutil.rmtree(r, ignore_errors=True)
            except (ValueError, OSError):
                pass
        return {"ok": True}

    def set_workspace(self, session_id: str, workspace: str) -> dict:
        self._ensure_all()
        assert self._store is not None
        ws = workspace.strip()
        Path(ws).mkdir(parents=True, exist_ok=True)
        self._store.set_workspace(session_id, ws)
        return {"ok": True, "workspace": ws}

    # ------------------------------------------------------------------ 对话
    def handle_chat(self, session_id: str | None, message: str, kb: list[str] | None = None) -> dict:
        """异步受理：立即返回 run_id，执行过程通过 /api/run_status 事件流实时可见。"""
        self._ensure_all()
        store = self._store
        assert store is not None and self._runner is not None
        if not session_id:
            session_id = store.create_session(title=self._short_title(message))
        self._ensure_sandbox(store.get_session(session_id) or {"id": session_id})
        run = self._runner.open_chat(session_id, message)
        threading.Thread(target=self._chat_bg,
                         args=(run, message, kb or []), daemon=True).start()
        return {"run_id": run.id, "session_id": session_id, "async": True}

    def _chat_bg(self, run, message: str, kb: list[str] | None = None) -> None:
        """对话执行体：决策/切换/轮次/token/工具全部进事件流。"""
        runner = self._runner
        store = self._store
        loop = self._loop
        assert runner is not None and store is not None and loop is not None
        emit = lambda kind, **kw: runner.emit(run, kind, **kw)
        sid = run.session_id
        try:
            emit("phase", phase="queued", msg="等待执行槽位…")
            with self._exec_lock:
                emit("phase", phase="prepare", msg="准备工作区…")
                sess = store.get_session(sid) or {}
                ws = self._ensure_sandbox(sess or {"id": sid})
                scope.WORKSPACE = Path(ws).resolve()
                loop.workspace = str(scope.WORKSPACE)
                kb_ctx = self._kb_context(kb or [])
                if kb_ctx:
                    emit("phase", phase="kb", msg=f"已载入全局知识库：{', '.join(kb or [])}")

                # ① 决策：选模型（规则/惯性），事件实时可见
                emit("phase", phase="route", msg="决策：选择模型…")
                info = self._maybe_route(message, session_id=sid,
                                         emit=lambda k, **kw: emit(k, **kw))
                cur = self._services.llm_status()
                exec_model = (info or {}).get("key") or cur.get("model") or ""
                run.model_key = exec_model
                if info:
                    emit("decision", key=info["key"],
                         msg=f"模型选择 → {info['key']}：{info.get('reason', '')}")
                else:
                    emit("decision", key=exec_model,
                         msg=f"沿用当前模型 {exec_model or '（未知）'}")
                if not cur.get("online"):
                    msg = "LLM 离线，请在左侧模型服务面板启动模型"
                    emit("error", msg=msg)
                    self._persist_error(sid, msg)
                    runner.close(run, "error")
                    return

                # ② 回调 → 事件流（轮次、每轮 token、工具入参/出参）+ 流式草稿/思考
                draft_acc = [""]
                think_acc = [""]
                cur_round = [0]
                think_flag = [False]
                text_flag = [False]

                def _on_round(i: int) -> None:
                    cur_round[0] = i
                    draft_acc[0] = ""  # 新一轮清空草稿，活气泡只显示当前轮文本
                    think_acc[0] = ""
                    think_flag[0] = False
                    text_flag[0] = False
                    runner.set_draft(run, "")
                    runner.set_thinking(run, "")
                    emit("round", i=i, msg=f"第 {i} 轮推理…")

                def _on_text(delta: str) -> None:
                    if not text_flag[0]:
                        text_flag[0] = True
                        emit("phase", phase="answer",
                             msg=f"第 {cur_round[0]} 轮：开始生成回答…")
                    draft_acc[0] += delta
                    runner.set_draft(run, draft_acc[0])

                def _on_reason(delta: str) -> None:
                    think_acc[0] += delta
                    runner.set_thinking(run, think_acc[0])
                    if not think_flag[0]:
                        think_flag[0] = True
                        emit("reasoning", i=cur_round[0],
                             msg=f"第 {cur_round[0]} 轮：模型开始思考…")

                loop.cb.on_round = _on_round
                loop.cb.on_note = lambda m: emit("phase", phase="nudge", msg=m)
                loop.cb.on_assistant = _on_text
                loop.cb.on_reasoning = _on_reason
                loop.cb.on_llm = lambda i, p, c: emit(
                    "llm", i=i, prompt=p, completion=c,
                    msg=f"第 {i} 轮：prompt {p} + completion {c}")
                loop.cb.on_tool_call = lambda n, a: emit(
                    "tool_call", i=cur_round[0], name=n, args=(a or "")[:4000])
                loop.cb.on_tool_result = lambda n, ok, t, e: emit(
                    "tool_result", i=cur_round[0], name=n, ok=ok,
                    brief=t.split("\n")[0][:120], text=(t or "")[:4000], ms=int(e * 1000))
                emit("phase", phase="waiting",
                     msg="等待模型响应（首个 token 可能要几十秒）…")
                try:
                    trace = getattr(loop, "trace", None)
                    if trace:
                        trace.start(run.id, message,
                                    plan={"kind": "chat", "steps": []},
                                    session_id=sid)
                    result = loop.run(message, sid, extra_system=kb_ctx)
                except LLMError as exc:
                    emit("error", msg=f"模型错误：{exc}")
                    self._persist_error(sid, f"模型错误：{exc}")
                    runner.close(run, "error")
                    return

                # ③ 收尾：任务惯性记模型、自动起名、完成事件
                cur_model = self._services.llm_status().get("model")
                if cur_model and result.stopped_reason == "done":
                    store.set_last_model(sid, cur_model)
                self._auto_title(sid, message)
                if trace:
                    trace.event("run_end", status=result.stopped_reason)
                emit("answer", msg=result.content, status=result.stopped_reason,
                     rounds=result.rounds,
                     prompt_tokens=result.prompt_tokens,
                     completion_tokens=result.completion_tokens)
                runner.close(run, "done" if result.stopped_reason == "done"
                             else result.stopped_reason)
        except Exception as exc:  # 兜底，绝不让后台线程把异常吞掉
            emit("error", msg=f"{type(exc).__name__}: {exc}")
            self._persist_error(run.session_id, f"{type(exc).__name__}: {exc}")
            runner.close(run, "error")

    def _persist_error(self, session_id: str, msg: str) -> None:
        """把报错写进会话历史：刷新或重启后错误气泡不会消失。"""
        store = self._store
        if not store:
            return
        try:
            store.append_message(session_id,
                                 {"role": "assistant", "content": f"⚠ {msg}"})
        except Exception:
            pass

    # ------------------------------------------------------------------ 自动标题
    def _auto_title(self, session_id: str, message: str) -> str:
        """标题仍是自动前缀时，让 AI 总结一个短标题；用户起过名的不动。"""
        store = self._store
        sess = store.get_session(session_id) if store else None
        if not sess:
            return ""
        cur = (sess.get("title") or "").strip()
        if cur and cur != message[:50] and not cur.startswith("未命名"):
            return ""
        title = self._gen_title(message)
        if title and store:
            store.touch_session(session_id, title=title)
        return title

    def _gen_title(self, message: str) -> str:
        """用主模型总结短标题；失败返回空。"""
        prompt = ("给下面的任务起一个中文短标题（不超过 12 个字），"
                  "只输出标题本身，不要任何解释和标点收尾：\n" + message[:300])
        text = ""
        try:
            if self._llm is not None:
                reply = self._llm.chat([{"role": "user", "content": prompt}],
                                       tools=None, stream=False)
                text = reply.content or ""
        except Exception:
            return ""
        line = text.strip().splitlines()[0] if text else ""
        return line.strip("《》\"' ：:。.!！?？")[:20]

    def _maybe_route(self, message: str, switch: bool = True,
                     session_id: str | None = None, emit=None) -> dict | None:
        """模型选择：本地规则（难度启发 → 任务惯性），零额外开销。
        switch=True 时顺带切换 :8080；emit 提供时切换过程写入事件流。

        迟滞：软性规则命中后，若距上次切换不足 router.switch_cooldown_sec（默认 30 分钟），
        放弃切换沿用当前模型——35B 级模型加载几分钟，来回切比用错模型更亏。
        硬性规则（看图→多模态）不受冷却限制。
        """
        from . import task_router
        current = self._services.llm_status().get("model")
        # 规则路由：难度启发优先，没命中沿用本任务上次的模型
        info = task_router.pick_by_rules(self.cfg, message, current=current)
        if not info and session_id and self._store:
            sess = self._store.get_session(session_id)
            last = (sess or {}).get("last_model")
            if last and last != current:
                info = {"key": last, "reason": "沿用本任务上次的模型", "hard": False}
            elif last:
                return None  # 上次用的就是当前模型，无需任何动作
        if not info:
            return None
        if switch:
            if current and current != info["key"]:
                cooldown = float(self.cfg.get("router.switch_cooldown_sec", 1800) or 0)
                since = time.time() - getattr(self, "_last_switch_ts", 0.0)
                if not info.get("hard") and self._last_switch_ts and since < cooldown:
                    if emit:
                        emit("decision", key=current,
                             msg=f"规则建议 {info['key']}，但距上次切换 {int(since)}s "
                                 f"不足冷却期 {int(cooldown)}s，沿用 {current}")
                    return None
                if emit:
                    emit("service", action="switch_llm",
                         msg=f"切换模型 {current} → {info['key']}（加载中…）")
                r = self._services.ensure_llm(info["key"])
                if not r.get("ok"):
                    if emit:
                        emit("service", action="switch_llm", ok=False,
                             msg=f"切换失败：{r.get('msg', '')[:80]}，留在 {current}")
                    return None  # 切换失败就留在当前模型，不阻塞对话
                self._last_switch_ts = time.time()
                if emit:
                    emit("service", action="switch_llm", ok=True,
                         msg=f"{info['key']} 就绪")
        return info

    # ------------------------------------------------------------------ 流水线
    def plan_run(self, session_id: str | None, message: str, model_key: str | None) -> dict:
        self._ensure_all()
        assert self._store is not None and self._runner is not None
        if not session_id:
            session_id = self._store.create_session(title=message[:50])
        route_info = None
        if not model_key:  # 未显式指定模型 → 规则/惯性挑一个（切换由流水线线程执行）
            route_info = self._maybe_route(message, switch=False, session_id=session_id)
            if route_info:
                model_key = route_info["key"]
        if model_key:
            self._store.set_last_model(session_id, model_key)
        run_id = self._runner.start(session_id, message, model_key)
        # 后台自动起名（路由器小模型，几秒完成，不阻塞受理）
        threading.Thread(target=self._auto_title, args=(session_id, message),
                         daemon=True).start()
        return {"run_id": run_id, "session_id": session_id, "route": route_info}

    def run_status(self, run_id: str | None, session_id: str | None) -> dict:
        """运行图查询：先查内存（实时/本次进程），未命中回落到持久化快照（重启后仍可回看）。"""
        self._ensure_all()
        assert self._runner is not None and self._store is not None
        if run_id:
            return (self._runner.get(run_id)
                    or self._store.load_run_graph(run_id) or {})
        if session_id:
            return (self._runner.latest_for_session(session_id)
                    or self._store.latest_run_graph(session_id) or {})
        return {}

    def run_cancel(self, run_id: str) -> dict:
        self._ensure_all()
        assert self._runner is not None
        return {"ok": self._runner.cancel(run_id)}

    def run_list(self, session_id: str) -> list[dict]:
        """该会话的历史运行（含 token），供运行图顶部「历史」切换。"""
        self._ensure_all()
        assert self._store is not None
        return self._store.list_run_graphs(session_id)

    # ------------------------------------------------------------------ 定时任务
    def _exec_scheduled(self, task_text: str) -> str:
        """调度器执行入口：新建会话跑一轮 loop，与普通聊天互斥。"""
        self._ensure_all()
        assert self._store is not None and self._loop is not None
        sid = self._store.create_session(title=f"定时任务 {time.strftime('%H:%M')}")
        with self._exec_lock:
            scope.WORKSPACE = self.cfg.path("paths.workspace")
            self._loop.workspace = str(scope.WORKSPACE)
            result = self._loop.run(task_text, sid)
        return f"轮数 {result.rounds} ｜ 工具 {result.tool_calls} 次 ｜ 状态 {result.stopped_reason}"

    def schedule_list(self) -> dict:
        self._ensure_all()
        assert self._sched is not None and self._sched_runner is not None
        tasks = []
        for t in self._sched.list():
            st = t.get("schedule_type")
            if st == "once":
                desc = f"一次性 · {t.get('run_at', '')}"
            elif st == "daily":
                desc = f"每天 {t.get('daily_time', '')}"
            else:
                desc = f"每 {t.get('interval_seconds', 0)} 秒"
            tasks.append({
                "id": t["id"], "task": t["task"], "desc": desc,
                "enabled": t.get("enabled", True),
                "run_count": t.get("run_count", 0), "last_run": t.get("last_run", ""),
            })
        return {"enabled": self._sched_runner._thread is not None, "tasks": tasks,
                "logs": self._sched_runner.recent_logs(5)}

    def schedule_add(self, body: dict) -> dict:
        self._ensure_all()
        assert self._sched is not None
        task = (body.get("task") or "").strip()
        st = body.get("schedule_type", "daily")
        if not task:
            return {"ok": False, "msg": "任务内容为空"}
        if st not in {"once", "daily", "interval"}:
            return {"ok": False, "msg": f"未知类型 {st}"}
        self._sched.add(
            task, st,
            run_at=(body.get("run_at") or "").strip(),
            daily_time=(body.get("daily_time") or "").strip(),
            interval_seconds=int(body.get("interval_seconds") or 0),
        )
        return {"ok": True}

    def schedule_cancel(self, task_id: str) -> dict:
        self._ensure_all()
        assert self._sched is not None
        return {"ok": self._sched.cancel(task_id)}

    def schedule_toggle(self, enabled: bool) -> dict:
        self._ensure_all()
        assert self._sched_runner is not None
        if enabled:
            self._sched_runner.start()
        else:
            self._sched_runner.stop()
        return {"ok": True, "enabled": enabled}

    # ------------------------------------------------------------------ 知识库
    _KB_KINDS = {".md", ".txt"}
    _KB_DEFAULT = ("知识", "记忆", "规则")

    def _kb_root(self) -> Path:
        return self._sandbox_base().parent / "knowledge"

    def _kb_dirs(self) -> Path:
        root = self._kb_root()
        root.mkdir(parents=True, exist_ok=True)
        for c in self._KB_DEFAULT:
            (root / c).mkdir(exist_ok=True)
        return root

    @staticmethod
    def _safe_name(name: str) -> str:
        return re.sub(r"[^\w.\-一-鿿]", "_", Path(name or "").name).strip("_") or ""

    def kb_tree(self) -> dict:
        root = self._kb_dirs()
        cats = []
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            files = []
            for f in sorted(d.iterdir()):
                if f.is_file() and f.suffix.lower() in self._KB_KINDS:
                    st = f.stat()
                    files.append({"name": f.name, "size": st.st_size,
                                  "mtime": time.strftime("%m-%d %H:%M",
                                                         time.localtime(st.st_mtime))})
            cats.append({"name": d.name, "files": files})
        return {"root": str(root), "categories": cats}

    def kb_read(self, category: str, name: str) -> dict:
        d = self._kb_dirs() / self._safe_name(category)
        f = d / self._safe_name(name)
        if not d.is_dir() or not f.is_file() or f.suffix.lower() not in self._KB_KINDS:
            return {"ok": False, "msg": "文件不存在", "content": ""}
        return {"ok": True, "content": f.read_text("utf-8", errors="replace")[:200000]}

    def kb_save(self, category: str, name: str, content: str) -> dict:
        cat = self._safe_name(category) or "知识"
        fname = self._safe_name(name) or "未命名.md"
        if Path(fname).suffix.lower() not in self._KB_KINDS:
            fname += ".md"
        d = self._kb_dirs() / cat
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_text(content or "", encoding="utf-8")
        return {"ok": True, "category": cat, "name": fname}

    def kb_delete(self, category: str, name: str) -> dict:
        f = self._kb_dirs() / self._safe_name(category) / self._safe_name(name)
        if f.is_file() and f.suffix.lower() in self._KB_KINDS:
            f.unlink()
            return {"ok": True}
        return {"ok": False, "msg": "文件不存在"}

    def kb_new_category(self, name: str) -> dict:
        cat = self._safe_name(name)
        if not cat:
            return {"ok": False, "msg": "门类名不能为空"}
        (self._kb_dirs() / cat).mkdir(parents=True, exist_ok=True)
        return {"ok": True, "name": cat}

    def _kb_context(self, cats: list[str], budget: int = 12000) -> str:
        """把勾选门类的知识文件拼成 system 附加段；未勾选则返回空。"""
        if not cats:
            return ""
        root = self._kb_dirs()
        parts, used = [], 0
        for c in cats:
            d = root / self._safe_name(c)
            if not d.is_dir():
                continue
            for f in sorted(d.iterdir()):
                if not f.is_file() or f.suffix.lower() not in self._KB_KINDS:
                    continue
                if used >= budget:
                    break
                txt = f.read_text("utf-8", errors="replace")[:4000]
                block = f"\n### [{d.name}] {f.name}\n{txt}"
                parts.append(block)
                used += len(block)
        if not parts:
            return ""
        head = ("以下是用户勾选的全局知识库内容，回答时优先遵循其中的规则与事实；"
                "与当前任务无关的部分可忽略：\n")
        return (head + "".join(parts))[:budget]

    # ------------------------------------------------------------------ 记忆浓缩
    def _session_ws(self, session_id: str) -> Path:
        """会话沙箱目录；老任务自动补建，绝不回落到全局工作区。"""
        assert self._store is not None
        sess = self._store.get_session(session_id) if session_id else None
        if sess:
            return Path(self._ensure_sandbox(sess))
        return self._sandbox_base()

    def consolidate_memory(self, session_id: str) -> dict:
        """把指定任务工作区里的归档片段蒸馏成记忆卡（在该任务目录写 MEMORY.md）。"""
        self._ensure_all()
        assert self._store is not None
        from .memory import rag
        if session_id and not self._store.get_session(session_id):
            return {"ok": False, "msg": "任务不存在"}
        ws = self._session_ws(session_id)
        with self._exec_lock:
            scope.WORKSPACE = ws
            try:
                msg = rag.consolidate()
            except Exception as exc:
                return {"ok": False, "msg": f"整理失败：{exc}"}
        return {"ok": True, "msg": msg}

    # ------------------------------------------------------------------ 产出预览
    _PREVIEW_KINDS = {
        ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
        ".webp": "image", ".bmp": "image", ".svg": "image", ".ico": "image", ".avif": "image",
        ".mp4": "video", ".webm": "video", ".mov": "video", ".mkv": "video",
        ".mp3": "audio", ".wav": "audio", ".ogg": "audio", ".m4a": "audio", ".flac": "audio",
        ".html": "html", ".htm": "html", ".pdf": "pdf",
        ".md": "text", ".txt": "text", ".json": "text", ".csv": "text", ".log": "text",
        ".py": "text", ".js": "text", ".ts": "text", ".css": "text", ".xml": "text",
        ".yml": "text", ".yaml": "text", ".toml": "text", ".ini": "text", ".conf": "text",
        ".sql": "text", ".sh": "text", ".bat": "text", ".ps1": "text", ".srt": "text",
        ".docx": "doc",
        ".xlsx": "file", ".xls": "file", ".pptx": "file", ".zip": "file", ".7z": "file",
        ".rar": "file", ".psd": "file", ".exe": "file",
    }
    # 纯文本类：按 UTF-8 直接当文本预览
    _TEXT_EXT = {
        ".md", ".txt", ".json", ".csv", ".log", ".py", ".js", ".ts", ".css", ".xml",
        ".yml", ".yaml", ".toml", ".ini", ".conf", ".sql", ".sh", ".bat", ".ps1", ".srt",
    }

    @staticmethod
    def _sniff_kind(p: Path) -> str:
        """未知扩展名：按内容判断是不是纯文本（支持 UTF-8 / GBK）。"""
        try:
            with p.open("rb") as fh:
                head = fh.read(4096)
        except OSError:
            return "file"
        if b"\x00" in head:
            return "file"
        # 控制字符（除 \t \n \r）过多 → 当二进制
        ctrl = sum(1 for b in head if b < 0x09 or 0x0E <= b <= 0x1F)
        if ctrl > max(2, len(head) // 50):
            return "file"
        for enc in ("utf-8", "gbk"):
            try:
                head.decode(enc)
                return "text"
            except UnicodeDecodeError as exc:
                if exc.start >= len(head) - 3:  # 只是末尾字符被 4KB 截断
                    return "text"
        return "file"

    def list_files(self, session_id: str) -> dict:
        """任务沙箱内的输入（uploads/、inputs/）与产出文件。"""
        self._ensure_all()
        ws = self._session_ws(session_id)
        if not ws.is_dir():
            return {"sandbox": ws.name, "inputs": [], "outputs": []}
        inputs, outputs = [], []
        for p in ws.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(ws).as_posix()
            if rel.startswith(("kb/", ".")) or "/." in rel:
                continue
            kind = self._PREVIEW_KINDS.get(p.suffix.lower()) or self._sniff_kind(p)
            st = p.stat()
            item = {"rel": rel, "name": p.name, "kind": kind, "size": st.st_size,
                    "mtime": time.strftime("%m-%d %H:%M", time.localtime(st.st_mtime))}
            (inputs if rel.startswith(("uploads/", "inputs/")) else outputs).append(item)
        for lst in (inputs, outputs):
            lst.sort(key=lambda f: f["mtime"], reverse=True)
            del lst[100:]
        return {"sandbox": ws.name, "inputs": inputs, "outputs": outputs}

    def read_file(self, session_id: str, rel: str) -> tuple[bytes, str] | None:
        """读取工作目录内的单个文件（防目录穿越），返回 (内容, MIME)。"""
        self._ensure_all()
        ws = self._session_ws(session_id)
        try:
            p = (ws / rel).resolve()
            p.relative_to(ws.resolve())
        except (OSError, ValueError):
            return None
        if not p.is_file():
            return None
        ext = p.suffix.lower()
        if ext == ".docx":
            # docx 没有浏览器内嵌渲染，抽成纯文本预览（保留段落与表格内容）
            try:
                import docx
                doc = docx.Document(str(p))
                lines = [para.text for para in doc.paragraphs]
                for tb in doc.tables:
                    for row in tb.rows:
                        lines.append(" | ".join(c.text for c in row.cells))
                return "\n".join(lines).encode("utf-8"), "text/plain; charset=utf-8"
            except Exception:
                return p.read_bytes(), "application/octet-stream"
        if ext in self._TEXT_EXT or ext in (".html", ".htm"):
            blob = p.read_bytes()
            mime = ("text/html; charset=utf-8" if ext in (".html", ".htm")
                    else "text/plain; charset=utf-8")
            # Windows 下 txt 常是 GBK，先 UTF-8 再回退 GBK，最后强制替换
            for enc in ("utf-8", "gbk"):
                try:
                    return blob.decode(enc).encode("utf-8"), mime
                except UnicodeDecodeError:
                    continue
            return blob.decode("utf-8", "replace").encode("utf-8"), mime
        kind = self._PREVIEW_KINDS.get(ext)
        if kind in ("image", "video", "audio", "pdf", "file"):
            # 已知二进制类型：原样返回，交给浏览器渲染或下载
            mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            return p.read_bytes(), mime
        blob = p.read_bytes()
        # 未知扩展名：能按 UTF-8 / GBK 读通且没有二进制特征，就当文本预览
        if len(blob) <= 2_000_000 and b"\x00" not in blob[:4096]:
            for enc in ("utf-8", "gbk"):
                try:
                    return blob.decode(enc).encode("utf-8"), "text/plain; charset=utf-8"
                except UnicodeDecodeError:
                    continue
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return blob, mime

    # ------------------------------------------------------------------ 服务 / 模型 / MCP
    def services_status(self) -> dict:
        self._ensure_all()
        assert self._services is not None
        data = self._services.status()
        data["log"] = self._services.log_tail(8)
        return data

    def service_action(self, action: str, key: str | None) -> dict:
        self._ensure_all()
        assert self._services is not None
        services = self._services

        def work() -> None:
            if action == "start_llm" and key:
                services.ensure_llm(key)
            elif action == "stop_llm":
                services.stop_llm()
            elif action == "start_comfy":
                services.ensure_comfy()
            elif action == "stop_comfy":
                services.stop_comfy()
            elif action == "start_embed":
                services.ensure_embed()
            elif action == "stop_embed":
                services.stop_embed()
            elif action == "start_rerank":
                services.ensure_rerank()
            elif action == "stop_rerank":
                services.stop_rerank()

        valid = {"start_llm", "stop_llm", "start_comfy", "stop_comfy",
                 "start_embed", "stop_embed", "start_rerank", "stop_rerank"}
        if action not in valid:
            return {"ok": False, "msg": f"未知动作 {action}"}
        if action == "start_llm" and not key:
            return {"ok": False, "msg": "缺少模型 key"}
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True, "msg": "已受理，切换过程见服务日志"}

    def models(self) -> list[dict]:
        self._ensure_all()
        assert self._services is not None
        return self._services.models()

    def mcp_list(self) -> list[dict]:
        self._ensure_all()
        assert self._services is not None
        out: list[dict] = []
        for srv in (self.cfg.get("mcp_servers", []) or []):
            if not isinstance(srv, dict):
                continue
            name = str(srv.get("name") or srv.get("command") or srv)
            entry = self._mcp.get(name)
            out.append({"name": name, "source": "config",
                        "peer": _MCP_PEERS.get(name, ""),
                        "enabled": bool(srv.get("enabled", True)),
                        "mounted": entry is not None,
                        "tools": len(entry[0]) if entry else 0})
        configured_names = {str(s.get("name")) for s in (self.cfg.get("mcp_servers", []) or [])
                            if isinstance(s, dict)}
        root = self._services.root
        craft = root / "tools" / "storytold-ArtCraft" / "apps"
        if craft.is_dir():
            for app in sorted(craft.iterdir()):
                if not app.is_dir() or app.name in configured_names:
                    continue  # 已写入 mcp_servers 的由配置行展示，避免重复
                if not (app / f"{app.name}-cli.exe").exists():
                    continue  # 无 MCP CLI 的应用（artcraft / launcher）不作为插件列出
                out.append({"name": f"Craft: {app.name}", "source": "scan", "enabled": False,
                            "mounted": False, "tools": 0,
                            "peer": _MCP_PEERS.get(app.name, ""), "note": ""})
        mcp_dir = root / "tools" / "mcp-servers"
        if mcp_dir.is_dir():
            for item in sorted(mcp_dir.iterdir()):
                linked = next((str(s.get("name")) for s in (self.cfg.get("mcp_servers", []) or [])
                               if isinstance(s, dict) and item.name in
                               f"{s.get('command', '')} {' '.join(map(str, s.get('args', [])))} {s.get('cwd', '')}"),
                              None)
                if linked is not None:
                    continue  # 已配置过的由配置行展示，避免重复出现且状态无处可挂
                out.append({"name": f"mcp-servers: {item.name}", "source": "scan",
                            "peer": _MCP_PEERS.get(item.name, ""),
                            "enabled": False,
                            "mounted": False, "tools": 0,
                            "note": "已安装，未写入 mcp_servers 配置"})
        return out

    def mcp_toggle(self, name: str, enabled: bool) -> dict:
        """WebUI 里启用/停用一个已配置的 MCP：即时挂载/卸载，并写回配置文件。"""
        self._ensure_all()
        assert self._loop is not None
        entries = [s for s in (self.cfg.get("mcp_servers", []) or []) if isinstance(s, dict)]
        entry = next((s for s in entries if s.get("name") == name), None)
        if entry is None:
            return {"ok": False, "msg": "配置里没有这个 MCP server"}

        def save() -> str:
            try:
                self.cfg.source.write_text(
                    json.dumps(self.cfg.data, ensure_ascii=False, indent=2), encoding="utf-8")
                return ""
            except OSError as exc:
                return f"写配置失败：{exc}"

        from .mcp_client import load_mcp_servers, unmount_mcp_server
        registry = self._loop.registry
        if enabled:
            if name not in self._mcp:
                # 注意：entry.enabled 此刻仍是 False，挂载用的副本要强制置 True
                single = Config({"mcp_servers": [dict(entry, enabled=True)]}, self.cfg.source)
                if not load_mcp_servers(single, registry, track=self._mcp):
                    entry["enabled"] = False
                    return {"ok": False, "msg": "启动失败，详见控制台输出"}
            entry["enabled"] = True
            error = save()
            if error:
                return {"ok": False, "msg": error}
            return {"ok": True, "msg": f"已挂载 {len(self._mcp[name][0])} 个工具"}
        removed = unmount_mcp_server(registry, name, self._mcp)
        entry["enabled"] = False
        error = save()
        if error:
            return {"ok": False, "msg": error}
        return {"ok": True, "msg": f"已卸载（移除 {removed} 个工具）"}

    # ------------------------------------------------------------------ 附件
    def handle_upload(self, session_id: str, filename: str, data: bytes) -> dict:
        self._ensure_all()
        assert self._store is not None
        # 附件一律进当前任务的沙箱 uploads/，不再落到全局工作区
        ws = str(self._session_ws(session_id)) if session_id else str(self._sandbox_base())
        safe = re.sub(r"[^\w.\-一-鿿]", "_", Path(filename).name) or "upload.bin"
        up_dir = Path(ws) / "uploads"
        up_dir.mkdir(parents=True, exist_ok=True)
        target = up_dir / safe
        stem, suffix = target.stem, target.suffix
        n = 1
        while target.exists():
            target = up_dir / f"{stem}_{n}{suffix}"
            n += 1
        target.write_bytes(data)
        return {"ok": True, "path": str(target), "name": target.name,
                "size": len(data)}


# MCP 插件的对标软件（取自各 Craft 应用 README 的官方定位）
_MCP_PEERS: dict[str, str] = {
    "cadcraft": "AutoCAD",
    "deckcraft": "PowerPoint",
    "designcraft": "InDesign",
    "effectcraft": "After Effects",
    "figcraft": "Figma",
    "filmcraft": "Premiere Pro",
    "gridcraft": "Excel",
    "lightcraft": "Lightroom",
    "pdfcraft": "Acrobat",
    "photocraft": "Photoshop",
    "soundcraft": "Pro Tools",
    "vectorcraft": "Illustrator",
    "wordcraft": "Word",
    "playwright": "Playwright",
    "playwright-mcp": "Playwright",
}


class _Server(ThreadingHTTPServer):
    """客户端中途断开（切页/关标签/取消轮询）属正常现象，不打印 traceback。"""

    daemon_threads = True

    def handle_error(self, request, client_address) -> None:  # noqa: ANN001
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        # 前端轮询/切页会主动断开连接，此时写回包会抛 ConnectionAbortedError，
        # 属正常现象，直接静默结束，避免刷出一大段 traceback
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            self.close_connection = True

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")

    def _body_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def do_GET(self) -> None:
        webui: WebUI = self.server.webui  # type: ignore[attr-defined]
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._send(200, _HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/sessions":
            self._json(webui.list_sessions())
        elif path.startswith("/api/session/"):
            self._json(webui.session_detail(path.split("/")[-1]))
        elif path == "/api/usage":
            qs = parse_qs(parsed.query)
            self._json(webui.session_usage((qs.get("session_id") or [""])[0]))
        elif path == "/api/resources":
            self._json(sample_resources())
        elif path == "/api/services":
            self._json(webui.services_status())
        elif path == "/api/models":
            self._json(webui.models())
        elif path == "/api/mcp":
            self._json(webui.mcp_list())
        elif path == "/api/schedule":
            self._json(webui.schedule_list())
        elif path == "/api/run_status":
            qs = parse_qs(parsed.query)
            run_id = (qs.get("run_id") or [None])[0]
            sid = (qs.get("session_id") or [None])[0]
            self._json(webui.run_status(run_id, sid))
        elif path == "/api/run_list":
            qs = parse_qs(parsed.query)
            self._json(webui.run_list((qs.get("session_id") or [""])[0]))
        elif path == "/api/live":
            # 实时画面：CDP screencast 的 JPEG 帧，用 MJPEG 推给前端 <img>
            from . import live_view
            if not live_view.available():
                self._send(503, b"no live page", "text/plain; charset=utf-8")
                return
            live_view.ensure()
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last, idle = 0.0, time.time()
            try:
                while True:
                    frame, stamp = live_view.latest()
                    if frame and (stamp != last or time.time() - idle > 1.5):
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                            + str(len(frame)).encode("ascii") + b"\r\n\r\n" + frame + b"\r\n")
                        self.wfile.flush()
                        last, idle = stamp, time.time()
                    if not live_view.available():
                        break
                    time.sleep(0.12)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        elif path == "/api/preview":
            # 与看板「浏览器预览（最近一步）」同源：浏览器工具每次截图都覆盖 latest.png
            img = webui.cfg.path("paths.preview") / "latest.png"
            if img.exists():
                self._send(200, img.read_bytes(), "image/png")
            else:
                self._send(404, b"no preview", "text/plain; charset=utf-8")
        elif path == "/api/files":
            qs = parse_qs(parsed.query)
            self._json(webui.list_files((qs.get("session_id") or [""])[0]))
        elif path == "/api/kb":
            self._json(webui.kb_tree())
        elif path == "/api/kb/read":
            qs = parse_qs(parsed.query)
            self._json(webui.kb_read((qs.get("category") or [""])[0],
                                     (qs.get("name") or [""])[0]))
        elif path == "/api/file":
            qs = parse_qs(parsed.query)
            got = webui.read_file((qs.get("session_id") or [""])[0],
                                  (qs.get("path") or [""])[0])
            if got is None:
                self._send(404, b"not found", "text/plain")
            else:
                self._send(200, got[0], got[1])
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        webui: WebUI = self.server.webui  # type: ignore[attr-defined]
        path = urlparse(self.path).path
        if path == "/api/upload":
            self._handle_upload(webui)
            return
        body = self._body_json()
        if path == "/api/chat":
            self._json(webui.handle_chat(body.get("session_id"), body.get("message", ""),
                                         body.get("kb")))
        elif path == "/api/plan_run":
            self._json(webui.plan_run(body.get("session_id"), body.get("message", ""),
                                      body.get("model_key")))
        elif path == "/api/run_cancel":
            self._json(webui.run_cancel(body.get("run_id", "")))
        elif path == "/api/session/new":
            self._json(webui.new_session(body.get("title", ""), body.get("workspace", "")))
        elif path == "/api/session/delete":
            self._json(webui.delete_session(body.get("session_id", "")))
        elif path == "/api/session/workspace":
            self._json(webui.set_workspace(body.get("session_id", ""),
                                           body.get("workspace", "")))
        elif path == "/api/service":
            self._json(webui.service_action(body.get("action", ""), body.get("key")))
        elif path == "/api/mcp/toggle":
            self._json(webui.mcp_toggle(str(body.get("name", "")), bool(body.get("enabled"))))
        elif path == "/api/schedule/add":
            self._json(webui.schedule_add(body))
        elif path == "/api/schedule/cancel":
            self._json(webui.schedule_cancel(body.get("id", "")))
        elif path == "/api/schedule/toggle":
            self._json(webui.schedule_toggle(bool(body.get("enabled"))))
        elif path == "/api/memory/consolidate":
            self._json(webui.consolidate_memory(body.get("session_id", "")))
        elif path == "/api/kb/save":
            self._json(webui.kb_save(body.get("category", ""), body.get("name", ""),
                                     body.get("content", "")))
        elif path == "/api/kb/delete":
            self._json(webui.kb_delete(body.get("category", ""), body.get("name", "")))
        elif path == "/api/kb/category":
            self._json(webui.kb_new_category(body.get("name", "")))
        else:
            self._send(404, b"not found", "text/plain")

    def _handle_upload(self, webui: WebUI) -> None:
        ctype = self.headers.get("Content-Type", "")
        m = re.search(r"boundary=([^;]+)", ctype)
        if not m:
            self._json({"ok": False, "error": "缺少 multipart boundary"}, 400)
            return
        boundary = m.group(1).strip().strip('"').encode()
        length = int(self.headers.get("Content-Length", 0))
        if length > 50 * 1024 * 1024:
            self._json({"ok": False, "error": "文件超过 50MB"}, 400)
            return
        raw = self.rfile.read(length)
        session_id, filename, data = "", "", b""
        for part in raw.split(b"--" + boundary):
            if b"\r\n\r\n" not in part:
                continue
            head, _, content = part.partition(b"\r\n\r\n")
            content = content.rstrip(b"\r\n")
            head_text = head.decode("utf-8", errors="replace")
            if 'name="session_id"' in head_text:
                session_id = content.decode("utf-8", errors="replace").strip()
            elif 'name="file"' in head_text:
                fm = re.search(r'filename="([^"]*)"', head_text)
                filename = fm.group(1) if fm else "upload.bin"
                data = content
        if not data:
            self._json({"ok": False, "error": "未收到文件内容"}, 400)
            return
        try:
            self._json(webui.handle_upload(session_id, filename, data))
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, 500)
