"""OCR 性能基准：定位"2 页 590 秒"的根因。

假设与对应测法：
  H1 线程数未拉满   → 设 FLAGS_use_mkldnn=0 + 不同 cpu_threads 各跑一次
  H2 medium 模型太大 → 换 mobile/轻量模型同页对比
  H3 DPI 过高       → 同一页 200 / 150 / 120 dpi 对比

★只测单页，避免整轮跑 10 分钟。结论写进 report/J3_判词.md。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pymupdf


def render(pdf: Path, page_no: int, dpi: int) -> np.ndarray:
    with pymupdf.open(pdf) as d:
        p = d.load_page(page_no)
        pix = p.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72))
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            arr = arr[:, :, :3]
        return np.ascontiguousarray(arr)


def timed(fn, *a, **kw) -> tuple[float, object]:
    t = time.perf_counter()
    out = fn(*a, **kw)
    return time.perf_counter() - t, out


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    pdf = root / "tests" / "fixtures" / "pdf" / "1706.03762v1_img.pdf"

    print("=" * 60)
    print("H1/H3: 线程数与 DPI 扫描（固定 mkldnn=False）")
    print("=" * 60)
    for threads in (4, 8, 16):
        os.environ["CPU_NUM"] = str(threads)
        from paddleocr import PaddleOCR

        ocr = PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )
        for dpi in (150, 200):
            img = render(pdf, 0, dpi)
            dt, res = timed(lambda: list(ocr.predict(img)))
            n = len(res[0]["rec_texts"]) if res and "rec_texts" in res[0] else 0
            print(f"  threads={threads:2d} dpi={dpi}: {dt:7.1f}s  lines={n}  shape={img.shape}")
            del img
        del ocr
        break  # 先只测一组，看量级

    print("=" * 60)
    print("结论：若单页仍 > 60s，说明瓶颈在模型本身而非线程")
    print("=" * 60)


if __name__ == "__main__":
    main()
