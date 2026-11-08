# -*- coding: utf-8 -*-
"""重量级任务的规划执行器：先出「模型运行图」，再按节点切换本地服务执行。

典型场景：小说 → 视频。流程：
  1. make_plan：让当前 LLM 产出分步计划（每步标注要用哪类模型/工具）；
  2. 逐步执行：
     - 文本类步骤：确保 LLM 在线，跑完整 AgentLoop（可用文件等工具）；
     - 生成类步骤（图/视频/音乐）：先让 LLM 产出工具参数 JSON，
       然后停 LLM、起 ComfyUI，直接调工具，结果回灌上下文；
     - 语音类步骤（TTS/ASR）：停 ComfyUI 与 LLM（脚本跑完自释放显存），再调工具；
  3. 每一步的服务切换、输入输出、token 用量都追加到事件流，UI 轮询渲染。

显存互斥是硬约束（README 定论），所以切换是「先停后起」，绝不并行常驻。
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config
from .llm import LLMClient, LLMError
from .loop import AgentLoop, Callbacks
from .memory.store import SessionStore
from .planner import GPU_RESOURCES, Plan, PlanStep, parse_plan
from .services import ServiceManager
from .tools import scope
from .tools.registry import ToolRegistry

COMFY_TOOLS = {"generate_image", "generate_video", "generate_music", "comfy_status"}
VOICE_TOOLS = {"tts_speak", "asr_transcribe"}

PIPELINE_PLAN_PROMPT = """你是多模型流水线规划器。把用户任务拆成有序步骤，每步标注该用哪类能力。

可用能力（tool 字段只能从这里选）：
- none：纯文本步骤（大纲、分镜脚本、文案、总结），由本地 LLM 完成，可用文件工具落盘
- generate_image：ComfyUI 出图（封面、分镜画面、角色设定图）
- generate_video：ComfyUI 出视频片段
- generate_music：ComfyUI 配乐
- tts_speak：文本转语音（旁白配音）
- asr_transcribe：语音转文字

规则：
- 步骤 2~8 步；生成类步骤前必须先有文本步骤产出所需文案/提示词；
- 每步 goal 要说清楚「产出什么、给谁用」，最后一步必须是汇总交付；
- **depends_on 必须如实填写**：本步骤要用到某前序步骤的产物时，写下它们的下标（从 0 开始）；
  完全独立的步骤写 []。漏填会导致调度器误把有依赖的步骤提前执行；
- 所有纯文本步骤尽量排在生成类步骤之前，同资源的步骤连续排列，减少服务切换；
- 只输出 JSON，不要解释、不要代码块标记。

输出格式：
{"approach":"路线名","reason":"一句话理由","est_cost":"low|medium|high",
 "steps":[{"goal":"这一步要做什么","tool":"none|generate_image|generate_video|generate_music|tts_speak|asr_transcribe",
           "resource":"gpu_llm|comfy|voice|cpu|mcp","depends_on":[0]}]}

用户任务：{task}
"""

ARGS_PROMPT = """为工具 {tool} 生成调用参数。

工具参数 schema（JSON Schema）：
{schema}

当前步骤目标：{goal}

前序步骤产出（摘要）：
{context}

