# -*- coding: utf-8 -*-
"""Agent 主循环：原生 tool-call 循环 + 护栏。

设计要点（针对 30B 级本地模型）：
- 一次只执行一个工具，结果立即回灌，降低格式退化概率；
- 相同工具+相同参数连续重复时主动打断，避免小模型卡死循环；
- 每轮调用前裁剪历史，防止长上下文把速度拖垮；
- 全流程消息落 SQLite，run 账本记录轮数/token。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import Config
from .context import estimate_tokens, split_trim, split_trim_tokens, total_tokens
from .llm import LLMClient, LLMError, Reply, ToolCall
from .memory.store import SessionStore
from .tools.registry import ToolRegistry

SYSTEM_TEMPLATE = """你是运行在用户本机的智能助手，通过调用工具完成任务。

规则：
1. 需要查看文件、执行命令、计算或获取外部信息时，调用工具；一次只调一个，等结果再决定下一步。
2. 不要用相同参数重复调用同一个工具。工具报错时先分析原因，换方法或向用户说明。
3. 能直接回答的问题直接回答，不要调用工具。
4. 工具参数必须是合法 JSON，不要编造不存在的参数。
5. 任务完成时用中文给出简短结论；不要输出思考过程，不要重复工具结果全文。
6. 文件操作限制在 {allowed} 内，相对路径按工作区 {workspace} 解析。
7. 产出类任务（文档、表格、演示、图片等）必须落成真实文件：用工具生成后调用保存/导出命令
   （如 deckcraft 的 save_presentation / export），把文件写到工作区，并在最终回复里给出路径。
   只把内容留在对话里、没有落地文件，视为任务未完成。

