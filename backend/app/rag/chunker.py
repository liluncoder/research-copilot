"""S2 · 结构化切块（M2 的创新点，技术文档要重点写）。

★为什么不用定长切块：
定长切块会把"5.3 Optimizer"里的一句话劈成两半，检索命中后无法说清"这段属于哪一节哪一页"，
而 J4 要求**出处锚点指向正确页段**。所以这里以**标题树**为边界：
每一块都带 `section_path / page_start / page_end`，检索结果天然可溯源。

规则：
1. 以 `ParsedDocument.sections`（标题树拍平后的章节）为容器
2. 章节过长才在**段落边界**处切开，绝不在句子中间切
3. 相邻块保留少量重叠，避免答案正好落在切口
4. 跳过 References（噪声，且 J8 另有引用召回通道）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.pdf_parser import ParsedDocument


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    filename: str
    section_label: str
    section_path: list[str]
    level: int
    page_start: int
    page_end: int
    text: str
    index_in_doc: int = 0

    @property
    def n_chars(self) -> int:
        return len(self.text)

    def as_metadata(self) -> dict[str, Any]:
        """Chroma 的 metadata 只接受标量，所以列表要压成字符串。"""
        return {
            "doc_id": self.doc_id,
            "filename": self.filename,
            "section_label": self.section_label,
            "section_path": " > ".join(self.section_path),
            "level": self.level,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "index_in_doc": self.index_in_doc,
        }

    def citation(self) -> str:
        """统一出处格式：文件名·页码·章节。"""
        page = f"p{self.page_start}" if self.page_start == self.page_end else f"p{self.page_start}-{self.page_end}"
        return f"[来源: {self.filename}·{page}·{self.section_label}]"


_SENT_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")


def _split_by_paragraph(text: str, max_chars: int) -> list[str]:
    """先按空行/句末切段，再贪心打包到 max_chars 以内。"""
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paras:
        paras = [text.strip()]

    units: list[str] = []
    for p in paras:
        if len(p) <= max_chars:
            units.append(p)
            continue
        # 段落本身超长 ⇒ 退一级，按句子打包
        buf = ""
        for sent in _SENT_SPLIT.split(p):
            if not sent:
                continue
            if len(buf) + len(sent) + 1 > max_chars and buf:
                units.append(buf.strip())
                buf = sent
            else:
                buf = f"{buf} {sent}".strip()
        if buf:
            units.append(buf.strip())

    packed: list[str] = []
    cur = ""
    for u in units:
        if len(cur) + len(u) + 2 > max_chars and cur:
            packed.append(cur.strip())
            cur = u
        else:
            cur = f"{cur}\n\n{u}".strip()
    if cur:
        packed.append(cur.strip())
    return packed


def _tail(text: str, n: int) -> str:
    return text[-n:] if len(text) > n else text


def chunk_document(
    doc: ParsedDocument,
    doc_id: str,
    *,
    max_chars: int = 900,
    overlap: int = 120,
    include_abstract: bool = True,
    skip_references: bool = True,
) -> list[Chunk]:
    """把一篇解析结果切成带出处元数据的块。"""
    filename = doc.source.rsplit("/", 1)[-1]
    chunks: list[Chunk] = []
    idx = 0

    def add(label: str, path: list[str], level: int, p_start: int, p_end: int, text: str) -> None:
        nonlocal idx
        text = text.strip()
        if len(text) < 40:  # 太短的块没有检索价值，纯粹添噪声
            return
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}-c{idx:04d}",
                doc_id=doc_id,
                filename=filename,
                section_label=label,
                section_path=path,
                level=level,
                page_start=p_start,
                page_end=p_end,
                text=text,
                index_in_doc=idx,
            )
        )
        idx += 1

    if include_abstract and doc.abstract and doc.abstract.strip():
        add("Abstract", ["Abstract"], 1, 1, 1, doc.abstract)

    for sec in doc.sections:
        label = str(sec.get("label", "")).strip()
        if skip_references and _norm_label(label).startswith("references"):
            continue
        paragraphs = [str(p).strip() for p in sec.get("paragraphs", []) if str(p).strip()]
        if not paragraphs:
            continue
        page_start = int(sec.get("page_start") or 1)
        page_end = int(sec.get("page_end") or page_start)

        body = "\n\n".join(paragraphs)
        parts = _split_by_paragraph(body, max_chars)

        prev_tail = ""
        for i, part in enumerate(parts):
            text = f"{prev_tail}\n\n{part}".strip() if prev_tail else part
            add(label, [label], int(sec.get("level") or 1), page_start, page_end, text)
            prev_tail = _tail(part, overlap) if overlap > 0 and i < len(parts) - 1 else ""

    return chunks


def _norm_label(label: str) -> str:
    return re.sub(r"[^a-z]", "", label.lower())


def chunk_document_dict(doc: dict, doc_id: str, **kw) -> list[Chunk]:
    """从 storage 里存下的 dict 版本切块（避免每次重新解析 PDF）。"""
    from app.services.pdf_parser import Reference  # noqa: F401  仅类型提示用

    class _Shim:
        def __init__(self, d: dict) -> None:
            self.source = d.get("source", "")
            self.abstract = d.get("abstract", "")
            self.sections = d.get("sections", [])
            self.references = d.get("references", [])

    return chunk_document(_Shim(doc), doc_id, **kw)  # type: ignore[arg-type]
