"""S3/S5 · 引用定位（数字制 + 作者-年份制）。

★为什么必须两种都支持（实测踩到）：
  · arXiv / IEEE 用数字制：`[11]`、`[11, 12]`、`[11–13]`
  · Nature / Neural Computation / Frontiers 用**作者-年份制**：`(Bellec et al., 2020)`
  只做数字制时，李论那 8 篇 SNN 论文里 3 篇的引用标记数几乎是 0
  （01:3 处、02:1 处、04:0 处）⇒ S5 引用图谱会几乎没有边。
  所以这里把两种都抽出来，统一成"参考文献编号"。

★作者-年份的匹配是**启发式**，但失败方向安全：
  匹配不上就当作"未识别"，不会乱连边（S5 的图宁可少边，不可错边）。
"""

from __future__ import annotations

import re
from typing import Any

# ---------- 数字制 ----------
NUM_RE = re.compile(r"\[(\d{1,3}(?:\s*[,–-]\s*\d{1,3})*)\]")

# ---------- 作者-年份制 ----------
# 抓括号里含四位数年份的片段：(Bellec et al., 2020) / (Zenke & Ganguli, 2018; Bellec, 2019)
PAREN_RE = re.compile(r"\(([^()]{2,140}?(?:19|20)\d{2}[a-z]?[^()]{0,60}?)\)")
# 括号内每个条目：姓氏 + 可选 et al./&/and + 年份
AY_ITEM = re.compile(
    r"([A-Z][A-Za-z\-'’]{2,})\s*(?:et\s+al\.?|and|&|,)?[^;)]{0,40}?((?:19|20)\d{2})[a-z]?"
)

# 不会出现在作者姓氏里的词（避免把 "(Table 3, 2019)" 之类当引用）
STOPWORDS = {
    "table", "figure", "fig", "eq", "equation", "section", "chapter", "appendix",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "springer", "ieee", "acm",
}


def expand_numeric(token: str) -> list[int]:
    """`"11, 12"` / `"11–13"` ⇒ [11,12] / [11,12,13]。"""
    out: list[int] = []
    for part in re.split(r"\s*,\s*", token):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d{1,3})\s*[–-]\s*(\d{1,3})", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 0 < b - a <= 30:
                out.extend(range(a, b + 1))
            else:
                out.extend([a, b])
        elif part.isdigit():
            out.append(int(part))
    return sorted({x for x in out if 1 <= x <= 999})


def surname_of(ref_raw: str) -> str:
    """从参考文献原文里猜第一作者姓氏。

    覆盖两种常见格式：
      "Bellec, P., Scherr, F., ..."        → Bellec（逗号前就是姓）
      "Guillaume Bellec, Franz Scherr, ..." → Bellec（多词取最后一个词）
    """
    head = ref_raw.split(".")[0]
    first = head.split(",")[0].strip()
    if not first:
        return ""
    words = [w for w in re.split(r"\s+", first) if w and w[0].isupper()]
    if not words:
        return ""
    return words[-1].strip(" .,;:")


def build_ref_index(references: list[dict[str, Any]]) -> dict[tuple[str, str], list[int]]:
    """(姓氏小写, 年份) → [参考文献编号]。"""
    idx: dict[tuple[str, str], list[int]] = {}
    for ref in references:
        raw = str(ref.get("raw") or "")
        surname = surname_of(raw)
        year = ref.get("year")
        if not year:
            m = re.search(r"(19|20)\d{2}", raw)
            year = int(m.group(0)) if m else None
        if surname and year:
            idx.setdefault((surname.lower(), str(year)), []).append(int(ref.get("index") or 0))
    return idx


def find_author_year(text: str, ref_index: dict[tuple[str, str], list[int]]) -> list[int]:
    """在文本里找作者-年份引用，返回命中的参考文献编号（已去重）。"""
    hits: list[int] = []
    for paren in PAREN_RE.finditer(text):
        inner = paren.group(1)
        for m in AY_ITEM.finditer(inner):
            surname = m.group(1)
            year = m.group(2)
            if surname.lower() in STOPWORDS:
                continue
            nums = ref_index.get((surname.lower(), year))
            if nums:
                hits.extend(nums)
    return sorted(set(hits))


def extract_citations(text: str, ref_index: dict[tuple[str, str], list[int]] | None = None) -> list[int]:
    """统一入口：数字制 + 作者-年份制 ⇒ 参考文献编号列表。"""
    cites: list[int] = []
    for m in NUM_RE.finditer(text):
        cites.extend(expand_numeric(m.group(1)))
    if ref_index:
        cites.extend(find_author_year(text, ref_index))
    return sorted(set(cites))
