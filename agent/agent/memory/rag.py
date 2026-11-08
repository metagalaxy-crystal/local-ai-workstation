# -*- coding: utf-8 -*-
"""RAG 子系统：文档解析 → 切片 → 向量化 → sqlite-vec 存储 → 召回/精排。

向量库跟随工作区：当前 scope.WORKSPACE 下的 kb/vectors.db，
即每个任务的文档与上下文记忆都沉淀在该任务自己的目录里。

外部服务（均为 llama-server，CPU 模式零显存）：
- Embedding: Qwen3-Embedding-0.6B，OpenAI 兼容 /v1/embeddings，默认 :8081
- Reranker:  Qwen3-Reranker-0.6B，/rerank 端点，默认 :8082（不可用时退化为纯向量召回）

给 agent 暴露三个工具：kb_ingest（入库）/ kb_search（检索）/ kb_stats（规模）。
另外给 loop 暴露 archive/recall：裁剪掉的对话片段归档入库、新任务按相关度召回。
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

import requests

from ..config import Config

EMBED_DIM = 1024

# ---------------------------------------------------------------- 配置
_embed_url = "http://127.0.0.1:8081/v1"
_rerank_url = "http://127.0.0.1:8082/rerank"
_chunk_size = 500
_chunk_overlap = 100
_top_k = 5
_candidates = 20
_cfg: Config | None = None  # memory_consolidate 需要用它创建 LLM 客户端


def configure(cfg: Config) -> None:
    global _embed_url, _rerank_url, _chunk_size, _chunk_overlap, _top_k, _candidates, _cfg
    _cfg = cfg
    _embed_url = cfg.get("rag.embed_url", _embed_url)
    _rerank_url = cfg.get("rag.rerank_url", _rerank_url)
    _chunk_size = int(cfg.get("rag.chunk_size", _chunk_size))
    _chunk_overlap = int(cfg.get("rag.chunk_overlap", _chunk_overlap))
    _top_k = int(cfg.get("rag.top_k", _top_k))
    _candidates = int(cfg.get("rag.recall_candidates", _candidates))


def current_db() -> Path:
    """知识库跟随当前工作区：每个任务的向量库落在其 workspace/kb/vectors.db。"""
    from ..tools import scope
    return Path(scope.WORKSPACE) / "kb" / "vectors.db"


# ---------------------------------------------------------------- 存储
def _connect() -> sqlite3.Connection:
    import sqlite_vec
    db_path = current_db()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS chunks(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               doc TEXT NOT NULL, page INTEGER, chunk_index INTEGER,
               content TEXT NOT NULL, hash TEXT UNIQUE, created_at TEXT)""")
    conn.execute(
        f"""CREATE VIRTUAL TABLE IF NOT EXISTS vec USING vec0(
               chunk_id INTEGER PRIMARY KEY, embedding float[{EMBED_DIM}])""")
    return conn


# ---------------------------------------------------------------- 解析
def _extract(path: Path) -> list[tuple[int, str]]:
    """返回 [(页号, 文本)]。支持 pdf/docx/txt/md。"""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import fitz  # pymupdf
        doc = fitz.open(str(path))
        return [(i + 1, page.get_text("text")) for i, page in enumerate(doc)]
    if suffix == ".docx":
        import docx
        doc = docx.Document(str(path))
        return [(1, "\n".join(p.text for p in doc.paragraphs))]
    if suffix in (".txt", ".md"):
        return [(1, path.read_text(encoding="utf-8", errors="replace"))]
    raise ValueError(f"暂不支持的格式：{suffix}（支持 pdf/docx/txt/md）")


