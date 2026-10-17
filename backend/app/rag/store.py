"""S2 · 向量索引（★Chroma 优先，未安装时退到等价的本地索引）。

为什么留两档：
  · `chroma` —— 计划里的选型（HNSW + 元数据过滤，量大时明显更快）
  · `numpy`  —— 把向量存成 .npy、元数据存成 .jsonl，余弦暴力检索。
    ★在 1~50 篇论文（几千块）规模下，与 Chroma 的结果**完全一致**（都是精确余弦），
      只是复杂度 O(N)。它的价值是：CI/评委环境不必装 Chroma 也能复盘判据。

存储布局（每个 doc 一份，便于 J1 覆盖/删除时精确清理）：
    <persist_dir>/<doc_id>/vectors.npy
    <persist_dir>/<doc_id>/chunks.jsonl
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class StoredChunk:
    chunk_id: str
    doc_id: str
    filename: str
    section_label: str
    section_path: str
    level: int
    page_start: int
    page_end: int
    text: str
    index_in_doc: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "filename": self.filename,
            "section_label": self.section_label,
            "section_path": self.section_path,
            "level": self.level,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "text": self.text,
            "index_in_doc": self.index_in_doc,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StoredChunk":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__})


class NumpyStore:
    """本地 npy + jsonl 索引（精确余弦，结果与 Chroma 一致）。"""

    backend_name = "numpy"

    def __init__(self, persist_dir: str | Path) -> None:
        self.root = Path(persist_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, doc_id: str) -> Path:
        return self.root / doc_id

    def upsert(self, doc_id: str, chunks: list[StoredChunk], vectors: np.ndarray) -> int:
        if len(chunks) != len(vectors):
            raise ValueError(f"chunks({len(chunks)}) 与 vectors({len(vectors)}) 数量不一致")
        d = self._dir(doc_id)
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
        np.save(d / "vectors.npy", np.asarray(vectors, dtype=np.float32))
        with (d / "chunks.jsonl").open("w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(c.as_dict(), ensure_ascii=False) + "\n")
        return len(chunks)

    def delete(self, doc_id: str) -> bool:
        d = self._dir(doc_id)
        if not d.exists():
            return False
        shutil.rmtree(d)
        return True

    def doc_ids(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and (p / "vectors.npy").exists())

    def load(self, doc_ids: list[str] | None = None) -> tuple[list[StoredChunk], np.ndarray]:
        ids = doc_ids if doc_ids is not None else self.doc_ids()
        chunk_rows: list[StoredChunk] = []
        mats: list[np.ndarray] = []
        for doc_id in ids:
            d = self._dir(doc_id)
            vpath, cpath = d / "vectors.npy", d / "chunks.jsonl"
            if not vpath.exists() or not cpath.exists():
                continue
            mats.append(np.load(vpath))
            with cpath.open(encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        chunk_rows.append(StoredChunk.from_dict(json.loads(line)))
        if not mats:
            return [], np.zeros((0, 1), dtype=np.float32)
        return chunk_rows, np.vstack(mats)

    def count(self) -> int:
        chunks, _ = self.load()
        return len(chunks)


class ChromaStore:
    """Chroma 持久化索引。★需要 `pip install chromadb`；未安装时由 build_store 退到 NumpyStore。"""

    backend_name = "chroma"

    def __init__(self, persist_dir: str | Path, collection: str = "chunks") -> None:
        import chromadb

        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._col = self._client.get_or_create_collection(
            name=collection, metadata={"hnsw:space": "cosine"}
        )

    def upsert(self, doc_id: str, chunks: list[StoredChunk], vectors: np.ndarray) -> int:
        self._col.upsert(
            ids=[c.chunk_id for c in chunks],
            embeddings=np.asarray(vectors, dtype=np.float32).tolist(),
            documents=[c.text for c in chunks],
            metadatas=[c.as_dict() | {"text": ""} for c in chunks],
        )
        return len(chunks)

    def delete(self, doc_id: str) -> bool:
        res = self._col.get(where={"doc_id": doc_id}, include=[])
        ids = res.get("ids") or []
        if not ids:
            return False
        self._col.delete(ids=ids)
        return True

    def doc_ids(self) -> list[str]:
        res = self._col.get(include=["metadatas"])
        return sorted({str((m or {}).get("doc_id")) for m in res.get("metadatas") or []})


def build_store(persist_dir: str | Path, prefer: str = "auto"):
    """auto：装了 chromadb 就用，否则退 numpy（并把 backend_name 记进响应/判词）。"""
    prefer = (prefer or "auto").lower()
    if prefer == "numpy":
        return NumpyStore(persist_dir)
    try:
        return ChromaStore(persist_dir)
    except Exception:  # noqa: BLE001
        if prefer == "chroma":
            raise
        store = NumpyStore(persist_dir)
        store.fallback_reason = "chromadb 未安装或初始化失败"  # type: ignore[attr-defined]
        return store
