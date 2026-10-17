"""把矢量 PDF 转成"无文本层"的扫描件 PDF（J3 扫描件判据的测试样本）。

★原理：渲染成图 → 图像重新封装为 PDF ⇒ 新 PDF 只有图像、没有文本层。
官方 `1706.03762v1_img.pdf` 未到手前，这就是等价替身；
到手后直接替换，判据逻辑一字不改。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf


def make_scanned(src: Path, out: Path, *, dpi: int = 200, pages: int | None = None) -> int:
    s = pymupdf.open(src)
    d = pymupdf.open()
    n = s.page_count if pages is None else min(pages, s.page_count)
    for i in range(n):
        page = s.load_page(i)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72))
        img_bytes = pix.tobytes("png")
        new_page = d.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=img_bytes)
        del pix, page
    d.save(out, garbage=4, deflate=True)
    d.close()
    s.close()
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=Path("tests/fixtures/pdf/1706.03762v1.pdf"))
    ap.add_argument("--out", type=Path, default=Path("tests/fixtures/pdf/1706.03762v1_img.pdf"))
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--pages", type=int, default=3, help="只取前 N 页（OCR 慢，判据够用）")
    a = ap.parse_args()
    n = make_scanned(a.src, a.out, dpi=a.dpi, pages=a.pages)
    print(f"built scanned PDF: {a.out}  pages={n}  size={a.out.stat().st_size/1024/1024:.1f} MB")

    # 自检：确认新 PDF 真的没有文本层
    with pymupdf.open(a.out) as chk:
        chars = sum(len(chk.load_page(i).get_text("text").strip()) for i in range(chk.page_count))
    print(f"self-check: 文本层字符数 = {chars}  (应为 0 或极小)")


if __name__ == "__main__":
    main()
