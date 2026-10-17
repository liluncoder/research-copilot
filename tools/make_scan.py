"""把矢量 PDF 光栅化成"无文本层的图片 PDF" —— J3 开发期的替代品生成器。

为什么要它：J3 判据要验"扫描件 OCR"，但官方那份 `1706.03762v1_img.pdf`
要等组委会发。没有输入就没法开发，所以先用官方同一篇论文造一个**功能等价**的替代件：
每页渲染成图片、重新装回 PDF ⇒ 文件里一个字都没有，只剩像素。
官方件到手后直接换输入即可，代码一行不用改。

用法：
    python tools/make_scan.py                      # v1 → 替代扫描件
    python tools/make_scan.py <源.pdf> <输出.pdf> [dpi]

★生成的替代件不进仓库（体积大且可随时重建），见 .gitignore 的 `*_local.pdf`。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = ROOT / "tests" / "fixtures" / "pdf" / "1706.03762v1.pdf"
DEFAULT_OUT = ROOT / "tests" / "fixtures" / "pdf" / "1706.03762v1_img_local.pdf"


def rasterize(src: Path, out_path: Path, dpi: int = 200) -> None:
    src_doc = pymupdf.open(src)
    out_doc = pymupdf.open()
    for page in src_doc:
        # 灰度 + 200dpi：接近真实扫描件的质量，又不至于让文件大得离谱
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        new_page = out_doc.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, pixmap=pix)
    out_doc.set_metadata({"title": f"{src.stem} (rasterized scan substitute)"})
    out_doc.save(out_path, deflate=True)
    out_doc.close()
    src_doc.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    src = Path(args[0]) if args else DEFAULT_SRC
    out_path = Path(args[1]) if len(args) > 1 else DEFAULT_OUT
    dpi = int(args[2]) if len(args) > 2 else 200

    if not src.exists():
        print(f"✗ 找不到源文件：{src}")
        return 2

    rasterize(src, out_path, dpi)

    # 自检：新文件必须"一个字都抽不出来"，否则不算扫描件
    doc = pymupdf.open(out_path)
    text_chars = sum(len(p.get_text().strip()) for p in doc)
    pages = doc.page_count
    doc.close()

    print(f"源文件      : {src.name}  ({src.stat().st_size / 1024 / 1024:.2f} MB)")
    print(f"替代扫描件  : {out_path}  ({out_path.stat().st_size / 1024 / 1024:.2f} MB)")
    print(f"页数        : {pages}     DPI: {dpi}")
    print(f"可抽出字符  : {text_chars}")
    if text_chars == 0:
        print("\n✓ 已无文本层 —— 功能上等价于扫描件，可作为 J3 的输入")
        return 0
    print("\n✗ 仍能抽出文字，说明没有真正光栅化")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
