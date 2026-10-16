"""S1 · PDF 结构化解析（判据 J2 前半：三级标题树 + 公式保留 + 参考文献）。

为什么不用"直接抽纯文本"：PDF 里没有"标题/段落/公式"这些概念，只有
"在某坐标画这几个字、用这个字号"。所以必须靠排版线索反推结构。

本文件对 1706.03762v1.pdf 实测出的排版规律（见 report/J2_判词.md 的勘探记录）：
  正文        10.0pt  NimbusRomNo9L-Regu   （9.9/10.1 是同一字号的浮点噪声）
  一级标题    12.0pt  NimbusRomNo9L-Medi   （Abstract / 1 / 2 / 3 / 7 / References）
  二三级标题  10.0pt  NimbusRomNo9L-Medi   （3.1 / 3.2 / 3.2.1 …）
  ★坑：编号与标题被 pdftotext 拆成两行（"3.1" 一行、"Encoder and Decoder Stacks" 一行），
     必须按 y 坐标合并回一行，否则标题树只剩下孤零零的编号。

设计取舍：
  - 先做"排版启发式"，不依赖 Marker/大模型 —— 零成本、可复跑、结果确定，便于评委复现。
  - 公式不做 LaTeX 还原（成本高、收益低），只做"识别 + 原文保留"，
    对应 `路线/02` 的失败去向："降级为保留 LaTeX 原文 + KaTeX 渲染"。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import pymupdf

# ---------- 排版启发式阈值（集中放这里，调参只改这一处）----------
BODY_SIZE = 10.0  # 正文基准字号
H1_MIN_SIZE = 11.5  # ≥ 此字号视为一级标题
HEADING_MAX_CHARS = 90  # 标题不会太长，超了当正文（防误判）
Y_MERGE_TOL = 2.5  # 同一视觉行里，两个片段 y 中心差 < 此值就合并

BOLD_FLAG = 1 << 4  # PyMuPDF span.flags 第 5 位 = 粗体
MATH_FONT_PREFIXES = ("CM", "MS")  # Computer Modern / Math Symbol 系列 = 公式字体
# ★踩坑：作者名后的角标 ∗ † 也是 CMSY 字体，会被误判成公式（首次运行"公式行 97"里
#   混进了作者行）。所以纯角标符号不算公式。
FOOTNOTE_MARK_RE = re.compile(r"^[∗†‡*]+$")

# 标题编号："3" / "3.1" / "3.2.1"
NUM_ONLY_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?$")
NUM_TITLE_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
# 参考文献条目："[1] Vaswani et al. ..."
REF_ITEM_RE = re.compile(r"^\[(\d{1,3})\]\s*(.*)$")
# 光秃秃的页码行（页眉/页脚），如 "12"；参考文献续行里绝不会出现
PAGE_NUM_RE = re.compile(r"^\d{1,3}$")


# ============================ 数据结构 ============================


@dataclass
class Line:
    """合并后的一"视觉行"（编号 + 标题已合回同一行）。"""

    page: int  # 1-based
    y: float
    x0: float
    x1: float
    size: float  # 该行最大字号
    font: str  # 最大字号对应的字体名
    text: str
    is_bold: bool
    has_math: bool
    math_chars: int  # 该行中数学字体字符数，用来区分"真公式"和"角标蹭进来的"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Heading:
    level: int  # 1 / 2 / 3
    number: str | None  # "3.2.1"；无编号（Abstract/References）为 None
    title: str
    page: int
    line_no: int
    path: list[str] = field(default_factory=list)  # 祖先标题链，供切块用元数据

    @property
    def label(self) -> str:
        return f"{self.number} {self.title}" if self.number else self.title


@dataclass
class Reference:
    index: int
    raw: str
    year: int | None = None
    arxiv_id: str | None = None


@dataclass
class ParsedDocument:
    source: str
    page_count: int
    title: str | None
    authors: list[str]
    abstract: str
    outline: list[Heading]
    sections: list[dict[str, Any]]
    references: list[Reference]
    math_lines: list[dict[str, Any]]
    warnings: list[str]
    stats: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "page_count": self.page_count,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "outline": [asdict(h) for h in self.outline],
            "sections": self.sections,
            "references": [asdict(r) for r in self.references],
            "math_lines": self.math_lines,
            "warnings": self.warnings,
            "stats": self.stats,
        }

    def outline_tree(self) -> list[dict[str, Any]]:
        """把扁平 outline 还原成嵌套树（前端标题树导航直接用这个）。"""
        return build_outline_tree([asdict(h) for h in self.outline])


def build_outline_tree(flat: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """扁平标题列表 ⇒ 嵌套树。用栈维护祖先链，遇到同级或更高级就弹栈。"""
    root: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []
    for h in flat:
        label = f"{h['number']} {h['title']}" if h.get("number") else h["title"]
        node = {"label": label, "level": h["level"], "page": h["page"], "children": []}
        while stack and stack[-1][0] >= h["level"]:
            stack.pop()
        (stack[-1][1]["children"] if stack else root).append(node)
        stack.append((h["level"], node))
    return root


# ============================ 底层：抽行 ============================


def _span_is_bold(span: dict) -> bool:
    return bool(span["flags"] & BOLD_FLAG)


def _span_is_math(span: dict) -> bool:
    """是不是"公式"字体的字符（排除纯角标符号 ∗†‡）。"""
    if not span["font"].startswith(MATH_FONT_PREFIXES):
        return False
    t = span["text"].strip()
    if not t or FOOTNOTE_MARK_RE.match(t):
        return False
    return True


def _merge_spans(spans: list[dict]) -> tuple[str, bool, bool, int]:
    """把一行内的 span 拼成文本；span 间有明显空隙时补空格，避免 "2Background"。"""
    spans = sorted(spans, key=lambda s: s["bbox"][0])
    out: list[str] = []
    prev_x1: float | None = None
    for s in spans:
        t = s["text"]
        if not t.strip():
            if t and out and not out[-1].endswith(" "):
                out.append(" ")
            continue
        if prev_x1 is not None:
            gap = s["bbox"][0] - prev_x1
            if gap > 1.2 and not out[-1].endswith(" "):
                out.append(" ")
        out.append(t)
        prev_x1 = s["bbox"][2]
    text = re.sub(r"\s+", " ", "".join(out)).strip()
    is_bold = any(_span_is_bold(s) for s in spans if s["text"].strip())
    math_chars = sum(len(s["text"].strip()) for s in spans if _span_is_math(s))
    return text, is_bold, math_chars > 0, math_chars


def _page_lines(page: pymupdf.Page, page_no: int) -> list[Line]:
    """抽出一页的视觉行，并把同块内 y 相近的行合并（修"编号/标题被拆行"）。"""
    groups: list[dict] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:  # 1 = 图片块，跳过
            continue
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            y = (line["bbox"][1] + line["bbox"][3]) / 2
            hit = None
            for g in reversed(groups[-6:]):  # 只跟最近几行比，避免跨段误合
                if abs(g["y"] - y) <= Y_MERGE_TOL:
                    hit = g
                    break
            if hit is None:
                groups.append({"y": y, "x0": line["bbox"][0], "x1": line["bbox"][2], "spans": list(spans)})
            else:
                hit["spans"].extend(spans)
                hit["x0"] = min(hit["x0"], line["bbox"][0])
                hit["x1"] = max(hit["x1"], line["bbox"][2])

    lines: list[Line] = []
    for g in groups:
        text, is_bold, has_math, math_chars = _merge_spans(g["spans"])
        if not text:
            continue
        biggest = max(g["spans"], key=lambda s: s["size"])
        lines.append(
            Line(
                page=page_no,
                y=g["y"],
                x0=g["x0"],
                x1=g["x1"],
                size=round(biggest["size"], 1),
                font=biggest["font"],
                text=text,
                is_bold=is_bold,
                has_math=has_math,
                math_chars=math_chars,
            )
        )
    return lines


# ============================ 结构识别 ============================


def _heading_level(line: Line) -> tuple[int, str | None, str] | None:
    """判定是否标题。返回 (level, number, title)，不是标题返回 None。

    两级信号：
      1) 字号 ≥ H1_MIN_SIZE ⇒ 一级标题（本文里是 12pt，如 "3 Model Architecture"）
      2) 粗体 + 以编号开头 ⇒ 层级由编号点号数量决定（"3.2.1" ⇒ level 3）
    """
    text = line.text.strip()
    if not text or len(text) > HEADING_MAX_CHARS:
        return None

    # 〔1〕字号信号
    if line.size >= H1_MIN_SIZE and line.is_bold:
        m = NUM_TITLE_RE.match(text)
        if m:
            return len(m.group(1).split(".")), m.group(1), m.group(2).strip()
        if NUM_ONLY_RE.match(text):
            return 1, text.rstrip("."), ""
        return 1, None, text

    # 〔2〕编号信号（必须粗体，避免把正文里的 "in section 3.2." 当标题）
    if line.is_bold:
        m = NUM_TITLE_RE.match(text)
        if m:
            number, title = m.group(1), m.group(2).strip()
            if len(number.split(".")) <= 3:
                return len(number.split(".")), number, title
        m = NUM_ONLY_RE.match(text)
        if m and len(text) <= 8:
            return len(m.group(1).split(".")), m.group(1), ""  # 标题在下一行，稍后补
    return None


def _attach_orphan_numbers(lines: list[Line]) -> list[str]:
    """把"只有编号没有标题"的行，用后面紧跟的粗体行补全（原地改 line.text）。

    ★必须两个条件同时成立，否则页码会被误当成标题编号：
      - 编号行本身是粗体（标题编号是 Medi；页眉的页码是正体）
      - 下一行也是粗体（标题文字是 Medi）
    实测教训：只判"纯数字"会把每页顶部的页码吃进来，把图注/附录标题/参考文献条目
    拼成一串（首次运行误合并 14 处）。
    """
    notes: list[str] = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if (
            line.is_bold
            and NUM_ONLY_RE.match(line.text)
            and nxt is not None
            and nxt.is_bold
            and not NUM_TITLE_RE.match(nxt.text)
        ):
            line.text = f"{line.text} {nxt.text}".strip()
            nxt.text = ""  # 已并入上一行，标记为空后统一过滤
            notes.append(f"第 {line.page} 页：编号行与标题行合并 → {line.text!r}")
    return notes


def _extract_front_matter(lines: list[Line]) -> tuple[str | None, list[str], str]:
    """从首页头部抽 标题 / 作者 / 摘要。"""
    head = [ln for ln in lines if ln.page == 1]
    if not head:
        return None, [], ""

    title_line = max(head[:12], key=lambda ln: ln.size, default=None)
    title = title_line.text if title_line else None

    authors: list[str] = []
    if title_line is not None:
        after = head[head.index(title_line) + 1 :]
        for ln in after:
            if ln.text in {"Abstract", "ABSTRACT"} or ln.size >= H1_MIN_SIZE:
                break
            # 作者行特征：粗体、较短、不含邮箱
            if ln.is_bold and "@" not in ln.text and len(ln.text) <= 120:
                # 一行里可能并排多个作者，用 LaTeX 的角标符号 ∗/†/‡ 切开
                for part in re.split(r"[∗†‡]", ln.text):
                    name = part.strip(" ,;")
                    if name and len(name) <= 60:
                        authors.append(name)

    # 摘要：Abstract 标题之后、第一个编号标题之前
    abstract_parts: list[str] = []
    started = False
    for ln in lines:
        if ln.text.strip() in {"Abstract", "ABSTRACT"}:
            started = True
            continue
        if started:
            if NUM_TITLE_RE.match(ln.text) or NUM_ONLY_RE.match(ln.text):
                break
            abstract_parts.append(ln.text)
    return title, authors, " ".join(abstract_parts).strip()


def _extract_references(lines: Iterable[Line]) -> list[Reference]:
    """References 标题之后，按 "[n]" 切条目；续行并入上一条。"""
    refs: list[Reference] = []
    lines = list(lines)
    start = None
    for i, ln in enumerate(lines):
        if ln.text.strip().lower() in {"references", "bibliography"}:
            start = i
    if start is None:
        return refs

    cur_idx: int | None = None
    buf: list[str] = []
    for ln in lines[start + 1 :]:
        m = REF_ITEM_RE.match(ln.text)
        if m:
            if cur_idx is not None:
                refs.append(_finalize_ref(cur_idx, buf))
            cur_idx, buf = int(m.group(1)), [m.group(2)]
        elif cur_idx is not None:
            if ln.size >= H1_MIN_SIZE:  # 撞上后续一级标题（如附录）⇒ 结束
                break
            if PAGE_NUM_RE.fullmatch(ln.text):  # ★页眉/页脚页码，不是文献续行
                continue
            buf.append(ln.text)
    if cur_idx is not None:
        refs.append(_finalize_ref(cur_idx, buf))
    return refs


def _finalize_ref(index: int, buf: list[str]) -> Reference:
    raw = re.sub(r"\s+", " ", " ".join(buf)).strip()
    year_match = re.findall(r"\b((?:19|20)\d{2})\b", raw)
    arxiv = re.search(r"arXiv[:\s]*(\d{4}\.\d{4,5})", raw, re.IGNORECASE)
    return Reference(
        index=index,
        raw=raw,
        year=int(year_match[-1]) if year_match else None,
        arxiv_id=arxiv.group(1) if arxiv else None,
    )


# ============================ 主入口 ============================


def parse_pdf(path: str | Path, max_pages: int | None = None) -> ParsedDocument:
    """解析一篇 PDF，产出结构化文档（标题树 / 章节内容 / 参考文献 / 公式行）。

    max_pages 用于 541 页长文档的分批处理（J3 的内存硬指标），这里先留口子。
    """
    path = Path(path)
    doc = pymupdf.open(path)
    warnings: list[str] = []

    lines: list[Line] = []
    limit = min(doc.page_count, max_pages) if max_pages else doc.page_count
    for i in range(limit):
        lines.extend(_page_lines(doc[i], i + 1))

    warnings.extend(_attach_orphan_numbers(lines))
    lines = [ln for ln in lines if ln.text.strip()]

    title, authors, abstract = _extract_front_matter(lines)
    if not authors:
        warnings.append("未识别到作者行（首页排版可能不标准）")

    # ---- 标题树 ----
    outline: list[Heading] = []
    heading_pos: list[int] = []
    skipped: list[str] = []
    for i, ln in enumerate(lines):
        if ln.text == title:  # 文档大标题不算章节
            continue
        hit = _heading_level(ln)
        if not hit:
            continue
        level, number, htitle = hit
        if not htitle:
            skipped.append(f"第 {ln.page} 页：编号 {number} 无标题，已跳过")
            continue
        stack = [h.title for h in outline if h.level < level]
        outline.append(
            Heading(
                level=level,
                number=number,
                title=htitle,
                page=ln.page,
                line_no=i,
                path=stack[-2:] if level == 3 else stack[-1:],
            )
        )
        heading_pos.append(i)
    warnings.extend(skipped)

    # ---- 章节正文 ----
    sections: list[dict[str, Any]] = []
    for idx, h in enumerate(outline):
        end = heading_pos[idx + 1] if idx + 1 < len(heading_pos) else len(lines)
        body = [lines[j] for j in range(h.line_no + 1, end)]
        paragraphs: list[str] = []
        cur: list[str] = []
        for ln in body:
            if not cur and not ln.text:
                continue
            cur.append(ln.text)
            if ln.text.endswith((".", ":", "?", "!", "。", "）", ")")) and len(" ".join(cur)) > 220:
                paragraphs.append(" ".join(cur).strip())
                cur = []
        if cur:
            paragraphs.append(" ".join(cur).strip())
        sections.append(
            {
                "label": h.label,
                "level": h.level,
                "page_start": h.page,
                "page_end": body[-1].page if body else h.page,
                "paragraphs": paragraphs,
                "math_lines": [ln.text for ln in body if ln.has_math],
                "n_chars": sum(len(p) for p in paragraphs),
            }
        )

    references = _extract_references(lines)
    if not references:
        warnings.append("未抽到参考文献条目（检查是否有 References 标题）")

    if limit < doc.page_count:
        warnings.append(f"仅解析前 {limit} 页（max_pages={max_pages}）")

    return ParsedDocument(
        source=str(path).replace("\\", "/"),
        page_count=doc.page_count,
        title=title,
        authors=authors,
        abstract=abstract,
        outline=outline,
        sections=sections,
        references=references,
        math_lines=[
            {"page": ln.page, "text": ln.text, "math_chars": ln.math_chars}
            for ln in lines
            if ln.has_math
        ],
        warnings=warnings,
        stats={
            "lines": len(lines),
            "text_chars": sum(len(ln.text) for ln in lines),
            "headings": len(outline),
            "h1": sum(1 for h in outline if h.level == 1),
            "h2": sum(1 for h in outline if h.level == 2),
            "h3": sum(1 for h in outline if h.level == 3),
            "references": len(references),
            "abstract_chars": len(abstract),
            "math_lines": sum(1 for ln in lines if ln.has_math),
        },
    )


if __name__ == "__main__":  # 手跑：python -m app.services.pdf_parser <pdf> [--json out.json]
    import json
    import sys

    # Windows 控制台默认 GBK，遇到 '∗'(U+2217) 这类公式符号会崩 ⇒ 强制 UTF-8
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pdf_path = args[0] if args else "tests/fixtures/pdf/1706.03762v1.pdf"
    parsed = parse_pdf(pdf_path)
    print(f"===== {pdf_path} =====")
    print(f"标题: {parsed.title}")
    print(f"作者: {parsed.authors}")
    print(f"摘要: {parsed.abstract[:120]}…")
    print(f"\n--- 标题树（{parsed.stats['headings']} 个）---")
    for h in parsed.outline:
        print(f"  {'  ' * (h.level - 1)}L{h.level} {h.label}   (p{h.page})")
    print(f"\n--- 参考文献 {len(parsed.references)} 条，前 3 条 ---")
    print(f"  编号序列: {[r.index for r in parsed.references]}")
    for r in parsed.references[:3]:
        print(f"  [{r.index}] ({r.year}) {r.raw[:110]}")
    print(f"\n--- stats ---\n{json.dumps(parsed.stats, ensure_ascii=False, indent=2)}")
    print(f"\n--- warnings ---")
    for w in parsed.warnings:
        print(f"  ⚠ {w}")
    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        Path(out).write_text(
            json.dumps(parsed.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n已写 JSON → {out}")
    if "--golden" in sys.argv:
        # 只落"判据要看的那几项"，避免把全文段落灌进仓库（体积大且会掩盖差异）
        out = sys.argv[sys.argv.index("--golden") + 1]
        golden = {
            "source": Path(pdf_path).name,
            "title": parsed.title,
            "authors": parsed.authors,
            "n_authors": len(parsed.authors),
            "outline": [
                {"level": h.level, "number": h.number, "title": h.title, "page": h.page}
                for h in parsed.outline
            ],
            "reference_indices": [r.index for r in parsed.references],
            "reference_first": parsed.references[0].raw if parsed.references else None,
            "reference_last": parsed.references[-1].raw if parsed.references else None,
            "stats": parsed.stats,
        }
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(
            json.dumps(golden, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"已写 golden → {out}")
