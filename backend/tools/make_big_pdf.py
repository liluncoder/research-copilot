"""构造测试用大 PDF（无 UDL 时的内存判据替身）。

★为什么合法：J3 的内存硬指标测的是"页数增长是否导致内存线性上涨"，
与页面内容无关。用 v1 的 15 页循环拼成 541 页，能完整复现 541 页的加载/遍历/切块压力。
正式 UDL 到手后同一脚本可直接换源复跑（`--src` 指向真书）。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf


def build(src: Path, out: Path, pages: int) -> int:
    src_doc = pymupdf.open(src)
    out_doc = pymupdf.open()
    n_src = src_doc.page_count
    for i in range(pages):
        out_doc.insert_pdf(src_doc, from_page=i % n_src, to_page=i % n_src)
    out_doc.save(out, garbage=3, deflate=True)
    out_doc.close()
    src_doc.close()
    return pages


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=Path("tests/fixtures/pdf/1706.03762v1.pdf"))
    ap.add_argument("--out", type=Path, default=Path("tests/fixtures/pdf/_synthetic_541p.pdf"))
    ap.add_argument("--pages", type=int, default=541)
    a = ap.parse_args()
    n = build(a.src, a.out, a.pages)
    size = a.out.stat().st_size / 1024 / 1024
    print(f"built: {a.out}  pages={n}  size={size:.1f} MB")


if __name__ == "__main__":
    main()