def _chunk(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    chunks, start = [], 0
    while start < len(text):
        end = start + _chunk_size
        # 尽量在句号/换行处断开
        if end < len(text):
            cut = max(text.rfind("。", start, end), text.rfind("\n", start, end))
            if cut > start + _chunk_size // 2:
                end = cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start = end - _chunk_overlap if end < len(text) else len(text)
    return chunks


# ---------------------------------------------------------------- 向量服务
def _embed(texts: list[str]) -> list[list[float]]:
    resp = requests.post(f"{_embed_url.rstrip('/')}/embeddings",
                         json={"input": texts, "model": "embedding"}, timeout=120)
    resp.raise_for_status()
    data = resp.json()["data"]
    data.sort(key=lambda x: x["index"])
    return [d["embedding"] for d in data]


def _rerank(query: str, docs: list[str], top_k: int) -> list[tuple[int, float]]:
    """返回 [(原文索引, 分数)]；服务不可用时返回 None 表示跳过精排。"""
    try:
        resp = requests.post(_rerank_url, json={
            "query": query, "documents": docs, "top_n": top_k}, timeout=60)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [(r["index"], r.get("relevance_score", 0.0)) for r in results]
    except Exception:
        return []


# ---------------------------------------------------------------- 对外操作
def ingest(path: str, pattern: str = "*") -> str:
    from ..tools import scope
    target = scope.resolve_path(path)
    files = ([target] if target.is_file()
             else [p for p in sorted(target.glob(pattern or "*"))
                   if p.suffix.lower() in (".pdf", ".docx", ".txt", ".md")])
    if not files:
        return f"未找到可入库文件：{target}"
    conn = _connect()
    total, skipped = 0, 0
    for file in files:
        try:
            pages = _extract(file)
        except Exception as exc:
            return f"解析失败：{file.name}（{exc}）"
        for page_no, text in pages:
            for i, chunk in enumerate(_chunk(text)):
                digest = hashlib.md5(f"{file}:{page_no}:{i}:{chunk[:64]}".encode()).hexdigest()
                exists = conn.execute("SELECT 1 FROM chunks WHERE hash=?", (digest,)).fetchone()
                if exists:
                    skipped += 1
                    continue
                vec = _embed([chunk])[0]
                cur = conn.execute(
                    "INSERT INTO chunks(doc, page, chunk_index, content, hash, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (file.name, page_no, i, chunk, digest,
                     time.strftime("%Y-%m-%d %H:%M:%S")))
                conn.execute("INSERT INTO vec(chunk_id, embedding) VALUES (?, ?)",
                             (cur.lastrowid, _pack(vec)))
                total += 1
    conn.commit()
    conn.close()
    return f"入库完成：{len(files)} 个文件，新增 {total} 个片段" + (f"，跳过重复 {skipped}" if skipped else "")


def _pack(vec: list[float]) -> bytes:
    import struct
    return struct.pack(f"{len(vec)}f", *vec)


def _search_items(query: str, top_k: int) -> list[tuple[str, int, str, float]]:
    """向量召回 + 可选精排，返回 [(doc, page, content, score)]。"""
    conn = _connect()
    try:
        qvec = _embed([query])[0]
        rows = conn.execute(
            """SELECT c.id, c.doc, c.page, c.content, v.distance
                 FROM (SELECT chunk_id, distance FROM vec
                       WHERE embedding MATCH ? AND k = ?) v
                 JOIN chunks c ON c.id = v.chunk_id""",
            (_pack(qvec), _candidates)).fetchall()
        if not rows:
            return []
        docs = [r[3] for r in rows]
        order = _rerank(query, docs, top_k)
        if order:  # 精排可用
            picked = [(rows[i], score) for i, score in order]
        else:     # 退化：按向量距离取前 top_k
            picked = [(rows[i], 1.0 / (1.0 + rows[i][4]))
                      for i in range(min(top_k, len(rows)))]
        return [(r[1], r[2], r[3], s) for r, s in picked]
    finally:
        conn.close()


def search(query: str, top_k: int | None = None) -> str:
    top_k = top_k or _top_k
    picked = _search_items(query, top_k)
    if not picked:
        return "知识库为空或未命中，请先用 kb_ingest 入库文档"
    lines = [f"知识库检索：{query}（{len(picked)} 条）"]
    for doc, page, content, score in picked:
        lines.append(f"[{doc} 第{page}页 score={score:.3f}]\n{content[:400]}")
    return "\n\n".join(lines)


