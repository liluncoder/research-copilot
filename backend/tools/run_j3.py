"""J3 判据复跑脚本 —— 评委/自己一条命令验证扫描件 OCR + 内存硬指标。

用法（backend 目录下）：
    PYTHONIOENCODING=utf-8 PYTHONPATH=. python tools/run_j3.py           # 跑全部
    PYTHONIOENCODING=utf-8 PYTHONPATH=. python tools/run_j3.py --j3a     # 只跑 OCR
    PYTHONIOENCODING=utf-8 PYTHONPATH=. python tools/run_j3.py --j3b     # 只跑内存

★判据定义见 路线/04 §三，本脚本是它的可执行形式。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

FIX = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pdf"
OUT = Path(__file__).resolve().parents[2] / "tests" / "out"

KEYWORDS = ["Attention", "Transformer", "BLEU"]


def j3a_scanned_ocr() -> dict:
    """J3-a：扫描件必须走 OCR 且抽出正文。"""
    from app.parsing.ocr import PaddleOcrEngine
    from app.parsing.pipeline import parse_pdf

    target = FIX / "1706.03762v1_img.pdf"
    if not target.exists():
        return {"judge": "J3-a", "status": "SKIP", "reason": f"缺文件 {target.name}"}

    t0 = time.perf_counter()
    doc = parse_pdf(target, ocr=PaddleOcrEngine())
    elapsed = time.perf_counter() - t0

    per_page = [(p.page_no, p.char_count, p.is_scanned, p.ocr_used) for p in doc.pages]
    all_scanned = all(p.is_scanned for p in doc.pages)
    all_ocr = all(p.ocr_used for p in doc.pages)
    min_chars = min((p.char_count for p in doc.pages), default=0)
    hit = [k for k in KEYWORDS if k.lower() in doc.full_text.lower()]

    checks = {
        "每页判为 scanned": all_scanned,
        "每页走 OCR": all_ocr,
        "每页字符数 > 500": min_chars > 500,
        "关键词命中 >= 2": len(hit) >= 2,
    }
    passed = all(checks.values())
    return {
        "judge": "J3-a",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "per_page": per_page,
        "keywords_hit": hit,
        "elapsed_s": round(elapsed, 1),
        "per_page_s": round(elapsed / max(len(doc.pages), 1), 1),
        "note_perf": "性能为记录项（沙箱限 CPU，非判据；见 路线/04 §三 J3-a）",
        "chars": doc.total_chars,
        "preview": doc.full_text[:300],
    }


def j3a_negative() -> dict:
    """J3-a 反向条件：矢量 PDF 必须 0 页被判 scanned（防"全都送去 OCR"的假通过）。"""
    from app.parsing.pipeline import parse_pdf

    target = FIX / "1706.03762v1.pdf"
    if not target.exists():
        return {"judge": "J3-a-neg", "status": "SKIP", "reason": "缺矢量 v1"}
    doc = parse_pdf(target)
    scanned = doc.scanned_pages
    return {
        "judge": "J3-a-neg",
        "status": "PASS" if not scanned else "FAIL",
        "scanned_pages": scanned,
        "expect": "0 页",
    }


def j3b_memory() -> dict:
    """J3-b：541 页级负载，RSS 增量 < 2048 MB 且曲线平台化。"""
    from app.parsing.memory import MemoryProbe, rss_mb
    from app.parsing.pipeline import parse_pdf

    big = FIX / "_synthetic_541p.pdf"
    src = FIX / "1706.03762v1.pdf"

    probe = MemoryProbe(sample_every=25)
    with probe:
        if big.exists() and big.stat().st_size > 100_000:
            doc = parse_pdf(big)
            probe.report.pages = doc.page_count
            probe.sample(doc.page_count)
            mode = f"真实大 PDF（{big.name}）"
            del doc
        else:
            # 合成压力：反复解析，总页数达到 541 以上
            base = rss_mb()
            total, rounds = 0, 0
            while total < 541:
                d = parse_pdf(src)
                total += d.page_count
                rounds += 1
                probe.report.pages = total
                if rounds % 10 == 0:
                    probe.sample(total)
                del d
            mode = f"合成压力（{src.name} × {rounds} 轮 = {total} 页）"

    r = probe.report
    samples = [d for _, d in r.samples]
    # 线性判定：后半段增量 > 前半段增量 * 2 ⇒ 视为线性增长（泄漏信号）
    linear = False
    if len(samples) >= 4:
        mid = len(samples) // 2
        first = samples[mid] - samples[0]
        second = samples[-1] - samples[mid]
        linear = second > max(first, 0.5) * 2 and second > 5

    checks = {
        "RSS 增量 < 2048 MB": r.passed,
        "曲线非线增长": not linear,
    }
    return {
        "judge": "J3-b",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "mode": mode,
        "pages": r.pages,
        "baseline_mb": round(r.baseline_rss_mb, 1),
        "peak_mb": round(r.peak_rss_mb, 1),
        "delta_mb": round(r.rss_delta_mb, 1),
        "elapsed_s": round(r.elapsed_s, 1),
        "samples": r.samples,
        "checks": checks,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--j3a", action="store_true")
    ap.add_argument("--j3b", action="store_true")
    ap.add_argument("--json", type=Path, default=OUT / "j3_report.json")
    a = ap.parse_args()
    run_all = not (a.j3a or a.j3b)

    results = []
    if run_all or a.j3a:
        print("=" * 60)
        print("J3-a 扫描件 OCR（首次运行会下载模型，约 1-3 分钟）")
        print("=" * 60)
        results.append(j3a_scanned_ocr())
        results.append(j3a_negative())
    if run_all or a.j3b:
        print("=" * 60)
        print("J3-b 541 页内存硬指标")
        print("=" * 60)
        results.append(j3b_memory())

    for r in results:
        print(f"\n[{r['judge']}] {r['status']}")
        for k, v in r.items():
            if k in ("judge", "status", "preview"):
                continue
            print(f"  {k}: {v}")

    a.json.parent.mkdir(parents=True, exist_ok=True)
    a.json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已存: {a.json}")

    return 0 if all(r["status"] == "PASS" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
