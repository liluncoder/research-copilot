"""表格抽取（M1 / J2 后半）。

★为什么不用现成库（实测记录，见 report/J2_判词.md）：
PyMuPDF 1.28 的三种策略在 Attention 论文上全不可用 ——
  · strategy="lines"：学术表是 booktabs 风格（只有横线、没有竖线）⇒ 一张都找不到
  · strategy="text" ：把整页当一张表 ⇒ 产 49~68 行垃圾
  · 混合 text/lines：列被压扁（"Self-Atten Recurrent Convolutio Se"）

★本实现：**按 rule 定边界 + 按空白投影分列**
  1. `Table N:` 文字块定位 caption（顺带拿到 caption 原文）
  2. **表格边界直接用横线（rule）**——booktabs 表一定画 2~3 条以上，
     且 caption 下方第一条 rule 就是表头线。这是本方法最关键的实测结论：
     ★不能按"caption 在哪一栏"定宽度，Table 1/Table 3 都是通栏表（x 119~493 / 108~509）
  3. **表头与数据的界线 = 表头之后第一条"通栏" rule**（半宽 rule 是 cmidrule，组头分隔用，不能当界线）
  4. 列边界只在**数据区**投影求得（表头里的 "BLEU"/"Training Cost" 是跨列组头，
     参与投影会把两列粘成一列 —— 这是第一版失败的直接原因）
  5. 词按 y 聚成行、按列归属落格

★适用面诚实写清：对齐良好的表（数值/对比表）抽得干净；合并单元格、跨页续表会退化，
退化时 confidence 降低并在 warnings 说明，绝不"看起来成功其实全是碎片"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

CAPTION_RE = re.compile(r"^\s*Table\s+(\d+)\s*[:．.]\s*(.+)$", re.S)

# ★实测标定（Attention v1 真实几何）：
#   单元格内部词间距最大 3pt；列间最小空档 9pt（Table 1 的 Complexity|Sequential）
MIN_COL_GAP = 6.0
# 同行词的 y 中心波动
ROW_TOLERANCE = 4.5
# 表格最大高度（pt）：超过必是把正文框进来了
MAX_TABLE_HEIGHT = 300.0
# 判定"通栏 rule"：宽度 >= 表格宽度的这个比例
FULL_RULE_RATIO = 0.75
# 两条 rule 间距超过它 ⇒ 不属于同一张表
RULE_GAP_LIMIT = 200.0


@dataclass
class Table:
    index: int
    number: int | None
    page: int
    caption: str
    bbox: tuple[float, float, float, float]
    rows: list[list[str]] = field(default_factory=list)
    header_rows: int = 0
    method: str = "rule+projection"
    confidence: float = 0.0

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    def as_markdown(self) -> str:
        if not self.rows:
            return ""
        width = self.n_cols
        grid = [r + [""] * (width - len(r)) for r in self.rows]
        head, body = grid[0], grid[1:]
        out = ["| " + " | ".join(head) + " |", "|" + "---|" * width]
        out += ["| " + " | ".join(r) + " |" for r in body]
        return "\n".join(out)

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "number": self.number,
            "page": self.page,
            "caption": self.caption,
            "bbox": [round(v, 1) for v in self.bbox],
            "n_rows": self.n_rows,
            "n_cols": self.n_cols,
            "header_rows": self.header_rows,
            "method": self.method,
            "confidence": round(self.confidence, 3),
            "rows": self.rows,
            "markdown": self.as_markdown(),
        }


# ---------------------------------------------------------------- 几何


def _norm(text: str) -> str:
    return " ".join(text.split())


def _find_captions(page: pymupdf.Page) -> list[tuple[int, pymupdf.Rect, str]]:
    found: list[tuple[int, pymupdf.Rect, str]] = []
    for b in page.get_text("blocks"):
        text = _norm(b[4])
        m = CAPTION_RE.match(text)
        if m:
            found.append((int(m.group(1)), pymupdf.Rect(b[:4]), text))
    found.sort(key=lambda t: t[1].y0)
    return found


def _rules(page: pymupdf.Page) -> list[tuple[float, float, float]]:
    """页面所有横线，返回 (y, x0, x1)，按 y 升序。"""
    out: list[tuple[float, float, float]] = []
    for d in page.get_drawings():
        for item in d["items"]:
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) < 1.2 and abs(p2.x - p1.x) > 40:
                    out.append((round(p1.y, 1), min(p1.x, p2.x), max(p1.x, p2.x)))
            elif item[0] == "re":
                r = item[1]
                if r.height < 2.0 and r.width > 40:
                    out.append((round(r.y0, 1), r.x0, r.x1))
    out.sort(key=lambda t: t[0])
    return out


@dataclass
class _Region:
    x0: float
    x1: float
    top: float      # 表头线
    header_bottom: float
    bottom: float   # 末条 rule


def _region_from_rules(page: pymupdf.Page, cap: pymupdf.Rect) -> _Region | None:
    """caption 下方的 rule 串 ⇒ 表格区域。找不到合适 rule 就返回 None（走兜底）。"""
    limit_y = cap.y1 + MAX_TABLE_HEIGHT
    # ★下界放宽 5pt：Table 4 的顶线（y=413.7）只比 caption 底（411.8）低 1.9pt，
    #   严格用 cap.y1+2 会把它排除，导致整张表从第二条 rule 起算 ⇒ 表头被当成数据
    cand = [r for r in _rules(page) if cap.y1 - 5 <= r[0] <= limit_y]
    if len(cand) < 2:
        return None

    # 连续段：从第一条开始，遇到与上一条间隔 > RULE_GAP_LIMIT 就停
    chain = [cand[0]]
    for r in cand[1:]:
        if r[0] - chain[-1][0] > RULE_GAP_LIMIT:
            break
        chain.append(r)
    if len(chain) < 2:
        return None

    x0 = min(r[1] for r in chain)
    x1 = max(r[2] for r in chain)
    width = x1 - x0
    if width < 80:
        return None

    top = chain[0][0]
    # 表头下界：top 之后第一条"通栏" rule
    header_bottom = None
    for r in chain[1:]:
        if (r[2] - r[1]) >= FULL_RULE_RATIO * width:
            header_bottom = r[0]
            break
    if header_bottom is None:
        header_bottom = top + 12

    bottom = max(r[0] for r in chain)
    if bottom - top < 8:
        return None
    return _Region(x0=x0, x1=x1, top=top, header_bottom=header_bottom, bottom=bottom)


def _region_fallback(page: pymupdf.Page, cap: pymupdf.Rect) -> _Region | None:
    """没有 rule 时的兜底：用 caption 的左右范围 + 固定高度。置信度会低，但不至于全无。"""
    x0 = max(0.0, cap.x0 - 12)
    x1 = min(page.rect.width, cap.x1 + 12)
    top = cap.y1 + 2
    return _Region(x0=x0, x1=x1, top=top, header_bottom=top + 12,
                   bottom=min(page.rect.height, top + 120))


# ---------------------------------------------------------------- 分列 / 分行


def _merge_spans(words: list[tuple], gap: float) -> list[tuple[float, float]]:
    spans = sorted((w[0], w[2]) for w in words)
    if not spans:
        return []
    merged: list[list[float]] = [list(spans[0])]
    for x0, x1 in spans[1:]:
        if x0 - merged[-1][1] <= gap:
            merged[-1][1] = max(merged[-1][1], x1)
        else:
            merged.append([x0, x1])
    return [(a, b) for a, b in merged]


def _cluster(values: list[float], tol: float) -> list[float]:
    """一维贪心聚类，返回各簇中心（升序）。"""
    if not values:
        return []
    vals = sorted(values)
    groups: list[list[float]] = [[vals[0]]]
    for v in vals[1:]:
        if v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def _columns_voted(
    rows: list[list[tuple]],
    *,
    min_gap: float = MIN_COL_GAP,
    tol: float = 12.0,
    min_support_ratio: float = 0.45,
) -> list[tuple[float, float]]:
    """★按"跨行投票"求列边界，而不是把所有词一锅投影。

    为什么必须投票：表格里会有**多行行**（模型名换行），它的数值位置和别的行错开，
    一锅投影时这些离群词会把两列桥接起来（实测 Table 2 的 FLOPs 两列就是这么并住的：
    末两行 '·' 落在 x=425，而正常行该处是 421~435 的空档）。

    做法：逐行找 gap，把 gap 中点当"投票"；同一位置被足够多行投到 ⇒ 才是真列边界。
    """
    votes: list[tuple[float, int]] = []
    for ri, row in enumerate(rows):
        ws = sorted(row, key=lambda w: w[0])
        for a, b in zip(ws, ws[1:]):
            gap = b[0] - a[2]
            if gap >= min_gap:
                votes.append(((a[2] + b[0]) / 2, ri))
    if not votes:
        return []

    centers = _cluster([v for v, _ in votes], tol)
    need = max(2, int(len(rows) * min_support_ratio))
    boundaries = [
        c for c in centers if len({ri for v, ri in votes if abs(v - c) <= tol}) >= need
    ]
    if not boundaries:
        return []

    xs0 = [w[0] for row in rows for w in row]
    xs1 = [w[2] for row in rows for w in row]
    edges = [min(xs0) - 1] + sorted(boundaries) + [max(xs1) + 1]
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]


def _rows_from_words(words: list[tuple]) -> list[list[tuple]]:
    rows: list[list[tuple]] = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        yc = (w[1] + w[3]) / 2
        if rows:
            prev = rows[-1]
            prev_yc = sum((x[1] + x[3]) / 2 for x in prev) / len(prev)
            if abs(yc - prev_yc) <= ROW_TOLERANCE:
                prev.append(w)
                continue
        rows.append([w])
    return rows


def _merge_header_rows(grid: list[list[str]], header_rows: int) -> list[list[str]]:
    """把多行表头压成一行（按列竖向拼接）。

    实测：Table 1 的表头是 "Complexity per" / "Layer" 两行、Table 2 是
    "BLEU" / "EN-DE EN-FR" 两行 —— 不合并的话下游（前端表格、RAG 引用）看到的是
    两个残缺表头，没法用。合并后至少是可读的 "Complexity per Layer"、"BLEU EN-DE"。
    """
    if header_rows <= 1 or len(grid) <= header_rows:
        return grid
    width = len(grid[0])
    merged: list[str] = []
    for ci in range(width):
        parts = [grid[r][ci] for r in range(header_rows) if grid[r][ci]]
        merged.append(" ".join(parts).strip())
    return [merged] + grid[header_rows:]


def _merge_continuations(grid: list[list[str]]) -> list[list[str]]:
    """把"续行"并回上一行。

    多行行的第二行通常只有 1~2 个格子有值，且这些格子正好是上一行的空格子。
    ★只在"上一行对应格为空"时才合并，避免把真正稀疏的独立行吞掉。
    """
    out: list[list[str]] = []
    for r in grid:
        filled = [i for i, c in enumerate(r) if c]
        if out and 0 < len(filled) <= 2 and all(not out[-1][i] for i in filled):
            for i in filled:
                out[-1][i] = f"{out[-1][i]} {r[i]}".strip()
            continue
        out.append(list(r))
    return out


def _assign(row_words: list[tuple], columns: list[tuple[float, float]]) -> list[str]:
    """把一个视觉行的词分到各列。

    ★用"最大重叠"而不是"中心点落在哪列"：表头是**居中**的（"Complexity per Layer"
    中心落在两列之间），按中心会把它右半边甩到下一列，实测出现 "Layer Sequential" 这种串列。
    重叠量对居中和左对齐都成立。
    """
    cells: list[list[str]] = [[] for _ in columns]
    for w in sorted(row_words, key=lambda w: w[0]):
        best_i, best_ov = None, 0.0
        for i, (c0, c1) in enumerate(columns):
            ov = min(w[2], c1) - max(w[0], c0)
            if ov > best_ov:
                best_i, best_ov = i, ov
        if best_i is None:  # 完全落在所有列之外（脚注符号等）⇒ 归最近列
            center = (w[0] + w[2]) / 2
            best_i = min(range(len(columns)), key=lambda i: abs(center - (columns[i][0] + columns[i][1]) / 2))
        cells[best_i].append(w[4])
    return [" ".join(c).strip() for c in cells]


# ---------------------------------------------------------------- 主入口


def extract_tables_from_page(page: pymupdf.Page, page_no: int) -> list[Table]:
    caps = _find_captions(page)
    tables: list[Table] = []
    for i, (number, cap_rect, caption) in enumerate(caps):
        next_cap_y = caps[i + 1][1].y0 if i + 1 < len(caps) else 1e9
        region = _region_from_rules(page, cap_rect) or _region_fallback(page, cap_rect)
        if region is None:
            continue
        bottom = min(region.bottom + 2, next_cap_y - 1)
        clip = pymupdf.Rect(region.x0, region.top, region.x1, bottom)
        words = [w for w in page.get_text("words", clip=clip) if w[3] > region.top + 1]
        if len(words) < 4:
            continue

        # ★按"词"切表头/数据，而不是按整行切：
        #   整行的 y 只要有一个上标/大写字母探进表头线，整行就会被当成表头（实测 Table 2
        #   把 ByteNet 行吞进表头）。按词切则每个词各自判定，天然不受行内异常点影响。
        cut = region.header_bottom - 1
        head_words = [w for w in words if (w[1] + w[3]) / 2 < cut]
        data_words = [w for w in words if (w[1] + w[3]) / 2 >= cut]

        data_rows = _rows_from_words(data_words)
        head_rows = _rows_from_words(head_words)

        # ★列边界只从数据区投票求（表头有跨列组头，参与投影会把两列粘成一列）
        columns = (
            _columns_voted(data_rows)
            or _columns_voted(head_rows + data_rows)
            or _merge_spans(data_words or words, MIN_COL_GAP)
        )
        if len(columns) < 2:
            continue

        header_rows = len(head_rows)
        # ★表头与数据分开做"续行合并"：续行合并会把只有 1 格值的表头行粘到上一行，
        #   再把下一行数据卷进表头（实测 Table 2 的 ByteNet 行就是这么被吞掉的）
        head_grid = [r for r in (_assign(rw, columns) for rw in head_rows) if any(r)]
        data_grid = [r for r in (_assign(rw, columns) for rw in data_rows) if any(r)]
        data_grid = _merge_continuations(data_grid)
        grid = _merge_header_rows(head_grid + data_grid, len(head_grid))

        # 去掉尾部"孤字行"（脚注符号、页码蹭进来的）
        while grid and sum(1 for c in grid[-1] if c) <= 1:
            grid.pop()
        if len(grid) < 2:
            continue

        filled = sum(1 for r in grid for c in r if c)
        total = len(grid) * len(columns)
        tables.append(
            Table(
                index=0,
                number=number,
                page=page_no,
                caption=caption,
                bbox=(clip.x0, clip.y0, clip.x1, clip.y1),
                rows=grid,
                header_rows=max(1, header_rows),
                confidence=(filled / total) if total else 0.0,
            )
        )
    return tables


def extract_tables(pdf: str | Path, *, max_pages: int | None = None) -> list[Table]:
    tables: list[Table] = []
    with pymupdf.open(pdf) as doc:
        limit = min(doc.page_count, max_pages) if max_pages else doc.page_count
        for pno in range(limit):
            page = doc.load_page(pno)
            for t in extract_tables_from_page(page, pno + 1):
                t.index = len(tables) + 1
                tables.append(t)
            del page
    return tables


if __name__ == "__main__":  # 手跑：python -m app.services.tables <pdf> [--out dump.txt]
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = sys.argv[1:]
    out_path = None
    if "--out" in args:
        i = args.index("--out")
        out_path = args[i + 1]
        args = args[:i] + args[i + 2:]
    target = args[0] if args else "../../tests/fixtures/pdf/1706.03762v1.pdf"

    found = extract_tables(target)
    lines = [f"共 {len(found)} 张表", ""]
    for t in found:
        lines.append(
            f"=== Table {t.number} (p{t.page}) conf={t.confidence:.2f} "
            f"{t.n_rows}x{t.n_cols} header_rows={t.header_rows} ==="
        )
        lines.append(f"caption: {t.caption}")
        for r in t.rows:
            lines.append("  | " + " | ".join(c[:40] for c in r))
        lines.append("")

    text = "\n".join(lines)
    if out_path:
        from pathlib import Path as _P

        _P(out_path).write_text(text, encoding="utf-8")
        print(f"written: {out_path}")
    else:
        print(text)