# ---------------------------------------------------------------- 上下文记忆（loop 调用）
def archive(texts: list[str], source: str = "context") -> int:
    """把文本片段写入当前工作区知识库（按内容哈希去重），返回新增条数。

    供 loop 在裁剪历史时归档被丢弃的对话片段；embed 服务不可用时抛异常，
    由调用方决定是否停用记忆功能。
    """
    conn = _connect()
    added = 0
    try:
        for text in texts:
            for j, chunk in enumerate(_chunk(text)):
                digest = hashlib.md5(f"{source}:{j}:{chunk[:64]}".encode()).hexdigest()
                if conn.execute("SELECT 1 FROM chunks WHERE hash=?", (digest,)).fetchone():
                    continue
                vec = _embed([chunk])[0]
                cur = conn.execute(
                    "INSERT INTO chunks(doc, page, chunk_index, content, hash, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (source, 0, j, chunk, digest, time.strftime("%Y-%m-%d %H:%M:%S")))
                conn.execute("INSERT INTO vec(chunk_id, embedding) VALUES (?, ?)",
                             (cur.lastrowid, _pack(vec)))
                added += 1
        conn.commit()
    finally:
        conn.close()
    return added


def recall(query: str, top_k: int = 3, min_score: float = 0.35) -> list[tuple[str, float]]:
    """上下文记忆召回：在归档片段（context*）与浓缩摘要（summary）里找，按阈值过滤。"""
    items = _search_items(query, top_k * 3)
    hits = [(content, score) for doc, _page, content, score in items
            if (doc.startswith("context") or doc == "summary") and score >= min_score]
    return hits[:top_k]


def clear_source(source: str) -> int:
    """删除某个来源（doc 字段）的全部片段及其向量，返回删除条数。"""
    conn = _connect()
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM chunks WHERE doc=?", (source,)).fetchall()]
        for cid in ids:
            conn.execute("DELETE FROM vec WHERE chunk_id=?", (cid,))
        conn.execute("DELETE FROM chunks WHERE doc=?", (source,))
        conn.commit()
        return len(ids)
    finally:
        conn.close()


# ---------------------------------------------------------------- 记忆浓缩
_CONSOLIDATE_PROMPT = """你是记忆整理器。下面是某个任务沉淀下来的历史对话片段（按时间排序，可能有冗余、矛盾或过时内容）。

请把它们蒸馏成一份「任务记忆卡」，用 markdown 输出，分四节：
## 设定与事实
（确定下来的人物/世界观/参数/路径等客观事实）
## 已定决策
（做过哪些选择、为什么；新旧矛盾时以较新的为准，丢弃被推翻的旧结论）
## 当前进展
（做到哪一步了，最近的关键结果）
## 待办与注意
（还没做的事、踩过的坑）

要求：只保留有长期价值的信息，丢弃闲聊和试错过程；直接输出 markdown 正文，不要解释。

历史片段：
"""


def consolidate() -> str:
    """浓缩当前工作区的归档记忆：LLM 蒸馏 → 更新 MEMORY.md + summary 向量块。"""
    from ..llm import LLMClient
    from ..tools import scope

    conn = _connect()
    try:
        rows = [r[0] for r in conn.execute(
            "SELECT content FROM chunks WHERE doc LIKE 'context%' ORDER BY id").fetchall()]
    finally:
        conn.close()
    if not rows:
        return "没有可整理的记忆片段（先聊几轮产生归档内容）"
    # 总量封顶 20000 字，超出时最新优先
    texts, total = [], 0
    for chunk in reversed(rows):
        if total + len(chunk) > 20000:
            break
        texts.append(chunk)
        total += len(chunk)
    texts.reverse()

    if _cfg is None:
        return "rag 未配置，无法整理"
    reply = LLMClient(_cfg).chat(
        [{"role": "user", "content": _CONSOLIDATE_PROMPT + "\n\n".join(texts)}])
    card = (reply.content or "").strip()
    if not card:
        return "模型没有产出记忆卡内容"

    ws = Path(scope.WORKSPACE)
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "MEMORY.md").write_text(card, encoding="utf-8")
    removed = clear_source("summary")          # 旧摘要整体替换，避免多版并存
    archive([card], source="summary")
    return (f"记忆整理完成：{len(rows)} 个片段 → 记忆卡 {len(card)} 字"
            f"（MEMORY.md 已更新，替换旧摘要 {removed} 条）")


def stats() -> str:
    conn = _connect()
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    docs = conn.execute("SELECT doc, COUNT(*) c FROM chunks GROUP BY doc ORDER BY c DESC").fetchall()
    conn.close()
    lines = [f"知识库：{chunks} 个片段 / {len(docs)} 个文档"]
    lines += [f"  {d}：{c} 段" for d, c in docs[:20]]
    return "\n".join(lines)


def register(reg) -> None:
    reg.tool("kb_ingest",
             "把本地文档（pdf/docx/txt/md）解析并写入知识库，path 可为文件或目录。",
             {"type": "object", "properties": {
                 "path": {"type": "string", "description": "文件或目录路径"},
                 "pattern": {"type": "string", "description": "目录模式时的 glob，默认 *"}}},
             timeout=600)(ingest)
    reg.tool("kb_search",
             "在本地知识库中检索相关片段（向量召回 + 精排），返回带来源的 top-k 结果。",
             {"type": "object", "properties": {
                 "query": {"type": "string", "description": "检索问题（自然语言）"},
                 "top_k": {"type": "integer", "description": "返回条数，默认取配置（5）"}},
              "required": ["query"]},
             timeout=120)(search)
    reg.tool("kb_stats", "查看知识库规模与已入库文档列表。",
             {"type": "object", "properties": {}}, timeout=20)(stats)
    reg.tool("memory_consolidate",
             "整理当前任务的长期记忆：把归档的历史片段蒸馏成记忆卡（MEMORY.md）并更新摘要。"
             "任务跑了很多轮、记忆变杂时使用。",
             {"type": "object", "properties": {}}, timeout=600)(lambda: consolidate())
