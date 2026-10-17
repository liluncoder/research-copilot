"""S2 · Embedding（★可插拔，保证"没有大模型也能跑通判据"）。

三档实现，按 `EMBEDDING_BACKEND` 选择：
  · `bge-m3`  —— BAAI/bge-m3（sentence-transformers，1024 维，多语言）。
                 ★这是产品形态：中英跨语言检索（中文问题 → 英文论文）靠它。
  · `hash`    —— 纯 Python 的字符 n-gram 哈希向量，**零依赖、确定性**。
                 用途：模型没下载完 / 离线环境 / CI 里跑判据时，管线照样能通，
                 判据不会因为"2.2GB 模型下不来"而假失败。
  · `auto`    —— 先试 bge-m3，失败自动退到 hash，并把退档原因记在 `backend_name` 里。

★为什么要有 hash 这档：本机沙箱下载 ~125KB/s，BGE-M3 要几小时。
  但"检索管线是否正确"和"向量质量好不好"是两件事，必须能分开验证。
  退档时接口返回 `embedding_backend: "hash"`，判词里如实记录 —— 不允许悄悄降级。
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path
from typing import Protocol

import numpy as np

_TOKEN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


class Embedder(Protocol):
    dim: int
    backend_name: str

    def encode(self, texts: list[str]) -> np.ndarray: ...


def _normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


class HashEmbedder:
    """字符 n-gram 哈希向量（离线兜底，确定性）。

    原理：把 token 与相邻 2-gram 用 blake2b 哈希到固定维度后累加，再做 L2 归一化。
    能力边界老实说：对"字面重合"敏感，对同义改写无能为力 —— 所以它只用于验证管线，
    真实检索质量必须用 BGE-M3 复跑（判词会写明用的是哪档）。
    """

    backend_name = "hash"

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        tokens = _TOKEN.findall(text.lower())
        grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        for g in grams:
            h = hashlib.blake2b(g.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            sign = 1.0 if h[4] & 1 else -1.0
            v[idx] += sign
        return v

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _normalize(np.vstack([self._vec(t) for t in texts]))


class BgeM3Embedder:
    """BAAI/bge-m3，CPU 推理。模型路径可由 env `BGE_M3_PATH` 指定（离线目录）。"""

    backend_name = "bge-m3"
    dim = 1024

    def __init__(self, model_name_or_path: str = "BAAI/bge-m3", device: str = "cpu") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name_or_path, device=device)
        self.dim = int(self._model.get_sentence_embedding_dimension() or 1024)

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vecs = self._model.encode(
            texts,
            batch_size=8,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return np.asarray(vecs, dtype=np.float32)


def build_embedder(backend: str = "auto", model: str = "BAAI/bge-m3", device: str = "cpu") -> Embedder:
    """按配置造 embedder；auto 模式下失败会退到 hash，并把原因留在返回值上。

    ★模型查找顺序：环境变量 `BGE_M3_PATH` 指向的本地目录 > HF 仓库名（BAAI/bge-m3）。
      本地目录的用途：离线部署（Docker 里拷贝模型）与"下载器先下好再指过来"。
    """
    backend = (backend or "auto").lower()
    local = os.environ.get("BGE_M3_PATH")
    if local and Path(local).exists() and any(Path(local).glob("*.safetensors")):
        model = local
    if backend == "hash":
        return HashEmbedder()

    errors: list[str] = []
    try:
        return BgeM3Embedder(model, device=device)
    except Exception as e:  # noqa: BLE001
        errors.append(f"{type(e).__name__}: {e}")
        if backend == "bge-m3":
            raise RuntimeError(
                "BGE-M3 加载失败（EMBEDDING_BACKEND=bge-m3 时不允许静默降级）：" + "; ".join(errors)
            ) from e

    emb = HashEmbedder()
    # 把降档原因挂在实例上，调用方可读出来写进响应/判词
    emb.fallback_reason = "; ".join(errors)  # type: ignore[attr-defined]
    return emb


def cosine_topk(query: np.ndarray, mat: np.ndarray, k: int) -> list[tuple[int, float]]:
    if mat.size == 0:
        return []
    sims = mat @ query.reshape(-1)
    order = np.argsort(-sims)[:k]
    return [(int(i), float(math.fsum([sims[i]]))) for i in order]
