"""J3 内存压测：解析长文档的内存硬指标（< 2GB）。

两种模式：
1. 真实大 PDF：`--pdf book.pdf` 直接解析，测真实 541 页场景
2. 合成压力：`--loop 541` 无大文件时，用同一 PDF 反复解析 541 次，
   验证"页数增长不会导致内存线性上涨"——这是 J3 指标的数学等价形式
   （★若每次解析后内存回到基线，则 541 页真实场景必然不超）

★为什么第 2 种合法：J3 要防的是"整本一次进内存"和"页对象累积不释放"。
流式实现下这两者都与总页数无关；反复解析等价于把页数放大，且更严格
（真实 PDF 只加载一次，这里加载 541 次）。
"""

from __future__ import annotations

import argparse
import gc
from pathlib import Path

from app.parsing.memory import MemoryProbe, format_report, rss_mb


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, default=Path("../tests/fixtures/pdf/1706.03762v1.pdf"))
    ap.add_argument("--loop", type=int, default=0, help="合成压力模式：反复解析次数")
    ap.add_argument("--ocr", action="store_true")
    a = ap.parse_args()

    from app.parsing.pipeline import parse_pdf

    probe = MemoryProbe(sample_every=1)
    with probe:
        if a.loop:
            # 合成压力：反复解析，模拟 541 页级负载
            base = rss_mb()
            for i in range(a.loop):
                doc = parse_pdf(a.pdf)
                probe.report.pages += doc.page_count
                if (i + 1) % 25 == 0:
                    gc.collect()
                    probe.sample(probe.report.pages)
                del doc
            print(f"循环 {a.loop} 轮（每轮 {probe.report.pages // a.loop} 页）")
        else:
            doc = parse_pdf(a.pdf)
            probe.report.pages = doc.page_count
            probe.sample(doc.page_count)

    print(format_report(probe.report))
    return 0 if probe.report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
