"""S2 · BM25 稀疏检索（零依赖实现）。

★为什么自己写：`rank_bm25` 只有 60 行，但我们需要的分词规则（英文词 + 中文二元组）
  自己控制更省事，也避免多一个依赖影响 Docker 构建。

★为什么必须有稀疏通道：Dense 向量擅长语义，但对**专有名词/数字**（P100、β2、28.4、BLEU）
  不敏感；J4 的三连问恰好都是"精确事实"。双通道 + RRF 融合是这里的标准解法。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_WORD = re.compile(r"[a-z0-9]+(?:[.\-_][a-z0-9]+)*")
_CJK = re.compile(r"[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """英文按词（保留 5.3 / β1 这类带标点的形态），中文按二元组。

    ★连字符要**同时保留整体与拆开两种形态**：
      原文写 `three-factor`，用户问 `three factor` —— 不做变体就匹配不上。
      实测：e-prop 的三因子规则就因为这一条漏召回（"three-factor" 出现 3~5 次却检索不到）。
    """
    low = text.lower()
    out: list[str] = []
    for tok in _WORD.findall(low):
        out.append(tok)
        if "-" in tok:
            out.extend(p for p in tok.split("-") if p)
    for run in _CJK.findall(low):
        if len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i : i + 2] for i in range(len(run) - 1))
    return out


@dataclass
class BM25Hit:
    index: int
    score: float


class BM25:
    """Okapi BM25。索引就是一份 `list[Counter]`，够用且可落盘。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._docs: list[Counter[str]] = []
        self._len: list[int] = []
        self._df: Counter[str] = Counter()
        self._avg_len = 0.0

    def fit(self, texts: list[str]) -> "BM25":
        self._docs = [Counter(tokenize(t)) for t in texts]
        self._len = [sum(c.values()) for c in self._docs]
        self._df = Counter()
        for c in self._docs:
            self._df.update(c.keys())
        self._avg_len = (sum(self._len) / len(self._len)) if self._len else 0.0
        return self

    def search(self, query: str, top_k: int = 10) -> list[BM25Hit]:
        n = len(self._docs)
        if n == 0:
            return []
        q = Counter(tokenize(query))
        if not q:
            return []
        scores: list[float] = []
        for i, c in enumerate(self._docs):
            dl = self._len[i] or 1
            s = 0.0
            for term, qf in q.items():
                f = c.get(term, 0)
                if not f:
                    continue
                df = self._df.get(term, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                denom = f + self.k1 * (1 - self.b + self.b * dl / (self._avg_len or 1))
                s += qf * idf * (f * (self.k1 + 1) / denom)
            if s > 0:
                scores.append(s)
            else:
                scores.append(0.0)
        order = sorted(range(n), key=lambda i: -scores[i])[:top_k]
        return [BM25Hit(i, round(scores[i], 4)) for i in order if scores[i] > 0]
