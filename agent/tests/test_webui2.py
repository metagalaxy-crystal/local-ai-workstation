"""WebUI 大改版单测：store 扩展、ServiceManager、PlannedRunner、新端点。

注意：子进程/网络全部 mock，不会真的启停模型服务。
"""
from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from agent.config import Config
from agent.llm import Reply
from agent.memory.store import SessionStore
from agent.monitor import Monitor
from agent.orchestrator import PlannedRunner
from agent.services import ServiceManager, kill_port
from agent.tools.registry import ToolResult
from agent.trace import Trace
from agent.webui import WebUI


def make_cfg(root: Path) -> Config:
    return Config({
        "llm": {"base_url": "http://127.0.0.1:1/v1", "model": "fake"},
        "loop": {"max_rounds": 4, "max_history_chars": 20000, "tool_result_max_chars": 2000},
        # 单元测试不跑验收，避免额外 LLM 调用影响服务切换与 token 断言
        "verify": {"enabled": False, "max_retry": 0},
        "tools": {
            "enabled": ["files", "shell"],
            "tool_timeout": 20, "retry": 0,
            "allowed_roots": [str(root)],
            "scripts_dir": str(root / "scripts"),
            "shell_whitelist": [], "blocked_patterns": [],
        },
        "paths": {"workspace": str(root / "ws"), "db": str(root / "s.db"),
                  "vectors_db": str(root / "v.db"), "output_root": str(root / "out"),
                  "preview": str(root / "preview"), "trace": str(root / "trace.jsonl")},
    }, Path("test-config"))


# ---------------------------------------------------------------------- store
class StoreExtTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = SessionStore(Path(self._tmp.name) / "s.db")

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_workspace_roundtrip(self) -> None:
        sid = self.store.create_session("任务A", workspace="d:/models/output/a")
        sess = self.store.get_session(sid)
        self.assertIsNotNone(sess)
        self.assertEqual(sess["workspace"], "d:/models/output/a")
        self.store.set_workspace(sid, "d:/models/output/b")
        self.assertEqual(self.store.get_session(sid)["workspace"], "d:/models/output/b")
        listed = self.store.list_sessions()
        self.assertEqual(listed[0]["workspace"], "d:/models/output/b")

    def test_workspace_default_none(self) -> None:
        sid = self.store.create_session("无目录")
        self.assertIsNone(self.store.get_session(sid)["workspace"])

    def test_delete_session_cascade(self) -> None:
        sid = self.store.create_session("待删")
        self.store.append_message(sid, {"role": "user", "content": "hi"})
        run_id = self.store.start_run(sid, "hi")
        self.store.finish_run(run_id, "ok", 1, 3, 4)
        self.store.delete_session(sid)
        self.assertIsNone(self.store.get_session(sid))
        self.assertEqual(self.store.load_messages(sid), [])
        self.assertEqual(self.store.usage_summary(sid), [])


# ---------------------------------------------------------------------- services
class ServiceManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        reg_dir = self.root / "scripts" / "llama_cpp"
        reg_dir.mkdir(parents=True)
        (reg_dir / "models.json").write_text(json.dumps({
            "_readme": "说明",
            "m1": {"name": "模型一", "task": "对话", "desc": "d1"},
            "m2": {"name": "模型二", "task": "出图", "desc": "d2"},
            "embed": {"name": "嵌入", "role": "embed", "task": "向量化"},
            "rerank": {"name": "精排", "role": "rerank", "task": "精排"},
            "router": {"name": "路由器", "role": "router", "task": "任务路由"},
        }), encoding="utf-8")
        self.cfg = make_cfg(self.root)
        self.svc = ServiceManager(self.cfg)

    def tearDown(self) -> None:
        self.svc.close()
        self._tmp.cleanup()

    def test_models_registry(self) -> None:
        models = self.svc.models()
        self.assertEqual([m["key"] for m in models], ["m1", "m2"])
        self.assertEqual(models[0]["name"], "模型一")
        self.assertIn("active", models[0])

    def test_models_registry_missing(self) -> None:
        (self.root / "scripts" / "llama_cpp" / "models.json").unlink()
        self.assertEqual(self.svc.models(), [])

    def test_status_keys(self) -> None:
        st = self.svc.status()
        for key in ("llm", "comfy", "embed", "rerank"):
            self.assertIn(key, st)
            self.assertIn("online", st[key])

    def test_kill_port_unused(self) -> None:
        self.assertEqual(kill_port(59999), [])

    def test_models_exclude_embed_rerank(self) -> None:
        # role=embed/rerank 的是 RAG 后端服务，不出现在对话模型切换列表
        keys = [m["key"] for m in self.svc.models()]
        self.assertEqual(keys, ["m1", "m2"])

    def test_aux_service_actions(self) -> None:
        # 端口已在线 → 直接返回成功，不再起进程
        with patch("agent.services._port_alive", return_value=True):
            self.assertTrue(self.svc.ensure_embed()["ok"])
            self.assertTrue(self.svc.ensure_rerank()["ok"])
        # 无进程无占用 → 停止返回「本就不在运行」
        with patch("agent.services._port_alive", return_value=False), \
                patch("agent.services.kill_port", return_value=[]):
            r = self.svc.stop_rerank()
        self.assertTrue(r["ok"])
        self.assertIn("本就不在运行", r["msg"])