规则：只输出合法 JSON 对象（不要代码块标记），字段严格符合 schema；
提示词类字段用中文写具体，不要留空泛描述。"""


@dataclass
class PlannedRun:
    id: str
    session_id: str
    task: str
    model_key: str
    status: str = "running"  # running/done/error/cancelled
    plan: dict | None = None
    events: list[dict] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    started_at: str = ""
    finished_at: str = ""
    draft: str = ""  # 正在生成的回复草稿（流式累积，前端轮询渲染活气泡）
    thinking: str = ""  # 正在输出的思考过程（reasoning_content，前端渲染成思考气泡）

    def to_dict(self) -> dict:
        return {
            "id": self.id, "session_id": self.session_id, "task": self.task,
            "model_key": self.model_key, "status": self.status, "plan": self.plan,
            "events": list(self.events),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "draft": self.draft, "thinking": self.thinking,
        }


class PlannedRunner:
    """后台线程跑流水线；WebUI 轮询事件流渲染。"""

    def __init__(
        self,
        cfg: Config,
        registry: ToolRegistry,
        store: SessionStore,
        services: ServiceManager,
        exec_lock: threading.Lock,
        trace=None,
    ):
        self.cfg = cfg
        self.registry = registry
        self.store = store
        self.services = services
        self.exec_lock = exec_lock  # 与 WebUI 普通聊天互斥，避免 scope.WORKSPACE 打架
        self.trace = trace  # 可选 Trace：写入后看板可按任务回放流程图
        self.mcp_track: dict | None = None  # WebUI 传入的 MCP 挂载记录，供自动挂载复用
        self._runs: dict[str, PlannedRun] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._save_ts: dict[str, float] = {}  # 运行图落库节流：每 1.5 秒最多写一次

    # ------------------------------------------------------------------ 对外
    def start(self, session_id: str, task: str, model_key: str | None = None) -> str:
        run_id = uuid.uuid4().hex[:12]
        run = PlannedRun(
            id=run_id, session_id=session_id, task=task,
            model_key=model_key or str(self.cfg.get("llm.model", "")),
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        cancel = threading.Event()
        with self._lock:
            self._runs[run_id] = run
            self._cancel[run_id] = cancel
        self._prune_session(session_id)
        th = threading.Thread(target=self._execute, args=(run, cancel), daemon=True)
        th.start()
        return run_id

    def get(self, run_id: str) -> dict | None:
        with self._lock:
            run = self._runs.get(run_id)
            return run.to_dict() if run else None

    # ---------------- 对话 run：由 WebUI 驱动，事件结构与流水线一致 ----------------
    def open_chat(self, session_id: str, message: str) -> PlannedRun:
        """注册一个 kind=chat 的 run（不自带执行线程，WebUI 的 _chat_bg 负责驱动事件）。"""
        run_id = uuid.uuid4().hex[:12]
        run = PlannedRun(
            id=run_id, session_id=session_id, task=message,
            model_key=str(self.cfg.get("llm.model", "")),
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        run.plan = {"kind": "chat", "approach": "对话执行", "steps": []}
        with self._lock:
            self._runs[run_id] = run
            self._cancel[run_id] = threading.Event()
        self._prune_session(session_id)
        return run

    def emit(self, run: PlannedRun, kind: str, **payload) -> None:
        """对外发事件；llm 事件累计 token。"""
        if kind == "llm":
            run.prompt_tokens += int(payload.get("prompt", 0))
            run.completion_tokens += int(payload.get("completion", 0))
        self._emit(run, kind, **payload)

    def set_draft(self, run: PlannedRun, text: str) -> None:
        """更新流式草稿快照（不进事件流，避免每个 token 一条事件）。"""
        with self._lock:
            run.draft = text

    def set_thinking(self, run: PlannedRun, text: str) -> None:
        """更新流式思考过程快照（reasoning_content 累积）。"""
        with self._lock:
            run.thinking = text

    def close(self, run: PlannedRun, status: str) -> None:
        run.status = status
        run.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self._persist(run, force=True)  # 收尾必落库，保证下次打开能看到完整运行图

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            ev = self._cancel.get(run_id)
        if ev:
            ev.set()
            return True
        return False

    def latest_for_session(self, session_id: str) -> dict | None:
        with self._lock:
            runs = [r for r in self._runs.values() if r.session_id == session_id]
        if not runs:
            return None
        return runs[-1].to_dict()

    # ------------------------------------------------------------------ 落库
    def _persist(self, run: PlannedRun, force: bool = False) -> None:
        """运行图节流落库：事件多时避免每个 token 都写一次；收尾强制写。"""
        if not force:
            last = self._save_ts.get(run.id, 0.0)
            if time.time() - last < 1.5:
                return
        self._save_ts[run.id] = time.time()
        try:
            data = run.to_dict()
            # 草稿/思考是流式快照，只留尾部，避免单条记录过大
            data["draft"] = (data.get("draft") or "")[-4000:]
            data["thinking"] = (data.get("thinking") or "")[-8000:]
            self.store.save_run_graph(run.id, run.session_id, data)
        except Exception:
            pass  # 落库失败不能影响任务本身

    def _prune_session(self, session_id: str, keep: int = 30) -> None:
        """内存里同会话只保留最近 30 次已结束运行（数据已落库，删内存不影响回看）。"""
        with self._lock:
            done = [r for r in self._runs.values()
                    if r.session_id == session_id and r.status != "running"]
            for r in done[:-keep]:
                self._runs.pop(r.id, None)
                self._cancel.pop(r.id, None)
                self._save_ts.pop(r.id, None)

    # ------------------------------------------------------------------ 执行
    def _emit(self, run: PlannedRun, kind: str, **payload) -> None:
        record = {"ts": time.strftime("%H:%M:%S"), "kind": kind}
        record.update(payload)
        with self._lock:
            run.events.append(record)
        self._persist(run)

    def _execute(self, run: PlannedRun, cancel: threading.Event) -> None:
        # 流水线运行也记进 runs 账本：步骤内 loop 用 store=None，不单独记账，
        # 这样按会话汇总 token 时不会漏掉流水线开销
        ledger_id = 0
        try:
            ledger_id = self.store.start_run(run.session_id, run.task)
        except Exception:
            pass
        try:
            # 按任务自动挂载 MCP（初始不挂载，规划/执行前按关键词补齐）
            try:
                from .mcp_router import auto_mount
                got = auto_mount(self.cfg, self.registry, run.task, track=self.mcp_track)
                if got:
                    self._emit(run, "phase", phase="mcp",
                               msg=f"按任务自动挂载 MCP：{', '.join(got)}")
            except Exception as exc:
                self._emit(run, "phase", phase="mcp",
                           msg=f"MCP 自动挂载失败（忽略）：{type(exc).__name__}: {exc}")
            self._emit(run, "phase", phase="queued", msg="等待执行槽位…")
            with self.exec_lock:
                self._pipeline(run, cancel)
        except Exception as exc:  # 兜底，绝不让线程把异常吞掉
            self._emit(run, "error", msg=f"{type(exc).__name__}: {exc}")
            run.status = "error"
        finally:
            run.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
            err = ""
            if (run.status or "") == "error":
                err = next((str(e.get("msg") or "") for e in reversed(run.events)
                            if e.get("kind") == "error" and e.get("msg")), "")
                if not err:
                    err = next((str(e.get("brief") or "") for e in reversed(run.events)
                                if e.get("kind") == "step_done" and e.get("ok") is False), "")
                # 失败原因写进会话历史，刷新/重启后仍能看到
                try:
                    self.store.append_message(
                        run.session_id,
                        {"role": "assistant", "content": f"⚠ 流水线失败：{err or '未知错误'}"})
                except Exception:
                    pass
            if ledger_id:
                rounds = sum(1 for e in run.events if e.get("kind") == "round")
                try:
                    self.store.finish_run(ledger_id, run.status or "error", rounds,
                                          run.prompt_tokens, run.completion_tokens, err)
                except Exception:
                    pass
            self._persist(run, force=True)

    def _pipeline(self, run: PlannedRun, cancel: threading.Event) -> None:
        session = self.store.get_session(run.session_id)
        workspace = (session or {}).get("workspace") or str(self.cfg.path("paths.workspace"))
        Path(workspace).mkdir(parents=True, exist_ok=True)
        scope.WORKSPACE = Path(workspace).resolve()

        # ---- 1. 规划（需要 LLM 在线）
        self._emit(run, "phase", phase="planning", msg="正在生成模型运行图…")
        self._emit(run, "phase", phase="ensure_llm",
                   msg=f"启动模型 {run.model_key}（加载中，首次可能要几十秒）…")
        svc = self.services.ensure_llm(run.model_key)
        self._emit(run, "service", action="ensure_llm", model=run.model_key, **svc)
        if not svc["ok"]:
            run.status = "error"
            self._emit(run, "error", msg=f"LLM 不可用：{svc['msg']}")
            return
        llm = LLMClient(self.cfg)
        plan, plan_usage = self._make_pipeline_plan(llm, run.task)
        run.prompt_tokens += plan_usage.get("prompt_tokens", 0)
        run.completion_tokens += plan_usage.get("completion_tokens", 0)
        run.plan = plan.to_dict()
        self._emit(run, "plan", plan=run.plan)
        if self.trace:
            self.trace.start(run.id, run.task, plan=run.plan, session_id=run.session_id)
            self.trace.event("llm", prompt=plan_usage.get("prompt_tokens", 0),
                             completion=plan_usage.get("completion_tokens", 0))

        # ---- 2. 逐步执行
        # 前序步骤产出（结构化 {goal, output, ok}），供后续步骤与验收引用；
        # 不再共享会话历史，避免步骤越多上下文越膨胀
        context: list[dict[str, Any]] = []
        if self._exec_steps(run, llm, plan, 0, context, cancel):
            return

        # ---- 3. 验收：独立模型检查是否达标，不合格就退回指定步骤重修
        self._verify_and_fix(run, llm, plan, context, cancel)
        if run.status in ("cancelled", "error"):
            return

        # ---- 4. 恢复对话环境：停 ComfyUI、确保 LLM 在线
        self.services.stop_comfy()
        back = self.services.ensure_llm(run.model_key)
        self._emit(run, "service", action="restore_llm", model=run.model_key, **back)
        run.status = "done"
        self._emit(run, "done", msg="流水线完成",
                   prompt_tokens=run.prompt_tokens, completion_tokens=run.completion_tokens)
        if self.trace:
            self.trace.event("run_end", status="ok")

    @staticmethod
    def _fmt_context(context: list[dict[str, Any]]) -> list[str]:
        """结构化 context → 文本行（验收与参数生成共用同一格式）。"""
        lines = []
        for k, entry in enumerate(context, 1):
            idx = int(entry.get("i", k - 1)) + 1
            if entry.get("ok", True):
                lines.append(f"步骤{idx}（{entry.get('goal', '')}）产出：{entry.get('output', '')}")
            else:
                lines.append(f"步骤{idx}（{entry.get('goal', '')}）失败：{entry.get('output', '')}")
        return lines

    @staticmethod
    def _pick_ready(ready: list[int], steps: list[PlanStep], resident: str) -> int:
        """就绪步骤里优先选与当前驻留服务同资源的（CPU/MCP 不改变驻留，同样算兼容）。

        8GB 显存下 LLM / ComfyUI / 语音互斥，每次切换都要几十秒；把同资源步骤聚在一起，
        切换次数就从「按步骤交替」降到「按资源相位」，这是这台机器上最直接的提速手段。
        """
        def key(i: int) -> tuple[int, int]:
            res = steps[i].resource_key()
            same = res == resident or res not in GPU_RESOURCES
            return (0 if same else 1, i)
        return min(ready, key=key)

    def _exec_steps(self, run: PlannedRun, llm: LLMClient, plan, start: int,
                    context: list[dict[str, Any]], cancel) -> bool:
        """依赖感知调度：返回 True 表示因取消/致命错误提前停止。

        依赖来自 planner 的 depends_on（parse_plan 已保证只指向前序步骤）；
        依赖无法满足时退回最小下标顺序执行，绝不死锁；
        scheduler.reorder=false 时完全按规划顺序执行。
        """
        steps = list(plan.steps)
        n = len(steps)
        done: set[int] = set(range(min(start, n)))  # 重修：start 之前的步骤视为已完成
        resident = "gpu_llm"  # 规划阶段刚 ensure_llm
        reorder = bool(self.cfg.get("scheduler.reorder", True))
        while len(done) < n:
            if cancel.is_set():
                run.status = "cancelled"
                self._emit(run, "cancelled", msg="用户取消")
                return True
            ready = [k for k in range(n)
                     if k not in done and all(d in done for d in steps[k].depends_on)]
            if not ready:
                k = min(idx for idx in range(n) if idx not in done)
                self._emit(run, "phase", phase="schedule",
                           msg=f"步骤 {k+1} 的依赖未就绪，按原顺序执行（可能规划漏填依赖）")
            else:
                k = self._pick_ready(ready, steps, resident) if reorder else min(ready)
                if k != min(ready):
                    self._emit(run, "phase", phase="schedule",
                               msg=f"调度：步骤 {k+1}（{steps[k].resource_key()}）提前，"
                                   f"与当前 {resident} 同资源，省一次服务切换")
            step = steps[k]
            resource = step.resource_key()
            self._emit(run, "step_start", i=k, goal=step.goal, tool=step.tool, resource=resource)
            if self.trace:
                self.trace.event("step_start", index=k, goal=step.goal, tool=step.tool,
                                 resource=resource)
            t0 = time.perf_counter()
            try:
                brief = self._run_step(run, llm, step, k, context)
            except LLMError as exc:
                brief = f"[LLM 错误] {exc}"
                self._emit(run, "step_done", i=k, ok=False, brief=brief,
                           ms=int((time.perf_counter() - t0) * 1000))
                if self.trace:
                    self.trace.event("step_end", index=k, status="failed")
                    self.trace.event("run_end", status="llm_error")
                run.status = "error"
                return True
            except Exception as exc:
                brief = f"[步骤失败] {type(exc).__name__}: {exc}"
                self._emit(run, "step_done", i=k, ok=False, brief=brief,
                           ms=int((time.perf_counter() - t0) * 1000))
                if self.trace:
                    self.trace.event("step_end", index=k, status="failed")
                done.add(k)
                context.append({"i": k, "goal": step.goal, "output": brief, "ok": False})
                continue  # 单步失败不拖死整条流水线
            done.add(k)
            context.append({"i": k, "goal": step.goal, "output": brief, "ok": True})
            self._emit(run, "step_done", i=k, ok=True, brief=brief,
                       ms=int((time.perf_counter() - t0) * 1000))
            if self.trace:
                self.trace.event("step_end", index=k, status="done")
            if resource in GPU_RESOURCES:
                resident = resource
        return False

    def _artifacts(self) -> list[str]:
        """工作区里最近产生的文件（供验收模型判断是否真的交付了东西）。"""
        try:
            root = Path(scope.WORKSPACE)
            files = [p for p in root.rglob("*") if p.is_file() and "uploads" not in p.parts]
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return [str(p.relative_to(root)) for p in files[:20]]
        except Exception:
            return []

    def _verify_and_fix(self, run: PlannedRun, llm: LLMClient, plan,
                        context: list[dict[str, Any]], cancel) -> None:
        """任务验收：不通过则按验收建议从指定步骤重修，最多重试 verify.max_retry 次。"""
        if not self.cfg.get("verify.enabled", True):
            return
        from . import verifier
        max_retry = int(self.cfg.get("verify.max_retry", 1) or 0)
        model = str(self.cfg.get("verify.model", "") or "") or None
        for attempt in range(max_retry + 1):
            vi = 1000 + attempt  # 验收节点用大序号，避免和执行步骤撞号
            self._emit(run, "step_start", i=vi, goal="验收", tool="verify", resource="llm")
            t0 = time.perf_counter()
            switched_back = False
            try:
                # 验收模型与执行模型不同就真切换（llama-server 单模型常驻，只改请求字段无效）
                cur = self.services.llm_status().get("model")
                if model and cur and cur != model:
                    self._emit(run, "service", action="switch_llm",
                               msg=f"验收切换模型 {cur} → {model}（加载中…）")
                    svc = self.services.ensure_llm(model)
                    self._emit(run, "service", action="switch_llm", **svc)
                    switched_back = svc.get("ok", False)
                v = verifier.verify(self.cfg, llm, run.task,
                                    [s.goal for s in plan.steps],
                                    self._fmt_context(context),
                                    self._artifacts(), model=model)
            except Exception as exc:
                self._emit(run, "step_done", i=vi, ok=False,
                           brief=f"验收没跑起来：{type(exc).__name__}: {exc}",
                           ms=int((time.perf_counter() - t0) * 1000))
                return
            finally:
                if switched_back:  # 验完切回执行模型，后续重修/收尾环境不变
                    back = self.services.ensure_llm(run.model_key)
                    self._emit(run, "service", action="restore_llm",
                               model=run.model_key, **back)
            run.prompt_tokens += v.prompt_tokens
            run.completion_tokens += v.completion_tokens
            self._emit(run, "step_done", i=vi, ok=v.ok, brief=v.brief(),
                       ms=int((time.perf_counter() - t0) * 1000))
            if v.ok:
                return
            reason = v.advice or "；".join(v.problems)
            if attempt >= max_retry:
                self._emit(run, "phase", phase="verify_fail",
                           msg=f"验收未通过：{reason}（已达重修上限 {max_retry} 次）")
                return
            start = max(0, (v.redo_from or len(plan.steps)) - 1)
            self._emit(run, "phase", phase="redo",
                       msg=f"验收未通过（{v.score} 分）：{reason}，从第 {start + 1} 步开始重修")
            # 丢掉重做区间里的旧产出，避免模型被过期结果带偏（按步骤下标过滤，不依赖执行顺序）
            context[:] = [e for e in context if int(e.get("i", 0)) < start]
            if self._exec_steps(run, llm, plan, start, context, cancel):
                return

    def _run_step(self, run: PlannedRun, llm: LLMClient, step: PlanStep,
                  i: int, context: list[dict[str, Any]]) -> str:
        tool = str(step.tool or "none")
        if tool in COMFY_TOOLS and tool != "comfy_status":
            return self._run_comfy_step(run, llm, step, i, context)
        if tool in VOICE_TOOLS:
            return self._run_voice_step(run, step, i, context)
        if tool.startswith("mcp_"):
            return self._run_mcp_step(run, llm, step, i, context)
        return self._run_text_step(run, step, i, context)

    # ------------------------------------------------------------------ 三类步骤
    def _run_text_step(self, run: PlannedRun, step: PlanStep, i: int,
                       context: list[dict[str, Any]]) -> str:
        self.services.stop_comfy()  # 文本步骤不需要 ComfyUI，腾显存
        self._emit(run, "phase", phase="ensure_llm",
                   msg=f"步骤 {i+1}：启动模型 {run.model_key}（加载中）…")
        svc = self.services.ensure_llm(run.model_key)
        self._emit(run, "service", action="ensure_llm", model=run.model_key, **svc)
        if not svc["ok"]:
            raise LLMError(svc["msg"])
        # 步骤内部的轮次/工具调用实时进事件流，长步骤也能看出在干什么
        step_cb = Callbacks(
            on_round=lambda n: self._emit(run, "round", i=i,
                                          msg=f"步骤 {i+1}：第 {n} 轮推理…"),
            on_llm=lambda n, p, c: self._emit(run, "tokens", i=i, prompt=p, completion=c),
            on_tool_call=lambda name, args: self._emit(
                run, "tool_call", i=i, name=name, args=(args or "")[:4000]),
            on_tool_result=lambda name, ok, text, sec: self._emit(
                run, "tool_result", i=i, name=name, ok=ok, ms=int(sec * 1000),
                brief=(text or "").split("\n")[0][:120],
                text=(text or "")[:4000]),
        )
        # 步骤隔离：store=None，不加载也不写入会话历史；前序成果靠 context 摘要传递，
        # 避免步骤越多 prompt 越大（原来每步都背全部历史 + 前面步骤的全部内部消息）
        loop = AgentLoop(self.cfg, LLMClient(self.cfg), self.registry,
                         store=None, callbacks=step_cb, stream=False)
        loop.workspace = str(scope.WORKSPACE)
        self._emit(run, "phase", phase="agent",
                   msg=f"步骤 {i+1}：Agent 执行中（{step.goal[:24]}）…")
        prior = "\n".join(self._fmt_context(context)[-6:]) or "（无）"
        task = (f"[流水线步骤 {i+1}] {step.goal}\n\n"
                f"前序步骤产出（摘要）：\n{prior}")
        result = loop.run(task, run.session_id)
        run.prompt_tokens += result.prompt_tokens
        run.completion_tokens += result.completion_tokens
        if self.trace:
            self.trace.event("llm", prompt=result.prompt_tokens,
                             completion=result.completion_tokens)
        # 只把本步骤的结论写回会话，用户在消息流里能看到阶段成果，内部过程不进历史
        if self.store and result.content:
            self.store.append_message(run.session_id, {
                "role": "assistant",
                "content": f"[流水线步骤 {i+1}/{run.plan and len(run.plan.get('steps', [])) or '?'}] "
                           f"{step.goal}\n{result.content[:2000]}"})
        return result.content.split("\n")[0][:200] if result.content else "(无产出)"

    def _run_mcp_step(self, run: PlannedRun, llm: LLMClient, step: PlanStep,
                      i: int, context: list[dict[str, Any]]) -> str:
        """MCP 步骤：CPU 子进程，不占显存——LLM 保持在线产参数，然后直接调工具。"""
        tool = str(step.tool)
        if tool not in self.registry.names():
            raise RuntimeError(f"规划器指定了未挂载的 MCP 工具：{tool}")
        schema = self._tool_schema(tool)
        prompt = (ARGS_PROMPT.replace("{tool}", tool)
                  .replace("{schema}", json.dumps(schema, ensure_ascii=False)[:1500])
                  .replace("{goal}", step.goal)
                  .replace("{context}", "\n".join(self._fmt_context(context)[-6:]) or "（无）"))
        reply = llm.chat([{"role": "user", "content": prompt}],
                         temperature=0.4, max_tokens=1200)
        run.prompt_tokens += reply.usage.get("prompt_tokens", 0)
        run.completion_tokens += reply.usage.get("completion_tokens", 0)
        args = self._parse_args(reply.content)
        self._emit(run, "tool_args", i=i, tool=tool,
                   args=json.dumps(args, ensure_ascii=False)[:4000])
        self._emit(run, "phase", phase="mcp",
                   msg=f"步骤 {i+1}：{tool} 执行中（MCP 子进程）…")
        if self.trace:
            self.trace.event("tool_call", name=tool,
                             args=json.dumps(args, ensure_ascii=False)[:160])
        started = time.perf_counter()
        result = self.registry.call(tool, args, retries=0)
        elapsed = time.perf_counter() - started
        text = result.output if result.ok else f"[工具失败] {result.error}"
        self._emit(run, "tool_result", i=i, tool=tool, ok=result.ok,
                   ms=int(elapsed * 1000), brief=text.split("\n")[0][:200],
                   text=text[:4000])
        if self.trace:
            self.trace.event("tool_result", name=tool, ok=result.ok,
                             ms=int(elapsed * 1000), brief=text.split("\n")[0][:120])
        if not result.ok:
            raise RuntimeError(result.error[:200])
        return text.split("\n")[0][:200]

    def _run_comfy_step(self, run: PlannedRun, llm: LLMClient, step: PlanStep,
                        i: int, context: list[dict[str, Any]]) -> str:
        # 1) LLM 产参数
        schema = self._tool_schema(step.tool)
        prompt = (ARGS_PROMPT.replace("{tool}", step.tool)
                  .replace("{schema}", json.dumps(schema, ensure_ascii=False)[:1500])
                  .replace("{goal}", step.goal)
                  .replace("{context}",
                           "\n".join(self._fmt_context(context)[-6:]) or "（无）"))
        reply = llm.chat([{"role": "user", "content": prompt}],
                         temperature=0.4, max_tokens=1200)
        run.prompt_tokens += reply.usage.get("prompt_tokens", 0)
        run.completion_tokens += reply.usage.get("completion_tokens", 0)
        args = self._parse_args(reply.content)
        self._emit(run, "tokens", i=i,
                   prompt=reply.usage.get("prompt_tokens", 0),
                   completion=reply.usage.get("completion_tokens", 0))
        self._emit(run, "tool_args", i=i, tool=step.tool,
                   args=json.dumps(args, ensure_ascii=False)[:4000])

        # 2) 换服务：停 LLM → 预算守门 → 起 ComfyUI
        self._emit(run, "service", action="stop_llm", **self.services.stop_llm())
        budget = self.services.check_budget(
            vram_mb=int(self.cfg.get("scheduler.comfy_vram_mb", 7800) or 0),
            ram_mb=int(self.cfg.get("scheduler.comfy_ram_mb", 12000) or 0))
        if budget.get("checked"):
            self._emit(run, "service", action="budget", **budget)
        if not budget.get("ok", True) and self.cfg.get("scheduler.guard", True):
            raise RuntimeError(f"显存/内存不足，已拒绝启动 ComfyUI：{budget.get('msg', '')}")
        svc = self.services.ensure_comfy()
        self._emit(run, "service", action="ensure_comfy", **svc)
        if not svc["ok"]:
            raise RuntimeError(f"ComfyUI 不可用：{svc['msg']}")

        # 3) 直接调工具
        self._emit(run, "phase", phase="comfy",
                   msg=f"步骤 {i+1}：{step.tool} 生成中（ComfyUI 可能需数分钟）…")
        if self.trace:
            self.trace.event("tool_call", name=step.tool,
                             args=json.dumps(args, ensure_ascii=False)[:160])
        started = time.perf_counter()
        result = self.registry.call(step.tool, args, retries=0)
        elapsed = time.perf_counter() - started
        text = result.output if result.ok else f"[工具失败] {result.error}"
        self._emit(run, "tool_result", i=i, tool=step.tool, ok=result.ok,
                   ms=int(elapsed * 1000), brief=text.split("\n")[0][:200],
                   text=text[:4000])
        if self.trace:
            self.trace.event("tool_result", name=step.tool, ok=result.ok,
                             ms=int(elapsed * 1000), brief=text.split("\n")[0][:120])
        if not result.ok:
            raise RuntimeError(result.error[:200])
        return text.split("\n")[0][:200]

    def _run_voice_step(self, run: PlannedRun, step: PlanStep, i: int,
                        context: list[dict[str, Any]]) -> str:
        # 语音脚本与 LLM/ComfyUI 显存互斥：两个都停，脚本跑完自释放
        self._emit(run, "service", action="stop_comfy", **self.services.stop_comfy())
        self._emit(run, "service", action="stop_llm", **self.services.stop_llm())
        args: dict[str, Any] = {}
        # 语音步骤参数简单（text/audio_path），直接从结构化上下文取，不再请 LLM 产参
        if step.tool == "tts_speak":
            args["text"] = (context[-1].get("output", "") if context else step.goal)[:500]
        else:
            m = re.search(r"[\w./\\-]+\.(?:wav|mp3|m4a|flac)", step.goal)
            args["audio_path"] = m.group(0) if m else step.goal[:200]
        self._emit(run, "tool_args", i=i, tool=step.tool,
                   args=json.dumps(args, ensure_ascii=False)[:4000])
        self._emit(run, "phase", phase="voice",
                   msg=f"步骤 {i+1}：{step.tool} 处理中（脚本运行，可能较慢）…")
        if self.trace:
            self.trace.event("tool_call", name=step.tool,
                             args=json.dumps(args, ensure_ascii=False)[:160])
        result = self.registry.call(step.tool, args, retries=0)
        text = result.output if result.ok else f"[工具失败] {result.error}"
        self._emit(run, "tool_result", i=i, tool=step.tool, ok=result.ok,
                   ms=0, brief=text.split("\n")[0][:200], text=text[:4000])
        if self.trace:
            self.trace.event("tool_result", name=step.tool, ok=result.ok,
                             ms=0, brief=text.split("\n")[0][:120])
        if not result.ok:
            raise RuntimeError(result.error[:200])
        return text.split("\n")[0][:200]

    # ------------------------------------------------------------------ 辅助
    def _make_pipeline_plan(self, llm: LLMClient, task: str) -> tuple[Plan, dict]:
        try:
            reply = llm.chat(
                [{"role": "user", "content": PIPELINE_PLAN_PROMPT.replace("{task}", task)}],
                temperature=0.2, max_tokens=1000)
        except LLMError:
            return Plan.fallback(task), {}
        plan = parse_plan(reply.content, task, max_steps=8)
        # 只允许已知的流水线 tool 取值；已挂载的 mcp_* 工具也合法，其余归 none
        allowed = {"none"} | COMFY_TOOLS | VOICE_TOOLS
        mounted = set(self.registry.names())
        for s in plan.steps:
            if s.tool in allowed:
                continue
            if s.tool.startswith("mcp_") and s.tool in mounted:
                continue
            s.tool = "none"
        return plan, reply.usage

    def _tool_schema(self, name: str) -> dict:
        for sch in self.registry.schemas():
            fn = sch.get("function", {})
            if fn.get("name") == name:
                return fn.get("parameters", {})
        return {}

    @staticmethod
    def _parse_args(raw: str) -> dict:
        match = re.search(r"\{.*\}", raw or "", re.S)
        if not match:
            raise LLMError("模型未返回参数 JSON")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMError(f"参数 JSON 解析失败：{exc}") from exc
        if not isinstance(data, dict):
            raise LLMError("参数必须是 JSON 对象")
        return data
