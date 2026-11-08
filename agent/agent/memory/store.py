# -*- coding: utf-8 -*-
"""记忆子系统的持久化层：SQLite 单文件。

三类数据：
  sessions  会话（标题、时间）
  messages  消息（含 tool_calls / tool_call_id，可直接还原成 OpenAI 格式）
  runs      每次任务执行（轮数、状态、token 用量）——本地监控的原始账本
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    role         TEXT NOT NULL,
    content      TEXT,
    tool_calls   TEXT,
    tool_call_id TEXT,
    name         TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id         TEXT NOT NULL,
    task               TEXT,
    started_at         TEXT NOT NULL,
    finished_at        TEXT,
    status             TEXT,
    rounds             INTEGER DEFAULT 0,
    prompt_tokens      INTEGER DEFAULT 0,
    completion_tokens  INTEGER DEFAULT 0,
    total_tokens       INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS run_graphs (
    run_id     TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    payload    TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_graphs_session ON run_graphs(session_id, updated_at);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class SessionStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """老库补列：sessions.workspace / last_model，runs.error（运行报错留档）。"""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(sessions)").fetchall()}
        if "workspace" not in cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN workspace TEXT")
        if "last_model" not in cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN last_model TEXT")
        run_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(runs)").fetchall()}
        if "error" not in run_cols:
            self._conn.execute("ALTER TABLE runs ADD COLUMN error TEXT")

    # ---------------------------------------------------------------- 会话
    def create_session(self, title: str = "", workspace: str | None = None) -> str:
        sid = uuid.uuid4().hex[:12]
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions(id, title, created_at, updated_at, workspace)"
                " VALUES (?,?,?,?,?)",
                (sid, title or "未命名会话", now, now, workspace),
            )
            self._conn.commit()
        return sid

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, title, created_at, updated_at, workspace, last_model"
            " FROM sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None

    def set_last_model(self, session_id: str, model_key: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET last_model=? WHERE id=?",
                (model_key, session_id),
            )
            self._conn.commit()

    def set_workspace(self, session_id: str, workspace: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET workspace=?, updated_at=? WHERE id=?",
                (workspace, _now(), session_id),
            )
            self._conn.commit()

    def delete_session(self, session_id: str) -> None:
        """删除会话及其消息、运行账本、运行图。"""
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            self._conn.execute("DELETE FROM runs WHERE session_id=?", (session_id,))
            self._conn.execute("DELETE FROM run_graphs WHERE session_id=?", (session_id,))
            self._conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            self._conn.commit()

    def touch_session(self, session_id: str, title: str | None = None) -> None:
        with self._lock:
            if title:
                self._conn.execute("UPDATE sessions SET title=?, updated_at=? WHERE id=?",
                                   (title, _now(), session_id))
            else:
                self._conn.execute("UPDATE sessions SET updated_at=? WHERE id=?",
                                   (_now(), session_id))
            self._conn.commit()

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, title, created_at, updated_at, workspace FROM sessions"
            " ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- 消息
    def append_message(self, session_id: str, msg: dict[str, Any]) -> None:
        tool_calls = msg.get("tool_calls")
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages(session_id, role, content, tool_calls, tool_call_id, name, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    session_id,
                    msg.get("role", ""),
                    msg.get("content") or "",
                    json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                    msg.get("tool_call_id"),
                    msg.get("name"),
                    _now(),
                ),
            )
            self._conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (_now(), session_id))
            self._conn.commit()

    def load_messages(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT role, content, tool_calls, tool_call_id, name FROM messages"
            " WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            msg: dict[str, Any] = {"role": row["role"], "content": row["content"] or ""}
            if row["tool_calls"]:
                msg["tool_calls"] = json.loads(row["tool_calls"])
            if row["tool_call_id"]:
                msg["tool_call_id"] = row["tool_call_id"]
            if row["name"]:
                msg["name"] = row["name"]
            messages.append(msg)
        return messages

    def clear_messages(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            self._conn.commit()

    # ---------------------------------------------------------------- 运行账本
    def start_run(self, session_id: str, task: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO runs(session_id, task, started_at, status) VALUES (?,?,?,?)",
                (session_id, task[:1000], _now(), "running"),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, rounds: int,
                   prompt_tokens: int = 0, completion_tokens: int = 0,
                   error: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET finished_at=?, status=?, rounds=?, prompt_tokens=?,"
                " completion_tokens=?, total_tokens=?, error=? WHERE id=?",
                (_now(), status, rounds, prompt_tokens, completion_tokens,
                 prompt_tokens + completion_tokens, (error or "")[:2000], run_id),
            )
            self._conn.commit()

    def runs_detail(self, limit: int = 500) -> list[dict[str, Any]]:
        """运行账本明细（含起止时间与报错），供看板按任务汇总开销。"""
        rows = self._conn.execute(
            "SELECT session_id, task, started_at, finished_at, status, rounds,"
            " prompt_tokens, completion_tokens, error FROM runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def usage_summary(self, session_id: str | None = None) -> list[dict[str, Any]]:
        sql = ("SELECT session_id, COUNT(*) AS runs, SUM(rounds) AS rounds,"
               " SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens"
               " FROM runs")
        params: tuple = ()
        if session_id:
            sql += " WHERE session_id=?"
            params = (session_id,)
        sql += " GROUP BY session_id ORDER BY runs DESC"
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    # ---------------------------------------------------------------- 运行图
    def save_run_graph(self, run_id: str, session_id: str, payload: dict[str, Any],
                       updated_at: str | None = None) -> None:
        """整份运行图（计划 + 事件流 + 逐步 token）落库，重启 WebUI 后仍可回看。

        `updated_at` 可显式传入：从 trace 回填老运行时用其开始时间，
        这样「最近一次运行」和历史列表的排序仍按真实时间，而不是回填时刻。
        """
        with self._lock:
            self._conn.execute(
                "INSERT INTO run_graphs(run_id, session_id, payload, updated_at) VALUES (?,?,?,?)"
                " ON CONFLICT(run_id) DO UPDATE SET payload=excluded.payload,"
                " updated_at=excluded.updated_at",
                (run_id, session_id, json.dumps(payload, ensure_ascii=False),
                 updated_at or _now()),
            )
            self._conn.commit()

    def run_graph_ids(self) -> set[str]:
        return {r["run_id"] for r in self._conn.execute(
            "SELECT run_id FROM run_graphs").fetchall()}

    def close_stale_runs(self, status: str = "interrupted") -> int:
        """进程重开后，上次没跑完的 run 不可能是活的：标记为中断，避免界面永远转圈。"""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE runs SET status=?, finished_at=? WHERE status='running'",
                (status, _now()))
            self._conn.commit()
            return cur.rowcount

    def mark_stale_run_graphs(self, status: str = "interrupted") -> int:
        """同上，同步修正运行图快照里的 running 状态。"""
        fixed = 0
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id, payload FROM run_graphs").fetchall()
            for row in rows:
                try:
                    p = json.loads(row["payload"])
                except Exception:
                    continue
                if p.get("status") != "running":
                    continue
                p["status"] = status
                p["finished_at"] = p.get("finished_at") or _now()
                self._conn.execute(
                    "UPDATE run_graphs SET payload=? WHERE run_id=?",
                    (json.dumps(p, ensure_ascii=False), row["run_id"]))
                fixed += 1
            self._conn.commit()
        return fixed

    def session_for_run_task(self, task: str, started_ts: float) -> str:
        """trace 只有任务文本与时间：用「同任务 + 起点最接近」反查所属会话。"""
        rows = self._conn.execute(
            "SELECT session_id, started_at FROM runs WHERE task=?", (task,)).fetchall()
        best, best_dt = "", None
        for row in rows:
            try:
                ts = time.mktime(time.strptime(row["started_at"], "%Y-%m-%d %H:%M:%S"))
            except Exception:
                continue
            dt = abs(ts - float(started_ts or 0))
            if best_dt is None or dt < best_dt:
                best, best_dt = row["session_id"], dt
        return best if (best_dt is not None and best_dt <= 300) else ""

    def session_by_user_message(self, text: str, started_ts: float = 0) -> str:
        """再去消息表里按原文找：更早的运行没进 runs 账本，只能靠用户消息反查会话。

        同一句任务可能在不同任务里重复出现，必须用会话创建时间与运行起点
        做窗口校验（默认 ±1 小时），否则会把孤立的运行挂到别的任务下。
        """
        rows = self._conn.execute(
            "SELECT session_id FROM messages WHERE role='user' AND content=?"
            " ORDER BY id DESC LIMIT 5", (text,)).fetchall()
        for row in rows:
            session = self._conn.execute(
                "SELECT created_at FROM sessions WHERE id=?", (row["session_id"],)).fetchone()
            if not session:
                continue
            try:
                created = time.mktime(
                    time.strptime(session["created_at"], "%Y-%m-%d %H:%M:%S"))
            except Exception:
                created = 0
            if not started_ts or abs(created - float(started_ts)) <= 3600:
                return row["session_id"]
        return ""

    def load_run_graph(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT payload FROM run_graphs WHERE run_id=?", (run_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def latest_run_graph(self, session_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT payload FROM run_graphs WHERE session_id=?"
            " ORDER BY updated_at DESC, rowid DESC LIMIT 1", (session_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_run_graphs(self, session_id: str, limit: int = 30) -> list[dict[str, Any]]:
        """历史运行摘要（不含事件流本体），供运行图的历史下拉选择。"""
        rows = self._conn.execute(
            "SELECT run_id, payload, updated_at FROM run_graphs WHERE session_id=?"
            " ORDER BY updated_at DESC, rowid DESC LIMIT ?", (session_id, limit)).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                p = json.loads(row["payload"])
            except Exception:
                p = {}
            status = p.get("status") or ""
            events = p.get("events") or []
            error = ""
            if status and status != "done":
                error = next((str(e.get("msg") or "") for e in reversed(events)
                              if e.get("kind") == "error" and e.get("msg")), "")
                if not error:
                    error = next((str(e.get("msg") or "") for e in reversed(events)
                                  if e.get("kind") == "answer" and e.get("status") != "done"), "")
            out.append({
                "run_id": row["run_id"], "updated_at": row["updated_at"],
                "task": (p.get("task") or "")[:120], "status": status,
                "started_at": p.get("started_at") or "",
                "prompt_tokens": p.get("prompt_tokens", 0),
                "completion_tokens": p.get("completion_tokens", 0),
                "kind": (p.get("plan") or {}).get("kind") or "pipeline",
                "error": error[:300],
            })
        return out

    def close(self) -> None:
        self._conn.close()