# ---------------------------------------------------------------------- RAG 上下文记忆
class RagMemoryTests(unittest.TestCase):
    """向量库跟随工作区；archive/recall 供 loop 的上下文记忆使用。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from agent.memory import rag
        from agent.tools import scope
        self.rag = rag
        self.scope = scope
        rag.configure(make_cfg(self.root))
        # 固定向量：距离恒 0 → 退化分数 1.0；精排关闭
        self._p1 = patch.object(rag, "_embed",
                                lambda texts: [[0.1] * rag.EMBED_DIM for _ in texts])
        self._p2 = patch.object(rag, "_rerank", lambda q, d, k: [])
        self._p1.start()
        self._p2.start()
        self._old_ws = scope.WORKSPACE
        self.ws_a = self.root / "wsA"
        self.ws_b = self.root / "wsB"
        scope.WORKSPACE = self.ws_a

    def tearDown(self) -> None:
        self.scope.WORKSPACE = self._old_ws
        self._p1.stop()
        self._p2.stop()
        self._tmp.cleanup()

    def test_db_follows_workspace(self) -> None:
        n = self.rag.archive(["主角名叫阿黎，第三章黑化"], source="context")
        self.assertEqual(n, 1)
        self.assertTrue((self.ws_a / "kb" / "vectors.db").exists())
        # 切到另一个任务工作区 → 召回不到（库互相隔离）
        self.scope.WORKSPACE = self.ws_b
        self.assertEqual(self.rag.recall("阿黎"), [])
        # 切回来 → 能召回
        self.scope.WORKSPACE = self.ws_a
        hits = self.rag.recall("主角设定")
        self.assertEqual(len(hits), 1)
        self.assertIn("阿黎", hits[0][0])

    def test_archive_dedup(self) -> None:
        self.assertEqual(self.rag.archive(["同一段话"]), 1)
        self.assertEqual(self.rag.archive(["同一段话"]), 0)  # 内容哈希去重

    def test_recall_only_context(self) -> None:
        self.rag.archive(["小说正文：青云山下的村庄"], source="novel")
        self.assertEqual(self.rag.recall("青云山"), [])          # 非 context 来源被过滤
        self.assertIn("青云山", self.rag.search("青云山"))        # 但 kb_search 能查到

    def test_recall_min_score(self) -> None:
        self.rag.archive(["低相关片段"], source="context")
        # 精排给出低分 → 被阈值挡掉
        with patch.object(self.rag, "_rerank", lambda q, d, k: [(0, 0.10)]):
            self.assertEqual(self.rag.recall("低相关", min_score=0.35), [])
        with patch.object(self.rag, "_rerank", lambda q, d, k: [(0, 0.90)]):
            self.assertEqual(len(self.rag.recall("低相关", min_score=0.35)), 1)

    def test_clear_source(self) -> None:
        self.rag.archive(["临时片段一", "临时片段二"], source="temp")
        self.assertEqual(self.rag.clear_source("temp"), 2)
        self.assertEqual(self.rag.clear_source("temp"), 0)
        self.assertIn("知识库为空", self.rag.search("临时"))

    def test_consolidate(self) -> None:
        self.rag.archive(["[user] 主角叫阿黎", "[assistant] 第三章黑化"], source="context")
        with patch("agent.llm.LLMClient", _CardLLM):
            msg = self.rag.consolidate()
        self.assertIn("记忆整理完成", msg)
        # 记忆卡写进工作区
        card = (self.ws_a / "MEMORY.md").read_text(encoding="utf-8")
        self.assertIn("阿黎", card)
        # 摘要块入库且 recall 能命中（doc=summary 不过滤）
        hits = self.rag.recall("主角")
        self.assertTrue(any("阿黎" in h[0] for h in hits))
        # 再次整理 → 旧摘要被整体替换，不叠加
        with patch("agent.llm.LLMClient", _CardLLM):
            self.rag.consolidate()
        import sqlite3
        conn = sqlite3.connect(str(self.ws_a / "kb" / "vectors.db"))
        n = conn.execute("SELECT COUNT(*) FROM chunks WHERE doc='summary'").fetchone()[0]
        conn.close()
        self.assertEqual(n, 1)

    def test_consolidate_empty(self) -> None:
        self.assertIn("没有可整理", self.rag.consolidate())


class _CardLLM:
    """记忆蒸馏用的假 LLM：直接产出记忆卡。"""

    def __init__(self, cfg=None) -> None:
        pass

    def chat(self, messages, **kw) -> Reply:
        return Reply(content="## 设定与事实\n主角阿黎，第三章黑化。", usage={})


# ---------------------------------------------------------------------- loop 记忆钩子
class _FinalLLM:
    """直接给最终答复的假 LLM。"""
    model = "fake"

    def chat(self, messages, **kw) -> Reply:
        return Reply(content="done", usage={"prompt_tokens": 1, "completion_tokens": 1})


class LoopMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from agent.loop import AgentLoop
        from agent.tools import scope
        cfg = Config({
            "llm": {"base_url": "http://127.0.0.1:1/v1", "model": "fake"},
            "loop": {"max_rounds": 2, "max_history_chars": 300,
                     "tool_result_max_chars": 200},
            "tools": {"enabled": [], "retry": 0, "allowed_roots": []},
            "paths": {"workspace": str(self.root / "ws"), "db": str(self.root / "s.db"),
                      "output_root": str(self.root / "out"),
                      "trace": str(self.root / "trace.jsonl")},
            "rag": {"memory": True, "recall_top_k": 3, "recall_min_score": 0.35},
        }, Path("test-config"))
        self._old_ws = scope.WORKSPACE
        scope.WORKSPACE = self.root / "ws"
        self.store = SessionStore(self.root / "s.db")
        self.loop = AgentLoop(cfg, _FinalLLM(), StubRegistry(), store=self.store)

    def tearDown(self) -> None:
        from agent.tools import scope
        scope.WORKSPACE = self._old_ws
        self.store.close()
        self._tmp.cleanup()

    def test_recall_injected_and_trim_archived(self) -> None:
        sid = self.store.create_session("记忆测试")
        with patch("agent.memory.rag.recall",
                   return_value=[("[user] 主角叫阿黎", 0.92)]) as rc, \
                patch("agent.memory.rag.archive", return_value=2) as ar:
            r1 = self.loop.run("任务一", sid)
            self.assertEqual(r1.stopped_reason, "done")
            # 召回片段注入 system prompt
            self.assertIn("历史记忆", r1.messages[0]["content"])
            self.assertIn("阿黎", r1.messages[0]["content"])
            self.assertTrue(rc.called)
            # 塞入超长历史，下一次运行必然裁剪
            self.store.append_message(sid, {"role": "user", "content": "问" * 400})
            self.store.append_message(sid, {"role": "assistant", "content": "答" * 400})
            r2 = self.loop.run("任务二", sid)
            self.assertEqual(r2.stopped_reason, "done")
            self.assertTrue(ar.called)  # 裁剪掉的片段被归档
            archived_texts = ar.call_args[0][0]
            self.assertTrue(any("任务一" in t for t in archived_texts))  # 最旧一轮先丢

    def test_memory_card_injected(self) -> None:
        ws = self.root / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "MEMORY.md").write_text("## 已定决策\n主角阿黎。", encoding="utf-8")
        sid = self.store.create_session("记忆卡")
        with patch("agent.memory.rag.recall", return_value=[]):
            r = self.loop.run("继续写第四章", sid)
        self.assertIn("任务记忆卡", r.messages[0]["content"])
        self.assertIn("阿黎", r.messages[0]["content"])
        self.assertNotIn("历史记忆", r.messages[0]["content"])

    def test_memory_broken_degrades_silently(self) -> None:
        sid = self.store.create_session("降级测试")
        with patch("agent.memory.rag.recall", side_effect=RuntimeError("embed 离线")):
            r = self.loop.run("任务", sid)  # 不抛异常，正常完成
        self.assertEqual(r.stopped_reason, "done")
        self.assertTrue(self.loop._memory_broken)
        self.assertNotIn("历史记忆", r.messages[0]["content"])


# ---------------------------------------------------------------------- task_router
class TaskRouterTests(unittest.TestCase):
    """task_router.route：注册表过滤、JSON 解析、降级。"""

    _REG = {
        "_readme": "说明",
        "m_small": {"name": "小模型", "task": "轻任务"},
        "m_big": {"name": "旗舰", "task": "重任务"},
        "embed": {"role": "embed"},
        "rerank": {"role": "rerank"},
        "router": {"role": "router"},
    }

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        reg_dir = self.root / "scripts" / "llama_cpp"
        reg_dir.mkdir(parents=True)
        (reg_dir / "models.json").write_text(
            json.dumps(self._REG, ensure_ascii=False), encoding="utf-8")
        self.cfg = Config({"tools": {"scripts_dir": str(self.root / "scripts")},
                           "router": {"enabled": True, "port": 8083, "timeout": 5}},
                          Path("test-config"))
        cfg_off = make_cfg(self.root)
        cfg_off.data["router"] = {"enabled": False}
        self.cfg_router_off = cfg_off

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---------------- 规则路由 ----------------
    def _reg_with_real_keys(self) -> None:
        reg = dict(self._REG)
        reg["qwen36"] = {"name": "旗舰", "task": "重任务"}
        reg["qwen25vl"] = {"name": "多模态", "task": "看图"}
        (self.root / "scripts" / "llama_cpp" / "models.json").write_text(
            json.dumps(reg, ensure_ascii=False), encoding="utf-8")

    def test_pick_by_rules(self) -> None:
        from agent import task_router
        self._reg_with_real_keys()
        # 看图 → 多模态
        info = task_router.pick_by_rules(self.cfg, "帮我识别这张图片里的文字")
        self.assertEqual(info["key"], "qwen25vl")
        # 长文 → 旗舰
        info = task_router.pick_by_rules(self.cfg, "把小说第三章改成分镜脚本")
        self.assertEqual(info["key"], "qwen36")
        # 闲聊/无命中 → None
        self.assertIsNone(task_router.pick_by_rules(self.cfg, "你好"))
        # 候选不在注册表 → None（兜底）
        self.cfg.data["tools"]["scripts_dir"] = str(self.root / "scripts2")
        self.assertIsNone(task_router.pick_by_rules(self.cfg, "写小说"))

    def test_inertia_fallback(self) -> None:
        """webui._maybe_route：规则没命中时沿用任务上次模型；规则优先于惯性。"""
        webui = WebUI(self.cfg_router_off, port=0)
        webui._ensure_all()
        store = webui._store
        assert store is not None
        sid = store.create_session(title="t")
        store.set_last_model(sid, "m_big")
        with patch.object(webui._services, "llm_status",
                          return_value={"model": "m_small", "online": True}), \
                patch.object(webui._services, "ensure_llm",
                             return_value={"ok": True}) as ens:
            # 无规则命中 → 惯性 m_big，触发切换
            info = webui._maybe_route("随便聊聊", session_id=sid)
            self.assertEqual(info["key"], "m_big")
            self.assertIn("沿用", info["reason"])
            ens.assert_called_once_with("m_big")
        with patch.object(webui._services, "llm_status",
                          return_value={"model": "m_big", "online": True}), \
                patch.object(webui._services, "ensure_llm") as ens2:
            # 已是 m_big → 不重复切换
            webui._maybe_route("继续", session_id=sid)
            ens2.assert_not_called()
        # 切换失败 → 返回 None，留在当前模型
        with patch.object(webui._services, "llm_status",
                          return_value={"model": "m_small", "online": True}), \
                patch.object(webui._services, "ensure_llm",
                             return_value={"ok": False}):
            self.assertIsNone(webui._maybe_route("继续", session_id=sid))
        webui.stop()
        import gc
        gc.collect()

    def test_chat_models_filters_roles(self) -> None:
        from agent import task_router
        self.assertEqual(sorted(task_router._chat_models(self.cfg)), ["m_big", "m_small"])


# ---------------------------------------------------------------------- orchestrator
class FakeServices:
    def __init__(self) -> None:
        self.actions: list[tuple] = []

    def ensure_llm(self, key: str, timeout: float = 600) -> dict:
        self.actions.append(("ensure_llm", key))
        return {"ok": True, "msg": "ok"}

    def stop_llm(self) -> dict:
        self.actions.append(("stop_llm",))
        return {"ok": True, "msg": "ok"}

    def ensure_comfy(self, timeout: float = 300) -> dict:
        self.actions.append(("ensure_comfy",))
        return {"ok": True, "msg": "ok"}

    def stop_comfy(self) -> dict:
        self.actions.append(("stop_comfy",))
        return {"ok": True, "msg": "ok"}


class StubRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def schemas(self) -> list[dict]:
        return [{"type": "function", "function": {
            "name": "generate_image",
            "parameters": {"type": "object",
                           "properties": {"prompt": {"type": "string"}}}}}]

    def names(self) -> list[str]:
        return ["generate_image"]

    def call(self, name: str, args: dict, retries: int = 0) -> ToolResult:
        self.calls.append((name, args))
        return ToolResult(name, True, "图片已保存: out.png", 1.0)


class FakeLLM:
    """按提示词特征分发：规划 / 文本步骤（带 system）/ 产参数。"""

    def __init__(self, cfg=None) -> None:
        self.model = "fake"

    def chat(self, messages, **kw) -> Reply:
        first = messages[0]
        content = first.get("content", "")
        if first.get("role") == "system":
            return Reply(content="文案完成", usage={"prompt_tokens": 5, "completion_tokens": 3})
        if "规划器" in content:
            return Reply(content=json.dumps({
                "approach": "novel2video", "reason": "测试", "est_cost": "high",
                "steps": [{"goal": "写文案", "tool": "none"},
                          {"goal": "出图", "tool": "generate_image"}],
            }), usage={"prompt_tokens": 10, "completion_tokens": 20})
        if "生成调用参数" in content:
            return Reply(content='{"prompt":"一只猫","width":512}',
                         usage={"prompt_tokens": 8, "completion_tokens": 6})
        return Reply(content="?", usage={})


class PlannedRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = make_cfg(Path(self._tmp.name))
        self.store = SessionStore(self.cfg.path("paths.db"))

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def _wait_done(self, runner: PlannedRunner, run_id: str, timeout: float = 10) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            run = runner.get(run_id)
            if run and run["status"] != "running":
                return run
            time.sleep(0.1)
        self.fail("流水线超时未结束")

    def test_pipeline_switches_services(self) -> None:
        services = FakeServices()
        registry = StubRegistry()
        runner = PlannedRunner(self.cfg, registry, self.store, services, threading.Lock())
        sid = self.store.create_session("小说转视频")
        with patch("agent.orchestrator.LLMClient", FakeLLM):
            run_id = runner.start(sid, "把小说第一章做成视频", model_key="m1")
            run = self._wait_done(runner, run_id)

        self.assertEqual(run["status"], "done")
        # 服务切换序列：规划 ensure_llm → 文本步 ensure_llm → 出图前 stop_llm+ensure_comfy
        # → 结束后 stop_comfy + restore ensure_llm
        seq = services.actions
        self.assertEqual(seq[0], ("ensure_llm", "m1"))
        self.assertIn(("stop_llm",), seq)
        self.assertIn(("ensure_comfy",), seq)
        self.assertEqual(seq[-2], ("stop_comfy",))
        self.assertEqual(seq[-1], ("ensure_llm", "m1"))
        # 生成工具被直接调用，参数来自 LLM 产出的 JSON
        self.assertEqual(registry.calls, [("generate_image", {"prompt": "一只猫", "width": 512})])
        # 事件流含规划、token、工具入参/结果
        kinds = [e["kind"] for e in run["events"]]
        for expect in ("plan", "service", "tokens", "tool_args", "tool_result", "done"):
            self.assertIn(expect, kinds)
        # token 汇总：规划 10+20、文本步 5+3、产参 8+6
        self.assertEqual(run["prompt_tokens"], 23)
        self.assertEqual(run["completion_tokens"], 29)
        # 文本步产出以「步骤摘要」形式落会话消息（内部轮次不再写入历史）
        msgs = self.store.load_messages(sid)
        step_msgs = [m.get("content") or "" for m in msgs
                     if (m.get("content") or "").startswith("[流水线步骤")]
        self.assertTrue(any("文案完成" in c for c in step_msgs))

    def test_run_graph_persisted(self) -> None:
        """运行图落库：重启后仍能按 run_id/会话回看，token 同时进 runs 账本。"""
        services = FakeServices()
        runner = PlannedRunner(self.cfg, StubRegistry(), self.store, services, threading.Lock())
        sid = self.store.create_session("落库")
        with patch("agent.orchestrator.LLMClient", FakeLLM):
            run_id = runner.start(sid, "把小说第一章做成视频", model_key="m1")
            self._wait_done(runner, run_id)

        graph = self.store.load_run_graph(run_id)
        self.assertIsNotNone(graph)
        self.assertEqual(graph["status"], "done")
        self.assertTrue(graph["plan"]["steps"])
        kinds = [e["kind"] for e in graph["events"]]
        self.assertIn("tool_result", kinds)
        self.assertEqual(self.store.latest_run_graph(sid)["id"], run_id)
        # 流水线本身也记进 runs 账本，后续规划/验收能查到 token
        rows = self.store.runs_detail()
        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0]["prompt_tokens"], 0)

    def test_plan_invalid_tool_normalized(self) -> None:
        class BadPlanLLM(FakeLLM):
            def chat(self, messages, **kw) -> Reply:
                content = messages[0].get("content", "")
                if "规划器" in content:
                    return Reply(content=json.dumps({
                        "approach": "x", "reason": "", "est_cost": "low",
                        "steps": [{"goal": "g", "tool": "delete_everything"}],
                    }), usage={})
                return super().chat(messages, **kw)

        services = FakeServices()
        runner = PlannedRunner(self.cfg, StubRegistry(), self.store, services, threading.Lock())
        sid = self.store.create_session("t")
        with patch("agent.orchestrator.LLMClient", BadPlanLLM):
            run_id = runner.start(sid, "任意任务", model_key="m1")
            run = self._wait_done(runner, run_id)
        self.assertEqual(run["plan"]["steps"][0]["tool"], "none")


# ---------------------------------------------------------------------- webui 端点
class WebUI2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.cfg = make_cfg(self.root)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.webui = WebUI(self.cfg, self.port)
        self.assertTrue(self.webui.start())

    def tearDown(self) -> None:
        self.webui.stop()
        import gc
        gc.collect()
        time.sleep(0.2)
        self._tmp.cleanup()

    def _get(self, path: str):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}{path}", timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _post(self, path: str, payload: dict):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _get_raw(self, path: str):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}{path}", timeout=5) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")

    def test_page_new_brand(self) -> None:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/", timeout=5) as resp:
            html = resp.read().decode("utf-8")
        self.assertIn("本地模型工作站", html)
        self.assertIn("规划执行", html)
        self.assertIn("theme", html)

    def test_session_lifecycle(self) -> None:
        ws = self.root / "task_ws"
        data = self._post("/api/session/new", {"title": "新任务", "workspace": str(ws)})
        sid = data["session_id"]
        self.assertTrue(ws.is_dir())

        detail = self._get(f"/api/session/{sid}")
        self.assertEqual(detail["session"]["workspace"], str(ws))
        self.assertEqual(detail["messages"], [])
        self.assertEqual(detail["usage"], [])

        ws2 = self.root / "task_ws2"
        self._post("/api/session/workspace", {"session_id": sid, "workspace": str(ws2)})
        self.assertEqual(self._get(f"/api/session/{sid}")["session"]["workspace"], str(ws2))

        self._post("/api/session/delete", {"session_id": sid})
        remaining = [s["id"] for s in self._get("/api/sessions")]
        self.assertNotIn(sid, remaining)

    def test_new_session_auto_workspace(self) -> None:
        data = self._post("/api/session/new", {"title": "小说/视频:第一章", "workspace": ""})
        ws = Path(data["workspace"])
        # 每个任务一个沙箱：memory/workspace/<session_id>/
        self.assertEqual(ws.parent, (self.root / "ws").resolve())
        self.assertEqual(ws.name, data["session_id"])
        self.assertTrue(ws.is_dir())
        # 新任务各自独立沙箱，不再按标题建目录
        data2 = self._post("/api/session/new", {"title": "小说/视频:第一章", "workspace": ""})
        self.assertNotEqual(data2["session_id"], data["session_id"])
        self.assertEqual(Path(data2["workspace"]).name, data2["session_id"])
        # 列表里的标题压成小标题（老任务同样处理）
        sess = [s for s in self._get("/api/sessions") if s["id"] == data["session_id"]][0]
        self.assertLessEqual(len(sess["title"]), 16)
        self.assertIn("小说", sess["title"])
        self.assertEqual(sess["sandbox"], data["session_id"])

    def test_upload_multipart(self) -> None:
        sid = self._post("/api/session/new", {"title": "上传", "workspace": ""})["session_id"]
        boundary = "XTESTBOUNDARY"
        body = (
            b"--" + boundary.encode() + b"\r\n"
            b'Content-Disposition: form-data; name="session_id"\r\n\r\n' + sid.encode() + b"\r\n"
            b"--" + boundary.encode() + b"\r\n"
            b'Content-Disposition: form-data; name="file"; filename="note.txt"\r\n'
            b"Content-Type: text/plain\r\n\r\n"
            b"hello-upload\r\n"
            b"--" + boundary.encode() + b"--\r\n"
        )
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/upload", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertTrue(data["ok"])
        saved = Path(data["path"])
        self.assertTrue(saved.exists())
        self.assertEqual(saved.read_bytes(), b"hello-upload")
        self.assertIn("uploads", str(saved))

    def test_misc_endpoints(self) -> None:
        self.assertIsInstance(self._get("/api/models"), list)
        self.assertIsInstance(self._get("/api/mcp"), list)
        res = self._get("/api/resources")
        self.assertIn("cpu", res)
        svc = self._get("/api/services")
        self.assertIn("llm", svc)
        self.assertIn("log", svc)
        # 未知服务动作被拒绝
        bad = self._post("/api/service", {"action": "boom"})
        self.assertFalse(bad["ok"])

    def test_run_status_empty(self) -> None:
        self.assertEqual(self._get("/api/run_status?run_id=nope"), {})

    def test_run_status_restores_from_store(self) -> None:
        """模拟 WebUI 重启（内存运行记录清空）后，运行图仍能从库恢复。"""
        webui = self.webui
        webui._ensure_all()
        sid = webui._store.create_session("恢复")
        run = webui._runner.open_chat(sid, "任务")
        webui._runner.emit(run, "round", i=1, msg="第 1 轮推理…")
        webui._runner.close(run, "done")
        rid = run.id
        webui._runner._runs.clear()  # 等价于进程重启，内存态丢失

        got = self._get(f"/api/run_status?run_id={rid}")
        self.assertEqual(got["id"], rid)
        self.assertEqual(got["status"], "done")
        self.assertEqual(self._get(f"/api/run_status?session_id={sid}")["id"], rid)
        lst = self._get(f"/api/run_list?session_id={sid}")
        self.assertEqual([x["run_id"] for x in lst], [rid])

    def test_run_list_keeps_error_text(self) -> None:
        """失败的运行在历史列表里直接带出报错原文。"""
        webui = self.webui
        webui._ensure_all()
        sid = webui._store.create_session("报错留档")
        run = webui._runner.open_chat(sid, "任务")
        webui._runner.emit(run, "error", msg="模型调用失败：连接被拒绝")
        webui._runner.close(run, "error")
        webui._runner._runs.clear()
        lst = self._get(f"/api/run_list?session_id={sid}")
        self.assertEqual(lst[0]["status"], "error")
        self.assertIn("连接被拒绝", lst[0]["error"])

    def test_backfill_graphs_from_trace(self) -> None:
        """运行图落库上线前的老运行，能从 trace.jsonl 还原事件与 token。"""
        webui = self.webui
        webui._ensure_all()
        store = webui._store
        sid = store.create_session("老任务")
        store.finish_run(store.start_run(sid, "老任务"), "error", 1, 100, 20, "历史错误")
        trace = Trace(self.cfg.path("paths.trace"))
        trace.start("run-old-1", "老任务",
                    plan={"kind": "chat", "steps": []}, session_id=sid)
        trace.event("round", round=1)
        trace.event("llm", round=1, prompt=100, completion=20, ms=10)
        trace.event("tool_call", name="web_search", args='{"q": "x"}')
        trace.event("tool_result", name="web_search", ok=True, ms=5, brief="搜索结果")
        trace.event("run_end", status="llm_error")
        webui._backfill_run_graphs()

        run = self._get("/api/run_status?run_id=run-old-1")
        self.assertEqual(run["status"], "error")
        self.assertEqual(run["session_id"], sid)
        self.assertEqual(run["prompt_tokens"], 100)
        self.assertEqual(run["completion_tokens"], 20)
        self.assertIn("tool_result", [e["kind"] for e in run["events"]])

    def test_stale_running_marked_interrupted(self) -> None:
        """进程重开后，上次未结束的运行不能一直显示“运行中”。"""
        webui = self.webui
        webui._ensure_all()
        sid = webui._store.create_session("中断")
        webui._store.start_run(sid, "中断任务")
        webui._recover_runs()
        rows = webui._store.runs_detail()
        self.assertTrue(any(r["status"] == "interrupted" for r in rows))

    def test_chat_async_run_events(self) -> None:
        """对话异步化：决策/轮次/token/工具/答案全部进事件流，token 累计正确。"""
        from agent.loop import LoopResult
        webui = self.webui
        webui._ensure_all()

        class _CB:
            on_round = on_llm = on_tool_call = on_tool_result = None

        class _Loop:
            cb = None
            def __init__(self):
                self.cb = _CB()
                self.workspace = ""
            def run(self, msg, sid, extra_system=""):
                self.extra_system = extra_system
                self.cb.on_round(1)
                self.cb.on_assistant("回")   # 流式增量应累积进 run.draft
                self.cb.on_assistant("答")
                self.cb.on_llm(1, 10, 5)
                self.cb.on_tool_call("run_command", "{}")
                self.cb.on_tool_result("run_command", True, "ok", 0.01)
                r = LoopResult(content="回答", stopped_reason="done")
                r.prompt_tokens, r.completion_tokens = 10, 5
                return r

        webui._loop = _Loop()
        # 后台线程 _chat_bg 在 POST 返回后才执行，patch 必须覆盖整个轮询区间
        patcher = patch.object(webui._services, "llm_status",
                               return_value={"model": "nanbeige", "online": True})
        patcher.start()
        try:
            resp = self._post("/api/chat", {"session_id": None, "message": "你好"})
            self.assertTrue(resp.get("run_id"))
            run = {}
            for _ in range(50):
                run = self._get(f"/api/run_status?run_id={resp['run_id']}")
                if run.get("status") != "running":
                    break
                time.sleep(0.1)
        finally:
            patcher.stop()
        self.assertEqual(run["status"], "done")
        kinds = [e["kind"] for e in run["events"]]
        for k in ("decision", "round", "llm", "tool_call", "tool_result", "answer"):
            self.assertIn(k, kinds)
        self.assertEqual(run["prompt_tokens"], 10)
        self.assertEqual(run["completion_tokens"], 5)
        self.assertEqual(run["plan"]["kind"], "chat")
        # 流式草稿累积了 on_assistant 的增量
        self.assertEqual(run["draft"], "回答")
        # 答案事件带最终内容
        ans = [e for e in run["events"] if e["kind"] == "answer"][0]
        self.assertEqual(ans["msg"], "回答")

    def test_maybe_route_switches_model(self) -> None:
        self.webui._ensure_all()
        reg_dir = self.root / "scripts" / "llama_cpp"
        reg_dir.mkdir(parents=True, exist_ok=True)
        (reg_dir / "models.json").write_text(json.dumps(
            {"qwen36": {"name": "旗舰", "task": "重"}},
            ensure_ascii=False), encoding="utf-8")
        # 规则命中且当前不是目标 → 切换
        with patch.object(self.webui._services, "llm_status",
                          return_value={"model": "nanbeige", "online": True}), \
                patch.object(self.webui._services, "ensure_llm",
                             return_value={"ok": True}) as ens:
            info = self.webui._maybe_route("把小说第三章改成分镜")
        self.assertEqual(info["key"], "qwen36")
        ens.assert_called_once_with("qwen36")
        # 已是目标模型 → 不重复切换；无命中 → None
        with patch.object(self.webui._services, "llm_status",
                          return_value={"model": "qwen36", "online": True}), \
                patch.object(self.webui._services, "ensure_llm") as ens2:
            self.webui._maybe_route("再写第四章小说")
            ens2.assert_not_called()
            self.assertIsNone(self.webui._maybe_route("你好"))

    def test_auto_title(self) -> None:
        self.webui._ensure_all()
        store = self.webui._store
        assert store is not None
        msg = "帮我把小说第三章改成电影分镜脚本，要求包含运镜说明"
        sid = store.create_session(title=msg[:50])       # 自动前缀标题
        with patch.object(self.webui, "_gen_title", return_value="小说第三章分镜脚本"):
            t = self.webui._auto_title(sid, msg)
        self.assertEqual(t, "小说第三章分镜脚本")
        self.assertEqual(store.get_session(sid)["title"], "小说第三章分镜脚本")
        # 用户显式命名过 → 不动
        sid2 = store.create_session(title="我的项目")
        with patch.object(self.webui, "_gen_title", return_value="x") as g:
            self.assertEqual(self.webui._auto_title(sid2, msg), "")
            g.assert_not_called()
        # 模型起不出名 → 标题保持原样
        sid3 = store.create_session(title=msg[:50])
        with patch.object(self.webui, "_gen_title", return_value=""):
            self.assertEqual(self.webui._auto_title(sid3, msg), "")
        self.assertEqual(store.get_session(sid3)["title"], msg[:50])

    def test_gen_title_cleanup(self) -> None:
        self.webui._ensure_all()

        class _LLM:
            def chat(self, msgs, tools=None, stream=False):
                return type("R", (), {"content": "《小说第三章》\n补充说明"})()

        self.webui._llm = _LLM()
        self.assertEqual(self.webui._gen_title("任意任务"), "小说第三章")
        # 主模型不可用 → 空
        self.webui._llm = None
        self.assertEqual(self.webui._gen_title("任意任务"), "")

    def test_files_endpoints(self) -> None:
        sid = self._post("/api/session/new", {"title": "产出", "workspace": ""})["session_id"]
        ws = Path(self._get("/api/sessions")[0]["workspace"])
        (ws / "kb").mkdir(parents=True, exist_ok=True)
        (ws / "uploads").mkdir(parents=True, exist_ok=True)
        (ws / "分镜01.png").write_bytes(b"\x89PNG fake")
        (ws / "说明.md").write_text("# 标题", encoding="utf-8")
        (ws / "uploads" / "原始.txt").write_text("输入", encoding="utf-8")
        (ws / "kb" / "vectors.db").write_bytes(b"db")          # 向量库应被排除
        data = self._get(f"/api/files?session_id={sid}")
        self.assertEqual(data["sandbox"], sid)
        rels = {f["rel"]: f["kind"] for f in data["outputs"]}
        self.assertEqual(rels.get("分镜01.png"), "image")
        self.assertEqual(rels.get("说明.md"), "text")
        self.assertNotIn("kb/vectors.db", rels)
        self.assertEqual([f["rel"] for f in data["inputs"]], ["uploads/原始.txt"])
        # 文件内容 + MIME
        from urllib.parse import quote
        code, data, ctype = self._get_raw(
            f"/api/file?session_id={sid}&path={quote('分镜01.png')}")
        self.assertEqual(code, 200)
        self.assertEqual(data, b"\x89PNG fake")
        self.assertIn("image/png", ctype)
        # 目录穿越被拒
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._get_raw(f"/api/file?session_id={sid}&path=" + quote("../../configs"))
        self.assertEqual(cm.exception.code, 404)

    def test_consolidate_endpoint(self) -> None:
        sid = self._post("/api/session/new", {"title": "整理", "workspace": ""})["session_id"]
        with patch("agent.memory.rag.consolidate", return_value="记忆整理完成：5 个片段"):
            r = self._post("/api/memory/consolidate", {"session_id": sid})
        self.assertTrue(r["ok"])
        self.assertIn("整理完成", r["msg"])
        bad = self._post("/api/memory/consolidate", {"session_id": "nope"})
        self.assertFalse(bad["ok"])

    def test_schedule_endpoints(self) -> None:
        # WebUI 内置调度器默认运行
        self.assertTrue(self._get("/api/schedule")["enabled"])
        r = self._post("/api/schedule/add",
                       {"task": "每日汇总", "schedule_type": "daily", "daily_time": "09:00"})
        self.assertTrue(r["ok"])
        tasks = self._get("/api/schedule")["tasks"]
        item = [t for t in tasks if t["task"] == "每日汇总"][0]
        self.assertEqual(item["desc"], "每天 09:00")
        # 取消 → 停用但不删除
        self.assertTrue(self._post("/api/schedule/cancel", {"id": item["id"]})["ok"])
        item2 = [t for t in self._get("/api/schedule")["tasks"] if t["id"] == item["id"]][0]
        self.assertFalse(item2["enabled"])
        # 暂停 / 恢复调度器
        self._post("/api/schedule/toggle", {"enabled": False})
        self.assertFalse(self._get("/api/schedule")["enabled"])
        self._post("/api/schedule/toggle", {"enabled": True})
        self.assertTrue(self._get("/api/schedule")["enabled"])
        # 空任务 / 未知类型被拒
        self.assertFalse(self._post("/api/schedule/add",
                                    {"task": "", "schedule_type": "daily"})["ok"])
        self.assertFalse(self._post("/api/schedule/add",
                                    {"task": "x", "schedule_type": "hourly"})["ok"])


# ---------------------------------------------------------------------- 看板任务汇总
class MonitorTasksTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.trace = Trace(self.root / "trace.jsonl")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.monitor = Monitor(self.trace, self.root / "preview", self.port,
                               db_path=self.root / "s.db")
        self.assertTrue(self.monitor.start())

    def tearDown(self) -> None:
        self.monitor.stop()
        import gc
        gc.collect()
        time.sleep(0.2)
        self._tmp.cleanup()

    def test_tasks_aggregation(self) -> None:
        # 账本：一次运行，100 prompt + 50 completion
        store = SessionStore(self.root / "s.db")
        sid = store.create_session("小说转视频")
        rid = store.start_run(sid, "把小说做成视频")
        store.finish_run(rid, "ok", 3, 100, 50)
        store.close()
        # 流程：同任务文本的 trace 事件
        self.trace.start("r1", "把小说做成视频",
                         plan={"steps": [{"goal": "写文案", "tool": "none"},
                                         {"goal": "出图", "tool": "generate_image"}]})
        self.trace.event("llm", prompt=100, completion=50)
        self.trace.event("step_start", index=0, goal="写文案", tool="none")
        self.trace.event("step_end", index=0, status="done")
        self.trace.event("tool_result", name="generate_image", ok=True, ms=500, brief="x")
        self.trace.event("run_end", status="ok")

        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/api/tasks", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(len(data["tasks"]), 1)
        t = data["tasks"][0]
        self.assertEqual(t["title"], "小说转视频")  # 标题取会话名
        self.assertEqual(t["runs"], 1)
        self.assertEqual(t["prompt"], 100)
        self.assertEqual(t["completion"], 50)
        self.assertEqual(len(t["flows"]), 1)
        flow = t["flows"][0]
        self.assertEqual(flow["tokens"], 150)
        self.assertEqual(flow["tools"], 1)
        self.assertEqual(flow["status"], "ok")
        self.assertEqual(flow["step_status"]["0"], "done")
        self.assertEqual(len(flow["plan"]["steps"]), 2)


if __name__ == "__main__":
    unittest.main()
