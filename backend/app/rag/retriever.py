"""S2 · 混合检索（Dense + Sparse → RRF 融合）。

★RRF（Reciprocal Rank Fusion）为什么优于分数加权：
  Dense 的余弦相似度（0~1）和 BM25 的分数（0~30+）量纲不同，直接加权要调参且不稳；
  RRF 只看**名次**：score = Σ 1/(k + rank)，k=60。零调参、跨查询稳定，
  这也是工业界混合检索的默认做法（Cormack et al. 2009）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.rag.bm25 import BM25
from app.rag.embedder import Embedder
from app.rag.store import StoredChunk

RRF_K = 60


@dataclass
class Hit:
    chunk: StoredChunk
    score: float
    dense_rank: int | None = None
    sparse_rank: int | None = None
    dense_score: float | None = None
    sparse_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        page = (
            f"p{self.chunk.page_start}"
            if self.chunk.page_start == self.chunk.page_end
            else f"p{self.chunk.page_start}-{self.chunk.page_end}"
        )
        return {
            "chunk_id": self.chunk.chunk_id,
            "doc_id": self.chunk.doc_id,
            "filename": self.chunk.filename,
            "section": self.chunk.section_label,
            "page": page,
            "score": round(self.score, 5),
            "dense_rank": self.dense_rank,
            "sparse_rank": self.sparse_rank,
            "text": self.chunk.text,
            "citation": f"[来源: {self.chunk.filename}·{page}·{self.chunk.section_label}]",
        }


@dataclass
class RetrievalResult:
    query: str
    hits: list[Hit] = field(default_factory=list)
    dense_n: int = 0
    sparse_n: int = 0
    backend: str = ""
    embedding_backend: str = ""

    @property
    def confident(self) -> bool:
        """★是否够胆回答：没有任何命中 ⇒ 不回答（J4/J8 的反幻觉前提）。"""
        return bool(self.hits)


class HybridRetriever:
    def __init__(
        self,
        chunks: list[StoredChunk],
        vectors: np.ndarray,
        embedder: Embedder,
        *,
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0,
    ) -> None:
        self.chunks = chunks
        self.vectors = vectors
        self.embedder = embedder
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight
        self._bm25 = BM25().fit([c.text for c in chunks]) if chunks else BM25()

    def search(self, query: str, top_k: int = 5, candidate_k: int = 20) -> RetrievalResult:
        res = RetrievalResult(
            query=query,
            backend="numpy",
            embedding_backend=getattr(self.embedder, "backend_name", "?"),
        )
        if not self.chunks or self.vectors.size == 0:
            return res

        # --- Dense ---
        qv = self.embedder.encode([query])[0]
        sims = self.vectors @ qv
        order = np.argsort(-sims)[:candidate_k]
        dense_rank = {int(i): r for r, i in enumerate(order)}
        dense_score = {int(i): float(sims[i]) for i in order}

        # --- Sparse ---
        sparse_hits = self._bm25.search(query, top_k=candidate_k)
        sparse_rank = {h.index: r for r, h in enumerate(sparse_hits)}
        sparse_score = {h.index: h.score for h in sparse_hits}

        res.dense_n = len(dense_rank)
        res.sparse_n = len(sparse_rank)

        # --- RRF 融合 ---
        fused: dict[int, float] = {}
        for i, r in dense_rank.items():
            fused[i] = fused.get(i, 0.0) + self.dense_weight / (RRF_K + r + 1)
        for i, r in sparse_rank.items():
            fused[i] = fused.get(i, 0.0) + self.sparse_weight / (RRF_K + r + 1)

        top = sorted(fused.items(), key=lambda kv: -kv[1])[:top_k]
        res.hits = [
            Hit(
                chunk=self.chunks[i],
                score=score,
                dense_rank=dense_rank.get(i),
                sparse_rank=sparse_rank.get(i),
                dense_score=dense_score.get(i),
                sparse_score=sparse_score.get(i),
            )
            for i, score in top
        ]
        return res
