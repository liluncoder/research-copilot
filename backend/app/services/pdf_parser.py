"""S1 · PDF 结构化解析（判据 J2 前半：三级标题树 + 公式保留 + 参考文献）。

为什么不用"直接抽纯文本"：PDF 里没有"标题/段落/公式"这些概念，只有
"在某坐标画这几个字、用这个字号/字体"。所以必须靠排版线索反推结构。

## ★核心设计：不写死任何出版社的字号

第一版把 arXiv 的字号规律（正文 10pt、一级标题 12pt 粗体…）写死在常量里，
结果换一篇 Nature 的论文立刻崩：那篇的标题跟正文**同字号**、**没有粗体标记**、
连字体名都被混淆过（`AdvOTea1a7398` 这种）。写死阈值等于只支持一类排版。

现在的做法：**先统计这份文档自己的样式分布，再判断哪些样式"用在短行上"**。
  1. 正文样式 = 贡献字符最多的 (字号, 字体) 组合
  2. 标题样式 = 非正文、且 ≥60% 的出现都在短行（≤60 字符）上的样式
  3. 标题层级：有编号按编号点号数；无编号则按字号降序排名
     （常见章节名如 Abstract/References 直接判一级，见 KNOWN_L1_SECTIONS）
  4. 行内标题（run-in，如 Nature 的 "Network models." 起一段）：
     用一个"只在行首出现、几乎不单独占整行"的样式来识别

这样 Transformer（LaTeX）与 Nature 两篇用的是同一套规则，只是统计结果不同。

## 其他实测踩过的坑（都留了回归意识）

- ★**空格 span 不能过滤**：PDF 会把空格单独做成一个 span，过滤掉就只剩"间距补空格"
  的启发式；而这类 PDF 的词是首尾相接的（gap=0）⇒ 单词全粘成一坨。
  实测：`Biologicallyinspiredalternativestobackpropagationthrough`。
- 编号与标题会被拆成两行（"3.1" / "Encoder and Decoder Stacks"），按 y 合并回来。
- 两栏排版不能跨栏合并：只在**同一个 block 内**按 y 合并。
- 公式不做 LaTeX 还原，只做"识别 + 原文保留"（见 `路线/02` 的失败去向）。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

import pymupdf

from app.services.tables import Table, extract_tables_from_page

# ---------- 排版启发式阈值（集中放这里，调参只改这一处）----------
HEADING_MAX_CHARS = 90  # 标题不会太长，超了当正文（防误判）
SHORT_LINE_CHARS = 60  # "短行"的门槛，用于统计某个样式是不是标题样式
Y_MERGE_TOL = 2.5  # 同一视觉行里，两个片段 y 中心差 < 此值就合并

# 常见的无编号一级章节名（★先去掉空格标点再比，兼容中英与各种大小写）
KNOWN_L1_SECTIONS = {
    "abstract", "introduction", "background", "relatedwork", "relatedworks",
    "results", "result", "discussion", "discussions", "methods", "method",
    "materialsandmethods", "conclusion", "conclusions", "summary",
    "references", "bibliography", "acknowledgement", "acknowledgements",
    "acknowledgment", "acknowledgments", "appendix", "appendices",
    "supplementaryinformation", "supplementarymaterial", "dataavailability",
    "codeavailability", "authorcontributions", "competinginterests",
    "conflictofinterest", "conflictsofinterest", "additionalinformation",
    "funding", "ethics", "figurecaptions", "tables", "摘 要", "摘要",
    "引言", "结论", "参考文献", "致谢",
}
NON_WORD_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")


def _norm_section(text: str) -> str:
    return NON_WORD_RE.sub("", text).lower()


def _style(size: float, font: str) -> tuple[float, str]:
    """样式的统一键：字号按 0.5pt 归并。

    ★踩坑：PDF 里同一个 10pt 正文会报成 9.9 / 10.0 / 10.1，
    不归并就会被当成三种样式 —— 正文样式只覆盖其中一部分，
    连带把"标题后面跟的是不是正文"也判错（实测：Abstract 因此被漏掉）。
    """
    return (round(size * 2) / 2, font)


# 作者行与机构行的区分（都不靠"加粗"，因为很多出版社的作者名是正体）
AUTHOR_NOISE_RE = re.compile(r"[\d\*†‡§¶✉∗°]+")
NAME_PARTICLES = {"van", "von", "de", "del", "der", "la", "le", "el", "al", "bin", "di", "da", "dos"}
AFFILIATION_WORDS = {
    "university", "universities", "institute", "institutes", "institution", "department",
    "departments", "laboratory", "laboratories", "lab", "labs", "school", "schools", "college",
    "center", "centre", "academy", "faculty", "division", "group", "research", "inc", "ltd",
    "gmbh", "corp", "corporation", "technologies", "technology", "sciences", "science",
    "email", "abstract", "authors", "author", "contributions", "for", "of", "the", "and",
    "at", "in", "on", "with", "from",
}

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
# 序号单独一行（Nature 风格）："1." / "12"
REF_NUM_LINE_RE = re.compile(r"^(\d{1,3})\.?$")
# 序号与条目同一行："1. LeCun, Y., Bengio, Y. & Hinton, G. Deep learning. …"
REF_INLINE_NUM_RE = re.compile(r"^(\d{1,3})\.\s+(\S.*)$")
# 作者-年份风格条目开头："Barrett, D. G., ..." / "LeCun, Y., ..."
REF_AUTHOR_YEAR_RE = re.compile(r"^[A-Z][\w'’\-]{1,30},\s*[A-Z]")
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
    size: float  # 主导样式的字号（按字符数加权，不看单个最大字号）
    font: str  # 主导样式的字体名
    text: str
    is_bold: bool
    has_math: bool
    math_chars: int  # 该行中数学字体字符数，用来区分"真公式"和"角标蹭进来的"
    math_by_font: dict[str, int] = field(default_factory=dict)  # 按字体拆开，供"排除正文字体"
    # 行首样式：run-in 标题（如 Nature 的 "Network models." 起一段）靠它识别
    lead_size: float = 0.0
    lead_font: str = ""
    lead_chars: int = 0
    force_heading: bool = False  # 段首小标题被切出来后的标记

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
    full_text: str
    outline: list[Heading]
    sections: list[dict[str, Any]]
    references: list[Reference]
    math_lines: list[dict[str, Any]]
    warnings: list[str]
    stats: dict[str, Any]
    tables: list[Table] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "page_count": self.page_count,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "full_text": self.full_text,
            "outline": [asdict(h) for h in self.outline],
            "sections": self.sections,
            "references": [asdict(r) for r in self.references],
            "math_lines": self.math_lines,
            "tables": [t.as_dict() for t in self.tables],
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


def _merge_spans(spans: list[dict]) -> dict[str, Any] | None:
    """把一行内的 span 拼成文本，并统计样式分布与行首样式。

    ★空格 span 必须保留。踩过的坑：这些 PDF 把空格单独做成一个 span，
    而相邻的词首尾相接（gap = 0.00），一旦把空格 span 过滤掉，
    "间距补空格"的启发式就完全失效 ⇒ 单词粘成一坨
    （实测 `Biologicallyinspiredalternativestobackpropagationthrough`）。
    """
    spans = sorted(spans, key=lambda s: s["bbox"][0])
    out: list[str] = []
    prev_x1: float | None = None
    styles: dict[tuple[float, str], int] = {}
    lead: tuple[float, str] | None = None
    lead_chars = 0
    lead_open = True

    for s in spans:
        t = s["text"]
        if not t.strip():
            if t and out and not out[-1].endswith(" "):  # 纯空格 span ⇒ 补一个空格
                out.append(" ")
            continue
        if prev_x1 is not None and out and not out[-1].endswith(" "):
            # 兜底：没有空格 span 时，按间距补（阈值随字号缩放，小字别误插）
            if s["bbox"][0] - prev_x1 > max(1.0, 0.18 * s["size"]):
                out.append(" ")
        out.append(t)
        prev_x1 = s["bbox"][2]

        key = _style(s["size"], s["font"])
        styles[key] = styles.get(key, 0) + len(t.strip())
        if lead is None:
            lead = key
        if lead_open and key == lead:
            lead_chars += len(t.strip())
        else:
            lead_open = False

    if not styles:
        return None
    text = re.sub(r"\s+", " ", "".join(out)).strip()
    if not text:
        return None
    dom_size, dom_font = max(styles, key=lambda k: styles[k])
    is_bold = any(_span_is_bold(s) for s in spans if s["text"].strip())
    math_chars = sum(len(s["text"].strip()) for s in spans if _span_is_math(s))
    math_by_font: dict[str, int] = {}
    for s in spans:
        if _span_is_math(s):
            math_by_font[s["font"]] = math_by_font.get(s["font"], 0) + len(s["text"].strip())
    return {
        "text": text,
        "size": dom_size,
        "font": dom_font,
        "is_bold": is_bold,
        "math_chars": math_chars,
        "math_by_font": math_by_font,
        "lead_size": lead[0] if lead else dom_size,
        "lead_font": lead[1] if lead else dom_font,
        "lead_chars": lead_chars,
    }


def _page_lines(page: pymupdf.Page, page_no: int) -> list[Line]:
    """抽出一页的视觉行，并把同块内 y 相近的行合并（修"编号/标题被拆行"）。"""
    groups: list[dict] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:  # 1 = 图片块，跳过
            continue
        for line in block["lines"]:
            spans = list(line["spans"])  # ★不筛空格 span（见 _merge_spans 的说明）
            if not any(s["text"].strip() for s in spans):
                continue
            y = (line["bbox"][1] + line["bbox"][3]) / 2
            hit = None
            for g in reversed(groups[-6:]):  # 只跟最近几行比，避免跨段误合
                # ★只在同一个 block 内合并：两栏排版的左右栏 y 相同，
                #   跨 block 合并会把两栏的文字串成一行
                if g["block"] is block and abs(g["y"] - y) <= Y_MERGE_TOL:
                    hit = g
                    break
            if hit is None:
                groups.append(
                    {
                        "block": block,
                        "y": y,
                        "x0": line["bbox"][0],
                        "x1": line["bbox"][2],
                        "spans": list(spans),
                    }
                )
            else:
                hit["spans"].extend(spans)
                hit["x0"] = min(hit["x0"], line["bbox"][0])
                hit["x1"] = max(hit["x1"], line["bbox"][2])

    height = page.rect.height or 1.0
    lines: list[Line] = []
    for g in groups:
        # ★丢页眉页脚（含页码）。踩坑：页码是"孤零零的短数字"，
        #   会被当成标题编号跟下一行拼起来（实测 '4 Figure 1: Scheme and…'），
        #   而它是正文之外的东西，直接去掉最干净。
        ratio = g["y"] / height
        group_text = re.sub(r"\s+", " ", "".join(s["text"] for s in g["spans"])).strip()
        if ratio < 0.08 or ratio > 0.94:
            continue
        if ratio > 0.86 and PAGE_NUM_RE.fullmatch(group_text):
            continue
        m = _merge_spans(g["spans"])
        if m is None:
            continue
        lines.append(
            Line(
                page=page_no,
                y=g["y"],
                x0=g["x0"],
                x1=g["x1"],
                size=m["size"],
                font=m["font"],
                text=m["text"],
                is_bold=m["is_bold"],
                has_math=m["math_chars"] > 0,
                math_chars=m["math_chars"],
                math_by_font=m["math_by_font"],
                lead_size=m["lead_size"],
                lead_font=m["lead_font"],
                lead_chars=m["lead_chars"],
            )
        )
    return lines


@dataclass
class StyleProfile:
    """这份文档自己的样式分布（★不写死任何出版社的字号）。"""

    body: tuple[float, str]
    heading_levels: dict[tuple[float, str], int]  # 样式 ⇒ 层级
    runin: tuple[float, str] | None  # 只在行首出现、几乎不占整行的样式
    text_fonts: set[str] = field(default_factory=set)  # 当作正文用的字体（不算公式）

    def is_heading_style(self, line: Line) -> bool:
        return (line.size, line.font) in self.heading_levels


def _analyze_styles(lines: list[Line]) -> StyleProfile:
    """先统计，再判断哪些样式"用在短行上" ⇒ 标题样式。

    这是本解析器能从 arXiv 泛化到 Nature 的关键：那篇 Nature 的标题
    与正文**同字号**、**无粗体标记**、字体名还被混淆过，任何写死的阈值都会失效；
    但"标题样式只出现在短行上"这件事在两类排版里都成立。
    """
    chars: dict[tuple[float, str], int] = {}
    whole_lines: dict[tuple[float, str], int] = {}
    total_len: dict[tuple[float, str], int] = {}
    max_len: dict[tuple[float, str], int] = {}
    lead_only: dict[tuple[float, str], int] = {}
    has_known_name: set[tuple[float, str]] = set()

    for ln in lines:
        key = (ln.size, ln.font)
        chars[key] = chars.get(key, 0) + len(ln.text)
        whole_lines[key] = whole_lines.get(key, 0) + 1
        total_len[key] = total_len.get(key, 0) + len(ln.text)
        max_len[key] = max(max_len.get(key, 0), len(ln.text))
        lead_key = (ln.lead_size, ln.lead_font)
        if lead_key != key:
            lead_only[lead_key] = lead_only.get(lead_key, 0) + 1
        if _norm_section(ln.text) in KNOWN_L1_SECTIONS:
            has_known_name.add(key)

    if not chars:
        return StyleProfile((0.0, ""), {}, None, set())
    body = max(chars, key=lambda k: chars[k])
    doc_chars = sum(chars.values()) or 1
    body_lines = whole_lines.get(body, 0)
    min_mean_len = 6  # 图片里的单词注释平均只有 3 个字符，真标题不会这么短

    # 该样式的行后面，有多少比例紧跟正文（标题后面是正文；图里坐标轴标注后面还是标注）
    followed_by_body: dict[tuple[float, str], int] = {}
    for ln, nxt in zip(lines, lines[1:]):
        k = (ln.size, ln.font)
        if k != body and (nxt.size, nxt.font) == body:
            followed_by_body[k] = followed_by_body.get(k, 0) + 1

    # 标题样式要同时满足 5 条 —— 单看"短行"会把图片里的单词注释也收进来
    # ★踩坑：v1 的 Attention Visualizations 图里有 "The / Law / will / never / be / …"
    #   一个词一行，曾被判成标题样式 ⇒ 标题数从 25 涨到 346。
    heading_styles: list[tuple[float, str]] = []
    for k, n in whole_lines.items():
        if k == body or n < 2:
            continue
        distinct = k[1] != body[1] or k[0] >= body[0] * 1.15
        rare = n <= max(3, int(body_lines * 0.2))
        mean_len = total_len.get(k, 0) / n
        shortish = min_mean_len <= mean_len <= SHORT_LINE_CHARS
        light = chars.get(k, 0) / doc_chars <= 0.15
        # ★"标题后面必须紧跟正文"这条单独用会误杀：Nature 的 Results 后面紧跟的是
        #   一个加粗的段首小标题，不是正文。所以给它配一个更强的豁免：
        #   样式里只要出现公认章节名（Results / Methods / References …），直接认定。
        #   图里的坐标轴标注不可能叫 Results，这条豁免不会误放。
        then_body = followed_by_body.get(k, 0) / n >= 0.3
        # ★真标题都很短。算法伪代码的行号与正文同一样式，加这条把它们挡在门外
        #   （实测：论文一的算法框里 "2 Simulate the network over the interval …" 被当成标题）
        not_too_long = max_len.get(k, 0) <= 120
        if distinct and rare and shortish and light and not_too_long and (
            then_body or k in has_known_name
        ):
            heading_styles.append(k)
    # 分级：按字号降序（有编号的行会在下面用编号覆盖层级）
    heading_levels = {
        k: min(i, 3) for i, k in enumerate(sorted(heading_styles, key=lambda k: -k[0]), start=1)
    }

    # run-in 样式：主要在行首出现，几乎不单独占整行 ⇒ 这是"段首小标题"的字体
    runin: tuple[float, str] | None = None
    for k, n in sorted(lead_only.items(), key=lambda kv: -kv[1]):
        if k == body or k in heading_levels or n < 3:
            continue
        if whole_lines.get(k, 0) <= max(1, int(n * 0.2)):
            runin = k
            break
    # 字体级占比：占比够大的字体是这个文档的"文字字体"，不该被当成公式
    # （★踩坑：LaTeX 写的论文正文就是 Computer Modern，被"CM=公式"一刀切会全篇误判）
    font_chars: dict[str, int] = {}
    for (_, f), c in chars.items():
        font_chars[f] = font_chars.get(f, 0) + c
    text_fonts = {f for f, c in font_chars.items() if c / doc_chars >= 0.02}
    return StyleProfile(body, heading_levels, runin, text_fonts)


# ============================ 结构识别 ============================


def _heading_level(
    line: Line, profile: StyleProfile, fallback_level: int = 1
) -> tuple[int, str | None, str] | None:
    """判定是否标题。返回 (level, number, title)，不是标题返回 None。

    信号来自 `_analyze_styles` 的统计，不再写死字号：
      1) 该行主导样式是"标题样式"（非正文、且只出现在短行上）
      2) 或粗体 + 以编号开头（兜住样式统计失手的文档）
      3) 或已被切出来的 run-in 小标题
    层级：有编号按点号数；无编号但命中常见章节名 ⇒ 一级；其余按样式字号排名。
    """
    text = line.text.strip()
    if not text or len(text) > HEADING_MAX_CHARS:
        return None

    key = (line.size, line.font)
    numbered = NUM_TITLE_RE.match(text) or NUM_ONLY_RE.match(text)
    styled = key in profile.heading_levels
    if not (styled or line.force_heading or (line.is_bold and numbered)):
        return None

    # 有编号 ⇒ 层级由编号决定（"3.2.1" ⇒ 3）
    m = NUM_TITLE_RE.match(text)
    if m:
        num, title = m.group(1), m.group(2).strip()
        # ★编号后面必须跟"像标题的东西"：首字母大写。
        #   否则伪代码行号会被吃掉（实测："1 for m ∈{1, …} do"、"7 end"）
        if not (title[:1].isupper() or not title[:1].isascii()):
            return None
        return min(len(num.split(".")), 3), num, title
    # ★只有编号没有标题的行（论文里是"标题在下一行"，Nature 参考文献里是"1."）
    #   不在这里判成标题：前者交给 _attach_orphan_numbers 合并，
    #   后者否则会截断参考文献区（实测：Reference 区被 '1.' 一刀切断 ⇒ 0 条）
    if NUM_ONLY_RE.match(text):
        return None

    # 无编号：先看是不是常见章节名（Abstract / References / Methods …）
    if _norm_section(text) in KNOWN_L1_SECTIONS:
        return 1, None, text

    # ★行内小标题常以冒号/分号收尾（如 Transformer 的 "Encoder:"），不是独立标题
    if text.rstrip().endswith((":", ";", ",")):
        return None
    # ★无编号的独立标题必然是短行；否则会把作者名单这种长粗体行误判成标题
    if len(text) > SHORT_LINE_CHARS:
        return None

    if line.force_heading:
        return min(fallback_level, 3), None, text
    lvl = profile.heading_levels.get(key, 1)
    # ★无编号、又不在最高层样式上 ⇒ 大概率是表格里的加粗表头
    #   实测：v1 第 9 页 Table 4 的表头 "Parser Training WSJ 23 F1" 曾被判成一级标题
    if lvl != 1:
        return None
    return 1, None, text


def _attach_orphan_numbers(
    lines: list[Line], profile: StyleProfile | None = None
) -> list[str]:
    """把"只有编号没有标题"的行，用后面紧跟的粗体行补全（原地改 line.text）。

    ★必须两个条件同时成立，否则页码会被误当成标题编号：
      - 编号行本身是标题样式（或粗体）
      - 下一行也是标题样式（或粗体）
    实测教训：只判"纯数字"会把每页顶部的页码吃进来，把图注/附录标题/参考文献条目
    拼成一串（首次运行误合并 14 处）。
    """
    def is_heading_style(ln: Line) -> bool:
        if profile is None:
            return ln.is_bold  # 第一遍：样式分析还没做，只靠粗体
        return (ln.size, ln.font) in profile.heading_levels or ln.is_bold

    notes: list[str] = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if (
            NUM_ONLY_RE.match(line.text)
            and len(line.text) <= 8
            and is_heading_style(line)
            and nxt is not None
            and is_heading_style(nxt)
            and not NUM_TITLE_RE.match(nxt.text)
        ):
            line.text = f"{line.text} {nxt.text}".strip()
            nxt.text = ""  # 已并入上一行，标记为空后统一过滤
            notes.append(f"第 {line.page} 页：编号行与标题行合并 → {line.text!r}")
    return notes


def _split_runin_headings(lines: list[Line], profile: StyleProfile) -> list[Line]:
    """把段首小标题（run-in）从正文行里切出来，变成独立标题行。

    典型场景：Nature 里 "Network models. To exhibit the generality ..." /
    "Mathematical basis for e-prop. Spikes are modeled as ..."
    —— 标题和正文挤在同一行，只靠"行首字体变了"才能认出来。

    ★判据是"行首样式属于标题样式（或 run-in 样式）"，
      而不只是"行首样式 == run-in" —— 否则 Nature 里用标题字体的
      "Mathematical basis for e-prop. …" 会被整行当成一个超长标题。

    ★但光靠样式边界会**切过头**：作者行 "Guillaume Bellec*, Franz Scherr*, …"
      里的角标 * 也是样式边界，于是作者名被切成了"标题"。
      所以再加四道：首字母大写、≥2 个词、以句号/冒号收尾、不含公式符号。
    """
    MATH_CHARS = set("=+−×∑∫·±≤≥∈")

    def looks_like_heading_head(head: str) -> bool:
        if not 8 <= len(head) <= SHORT_LINE_CHARS:
            return False
        if head[0].islower() or not head.rstrip().endswith((".", "。", ":", "：")):
            return False
        if len(head.split()) < 2:
            return False
        return not any(ch in MATH_CHARS for ch in head)

    out: list[Line] = []
    for ln in lines:
        lead_style = (ln.lead_size, ln.lead_font)
        lead_is_heading = lead_style in profile.heading_levels or (
            profile.runin is not None and lead_style == profile.runin
        )
        if (
            lead_is_heading
            and 0 < ln.lead_chars <= SHORT_LINE_CHARS
            and ln.lead_chars < len(ln.text) - 2  # 后面还有正文才算 run-in
        ):
            cut = ln.lead_chars
            while cut < len(ln.text) and ln.text[cut] != " ":
                cut += 1  # 字符数会差一两个空格，扩展到词边界
            head_text, rest = ln.text[:cut].strip(), ln.text[cut:].strip()
            if head_text and rest and looks_like_heading_head(head_text):
                out.append(replace(ln, text=head_text, force_heading=True))
                out.append(
                    replace(
                        ln,
                        text=rest,
                        size=profile.body[0],
                        font=profile.body[1],
                        lead_size=profile.body[0],
                        lead_font=profile.body[1],
                        lead_chars=0,
                    )
                )
                continue
        out.append(ln)
    return out


def _looks_like_authors(text: str) -> bool:
    """判断一行像不像"作者名单"（而不是机构 / 日期 / 脚注）。

    ★第一版要求"粗体"才认作者，结果两篇 Nature/预印本论文（作者行是正体）
    一个作者都没抽出来。改成看"形状"：逗号/and 分出来的片段，
    多数应该是 1-4 个首字母大写的词，且不含机构/虚词。
    """
    segs = [s.strip() for s in re.split(r",|\band\b|&", AUTHOR_NOISE_RE.sub(" ", text)) if s.strip()]
    if not segs:
        return False
    good = 0
    for seg in segs:
        toks = seg.split()
        if not 1 <= len(toks) <= 4:
            continue
        if all(
            t.lower() in NAME_PARTICLES
            or (t[0].isupper() and t.lower() not in AFFILIATION_WORDS)
            for t in toks
        ):
            good += 1
    return good >= 1 and good / len(segs) >= 0.6


def _split_author_names(text: str) -> list[str]:
    """从一行里切出人名。

    ★只保留"像个名字"的片段（2-4 个词）。踩坑：不加这道过滤，
    机构与日期行会被切成单名"作者" —— 实测抽出过 ['Austria', 'February']。
    """
    cleaned = AUTHOR_NOISE_RE.sub(" ", text)
    names = []
    for seg in re.split(r",|\band\b|&", cleaned):
        name = " ".join(seg.split())
        toks = name.split()
        if not 2 <= len(toks) <= 4 or len(name) > 60:
            continue
        if not all(
            t.lower() in NAME_PARTICLES
            or (t[0].isupper() and t.lower() not in AFFILIATION_WORDS)
            for t in toks
        ):
            continue
        if name:
            names.append(name)
    return names


def _extract_front_matter(
    lines: list[Line], profile: StyleProfile
) -> tuple[str | None, list[str], str, set[str]]:
    """从首页头部抽 标题 / 作者 / 摘要。

    返回 (title, authors, abstract, 已消费行文本集) —— 最后一个用于让标题树
    跳过"文档大标题"和"作者行"（作者行常常恰好与二三级标题同一字体，
    ★不排掉就会被当成章节）。
    """
    head = [ln for ln in lines if ln.page == 1]
    if not head:
        return None, [], "", set()

    # ---- 标题：可能跨多行（Nature/预印本常见），同字号连续行一起收 ----
    window = head[:16]
    top = max(ln.size for ln in window)
    start = next((i for i, ln in enumerate(window) if ln.size >= top - 0.2), None)
    if start is None:
        return None, [], "", set()
    end = start
    while end + 1 < len(head) and head[end + 1].size >= top - 0.2:
        end += 1
    title_lines = head[start : end + 1]
    title = " ".join(ln.text for ln in title_lines).strip() or None
    title_texts = {ln.text for ln in title_lines}
    consumed = set(title_texts)

    # ---- 作者：标题之后，锁定"第一行作者"的样式，只认同样式的行 ----
    #   ★这样能自动跳过机构名与邮箱（与作者同字号、不同字体），
    #     也不需要"作者必须加粗"（很多出版社的作者名是正体）。
    authors: list[str] = []
    last_author_idx = end
    author_style: tuple[float, str] | None = None
    for i in range(end + 1, len(head)):
        ln = head[i]
        if _norm_section(ln.text) in KNOWN_L1_SECTIONS:
            body_start = i
            break
        if "@" in ln.text:
            continue
        # ★先判作者再判标题：作者行常与二三级标题同字体，顺序反了会被"标题"截胡
        if _looks_like_authors(ln.text) and (
            author_style is None or (ln.size, ln.font) == author_style
        ):
            author_style = (ln.size, ln.font)
            authors.extend(_split_author_names(ln.text))
            consumed.add(ln.text)
            last_author_idx = i
            continue
        if _heading_level(ln, profile):
            last_author_idx = i - 1
            break
    body_start = min(last_author_idx + 1, len(head))

    # ---- 摘要 ----
    abstract_parts: list[str] = []
    started_at: int | None = None
    for i, ln in enumerate(lines):
        if _norm_section(ln.text) == "abstract":
            started_at = i
            break
    if started_at is not None:
        for ln in lines[started_at + 1 :]:
            if _heading_level(ln, profile):
                break
            abstract_parts.append(ln.text)
    else:
        # Nature 类排版没有 "Abstract" 小标题，摘要就是正文第一段
        for ln in head[body_start:]:
            if _heading_level(ln, profile):
                break
            if ln.text.strip():
                abstract_parts.append(ln.text)

    return title, authors, " ".join(abstract_parts).strip(), consumed


def _extract_references(lines: Iterable[Line], profile: StyleProfile) -> list[Reference]:
    """参考文献区解析：自动识别三种排版风格。

    ★第一版只认 `[1]` 那种编号，结果换两篇论文立刻归零：
      - 预印本/elife：**作者-年份**格式，条目以 `Barrett, D. G., ...` 开头，无编号
      - Nature Communications：**序号单独占一行**（`1.` 换行后才是条目正文）
    所以先统计这一段里哪种模式占多数，再按那种模式切。
    """
    refs: list[Reference] = []
    lines = list(lines)
    start = None
    for i, ln in enumerate(lines):
        if ln.text.strip().lower() in {"references", "bibliography"}:
            start = i
    if start is None:
        return refs

    # 取出参考文献区（到下一个标题为止）
    section: list[Line] = []
    for ln in lines[start + 1 :]:
        if _heading_level(ln, profile):
            break
        section.append(ln)
    if not section:
        return refs

    n_bracket = sum(1 for ln in section if REF_ITEM_RE.match(ln.text))
    n_numline = sum(
        1
        for ln in section
        if REF_NUM_LINE_RE.fullmatch(ln.text.strip()) or REF_INLINE_NUM_RE.match(ln.text)
    )
    n_author = sum(1 for ln in section if REF_AUTHOR_YEAR_RE.match(ln.text))

    if n_bracket >= 3 and n_bracket >= n_numline and n_bracket >= n_author:
        return _refs_from_brackets(section, profile)
    if n_numline >= 3 and n_numline >= n_author:
        return _refs_from_number_lines(section)
    if n_author >= 3:
        return _refs_from_author_year(section, profile)
    # 兜底：仍按 [n] 试一遍
    return _refs_from_brackets(section, profile)


def _refs_from_brackets(lines: list[Line], profile: StyleProfile) -> list[Reference]:
    """`[1] ...` 格式（LaTeX / arXiv 最常见）。"""
    refs: list[Reference] = []
    cur: int | None = None
    buf: list[str] = []
    for ln in lines:
        m = REF_ITEM_RE.match(ln.text)
        if m:
            if cur is not None:
                refs.append(_finalize_ref(cur, buf))
            cur, buf = int(m.group(1)), [m.group(2)]
        elif cur is not None:
            if PAGE_NUM_RE.fullmatch(ln.text):  # ★页眉/页脚页码，不是文献续行
                continue
            buf.append(ln.text)
    if cur is not None:
        refs.append(_finalize_ref(cur, buf))
    return refs


def _refs_from_number_lines(lines: list[Line]) -> list[Reference]:
    """编号式条目：序号可能单独占一行（`1.` 换行后是正文），也可能与正文同行。"""
    refs: list[Reference] = []
    cur: int | None = None
    buf: list[str] = []
    for ln in lines:
        text = ln.text.strip()
        inline = REF_INLINE_NUM_RE.match(text)
        alone = REF_NUM_LINE_RE.fullmatch(text)
        if inline or alone:
            if cur is not None:
                refs.append(_finalize_ref(cur, buf))
            if inline:
                cur, buf = int(inline.group(1)), [inline.group(2)]
            else:
                cur, buf = int(alone.group(1)), []
        elif cur is not None:
            if PAGE_NUM_RE.fullmatch(text):
                continue
            buf.append(ln.text)
    if cur is not None:
        refs.append(_finalize_ref(cur, buf))
    return refs


def _refs_from_author_year(lines: list[Line], profile: StyleProfile) -> list[Reference]:
    """作者-年份格式：新条目以 `姓, 缩写. …` 开头，续行并入上一条。"""
    refs: list[Reference] = []
    buf: list[str] = []
    idx = 0
    for ln in lines:
        text = ln.text.strip()
        if not text or PAGE_NUM_RE.fullmatch(text):
            continue
        if REF_AUTHOR_YEAR_RE.match(text):
            if buf:
                idx += 1
                refs.append(_finalize_ref(idx, buf))
            buf = [text]
        elif buf:
            buf.append(text)
    if buf:
        idx += 1
        refs.append(_finalize_ref(idx, buf))
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


def parse_pdf(path: str | Path, max_pages: int | None = None, *, with_tables: bool = True) -> ParsedDocument:
    """解析一篇 PDF，产出结构化文档（标题树 / 章节内容 / 参考文献 / 公式行 / 表格）。

    max_pages 用于 541 页长文档的分批处理（J3 的内存硬指标），这里先留口子。
    with_tables=False 可跳过表格抽取（纯文本用途时省时间）。
    """
    path = Path(path)
    doc = pymupdf.open(path)
    warnings: list[str] = []

    lines: list[Line] = []
    pages_text: list[str] = []
    all_tables: list[Table] = []
    limit = min(doc.page_count, max_pages) if max_pages else doc.page_count
    for i in range(limit):
        pages_text.append(doc[i].get_text())
        lines.extend(_page_lines(doc[i], i + 1))
        if with_tables:
            all_tables.extend(extract_tables_from_page(doc[i], i + 1))

    lines = [ln for ln in lines if ln.text.strip()]
    # ⓪ 第一遍合并：样式分析还没做，只能靠粗体。否则"1"与"Introduction"分家，
    #    会让整个 12pt 标题样式通不过"标题后面跟正文"的检查（实测：Abstract 被漏掉）
    warnings.extend(_attach_orphan_numbers(lines))
    lines = [ln for ln in lines if ln.text.strip()]
    # ① 先统计这份文档自己的样式分布（不写死出版社的字号）
    profile = _analyze_styles(lines)
    # ★"CM 字体 = 公式"这条对 LaTeX 写的论文会全线误判 —— 它们的**正文就是**
    #   Computer Modern。所以按文档自己的正文字体再排除一次
    #   （实测：论文一 3023 行"公式"里绝大多数其实是正文）
    for ln in lines:
        if ln.math_by_font:
            ln.math_chars = sum(
                c for f, c in ln.math_by_font.items() if f not in profile.text_fonts
            )
            ln.has_math = ln.math_chars > 0
    # ② 合并被拆开的"编号 / 标题"，并把段首小标题（run-in）切成独立行
    warnings.extend(_attach_orphan_numbers(lines, profile))
    lines = [ln for ln in lines if ln.text.strip()]
    lines = _split_runin_headings(lines, profile)

    title, authors, abstract, consumed_texts = _extract_front_matter(lines, profile)
    if not authors:
        warnings.append("未识别到作者行（首页排版不常见，已回退为空）")

    # ---- 标题树 ----
    outline: list[Heading] = []
    heading_pos: list[int] = []
    skipped: list[str] = []
    last_level = 1
    for i, ln in enumerate(lines):
        if ln.text in consumed_texts:  # 文档大标题 / 作者行 不算章节
            continue
        hit = _heading_level(ln, profile, fallback_level=last_level + 1)
        if not hit:
            continue
        level, number, htitle = hit
        last_level = level
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

    references = _extract_references(lines, profile)
    if not references:
        warnings.append("未抽到参考文献条目（检查是否有 References 标题）")

    # ---- 表格 ----
    for idx, t in enumerate(all_tables, start=1):
        t.index = idx
    if with_tables:
        if not all_tables:
            warnings.append("未识别到表格（可能无表、或表无 caption 无 rule）")
        else:
            low = [f"Table {t.number}(p{t.page},conf={t.confidence:.2f})"
                   for t in all_tables if t.confidence < 0.7]
            if low:
                warnings.append("以下表格结构置信度偏低，单元格可能错位：" + "、".join(low))

    if limit < doc.page_count:
        warnings.append(f"仅解析前 {limit} 页（max_pages={max_pages}）")

    return ParsedDocument(
        source=str(path).replace("\\", "/"),
        page_count=doc.page_count,
        title=title,
        authors=authors,
        abstract=abstract,
        full_text="\n".join(pages_text),
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
            "tables": len(all_tables),
        },
        tables=all_tables,
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
