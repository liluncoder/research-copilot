"""OCR 引擎速度对比：PaddleOCR(no-mkldnn) vs RapidOCR(onnxruntime)。

★背景：J3-a 用 PaddleOCR 关了 mkldnn 后 2 页跑 589.7 s，超 120 s 判据。
本脚本只测**单页**，用来定"哪个引擎做主"。
"""

from __future__ import annotations

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


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    pdf = root / "tests" / "fixtures" / "pdf" / "1706.03762v1_img.pdf"

    print("=" * 56)
    print("RapidOCR (onnxruntime CPU)")
    print("=" * 56)
    from rapidocr_onnxruntime import RapidOCR

    t0 = time.perf_counter()
    engine = RapidOCR()
    print(f"  引擎初始化: {time.perf_counter() - t0:.1f}s")
    for dpi in (150, 200):
        img = render(pdf, 0, dpi)
        t = time.perf_counter()
        result, _ = engine(img)
        dt = time.perf_counter() - t
        n = len(result) if result else 0
        sample = result[0][1] if result else ""
        print(f"  dpi={dpi}: {dt:6.1f}s  行数={n}  首行={str(sample)[:40]!r}  shape={img.shape}")
        del img


if __name__ == "__main__":
    main()
