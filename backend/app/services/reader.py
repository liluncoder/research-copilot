"""S3 · 阅读器数据层（J5 的地基）。

把解析结果加工成"可跳转"的视图：
1. 段落切分 + 稳定 id（`p<节序号>-<段序号>`）—— 联动滚动和双向跳转都靠它定位
2. 从段文本里抽引用标记 —— **数字制** `[11]` 与**作者-年份制** `(Bellec et al., 2020)` 都支持
   （Nature/Neural Computation 用后者，只做数字制会让这些论文的引用数接近 0），建立两套索引：
   · `citations_of[para_id] = [11, 12]`  （正文 → 参考文献）
   · `cited_by[11] = [para_id, ...]`     （参考文献 → 正文，即"反查引用"）
3. 参考文献按 index 归位，标出"被正文引用过几次"

★为什么不直接在前端做正则：双向跳转要求两边索引一致，
  前端各写一套必然漂移；这里算一次，前端只做渲染与滚动。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.citations import build_ref_index, extract_citations


@dataclass
class Paragraph:
    para_id: str
    section_label: str
    section_index: int
    page_start: int
    page_end: int
    index_in_section: int
    text: str
    citations: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "para_id": self.para_id,
            "section": self.section_label,
            "section_index": self.section_index,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "index_in_section": self.index_in_section,
            "text": self.text,
            "citations": self.citations,
        }


def build_reader_view(parsed: dict, doc_id: str) -> dict[str, Any]:
    """parsed（storage 里存的那份 dict）⇒ 阅读器需要的全部结构。"""
    paragraphs: list[Paragraph] = []
    sections_out: list[dict[str, Any]] = []
    ref_index = build_ref_index(parsed.get("references") or [])

    for si, sec in enumerate(parsed.get("sections") or []):
        label = str(sec.get("label", "")).strip()
        p_start = int(sec.get("page_start") or 1)
        p_end = int(sec.get("page_end") or p_start)
        ids: list[str] = []
        for pi, text in enumerate(sec.get("paragraphs") or []):
            text = str(text).strip()
            if not text:
                continue
            para_id = f"p{si}-{pi}"
            cites = extract_citations(text, ref_index)
            paragraphs.append(
                Paragraph(
                    para_id=para_id,
                    section_label=label,
                    section_index=si,
                    page_start=p_start,
                    page_end=p_end,
                    index_in_section=pi,
                    text=text,
                    citations=cites,
                )
            )
            ids.append(para_id)
        sections_out.append(
            {
                "index": si,
                "label": label,
                "level": int(sec.get("level") or 1),
                "page_start": p_start,
                "page_end": p_end,
                "n_paragraphs": len(ids),
                "para_ids": ids,
            }
        )

    # ★空父节（如 "6 Results" 的内容都在 6.1/6.2）没有自己的段落，
    #   点它会跳空 ⇒ 给它补一个"导航目标"：往后找第一个有内容的节，用其首段 id。
    for i, s in enumerate(sections_out):
        if s["para_ids"]:
            s["nav_para_id"] = s["para_ids"][0]
            continue
        nxt = next((x for x in sections_out[i + 1 :] if x["para_ids"]), None)
        s["nav_para_id"] = nxt["para_ids"][0] if nxt else None
        s["is_parent_only"] = True

    # 参考文献 → 正文（反查）
    cited_by: dict[int, list[str]] = {}
    for p in paragraphs:
        for c in p.citations:
            cited_by.setdefault(c, []).append(p.para_id)

    refs_out: list[dict[str, Any]] = []
    for ref in parsed.get("references") or []:
        idx = int(ref.get("index") or 0)
        refs_out.append(
            {
                "index": idx,
                "raw": str(ref.get("raw") or ""),
                "year": ref.get("year"),
                "arxiv_id": ref.get("arxiv_id"),
                "cited_count": len(cited_by.get(idx, [])),
                "cited_in": cited_by.get(idx, []),
            }
        )

    valid_ids = {r["index"] for r in refs_out}
    dangling = sorted({c for c in cited_by if c not in valid_ids})

    return {
        "doc_id": doc_id,
        "source": parsed.get("source", ""),
        "title": parsed.get("title"),
        "authors": parsed.get("authors") or [],
        "abstract": parsed.get("abstract") or "",
        "outline": parsed.get("outline") or [],
        "sections": sections_out,
        "paragraphs": [p.as_dict() for p in paragraphs],
        "references": refs_out,
        "cited_by": {str(k): v for k, v in sorted(cited_by.items())},
        "stats": {
            "n_sections": len(sections_out),
            "n_paragraphs": len(paragraphs),
            "n_references": len(refs_out),
            "n_citation_marks": sum(len(p.citations) for p in paragraphs),
            "n_refs_cited": len([r for r in refs_out if r["cited_count"] > 0]),
            "dangling_citations": dangling,
        },
    }
