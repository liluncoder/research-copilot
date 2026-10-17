"""J3-b 内存判据：541 页真实大 PDF（不是 loop 模拟）。

★两种负载都测，取更严的结果：
  1. 92.7MB / 541 页（v1 循环拼成的重样本，比真实 UDL 更重）
  2. 若 UDL 到手，直接换源即可（--pdf 指定）

口径：peak_rss - baseline_rss < 2048 MB，且曲线非线性增长。
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path

# ★让脚本从任何目录、任何方式调用都能 import app（不依赖 PYTHONPATH 环境变量）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.parsing.memory import MemoryProbe
from app.parsing.pipeline import iter_text_chunks, parse_pdf


def run(pdf: Path, sample_every: int = 50) -> dict:
    probe = MemoryProbe(sample_every=sample_every)
    chunks = 0
    chunk_chars = 0
    with probe:
        doc = parse_pdf(pdf)
        probe.report.pages = doc.page_count
        for _ in iter_text_chunks(doc):
            chunks += 1
        # 关键：解析完 + 切块完再看内存（切块是最容易攒内存的环节）
        gc.collect()
        probe.sample(doc.page_count)

    r = probe.report
    return {
        "file": pdf.name,
        "size_mb": round(pdf.stat().st_size / 1024 / 1024, 1),
        "pages": r.pages,
        "chunks": chunks,
        "baseline_mb": round(r.baseline_rss_mb, 1),
        "peak_mb": round(r.peak_rss_mb, 1),
        "delta_mb": round(r.rss_delta_mb, 1),
        "elapsed_s": round(r.elapsed_s, 1),
        "passed_2gb": r.passed,
        "samples": r.samples,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args()

    root = Path(__file__).resolve().parents[2]
    pdf = a.pdf or root / "tests" / "fixtures" / "pdf" / "_synthetic_541p.pdf"
    if not pdf.exists():
        print(f"缺文件: {pdf}")
        return 2

    res = run(pdf)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if res["passed_2gb"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
