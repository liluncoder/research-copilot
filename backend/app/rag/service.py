"""S2 · 检索服务层（索引 + 查询 + 缓存）。

★职责边界：
  · `index_document` —— 解析结果 → 结构化切块 → 向量 → 落索引（幂等，按 doc_id 覆盖）
  · `search`         —— 载入指定文献的索引 → 混合检索 → 返回带出处的命中

★缓存策略：embedder（BGE-M3 加载一次约 10~30s）和 retriever（BM25 构建）都按
  "文献集合 + 块数"做键缓存；索引变化（重新上传/删除）会让键变化，自动重建。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.rag.chunker import chunk_document_dict
from app.rag.embedder import Embedder, build_embedder
from app.rag.retriever import HybridRetriever, RetrievalResult
from app.rag.store import StoredChunk, build_store

_lock = threading.Lock()
_embedder: Embedder | None = None
_retriever_cache: dict[tuple, HybridRetriever] = {}


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        s = get_settings()
        with _lock:
            if _embedder is None:
                _embedder = build_embedder(
                    s.embedding_backend, s.embedding_model, s.embedding_device
                )
    return _embedder


def reset_caches() -> None:
    """测试/重跑用：丢掉 embedder 与 retriever 缓存。"""
    global _embedder
    with _lock:
        _embedder = None
        _retriever_cache.clear()


def _store():
    s = get_settings()
    return build_store(s.chroma_persist_dir)


def index_document(doc_id: str, parsed: dict, *, filename: str | None = None) -> dict[str, Any]:
    """把一篇已解析文献写进检索索引。返回索引统计（供 API/判据核对）。"""
    s = get_settings()
    chunks = chunk_document_dict(
        parsed, doc_id, max_chars=s.rag_chunk_chars, overlap=s.rag_chunk_overlap
    )
    if not chunks:
        return {"doc_id": doc_id, "chunks": 0, "warning": "没有可索引的正文（可能全是参考文献/过短）"}

    emb = get_embedder()
    vectors = emb.encode([c.text for c in chunks])

    store = _store()
    stored = [
        StoredChunk(
            chunk_id=c.chunk_id,
            doc_id=c.doc_id,
            filename=filename or c.filename,
            section_label=c.section_label,
            section_path=" > ".join(c.section_path),
            level=c.level,
            page_start=c.page_start,
            page_end=c.page_end,
            text=c.text,
            index_in_doc=c.index_in_doc,
        )
        for c in chunks
    ]
    store.upsert(doc_id, stored, vectors)
    _retriever_cache.clear()

    return {
        "doc_id": doc_id,
        "chunks": len(chunks),
        "dim": int(vectors.shape[1]) if vectors.size else 0,
        "store_backend": store.backend_name,
        "embedding_backend": getattr(emb, "backend_name", "?"),
        "embedding_fallback_reason": getattr(emb, "fallback_reason", None),
    }


def delete_document_index(doc_id: str) -> bool:
    ok = _store().delete(doc_id)
    _retriever_cache.clear()
    return ok


def _load_retriever(doc_ids: list[str] | None) -> HybridRetriever:
    s = get_settings()
    store = _store()
    chunks, vectors = store.load(doc_ids)
    key = (tuple(sorted({c.doc_id for c in chunks})), len(chunks), getattr(get_embedder(), "backend_name", "?"))
    cached = _retriever_cache.get(key)
    if cached is not None:
        return cached
    r = HybridRetriever(
        chunks,
        vectors,
        get_embedder(),
        dense_weight=s.rag_dense_weight,
        sparse_weight=s.rag_sparse_weight,
    )
    _retriever_cache[key] = r
    return r


def search(
    query: str,
    *,
    doc_ids: list[str] | None = None,
    top_k: int | None = None,
) -> RetrievalResult:
    s = get_settings()
    retriever = _load_retriever(doc_ids)
    res = retriever.search(query, top_k=top_k or s.rag_top_k)
    res.backend = _store().backend_name
    res.embedding_backend = getattr(get_embedder(), "backend_name", "?")
    return res


def index_status() -> dict[str, Any]:
    store = _store()
    emb = get_embedder()
    return {
        "store_backend": store.backend_name,
        "store_fallback_reason": getattr(store, "fallback_reason", None),
        "embedding_backend": getattr(emb, "backend_name", "?"),
        "embedding_fallback_reason": getattr(emb, "fallback_reason", None),
        "embedding_dim": getattr(emb, "dim", None),
        "chunks_indexed": store.count() if hasattr(store, "count") else None,
        "docs_indexed": store.doc_ids() if hasattr(store, "doc_ids") else None,
        "persist_dir": str(Path(get_settings().chroma_persist_dir)),
    }
