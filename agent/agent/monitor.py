# -*- coding: utf-8 -*-
"""本地运行看板：步骤框图 + 资源仪表 + 浏览器预览 + 事件日志。

实现只用标准库 http.server，页面轮询 /state（1 秒），无外部依赖。
访问：http://127.0.0.1:8090
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .trace import Trace, sample_resources
from .memory.store import SessionStore


def _duration(started: str | None, finished: str | None) -> int:
    """runs 表时间字符串 → 秒数；没结束则算到现在。"""
    if not started:
        return 0
    try:
        st = time.mktime(time.strptime(started, "%Y-%m-%d %H:%M:%S"))
        et = (time.mktime(time.strptime(finished, "%Y-%m-%d %H:%M:%S"))
              if finished else time.time())
        return max(0, int(et - st))
    except (ValueError, OverflowError):
        return 0


class Monitor:
    def __init__(self, trace: Trace, preview_dir: Path, port: int = 8090,
                 db_path: Path | None = None):
        self.trace = trace
        self.preview_dir = preview_dir
        self.port = port
        self.db_path = db_path or Path("session.db")
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> bool:
        if self._server is not None:
            return True
        try:
            server = ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        except OSError:
            return False
        server.monitor = self              # type: ignore[attr-defined]
        server.daemon_threads = True
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._thread = None

    # ------------------------------------------------------------------ 数据
    def snapshot(self) -> dict:
        run_id = self.trace.latest_run()
        events = self.trace.events(run_id, limit=300) if run_id else []
        preview = self.preview_dir / "latest.png"
        return {
            "run": run_id,
            "events": events,
            "resources": sample_resources(),
            "preview": preview.stat().st_mtime if preview.exists() else 0,
            "monitor_url": self.url,
        }

    def tasks(self) -> dict:
        """按任务汇总：开销来自 SQLite 账本，流程图来自 trace.jsonl。

        两边的关联键是任务文本前 80 字（run_start.task 与 runs.task 同源）。
        """
        try:
            store = SessionStore(self.db_path)
            sessions = {s["id"]: s for s in store.list_sessions(limit=200)}
            runs = store.runs_detail()
            store.close()
        except Exception:
            sessions, runs = {}, []

        tasks: dict[str, dict] = {}

        def bucket(key: str) -> dict:
            return tasks.setdefault(key, {
                "key": key, "title": key, "runs": 0, "rounds": 0,
                "prompt": 0, "completion": 0, "duration_s": 0, "flows": [],
            })

        for r in runs:
            key = (r.get("task") or "").strip()[:80] or "(空任务)"
            t = bucket(key)
            sess = sessions.get(r.get("session_id") or "")
            if sess and sess.get("title") and sess["title"] != "未命名会话":
                t["title"] = sess["title"]
            t["runs"] += 1
            t["rounds"] += r.get("rounds") or 0
            t["prompt"] += r.get("prompt_tokens") or 0
            t["completion"] += r.get("completion_tokens") or 0
            t["duration_s"] += _duration(r.get("started_at"), r.get("finished_at"))

        flows: dict[str, dict] = {}
        for ev in self.trace.events(limit=2000):
            rid = ev.get("run")
            if not rid:
                continue
            f = flows.setdefault(rid, {
                "run": rid, "ts": 0, "task": "", "plan": None,
                "tokens": 0, "tools": 0, "status": "running", "step_status": {},
            })
            kind = ev.get("kind")
            if kind == "run_start":
                f["ts"] = ev.get("ts", 0)
                f["task"] = ev.get("task", "")
                f["plan"] = ev.get("plan")
            elif kind == "llm":
                f["tokens"] += (ev.get("prompt") or 0) + (ev.get("completion") or 0)
            elif kind == "tool_result":
                f["tools"] += 1
            elif kind == "step_start":
                f["step_status"][str(ev.get("index"))] = "running"
            elif kind == "step_end":
                f["step_status"][str(ev.get("index"))] = ev.get("status", "done")
            elif kind == "run_end":
                f["status"] = ev.get("status", "ok")
        for f in flows.values():
            if f["task"]:
                bucket(f["task"].strip()[:80])["flows"].append(f)

        result = sorted(tasks.values(),
                        key=lambda t: t["prompt"] + t["completion"], reverse=True)
        for t in result:
            t["flows"].sort(key=lambda f: f["ts"], reverse=True)
        return {"tasks": result[:50]}

    def metrics(self, db_path: Path) -> str:
        """Prometheus 格式指标，从 SQLite 账本读取。"""
        store = SessionStore(db_path)
        rows = store.usage_summary()
        store.close()

        lines = [
            "# HELP agent_runs_total 总运行次数",
            "# TYPE agent_runs_total counter",
        ]
        total_runs = sum(r["runs"] or 0 for r in rows)
        lines.append(f"agent_runs_total {total_runs}")

        lines += [
            "# HELP agent_rounds_total 总轮数",
            "# TYPE agent_rounds_total counter",
            f"agent_rounds_total {sum(r['rounds'] or 0 for r in rows)}",
        ]

        lines += [
            "# HELP agent_tokens_total 总 token 消耗",
            "# TYPE agent_tokens_total counter",
            f"agent_tokens_total {{kind=\"prompt\"}} {sum(r['prompt_tokens'] or 0 for r in rows)}",
            f"agent_tokens_total {{kind=\"completion\"}} {sum(r['completion_tokens'] or 0 for r in rows)}",
        ]

        lines += [
            "# HELP agent_sessions 活跃会话数",
            "# TYPE agent_sessions gauge",
            f"agent_sessions {len(rows)}",
        ]
        return "\n".join(lines) + "\n"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:      # 静音访问日志
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        monitor: Monitor = self.server.monitor      # type: ignore[attr-defined]
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/state":
            body = json.dumps(monitor.snapshot(), ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
        elif path == "/preview.png":
            file = monitor.preview_dir / "latest.png"
            if file.exists():
                self._send(200, file.read_bytes(), "image/png")
            else:
                self._send(404, b"no preview", "text/plain")
        elif path == "/trace.jsonl":
            file = monitor.trace.path
            body = file.read_bytes() if file.exists() else b""
            self._send(200, body, "application/jsonlines; charset=utf-8")
        elif path == "/api/tasks":
            body = json.dumps(monitor.tasks(), ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
        elif path == "/metrics":
            body = monitor.metrics(monitor.db_path).encode("utf-8")
            self._send(200, body, "text/plain; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")


HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>本地 Agent 运行看板</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--line:#262b36;--txt:#e6e8ee;--dim:#8b93a3;
--ok:#3ddc97;--run:#4da3ff;--warn:#ffb454;--err:#ff5d5d;--accent:#8a7dff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font:13px/1.5 "Segoe UI","Microsoft YaHei",sans-serif}
header{display:flex;align-items:center;gap:14px;padding:14px 20px;border-bottom:1px solid var(--line)}
header h1{font-size:15px;margin:0;font-weight:600}
.pill{font-size:11px;padding:2px 10px;border-radius:20px;background:#242a36;color:var(--dim)}
.pill.run{background:rgba(77,163,255,.15);color:var(--run)}
.pill.ok{background:rgba(61,220,151,.15);color:var(--ok)}
.pill.err{background:rgba(255,93,93,.15);color:var(--err)}
main{display:grid;grid-template-columns:1fr 380px;gap:14px;padding:14px 20px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.card h2{font-size:12px;margin:0 0 10px;color:var(--dim);font-weight:600;letter-spacing:.5px}
.res{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px}
.meter{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.meter .k{font-size:11px;color:var(--dim)}
.meter .v{font-size:18px;font-weight:600;margin-top:2px}
.bar{height:4px;border-radius:4px;background:#242a36;margin-top:8px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent);width:0;transition:width .4s}
.bar.gpu i{background:var(--ok)}
.flow{display:flex;gap:8px;overflow-x:auto;padding-bottom:6px;min-height:96px;align-items:stretch}
.step{min-width:150px;max-width:210px;border:1px solid var(--line);border-radius:8px;padding:9px 11px;background:#141821;flex:none}
.step .idx{font-size:10px;color:var(--dim)}
.step .goal{font-size:12px;margin:3px 0 6px;max-height:54px;overflow:hidden}
.step .tool{font-size:10px;color:var(--dim);background:#1d2330;display:inline-block;padding:1px 7px;border-radius:10px}
.step.running{border-color:var(--run);box-shadow:0 0 0 1px rgba(77,163,255,.3)}
.step.done{border-color:var(--ok)}
.step.failed{border-color:var(--err)}
.step.done .idx{color:var(--ok)}
.step.failed .idx{color:var(--err)}
.arrow{align-self:center;color:#3a4150;flex:none}
.round{min-width:92px;flex:none;border:1px solid var(--line);border-radius:8px;padding:8px;background:#141821}
.round b{font-size:11px;color:var(--accent)}
.round div{font-size:10px;color:var(--dim);margin-top:3px;max-height:52px;overflow:hidden}
#preview{width:100%;border-radius:6px;border:1px solid var(--line);display:block;background:#0b0d11}
.empty{color:var(--dim);font-size:12px;padding:16px 0}
#log{font-family:Consolas,monospace;font-size:11px;max-height:260px;overflow:auto}
#log div{padding:2px 0;border-bottom:1px solid #1d212b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#log .t{color:#5a6272;margin-right:6px}
#log .k{display:inline-block;min-width:74px;color:var(--accent)}
#log .ok{color:var(--ok)} #log .err{color:var(--err)}
.col{display:flex;flex-direction:column;gap:14px}
#tasks{width:100%;border-collapse:collapse;font-size:12px}
#tasks th{color:var(--dim);text-align:left;padding:4px 8px;border-bottom:1px solid var(--line);font-weight:600}
#tasks td{padding:5px 8px;border-bottom:1px solid #1d212b}
.trow{cursor:pointer}
.trow:hover{background:rgba(138,125,255,.08)}
.trow.sel{background:rgba(138,125,255,.14)}
</style></head><body>
<header>
  <h1>本地 Agent 运行看板</h1>
  <span class="pill" id="status">等待任务…</span>
  <span class="pill" id="runid"></span>
  <span class="pill" id="tokens">tokens 0</span>
  <span class="pill" id="elapsed"></span>
</header>
<main>
  <div class="col">
    <div class="res" id="res"></div>
    <section class="card"><h2 id="flow-title">运行步骤</h2><div class="flow" id="flow"><div class="empty">暂无计划</div></div></section>
    <section class="card"><h2>事件流</h2><div id="log"></div></section>
  </div>
  <div class="col">
    <section class="card"><h2>浏览器预览（最近一步）</h2><img id="preview" alt="浏览器截图" src="/preview.png"><div class="empty" id="pempty">尚未打开网页</div></section>
  </div>
</main>
<section class="card" style="margin:0 20px 16px">
  <h2>任务汇总（按总 tokens 排序 · 点击行回放该任务的模型运行图）</h2>
  <table id="tasks">
    <thead><tr><th>任务</th><th>运行</th><th>轮数</th><th>prompt</th><th>completion</th>
      <th>总 tokens</th><th>累计用时</th><th>流程记录</th></tr></thead>
    <tbody id="task-rows"></tbody>
  </table>
</section>
<script>
const el = id => document.getElementById(id);
let previewTs = 0;

function fmtTime(ts){ return new Date(ts*1000).toLocaleTimeString('zh-CN',{hour12:false}); }
function esc(s){ return (s||'').replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function meters(r){
  const m=[
    ['CPU', r.cpu.toFixed(0)+'%', r.cpu],
    ['内存', r.ram_used.toFixed(1)+' / '+r.ram_total.toFixed(0)+' GB', r.ram_percent],
    ['显存', (r.vram_used?r.vram_used+' / '+r.vram_total+' MB':'—'), r.vram_total?100*r.vram_used/r.vram_total:0, 'gpu'],
    ['GPU 利用率', (r.gpu_util!=null?r.gpu_util+'%':'—'), r.gpu_util||0, 'gpu'],
  ];
  el('res').innerHTML = m.map(([k,v,pct,cls])=>`<div class="meter"><div class="k">${k}</div><div class="v">${v}</div>
    <div class="bar ${cls||''}"><i style="width:${Math.min(100,pct||0)}%"></i></div></div>`).join('');
}

function flow(events){
  const run = events.find(e=>e.kind==='run_start') || {};
  const plan = run.plan;
  if(plan && plan.steps && plan.steps.length){
    const status = {};
    events.forEach(e=>{ if(e.kind==='step_start') status[e.index]='running';
                        if(e.kind==='step_end') status[e.index]=e.status; });
    el('flow').innerHTML = plan.steps.map((s,i)=>{
      const st = status[i] || 'pending';
      return `<div class="step ${st}"><div class="idx">步骤 ${i+1} · ${st}</div>
        <div class="goal">${esc(s.goal)}</div><span class="tool">${esc(s.tool||'none')}</span></div>`;
    }).join('<div class="arrow">→</div>');
    return;
  }
  const rounds = {};
  events.forEach(e=>{
    if(e.kind==='round') rounds[e.round] = rounds[e.round] || {tools:[]};
    if(e.kind==='tool_call'){ const r = Object.keys(rounds).pop(); if(r) rounds[r].tools.push(e.name); }
  });
  const keys = Object.keys(rounds);
  el('flow').innerHTML = keys.length ? keys.map(k=>`<div class="round"><b>轮次 ${k}</b>
      <div>${esc(rounds[k].tools.join(' → ')||'模型思考')}</div></div>`).join('<div class="arrow">→</div>')
    : '<div class="empty">暂无事件</div>';
}

function log(events){
  el('log').innerHTML = events.slice(-60).reverse().map(e=>{
    let text = '';
    if(e.kind==='tool_result') text = `${e.name} ${e.ok?'✓':'✗'} ${e.ms}ms ${esc(e.brief||'')}`;
    else if(e.kind==='tool_call') text = `${e.name} ${esc(e.args||'')}`;
    else if(e.kind==='llm') text = `prompt ${e.prompt} / completion ${e.completion} tokens`;
    else if(e.kind==='step_start') text = `开始：${esc(e.goal||'')}`;
    else if(e.kind==='step_end') text = `结束：${e.status}`;
    else if(e.kind==='run_start') text = esc(e.task||'');
    else text = Object.keys(e).filter(k=>!['ts','run','kind'].includes(k)).map(k=>k+'='+e[k]).join(' ');
    const cls = e.kind==='tool_result' ? (e.ok?'ok':'err') : '';
    return `<div><span class="t">${fmtTime(e.ts)}</span><span class="k">${e.kind}</span><span class="${cls}">${text}</span></div>`;
  }).join('');
}

function statusOf(events){
  const start = events.find(e=>e.kind==='run_start');
  const end = [...events].reverse().find(e=>e.kind==='run_end');
  if(!start) return ['等待任务…',''];
  if(!end) return ['运行中','run'];
  return end.status==='ok' ? ['已完成','ok'] : ['结束：'+end.status,'err'];
}

async function tick(){
  try{
    const s = await (await fetch('/state')).json();
    meters(s.resources);
    flow(s.events); log(s.events);
    const [txt,cls] = statusOf(s.events); el('status').textContent = txt;
    el('status').className = 'pill '+cls;
    el('runid').textContent = s.run ? 'run '+s.run : '';
    const tokens = s.events.filter(e=>e.kind==='llm').reduce((a,e)=>a+(e.prompt||0)+(e.completion||0),0);
    el('tokens').textContent = 'tokens '+tokens;
    const start = s.events.find(e=>e.kind==='run_start');
    if(start){ const end=[...s.events].reverse().find(e=>e.kind==='run_end');
      const secs = Math.round((end?end.ts:Date.now()/1000) - start.ts);
      el('elapsed').textContent = `用时 ${Math.floor(secs/60)}m${secs%60}s`; }
    if(s.preview && s.preview !== previewTs){ previewTs = s.preview;
      el('preview').src = '/preview.png?v='+Math.round(s.preview); el('pempty').style.display='none'; }
  }catch(err){ el('status').textContent='看板断连'; }
}
/* ---------- 任务汇总 ---------- */
let tasksCache = [];
async function tickTasks(){
  try{
    const d = await (await fetch('/api/tasks')).json();
    tasksCache = d.tasks || [];
    el('task-rows').innerHTML = tasksCache.map((t,i)=>{
      const dur = t.duration_s>=60 ? Math.floor(t.duration_s/60)+'m'+(t.duration_s%60)+'s'
                                   : t.duration_s+'s';
      return `<tr class="trow" id="trow-${i}" onclick="showTaskFlow(${i})">
        <td>${esc(t.title.slice(0,42))}</td><td>${t.runs}</td><td>${t.rounds}</td>
        <td>${t.prompt}</td><td>${t.completion}</td><td><b>${t.prompt+t.completion}</b></td>
        <td>${dur}</td><td>${t.flows.length ? t.flows.length+' 次流程' : '—'}</td></tr>`;
    }).join('') || '<tr><td colspan="8" class="empty">暂无任务记录</td></tr>';
  }catch(e){}
}
function showTaskFlow(i){
  const t = tasksCache[i]; if(!t) return;
  tasksCache.forEach((_,j)=>{ const r=el('trow-'+j); if(r) r.className = 'trow'+(j===i?' sel':''); });
  const f = (t.flows||[])[0];
  if(!f || !f.plan || !f.plan.steps || !f.plan.steps.length){
    el('flow-title').textContent = '运行步骤 · '+t.title.slice(0,30)+'（无流程图记录）';
    return;
  }
  const ss = f.step_status || {};
  el('flow').innerHTML = f.plan.steps.map((s,idx)=>{
    const st = ss[String(idx)] || 'pending';
    const cls = st==='done'?'done':(st==='failed'?'failed':(st==='running'?'running':''));
    return `<div class="step ${cls}"><div class="idx">步骤 ${idx+1} · ${st}</div>
      <div class="goal">${esc(s.goal)}</div><span class="tool">${esc(s.tool||'none')}</span></div>`;
  }).join('<div class="arrow">→</div>');
  el('flow-title').textContent = `运行步骤 · ${t.title.slice(0,26)}（${f.tokens} tokens / ${f.tools} 次工具调用）`;
  window.scrollTo(0,0);
}

tick(); setInterval(tick, 1000);
tickTasks(); setInterval(tickTasks, 5000);
</script></body></html>
"""
