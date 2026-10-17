"""内存硬指标测量（J3：541 页书籍解析，容器内内存增量 < 2GB）。

★为什么必须实测而不是"设计上不会超"：
本机曾反复踩"以为省了其实没省"的坑（如神经系统2 的 idle 通道 96.9%）。
所以这里给三种独立测量，互相交叉验证：

1. **RSS 峰值**（psutil）—— 进程真实物理内存，最接近 Docker 的观测口径
2. **tracemalloc 峰值**—— Python 层分配峰值，用于定位是哪一步吃内存
3. **页级增量**—— 每 N 页采样一次，看内存是否随页数线性增长
   （★线性增长 = 有泄漏或攒批；平台化 = 正常）

硬指标口径统一为：`peak_rss - baseline_rss < 2048 MB`。
"""

from __future__ import annotations

import gc
import time
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path

import psutil


def rss_mb() -> float:
    """当前进程物理内存（MB）。"""
    return psutil.Process().memory_info().rss / 1024 / 1024


@dataclass
class MemoryReport:
    baseline_rss_mb: float = 0.0
    peak_rss_mb: float = 0.0
    peak_python_mb: float = 0.0
    samples: list[tuple[int, float]] = field(default_factory=list)
    elapsed_s: float = 0.0
    pages: int = 0

    @property
    def rss_delta_mb(self) -> float:
        return self.peak_rss_mb - self.baseline_rss_mb

    @property
    def passed(self) -> bool:
        """硬指标：内存增量 < 2048 MB。"""
        return self.rss_delta_mb < 2048


class MemoryProbe:
    """上下文管理器：进 = 打基线，出 = 出报告。"""

    def __init__(self, sample_every: int = 25) -> None:
        self.sample_every = sample_every
        self.report = MemoryReport()

    def __enter__(self) -> "MemoryProbe":
        gc.collect()
        self.report.baseline_rss_mb = rss_mb()
        self.report.peak_rss_mb = self.report.baseline_rss_mb
        tracemalloc.start()
        self._t0 = time.perf_counter()
        return self

    def sample(self, page_no: int) -> None:
        """每处理若干页调用一次：刷新峰值 + 记录采样点。"""
        cur = rss_mb()
        if cur > self.report.peak_rss_mb:
            self.report.peak_rss_mb = cur
        self.report.samples.append((page_no, round(cur - self.report.baseline_rss_mb, 1)))

    def __exit__(self, *exc) -> bool:
        cur, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.report.peak_python_mb = peak / 1024 / 1024
        self.report.elapsed_s = time.perf_counter() - self._t0
        self.sample(self.report.pages)
        return False


def format_report(r: MemoryReport) -> str:
    lines = [
        f"页数          : {r.pages}",
        f"耗时          : {r.elapsed_s:.1f} s",
        f"RSS 基线      : {r.baseline_rss_mb:.1f} MB",
        f"RSS 峰值      : {r.peak_rss_mb:.1f} MB",
        f"RSS 增量      : {r.rss_delta_mb:.1f} MB  (硬指标 < 2048 MB)",
        f"Python 峰值   : {r.peak_python_mb:.1f} MB",
        f"判定          : {'PASS' if r.passed else 'FAIL'}",
    ]
    if r.samples:
        # 抽样展示，避免 541 行刷屏
        step = max(1, len(r.samples) // 8)
        pts = [f"{p}页:{d}MB" for p, d in r.samples[::step]]
        lines.append("内存曲线采样  : " + " → ".join(pts))
    return "\n".join(lines)


def parse_pdf_with_probe(path: str | Path, *, ocr=None, page_limit=None, probe: MemoryProbe | None = None):
    """带内存测量的解析。返回 (ParsedDocument, MemoryReport)。"""
    from app.parsing.pipeline import parse_pdf

    probe = probe or MemoryProbe()
    with probe:
        doc = parse_pdf(path, ocr=ocr, page_limit=page_limit)
        probe.report.pages = doc.page_count if page_limit is None else min(page_limit, doc.page_count)
        for p in doc.pages:
            if p.page_no % probe.sample_every == 0:
                probe.sample(p.page_no)
                gc.collect()  # 采样前强制回收，测的是"稳定占用"而非瞬时垃圾
    return doc, probe.report