当前日期：{today}
可用工具：{tools}"""


@dataclass
class Callbacks:
    on_assistant: Callable[[str], None] | None = None
    on_reasoning: Callable[[str], None] | None = None
    on_tool_call: Callable[[str, str], None] | None = None
    on_tool_result: Callable[[str, bool, str, float], None] | None = None
    on_trim: Callable[[int], None] | None = None
    on_round: Callable[[int], None] | None = None
    # 每次 LLM 调用完成后回调（轮次, prompt_tokens, completion_tokens）
    on_llm: Callable[[int, int, int], None] | None = None
    # 过程提示（如"模型只给了计划，自动催促继续"），用于运行图展示
    on_note: Callable[[str], None] | None = None


@dataclass
class LoopResult:
    content: str = ""
    rounds: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: int = 0
    stopped_reason: str = "done"
    messages: list[dict[str, Any]] = field(default_factory=list)


class AgentLoop:
    def __init__(
        self,
        cfg: Config,
        llm: LLMClient,
        registry: ToolRegistry,
        store: SessionStore | None = None,
        callbacks: Callbacks | None = None,
        stream: bool = False,
        trace=None,
    ):
        self.cfg = cfg
        self.llm = llm
        self.registry = registry
        self.store = store
        self.cb = callbacks or Callbacks()
        self.stream = stream
        self.trace = trace
        self.services = None  # 可选：WebUI 注入 ServiceManager，验收时真切模型用

        self.max_rounds = int(cfg.get("loop.max_rounds", 12))
        self.max_history_chars = int(cfg.get("loop.max_history_chars", 24000))
        self.tool_result_max_chars = int(cfg.get("loop.tool_result_max_chars", 3000))
        self.retry = int(cfg.get("tools.retry", 1))
        # 上下文硬上限：llama-server 的 -c（16384/8192…）超出会直接 400。
        # 0 = 按 models.json 里当前模型的 -c 自动推断，避免"配置写死 24K 字符 → 必爆"
        self.context_size = int(cfg.get("llm.context_size", 0) or 0)
        self._ctx_cache: dict[str, int] = {}
        self._budget_scale = 1.0  # 触发过上下文超限后，本次运行持续收窄预算
        self._est_ratio = 1.0     # 实测 prompt / 本地估计；被低估时用它收窄预算
        # run 级预算：0 = 不限。防失控任务（30 轮 × 工具超时能跑非常久）
        self.max_wall_time = float(cfg.get("loop.max_wall_time_sec", 0) or 0)
        self.max_total_tokens = int(cfg.get("loop.max_total_tokens", 0) or 0)
        self.workspace = cfg.path("paths.workspace")
        allowed = cfg.get("tools.allowed_roots", []) or []
        self.allowed = ", ".join(allowed) if allowed else "（未限制）"

        # 上下文记忆：裁剪掉的片段归档进工作区知识库，新任务按相关度召回
        self.memory_on = bool(cfg.get("rag.memory", False))
        self.recall_top_k = int(cfg.get("rag.recall_top_k", 3))
        self.recall_min_score = float(cfg.get("rag.recall_min_score", 0.35))
        self._memory_broken = False

    # ------------------------------------------------------------------ 主流程
    # 只说不做：模型回了一句"我会先…/稍等片刻"这类计划，却没调用任何工具
    _PROMISE_WORDS = ("我会", "我将", "稍等", "稍候", "接下来", "现在开始", "马上",
                      "正在", "先搜集", "先搜索", "让我", "等待", "这就")
    _RESULT_WORDS = ("已完成", "已生成", "结果如下", "以下是", "总结如下", "详见", "已经完成")

    @classmethod
    def _promise_only(cls, text: str) -> bool:
        s = (text or "").strip()
        if not s or len(s) > 300:
            return False
        if any(w in s for w in cls._RESULT_WORDS):
            return False
        return any(w in s for w in cls._PROMISE_WORDS)

    def _rescue_tool_call(self, content: str) -> ToolCall | None:
        """把文本形态的伪工具调用捞成真正的 ToolCall。

        本地小模型（尤其多模态）常把 {"tool": ..., "tool_args": {...}} 当正文输出，
        而不是走正式 tool_calls 通道——不捞的话任务就在"计划"阶段假完成。
        取最后出现的、工具名已注册且 JSON 合法的一段。
        """
        text = content or ""
        if '"tool"' not in text and '"name"' not in text:
            return None
        known = set(self.registry.names())
        found: ToolCall | None = None
        decoder = json.JSONDecoder()
        for m in re.finditer(r"\{\s*\"(?:tool|name)\"", text):
            try:
                data, _ = decoder.raw_decode(text, m.start())
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            name = data.get("tool") or data.get("name")
            args = data.get("tool_args") or data.get("arguments") or {}
            if name in known and isinstance(args, dict):
                found = ToolCall(id="rescued", name=name,
                                 arguments=json.dumps(args, ensure_ascii=False))
        return found

    @staticmethod
    def _looks_like_fake_call(text: str) -> bool:
        """正文里残留工具调用 JSON 的残骸（没捞成功的），需要催促重发。"""
        s = text or ""
        return '"tool"' in s and ('"tool_args"' in s or '"arguments"' in s)

    def _has_tools(self) -> bool:
        try:
            return bool(self.registry.names())
        except Exception:
            return False

    def _verify_chat(self, task: str, answer: str):
        """对话任务的验收：独立模型判断这次的交付是否达标。失败则返回 None（不拦流程）。

        verify.model 非空时，先切到验收模型再验、验完切回执行模型——llama-server
        单模型常驻，只改请求字段没用，必须真的把模型换上去。
        """
        services = getattr(self, "services", None)  # WebUI 注入；CLI 场景无，退化为同模型
        prev = None
        try:
            from . import verifier
            model = str(self.cfg.get("verify.model", "") or "") or None
            if model and services:
                try:
                    cur = services.llm_status().get("model")
                    if cur and cur != model:
                        svc = services.ensure_llm(model)
                        if svc.get("ok"):
                            prev = cur
                            if self.cb.on_note:
                                self.cb.on_note(f"验收切换模型 {cur} → {model}")
                except Exception:
                    prev = None
            try:
                return verifier.verify(self.cfg, self.llm, task, [],
                                       [f"最终回复：{answer}"], self._chat_artifacts(),
                                       model=model)
            finally:
                if prev:
                    try:
                        services.ensure_llm(prev)
                        if self.cb.on_note:
                            self.cb.on_note(f"验收完毕，切回 {prev}")
                    except Exception:
                        pass
        except Exception:
            return None

    @staticmethod
    def _chat_artifacts() -> list[str]:
        """沙箱里最近产生的文件，让验收模型能判断"文件是否真的产出了"。"""
        try:
            from .tools import scope
            root = Path(scope.WORKSPACE)
            files = [p for p in root.rglob("*")
                     if p.is_file() and "uploads" not in p.parts and "kb" not in p.parts]
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return [str(p.relative_to(root)) for p in files[:20]]
        except Exception:
            return []

    def run(self, task: str, session_id: str, extra_system: str = "") -> LoopResult:
        # 按任务自动挂载需要的 MCP（初始不挂载任何 MCP，用到才起）
        try:
            from .mcp_router import auto_mount
            got = auto_mount(self.cfg, self.registry, task,
                             track=getattr(self, "mcp_track", None))
            if got:
                print(f"[mcp] 按任务自动挂载：{', '.join(got)}", flush=True)
        except Exception as exc:  # 自动挂载失败不影响主流程
            print(f"[mcp] 自动挂载失败：{type(exc).__name__}: {exc}", flush=True)
        history = self.store.load_messages(session_id) if self.store else []
        system_content = (self._system_prompt()
                          + self._memory_card() + self._recall_block(task)
                          + (("\n\n" + extra_system) if extra_system else ""))
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
        messages.extend(history)
        messages.append({"role": "user", "content": task})
        self._persist(session_id, {"role": "user", "content": task})

        run_id = self.store.start_run(session_id, task) if self.store else 0
        result = LoopResult(messages=messages)
        usage_prompt = usage_completion = 0
        last_signature = ""
        repeat = 0
        nudges = 0  # "只说不做"的自动催促次数
        verifies = 0  # 验收不合格后的重修次数
        # 与流水线语义一致：验收至少跑 1 次，max_retry 控制的是重修次数
        verify_max = max(1, int(self.cfg.get("verify.max_retry", 1) or 0))
        run_started = time.perf_counter()
        self._budget_scale = 1.0
        self._est_ratio = 1.0

        try:
            for round_no in range(1, self.max_rounds + 1):
                # run 级预算：超时间 / 超 token 都优雅收尾，不再无限烧
                if self.max_wall_time and time.perf_counter() - run_started > self.max_wall_time:
                    result.stopped_reason = "time_budget"
                    result.content = (f"已达到本次运行时间上限 {int(self.max_wall_time)}s，任务中止。"
                                      "可调大 loop.max_wall_time_sec 或把任务拆小。")
                    self._persist(session_id, {"role": "assistant", "content": result.content})
                    break
                if (self.max_total_tokens
                        and usage_prompt + usage_completion > self.max_total_tokens):
                    result.stopped_reason = "token_budget"
                    result.content = (f"已达到本次运行 token 上限 {self.max_total_tokens}，任务中止。"
                                      "可调大 loop.max_total_tokens 或把任务拆小。")
                    self._persist(session_id, {"role": "assistant", "content": result.content})
                    break
                result.rounds = round_no
                if self.cb.on_round:
                    self.cb.on_round(round_no)
                if self.trace:
                    self.trace.event("round", round=round_no)

                budget = self._prompt_budget_tokens()
                trimmed, dropped_msgs, dropped_rounds = split_trim_tokens(
                    messages, budget, self.tool_result_max_chars)
                # 兼容旧配置：max_history_chars 作为额外的字符上限（0 = 关闭）
                if self.max_history_chars > 0:
                    trimmed, more_msgs, more_rounds = split_trim(
                        trimmed, self.max_history_chars, self.tool_result_max_chars)
                    dropped_msgs += more_msgs
                    dropped_rounds += more_rounds
                if dropped_rounds and self.cb.on_trim:
                    self.cb.on_trim(dropped_rounds)
                if dropped_msgs:
                    self._archive(dropped_msgs)

                started = time.perf_counter()
                reply = self._call_llm(trimmed, budget)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                usage_prompt += reply.usage.get("prompt_tokens", 0)
                usage_completion += reply.usage.get("completion_tokens", 0)
                # 用服务端真实 prompt token 校准本地估算：估少了就永久收窄预算，
                # 否则 prompt 会一路贴着 -c 上限，把生成空间挤成 0
                est_prompt = total_tokens(trimmed) + self._schema_token_cost()
                real_prompt = reply.usage.get("prompt_tokens", 0)
                if est_prompt > 0 and real_prompt > 0:
                    ratio = real_prompt / est_prompt
                    if ratio > self._est_ratio:
                        self._est_ratio = min(4.0, ratio)
                if self.cb.on_llm:
                    self.cb.on_llm(round_no, reply.usage.get("prompt_tokens", 0),
                                   reply.usage.get("completion_tokens", 0))
                if self.trace:
                    self.trace.event("llm", round=round_no, ms=elapsed_ms,
                                     prompt=reply.usage.get("prompt_tokens", 0),
                                     completion=reply.usage.get("completion_tokens", 0))

                if not reply.has_tool_calls:
                    # 本地小模型常把工具调用 JSON 当正文输出：先尝试捞回真调用
                    rescued = self._rescue_tool_call(reply.content or "") \
                        if self._has_tools() else None
                    if rescued is not None:
                        reply.tool_calls = [rescued]
                        reply.content = ""
                        if self.cb.on_note:
                            self.cb.on_note(
                                f"模型把工具调用写成了正文，已转为真实调用：{rescued.name}")
                    else:
                        # 常见失败：模型只回一句"我会先…，稍等片刻"，既不调工具也不给结果，
                        # 任务就"完成"了。检测到这种只说不做的回复，自动催促继续执行（最多 2 次）
                        fake_call = self._looks_like_fake_call(reply.content or "")
                        if nudges < 2 and self._has_tools() and (
                                fake_call or self._promise_only(reply.content)):
                            nudges += 1
                            if self.cb.on_note:
                                self.cb.on_note(
                                    f"模型只给了计划、没有调用工具，自动催促继续（第 {nudges} 次）")
                            messages.append({"role": "user", "content":
                                             ("不要把工具调用以 JSON 文本写在回复里，请使用正式的工具调用通道。"
                                              if fake_call else "")
                                             + "不要只说明计划或让我等待。请立刻调用合适的工具开始执行；"
                                               "如果已经做完，就直接给出完整结果。"})
                            continue
                        # 这次什么都没回（典型：prompt 贴满窗口，只剩几个 token 生成）。
                        # 不能当"完成"，先收窄历史催一次；仍空则明确判失败
                        if not (reply.content or "").strip():
                            if nudges < 2 and result.tool_calls > 0:
                                nudges += 1
                                self._budget_scale *= 0.7
                                if self.cb.on_note:
                                    self.cb.on_note("模型没有返回内容（上下文被占满），收窄历史后自动重试")
                                messages.append({"role": "user", "content":
                                                 ("你刚才没有返回任何内容。请继续完成任务："
                                                  "先把产物保存/导出成真实文件，再给出简短结论。"
                                                  "历史里不必要的内容已被裁掉。")})
                                continue
                            result.stopped_reason = "empty_answer"
                            result.content = (
                                "模型没有返回任何内容：本次运行的上下文窗口已被占满，"
                                "没有留给回答的空间，任务未完成。\n"
                                "可以：① 把任务拆小分步执行；② 减少一次性贴入的资料量；"
                                "③ 调大模型的上下文窗口（models.json 里的 -c）。")
                            self._persist(session_id, {"role": "assistant",
                                                       "content": f"⚠ {result.content}"})
                            if self.trace:
                                self.trace.event("error", where="answer",
                                                 message="空回答（上下文占满）")
                            break
                        # 验收：调用过工具才算"任务"；纯问答不额外跑一次模型
                        if (verifies < verify_max and result.tool_calls > 0
                                and self.cfg.get("verify.enabled", True)):
                            v = self._verify_chat(task, reply.content or "")
                            if v is not None and not v.ok:
                                verifies += 1
                                reason = v.advice or "；".join(v.problems)
                                if self.cb.on_note:
                                    self.cb.on_note(f"验收未通过（{v.score} 分）：{reason}，让模型修正后重出结果")
                                messages.append({"role": "user", "content":
                                                 f"验收未通过：{reason}。请修正后重新给出完整结果。"})
                                continue
                        result.content = reply.content
                        result.stopped_reason = "done"
                        final_msg = {"role": "assistant", "content": result.content}
                        messages.append(final_msg)
                        self._persist(session_id, final_msg)
                        break

                assistant_msg = {
                    "role": "assistant",
                    "content": reply.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.name, "arguments": tc.arguments}}
                        for tc in reply.tool_calls
                    ],
                }
                messages.append(assistant_msg)
                self._persist(session_id, assistant_msg)

                for tc in reply.tool_calls:
                    result.tool_calls += 1
                    signature = f"{tc.name}:{tc.arguments}"
                    repeat = repeat + 1 if signature == last_signature else 0
                    last_signature = signature

                    if repeat >= 2:
                        text = ("[护栏] 你已经用相同参数连续调用该工具两次，"
                                "结果不会变化。请换方法或直接给出结论。")
                        ok, elapsed = False, 0.0
                        if self.trace:
                            self.trace.event("tool_result", name=tc.name, ok=False,
                                             ms=0, brief="重复调用已拦截")
                    else:
                        if self.cb.on_tool_call:
                            self.cb.on_tool_call(tc.name, tc.arguments)
                        if self.trace:
                            self.trace.event("tool_call", name=tc.name,
                                             args=_brief(tc.arguments, 160))
                        tool_result = self._call_tool(tc)
                        text = tool_result.output if tool_result.ok else f"[工具失败] {tool_result.error}"
                        ok, elapsed = tool_result.ok, tool_result.elapsed
                        if self.cb.on_tool_result:
                            self.cb.on_tool_result(tc.name, ok, text, elapsed)
                        if self.trace:
                            self.trace.event("tool_result", name=tc.name, ok=ok,
                                             ms=int(elapsed * 1000),
                                             brief=_brief(text, 120))

                    tool_msg = {"role": "tool", "tool_call_id": tc.id,
                                "name": tc.name, "content": text}
                    messages.append(tool_msg)
                    self._persist(session_id, tool_msg)
            else:
                result.stopped_reason = "max_rounds"
                result.content = (f"已达到最大轮数 {self.max_rounds}，任务中止。"
                                  "可调大 loop.max_rounds 或把任务拆小。")
                self._persist(session_id, {"role": "assistant", "content": result.content})
        except LLMError as exc:
            result.stopped_reason = "llm_error"
            result.content = f"模型调用失败：{exc}"
            # 报错也要进会话历史与运行账本，刷新/重启后仍能看到失败原因
            self._persist(session_id, {"role": "assistant", "content": f"⚠ {result.content}"})
        finally:
            result.prompt_tokens = usage_prompt
            result.completion_tokens = usage_completion
            result.messages = messages
            if self.store and run_id:
                status = "ok" if result.stopped_reason == "done" else result.stopped_reason
                self.store.finish_run(run_id, status, result.rounds,
                                      usage_prompt, usage_completion,
                                      "" if result.stopped_reason == "done" else result.content)
        return result

    # ------------------------------------------------------------------ 内部
    def _context_size_of(self) -> int:
        """当前模型的上下文窗口：配置优先，其次 models.json 的 -c，兜底 16384。"""
        model = str(getattr(self.llm, "model", "") or self.cfg.get("llm.model", ""))
        if model in self._ctx_cache:
            return self._ctx_cache[model]
        size = self.context_size
        if not size:
            size = 16384
            try:
                from .router import Router
                args = list((Router().models.get(model) or {}).get("server_args") or [])
                if "-c" in args:
                    size = int(args[args.index("-c") + 1])
            except Exception:
                pass
        self._ctx_cache[model] = size
        return size

    def _schema_token_cost(self) -> int:
        """工具 schema 自身占用的 token（多挂一个 MCP 就多几千）。"""
        try:
            return estimate_tokens(
                json.dumps(self.registry.schemas(), ensure_ascii=False, default=str))
        except Exception:
            return 0

    def _prompt_budget_tokens(self) -> int:
        """留给 messages 的 token 预算：窗口 - 生成预留 - 工具 schema - 余量。

        _est_ratio 是「服务端实际 prompt token ÷ 本地估计值」的历史最大值：
        CJK 估算、chat template、工具 schema 都可能被低估，一旦实际贴着
        窗口跑（16379/16384），模型就只剩几个 token 生成、直接回空。
        所以把预算按实测比例整体折算，宁可多裁一点，也要给回答留出空间。
        """
        ctx = self._context_size_of()
        max_out = int(getattr(self.llm, "max_tokens", 4096) or 4096)
        out_reserve = min(max_out, max(512, ctx // 4))  # 生成预留最多占窗口 1/4
        ratio = max(1.0, self._est_ratio)
        schema_tokens = self._schema_token_cost()
        usable = (ctx - out_reserve - 256) / ratio
        budget = usable - schema_tokens
        return max(768, int(budget * self._budget_scale))

    @staticmethod
    def _is_context_error(exc: Exception) -> bool:
        s = str(exc).lower()
        return any(k in s for k in (
            "exceeds the available context size", "exceeded_context_size",
            "context length", "maximum context", "context window",
            "too many tokens", "reduce the length"))

    def _call_llm(self, messages: list[dict[str, Any]], budget: int | None = None) -> Reply:
        """调 LLM；上下文超限时逐步压缩重试，瞬时故障隔 2s 重试一次。"""
        if budget is None:
            budget = self._prompt_budget_tokens()
        ctx_tries = 0
        net_tried = False
        while True:
            try:
                return self.llm.chat(
                    messages,
                    tools=self.registry.schemas(),
                    stream=self.stream,
                    on_text=self.cb.on_assistant,
                    on_reasoning=self.cb.on_reasoning,
                )
            except LLMError as exc:
                if self._is_context_error(exc) and ctx_tries < 2:
                    ctx_tries += 1
                    self._budget_scale *= 0.85  # 本轮任务后续轮次也按更小预算裁
                    budget = max(512, int(budget * 0.65))
                    messages = split_trim_tokens(
                        messages, budget,
                        max(600, self.tool_result_max_chars // 2), keep_units=1)[0]
                    if self.cb.on_note:
                        self.cb.on_note(
                            f"请求超出模型上下文窗口，已压缩到约 {budget} tokens 后重试"
                            f"（第 {ctx_tries}/2 次）")
                    continue
                if not net_tried:
                    net_tried = True
                    if self.cb.on_note:
                        self.cb.on_note("模型调用失败，2 秒后重试一次…")
                    time.sleep(2.0)
                    continue
                raise

    def _call_tool(self, tc: ToolCall):
        try:
            args = tc.parsed_arguments()
        except LLMError as exc:
            from .tools.registry import ToolResult
            return ToolResult(tc.name, False, "", 0.0, str(exc))
        return self.registry.call(tc.name, args, retries=self.retry)

    def _persist(self, session_id: str, msg: dict[str, Any]) -> None:
        if self.store:
            self.store.append_message(session_id, msg)

    # ------------------------------------------------------------------ 上下文记忆
    def _memory_card(self) -> str:
        """任务记忆卡（MEMORY.md）无条件注入：长期有效的事实与决策，不走相似度。"""
        if not self.memory_on:
            return ""
        try:
            from .tools import scope
            card = Path(scope.WORKSPACE) / "MEMORY.md"
            if not card.is_file():
                return ""
            text = card.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""
        if not text:
            return ""
        return ("\n\n任务记忆卡（本任务长期有效的事实与决策，与召回片段冲突时以此为准）：\n"
                + text[:2000])

    def _recall_block(self, task: str) -> str:
        """开工前从本工作区知识库召回相关历史片段，拼进 system prompt。"""
        if not self.memory_on or self._memory_broken:
            return ""
        try:
            from .memory import rag
            hits = rag.recall(task, self.recall_top_k, self.recall_min_score)
        except Exception:
            self._memory_broken = True  # embed/rerank 不在线时静默降级，本次任务不再尝试
            return ""
        if not hits:
            return ""
        lines = ["", "", "历史记忆（本任务工作区沉淀的相关片段，供参考，可能已过时）："]
        lines += [f"- {' '.join(text.split())[:300]}" for text, _score in hits]
        return "\n".join(lines)

    def _archive(self, dropped: list[dict[str, Any]]) -> None:
        """裁剪掉的对话片段归档进工作区知识库（doc=context）。"""
        if not self.memory_on or self._memory_broken:
            return
        texts = []
        for m in dropped:
            content = (m.get("content") or "").strip()
            if not content:
                continue
            role = m.get("role", "")
            name = m.get("name") or ""
            head = f"[{role}:{name}]" if name else f"[{role}]"
            texts.append(f"{head} {content}")
        if not texts:
            return
        try:
            from .memory import rag
            n = rag.archive(texts, source="context")
            if n and self.trace:
                self.trace.event("memory_archive", chunks=n)
        except Exception:
            self._memory_broken = True

    def _system_prompt(self) -> str:
        return SYSTEM_TEMPLATE.format(
            allowed=self.allowed,
            workspace=self.workspace,
            today=self._today(),
            tools=", ".join(self.registry.names()),
        )

    @staticmethod
    def _today() -> str:
        return time.strftime("%Y-%m-%d")


def _brief(text: str, limit: int) -> str:
    line = " ".join((text or "").split())
    return line if len(line) <= limit else line[:limit] + "…"


def dump_messages(messages: list[dict[str, Any]]) -> str:
    """调试用：把消息序列渲染成可读文本。"""
    lines = []
    for msg in messages:
        role = msg.get("role")
        lines.append(f"--- {role} ---")
        if msg.get("content"):
            lines.append(msg["content"])
        if msg.get("tool_calls"):
            lines.append(json.dumps(msg["tool_calls"], ensure_ascii=False, indent=2))
    return "\n".join(lines)
