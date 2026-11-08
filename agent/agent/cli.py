# -*- coding: utf-8 -*-
"""命令行入口。

用法：
    python -m agent.cli                      # 交互式会话（新建 session）
    python -m agent.cli --task "统计目录文件数并写报告"
    python -m agent.cli --session <id>        # 续接已有会话
    python -m agent.cli --list-sessions
    python -m agent.cli --check               # 只探测模型服务与工具清单
    python -m agent.cli --tools               # 列出工具与 JSON schema

交互命令：/exit /new /sessions /tools /model <名> /think on|off /stream on|off /usage /help
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from dataclasses import dataclass

from .config import Config
from .llm import LLMClient, LLMError
from .loop import AgentLoop, Callbacks
from .memory.store import SessionStore
from .monitor import Monitor
from .planner import Plan, make_plan
from .router import Router
from .scheduler import SchedulerRunner
from .tools import build_registry
from .trace import Trace
from .webui import WebUI


def _setup_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


@dataclass
class Console:
    """终端渲染：流式文本 + 工具事件，避免重复打印最终答案。"""
    stream: bool = False
    _text_open: bool = False
    _printed: bool = False

    def on_assistant(self, text: str) -> None:
        if not self.stream:
            return
        if not self._text_open:
            print("\n助手> ", end="", flush=True)
            self._text_open = True
        self._printed = True
        print(text, end="", flush=True)

    def end_text(self) -> None:
        if self._text_open:
            print()
            self._text_open = False

    def on_tool_call(self, name: str, args: str) -> None:
        self.end_text()
        brief = args if len(args) <= 160 else args[:160] + "…"
        print(f"  ↳ {name} {brief}", flush=True)

    def on_tool_result(self, name: str, ok: bool, text: str, elapsed: float) -> None:
        first = (text.splitlines() or [""])[0]
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name} {elapsed:.1f}s  {first[:120]}", flush=True)

    def on_trim(self, dropped: int) -> None:
        print(f"  [上下文] 已裁剪最旧 {dropped} 轮历史", flush=True)


def _make_loop(cfg: Config, store: SessionStore, llm: LLMClient, console: Console,
               stream: bool, trace: Trace | None = None, registry=None,
               mount_mcp: bool = True):
    if registry is None:
        registry = build_registry(cfg)
    if mount_mcp and cfg.get("mcp_servers"):
        from .mcp_client import load_mcp_servers
        loaded = load_mcp_servers(cfg, registry)
        if loaded:
            print(f"[mcp] 已挂载：{', '.join(loaded)}")
    callbacks = Callbacks(
        on_assistant=console.on_assistant,
        on_tool_call=console.on_tool_call,
        on_tool_result=console.on_tool_result,
        on_trim=console.on_trim,
    )
    return AgentLoop(cfg, llm, registry, store=store,
                     callbacks=callbacks, stream=stream, trace=trace)


def _print_plan(plan: Plan) -> None:
    print(f"\n[规划] 路线：{plan.approach} ｜ 预估成本：{plan.est_cost}")
    if plan.reason:
        print(f"       理由：{plan.reason}")
    for i, step in enumerate(plan.steps, 1):
        print(f"       {i}. {step.goal}  [{step.tool}]")


def _run_planned(loop: AgentLoop, llm: LLMClient, task: str, session_id: str,
                 trace: Trace, console: Console) -> None:
    """先规划再逐步执行；每步单独一轮 run，看板按步骤显示进度。"""
    print("\n[规划中] 正在评估可行路线与成本…", flush=True)
    plan = make_plan(llm, task)
    _print_plan(plan)

    run_id = uuid.uuid4().hex[:8]
    trace.start(run_id, task, plan.to_dict())
    totals = {"prompt": 0, "completion": 0, "rounds": 0, "tools": 0}
    ok_steps = 0
    step_rounds = loop.max_rounds
    loop.max_rounds = min(step_rounds, 8)      # 单步设上限，防止小模型在一步里反复重试

    for i, step in enumerate(plan.steps):
        trace.event("step_start", index=i, goal=step.goal, tool=step.tool)
        print(f"\n{'=' * 60}\n[步骤 {i + 1}/{len(plan.steps)}] {step.goal}\n{'=' * 60}", flush=True)
        prompt = (f"总目标：{task}\n"
                  f"当前步骤（第 {i + 1}/{len(plan.steps)} 步）：{step.goal}\n"
                  "只完成当前步骤，完成后用一两句话说明结果，不要继续下一步。")
        result = loop.run(prompt, session_id)
        status = "done" if result.stopped_reason == "done" else "failed"
        if status == "done":
            ok_steps += 1
        trace.event("step_end", index=i, status=status, rounds=result.rounds,
                    tokens=result.prompt_tokens + result.completion_tokens)
        totals["prompt"] += result.prompt_tokens
        totals["completion"] += result.completion_tokens
        totals["rounds"] += result.rounds
        totals["tools"] += result.tool_calls
        _print_result(result, loop.stream, console)
        if status != "done" and result.stopped_reason == "llm_error":
            break

    final_status = "ok" if ok_steps == len(plan.steps) else "partial"
    loop.max_rounds = step_rounds
    trace.event("run_end", status=final_status, rounds=totals["rounds"],
                prompt=totals["prompt"], completion=totals["completion"])
    print(f"\n[计划完成] {ok_steps}/{len(plan.steps)} 步成功 ｜ 总轮数 {totals['rounds']} ｜ "
          f"工具 {totals['tools']} 次 ｜ token {totals['prompt']}+{totals['completion']}"
          f"={totals['prompt'] + totals['completion']}", flush=True)


def _run_once(loop: AgentLoop, trace: Trace, task: str, session_id: str,
              console: Console) -> None:
    run_id = uuid.uuid4().hex[:8]
    trace.start(run_id, task, None)
    result = loop.run(task, session_id)
    trace.event("run_end", status="ok" if result.stopped_reason == "done" else result.stopped_reason,
                rounds=result.rounds, prompt=result.prompt_tokens,
                completion=result.completion_tokens)
    _print_result(result, loop.stream, console)


def _print_result(result, stream: bool, console: Console) -> None:
    console.end_text()
    if not stream:
        print("\n助手> " + (result.content or "（无内容）"))
    elif result.stopped_reason != "done":
        print("\n" + result.content)
    print(f"\n[统计] 轮数 {result.rounds} ｜ 工具调用 {result.tool_calls} 次 ｜ "
          f"token {result.prompt_tokens}+{result.completion_tokens}"
          f"={result.prompt_tokens + result.completion_tokens}"
          f" ｜ 结束原因 {result.stopped_reason}", flush=True)


def _cmd_tools(loop: AgentLoop) -> None:
    for spec in loop.registry._specs.values():
        print(f"\n【{spec.name}】{spec.description}")
        print("  参数：" + ", ".join(spec.parameters.get("properties", {})) or "（无）")


def _start_monitor(cfg: Config, trace: Trace, args, one_shot: bool = False) -> Monitor | None:
    """默认启动运行看板；--no-monitor 关闭。--check/--tools 这类一次性命令不启动。"""
    if args.no_monitor or one_shot:
        return None
    port = int(cfg.get("monitor.port", 8090))
    monitor = Monitor(trace, cfg.path("paths.preview"), port, db_path=cfg.path("paths.db"))
    if monitor.start():
        print(f"[看板] {monitor.url}")
        return monitor
    print(f"[看板] 端口 {port} 被占用，未启动")
    return None


def main(argv: list[str] | None = None) -> int:
    _setup_stdout()
    parser = argparse.ArgumentParser(description="本地 Agent（P1 + 规划/看板）")
    parser.add_argument("--config", help="配置文件路径，默认 configs/agent.json")
    parser.add_argument("--task", help="一次性任务（不给则进入交互模式）")
    parser.add_argument("--session", help="续接指定会话 id")
    parser.add_argument("--list-sessions", action="store_true", help="列出历史会话")
    parser.add_argument("--tools", action="store_true", help="列出工具清单")
    parser.add_argument("--check", action="store_true", help="检查模型服务连通性")
    parser.add_argument("--model", help="覆盖模型名（llama-server 实际会忽略，仅日志用）")
    parser.add_argument("--thinking", choices=["on", "off"], help="思考模式开关")
    parser.add_argument("--stream", action="store_true", help="流式输出")
    parser.add_argument("--max-rounds", type=int, help="覆盖最大轮数")
    parser.add_argument("--plan", action="store_true",
                        help="先由模型自主规划路线，再逐步执行")
    parser.add_argument("--no-monitor", action="store_true", help="不启动运行看板（默认启动）")
    parser.add_argument("--webui", action="store_true", help="开启 Web 聊天界面（:8088）")
    parser.add_argument("--scheduler", action="store_true", help="启动定时任务调度器")
    args = parser.parse_args(argv)

    cfg = Config.load(args.config)
    cfg.ensure_dirs()
    store = SessionStore(cfg.path("paths.db"))

    if args.list_sessions:
        rows = store.list_sessions()
        if not rows:
            print("（暂无会话）")
        for row in rows:
            print(f"{row['id']}  {row['updated_at']}  {row['title']}")
        return 0

    llm = LLMClient(cfg)
    if args.model:
        llm.set_model(args.model)
    if args.thinking:
        llm.set_thinking(args.thinking == "on")
    if args.max_rounds:
        cfg.data.setdefault("loop", {})["max_rounds"] = args.max_rounds

    try:
        model_id = llm.ping()
    except LLMError as exc:
        # WebUI 模式可在页面「模型服务」面板启动/切换模型，启动时不强制在线
        if args.webui and not (args.task or args.check or args.tools):
            print(f"[警告] 模型服务暂不在线：{exc}\n"
                  f"        可在 WebUI 左侧「模型服务」面板一键启动。", file=sys.stderr)
            model_id = None
        else:
            print(f"[启动失败] {exc}", file=sys.stderr)
            return 1

    console = Console(stream=args.stream)
    trace = Trace(cfg.path("paths.trace"))
    monitor = _start_monitor(cfg, trace, args, one_shot=bool(args.check or args.tools))
    # 注册表只建一次：CLI 与 WebUI 共用，MCP 也只挂一次（避免两个浏览器会话）
    registry = build_registry(cfg)
    mcp_track: dict = {}
    if cfg.get("mcp_servers") and not (args.check or args.tools):
        from .mcp_client import load_mcp_servers
        loaded = load_mcp_servers(cfg, registry, track=mcp_track)
        if loaded:
            print(f"[mcp] 已挂载：{', '.join(loaded)}", flush=True)
    loop = _make_loop(cfg, store, llm, console, args.stream, trace,
                      registry=registry, mount_mcp=False)
    loop.mcp_track = mcp_track  # 任务开始时按需自动挂载 MCP，复用同一份挂载记录

    # 定时任务调度器（--webui 时由 WebUI 内置接管，避免同一任务被触发两次）
    scheduler_runner = None
    if args.scheduler and not args.webui:
        from .scheduler import Scheduler
        sched = Scheduler(cfg.path("paths.db").parent / "scheduled_tasks.json")

        def _exec_task(task_text: str) -> str:
            r = loop.run(task_text, store.create_session(title=f"定时任务 {time.strftime('%H:%M')}"))
            return f"轮数 {r.rounds} ｜ 工具 {r.tool_calls} 次 ｜ 状态 {r.stopped_reason}"

        scheduler_runner = SchedulerRunner(sched, _exec_task)
        scheduler_runner.start()
        print(f"[调度器] 已启动，每 30s 检查一次到期任务")

    # Web UI
    webui = None
    if args.webui:
        port = int(cfg.get("webui.port", 8088))
        webui = WebUI(cfg, port, registry=registry, mcp=mcp_track)
        if webui.start():
            print(f"[Web UI] {webui.url}")
        else:
            print(f"[Web UI] 端口 {port} 被占用，未启动")
            webui = None

    if args.check:
        print(f"模型服务：{llm.base_url} ｜ 实际模型 id：{model_id}")
        print(f"工作区：{cfg.path('paths.workspace')}")
        print(f"会话库：{store.path}")
        print(f"工具：{', '.join(loop.registry.names())}")
        print(Router().describe())
        return 0

    if args.tools:
        _cmd_tools(loop)
        return 0

    # 会话按需创建：只跑 --task 时才立刻落库，交互模式首次输入后才创建，避免留下空白会话
    session_id = args.session
    if args.task and not session_id:
        session_id = store.create_session(title=args.task[:16])

    if args.task:
        if args.plan:
            _run_planned(loop, llm, args.task, session_id, trace, console)
        else:
            _run_once(loop, trace, args.task, session_id, console)
        if monitor or webui or scheduler_runner:
            urls = []
            if monitor:
                urls.append(f"看板 {monitor.url}")
            if webui:
                urls.append(f"Web UI {webui.url}")
            if scheduler_runner:
                urls.append("调度器运行中")
            print(f"\n[服务] {' ｜ '.join(urls)} ｜ Ctrl+C 结束", flush=True)
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                pass
            if monitor:
                monitor.stop()
            if webui:
                webui.stop()
            if scheduler_runner:
                scheduler_runner.stop()
        return 0

    plan_mode = args.plan
    print(f"本地 Agent ｜ 模型 {model_id or '未在线（先在 WebUI 面板启动）'} ｜ "
          f"会话 {session_id or '未创建（首次输入后建立）'} ｜ "
          f"规划 {'开' if plan_mode else '关'}")
    if webui:
        print(f"[Web UI] {webui.url}")
    if scheduler_runner:
        print(f"[调度器] 已启动")
    print("输入任务开始；/help 查看命令，/exit 退出。")
    while True:
        try:
            text = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出")
            break
        if not text:
            continue
        if text.startswith("/"):
            command, _, rest = text[1:].partition(" ")
            if command in ("exit", "quit"):
                break
            if command == "help":
                print("/new 新建会话 ｜ /sessions 列出会话 ｜ /tools 工具清单"
                      " ｜ /model <名> ｜ /think on|off ｜ /stream on|off"
                      " ｜ /plan on|off 自主规划 ｜ /monitor 运行看板"
                      " ｜ /usage token 账本 ｜ /exit")
            elif command == "plan":
                plan_mode = rest.strip().lower() not in ("off", "0", "no")
                print(f"自主规划：{'开' if plan_mode else '关'}")
            elif command == "monitor":
                if monitor:
                    print(f"[看板] {monitor.url}")
                else:
                    port = int(cfg.get("monitor.port", 8090))
                    monitor = Monitor(trace, cfg.path("paths.preview"), port)
                    if monitor.start():
                        print(f"[看板] {monitor.url}")
                    else:
                        print(f"[看板] 端口 {port} 被占用，未启动")
                        monitor = None
            elif command == "new":
                session_id = None
                print("新会话：首次输入后创建")
            elif command == "sessions":
                for row in store.list_sessions():
                    print(f"{row['id']}  {row['updated_at']}  {row['title']}")
            elif command == "tools":
                _cmd_tools(loop)
            elif command == "model":
                if rest.strip():
                    llm.set_model(rest.strip())
                    print(f"请求模型名已设为 {llm.model}（单模型常驻时以服务端为准）")
            elif command == "think":
                enabled = rest.strip() != "off"
                llm.set_thinking(enabled)
                print(f"思考模式：{'开' if enabled else '关'}")
            elif command == "stream":
                console.stream = rest.strip() != "off"
                loop.stream = console.stream
                print(f"流式输出：{'开' if loop.stream else '关'}")
            elif command == "usage":
                rows = store.usage_summary()
                if not rows:
                    print("（暂无记录）")
                for row in rows:
                    print(f"{row['session_id']}  runs={row['runs']}  rounds={row['rounds']}"
                          f"  tokens={row['prompt_tokens']}+{row['completion_tokens']}")
            else:
                print(f"未知命令：/{command}")
            continue

        if not session_id:
            session_id = store.create_session(title=text[:24])
            print(f"会话：{session_id}")
        if plan_mode:
            _run_planned(loop, llm, text, session_id, trace, console)
        else:
            _run_once(loop, trace, text, session_id, console)

    # 退出：每一步都单独兜住异常，任何一步卡住/失败都不影响后面照常收尾
    if monitor:
        try:
            monitor.stop()
        except Exception:  # noqa: BLE001
            pass
    if webui:
        try:
            webui.stop()
        except Exception:  # noqa: BLE001
            pass
    if scheduler_runner:
        try:
            scheduler_runner.stop()
        except Exception:  # noqa: BLE001
            pass
    # 关掉常驻 MCP 会话（CLI 自动挂载与 loop 自带的记录都清一遍），杀掉子进程
    try:
        from .mcp_router import close_all
        close_all(getattr(loop, "mcp_track", None))
        close_all(None)
    except Exception:  # noqa: BLE001
        pass
    try:
        store.close()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    code = main()
    # 直接 _exit：跳过 atexit 对残留线程的 join。
    # 工具线程是 daemon，但如果某个第三方库（如旧版线程池）留下非 daemon 线程
    # 卡在 MCP/网络读取里，正常退出会永久挂住，Ctrl+C 之后终端不返回。
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        os._exit(code)
