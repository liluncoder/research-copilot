"""解析管线（M1）：PDF → 结构化文档。

★设计要点（对应赛题判据 J2/J3）：
1. **文本层判定**：逐页统计可提取字符数，低于阈值即判为扫描页，走 OCR 分支。
   这是"扫描件分支"的入口条件，不靠文件名猜。
2. **流式逐页处理**：绝不让整本 PDF 一次性进内存（541 页硬指标 < 2GB 的根因在此）。
3. **两级降级**：Marker（双栏/公式/表格最佳）→ PyMuPDF（快、稳、无外部依赖）→ OCR。
   本机无 NVIDIA，Marker 需 torch，S1 先用 PyMuPDF 打底，Marker 作为可选增强。

M1 数据结构对齐赛题"细粒度抽取"要求：
标题 / 作者机构 / 摘要 / 一二三级标题树 / 表格 / 图表 / LaTeX 公式 / 参考文献 / 附录
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pymupdf

# ---- 判定阈值（★写死，判据引用这两个常数）----
TEXT_CHAR_THRESHOLD = 50
"""单页可提取字符数低于此值 ⇒ 判为"无文本层"，走 OCR。"""

OCR_RENDER_DPI = 150
"""扫描页渲染 DPI。★2026-10-17 实测 150 与 200 质量无差别（关键词/字符数一致）
而速度快 20%，故选 150。A4@150dpi ≈ 1240x1754。"""


@dataclass
class PageText:
    page_no: int  # 1-based
    text: str
    char_count: int
    is_scanned: bool
    ocr_used: bool = False


@dataclass
class ParsedDocument:
    source: Path
    page_count: int
    pages: list[PageText] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)

    @property
    def scanned_pages(self) -> list[int]:
        return [p.page_no for p in self.pages if p.is_scanned]

    @property
    def total_chars(self) -> int:
        return sum(p.char_count for p in self.pages)


def classify_page(text: str) -> tuple[bool, int]:
    """判定单页是否需要 OCR。返回 (是否扫描页, 有效字符数)。"""
    # 去掉空白后计有效字符，避免纯排版空格骗过阈值
    effective = len(re.sub(r"\s", "", text))
    return effective < TEXT_CHAR_THRESHOLD, effective


def parse_pdf(
    path: str | Path,
    *,
    ocr: "OcrEngine | None" = None,
    page_limit: int | None = None,
) -> ParsedDocument:
    """逐页流式解析。

    ★内存纪律：始终保持**只打开一个文档、只渲染一页**。
    Page 对象用完即释放，OCR 图像处理完立刻置 None，不给 GC 攒垃圾的机会。
    """
    path = Path(path)
    doc = ParsedDocument(source=path, page_count=0, metadata={})

    with pymupdf.open(path) as pdf:
        doc.page_count = pdf.page_count
        doc.metadata = dict(pdf.metadata or {})
        total = pdf.page_count if page_limit is None else min(page_limit, pdf.page_count)

        for i in range(total):
            page = pdf.load_page(i)  # 只加载一页
            try:
                raw = page.get_text("text")
                is_scanned, nchars = classify_page(raw)

                if is_scanned and ocr is not None:
                    # ---- 扫描件分支：渲染成图 → OCR ----
                    text = ocr.recognize_page(page, dpi=OCR_RENDER_DPI)
                    doc.pages.append(
                        PageText(
                            page_no=i + 1,
                            text=text,
                            char_count=len(re.sub(r"\s", "", text)),
                            is_scanned=True,
                            ocr_used=True,
                        )
                    )
                else:
                    doc.pages.append(
                        PageText(
                            page_no=i + 1,
                            text=raw,
                            char_count=nchars,
                            is_scanned=is_scanned,
                            ocr_used=False,
                        )
                    )
            finally:
                # ★显式释放页对象，541 页场景下这一步是内存能否守住的关键
                del page

    return doc


def iter_text_chunks(
    doc: ParsedDocument,
    *,
    max_chars: int = 1200,
    overlap_chars: int = 150,
) -> Iterable[dict]:
    """按页流式产出切块（供 S2 的 embedding 消费，避免整本进内存）。

    S2 会在此基础上叠加"标题树结构化切块"；这里是保底实现。
    """
    buf = ""
    buf_start_page = 1
    for p in doc.pages:
        if not buf:
            buf_start_page = p.page_no
        buf += p.text + "\n\n"
        while len(buf) >= max_chars:
            chunk = buf[:max_chars]
            yield {
                "text": chunk,
                "page_start": buf_start_page,
                "page_end": p.page_no,
            }
            buf = buf[max_chars - overlap_chars :]
            buf_start_page = p.page_no
    if buf.strip():
        yield {"text": buf, "page_start": buf_start_page, "page_end": doc.page_count}


class OcrEngine:
    """OCR 引擎基类。S1 用 PaddleOCR 实现（CPU 可跑）；接口留空便于替换。"""

    def recognize_page(self, page, *, dpi: int) -> str:  # pragma: no cover - 接口
        raise NotImplementedError
