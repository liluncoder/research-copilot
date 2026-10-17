"""解析管线 CLI —— 判据复跑入口。

用法（backend 目录下）：
    python -m app.parsing.cli tests/fixtures/pdf/1706.03762v1.pdf
    python -m app.parsing.cli <某书.pdf> --probe --limit 541 --json out.json
    python -m app.parsing.cli <扫描件.pdf> --ocr

★为什么要有 CLI：`路线/04` 纪律 3 要求"判据要能复跑，评委 clone 后能自己复现"。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PDF 解析管线")
    ap.add_argument("pdf", type=Path, help="PDF 路径")
    ap.add_argument("--ocr", action="store_true", help="启用 OCR 分支（扫描件必需）")
    ap.add_argument("--ocr-lang", default="ch", help="OCR 语言，默认 ch")
    ap.add_argument("--limit", type=int, default=None, help="只解析前 N 页（调试用）")
    ap.add_argument("--probe", action="store_true", help="测量内存（J3 硬指标）")
    ap.add_argument("--json", type=Path, default=None, help="结构化结果输出路径")
    ap.add_argument("--dump-text", type=Path, default=None, help="全文导出路径")
    args = ap.parse_args(argv)

    if not args.pdf.exists():
        print(f"❌ 文件不存在: {args.pdf}", file=sys.stderr)
        return 2

    ocr = None
    if args.ocr:
        from app.parsing.ocr import PaddleOcrEngine

        ocr = PaddleOcrEngine(lang=args.ocr_lang)

    if args.probe:
        from app.parsing.memory import format_report, parse_pdf_with_probe

        doc, report = parse_pdf_with_probe(args.pdf, ocr=ocr, page_limit=args.limit)
        print(format_report(report))
    else:
        from app.parsing.pipeline import parse_pdf

        doc = parse_pdf(args.pdf, ocr=ocr, page_limit=args.limit)

    scanned = doc.scanned_pages
    print(f"文件       : {doc.source.name}")
    print(f"页数       : {doc.page_count}")
    print(f"总字符数   : {doc.total_chars}")
    print(f"扫描页数   : {len(scanned)}  {'(前10: ' + str(scanned[:10]) + ')' if scanned else ''}")
    print(f"标题       : {(doc.metadata.get('title') or '').strip()[:80]}")
    print(f"作者       : {(doc.metadata.get('author') or '').strip()[:80]}")

    if args.json:
        payload = {
            "source": str(doc.source),
            "page_count": doc.page_count,
            "total_chars": doc.total_chars,
            "scanned_pages": scanned,
            "metadata": doc.metadata,
            "pages": [
                {
                    "page_no": p.page_no,
                    "chars": p.char_count,
                    "is_scanned": p.is_scanned,
                    "ocr_used": p.ocr_used,
                    "preview": p.text[:120],
                }
                for p in doc.pages
            ],
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON       : {args.json}")

    if args.dump_text:
        args.dump_text.parent.mkdir(parents=True, exist_ok=True)
        args.dump_text.write_text(doc.full_text, encoding="utf-8")
        print(f"全文       : {args.dump_text}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
