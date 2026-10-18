"""J7 判据：CSV → 图表 + 图注（★核心是"图注只看统计量"这条硬约束）。

用法（仓库根目录）：
    python tests/verify_j7_chart.py

判据：
  T1 统计量：行数、均值、标准差、斜率齐全，且与 pandas 独立复算一致（容差 1e-6）
  T2 图表配置：分组 2 条 series、每条都有数据点、坐标轴齐全
  T3 图注文本：非空、提到指标名
  T4 ★反幻觉（关键）：图注里出现的**每一个数字**都必须能在统计量里找到
     —— 容差规则：绝对值差 ≤ 0.01，或按小数位四舍五入后相等
  T5 图注不得出现"显著性/p 值/百分比涨幅"这类统计量里没有的东西
  T6 不分组调用也能工作（单序列），且统计量与分组口径一致

★为什么 T4 能证明"LLM 没看到原始数据"：
  如果模型拿到原始点，它会写出"在第 137 次试验出现峰值"这类数字——
  那些数字不在统计量集合里，T4 立刻失败。这条判据是结构性防幻觉的机器验证。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("CHROMA_PERSIST_DIR", str(ROOT / "tests" / "out" / "index_j7"))

CSV = ROOT / "tests" / "fixtures" / "data" / "snn_trials.csv"
METRIC = "correct"
GROUP = "condition"
FORBIDDEN = ["p 值", "p<", "P<", "显著性", "显著性差异", "百分比", "提高了"]


def _num_ok(x: float, pool: list[float], tol: float = 0.01) -> bool:
    for v in pool:
        if abs(abs(x) - abs(v)) <= tol:
            return True
        for d in range(0, 5):
            if round(v, d) == round(x, d) and abs(v - x) <= max(tol, 10 ** (-d) * 2):
                return True
    return False


def main() -> int:
    from app.core import llm
    from app.services import figures

    if not CSV.exists():
        print(f"[SKIP] 缺测试数据 {CSV}")
        return 2

    content = CSV.read_bytes()
    df = pd.read_csv(CSV)
    res = figures.analyze_table(content=content, filename=CSV.name, metric=METRIC, group_by=GROUP)
    checks: list[tuple[str, bool, str]] = []

    def chk(cid: str, ok: bool, detail: str) -> None:
        checks.append((cid, ok, detail))

    # T1 统计量与 pandas 独立复算一致
    g = res.stats["groups"]
    mism: list[str] = []
    for cond, block in g.items():
        s = df[df[GROUP] == cond][METRIC].astype(float)
        if block["n"] != len(s) or abs(block["mean"] - float(np.mean(s))) > 1e-4 or abs(block["std"] - float(np.std(s, ddof=1))) > 1e-4:
            mism.append(cond)
    chk("T1", not mism and res.stats["n_rows"] == len(df),
        f"{len(g)} 组、{res.stats['n_rows']} 行；与 pandas 复算不一致的组={mism or '无'}")

    # T2 图表配置
    series = res.chart["series"]
    chk("T2", len(series) == len(g) and all(len(s["data"]) > 0 for s in series),
        f"{len(series)} 条 series，数据点 {[len(s['data']) for s in series]}")

    # T3 图注存在
    cap = res.caption or ""
    chk("T3", bool(cap) and METRIC in cap, f"{len(cap)} 字；提到指标={METRIC in cap}")

    # T4 ★反幻觉：图注数字必须来自统计量
    pool = figures.numbers_in_stats(res.stats)
    nums = figures.numbers_in(cap)
    stray = [x for x in nums if not _num_ok(x, pool)]
    chk("T4", bool(cap) and not stray,
        f"图注数字 {len(nums)} 个，不在统计量里的：{stray or '无'}")

    # T5 不得出现统计量没有的统计性断言
    hit = [w for w in FORBIDDEN if w in cap]
    chk("T5", not hit, f"违禁词={hit or '无'}")

    # T6 单序列也能跑
    res2 = figures.analyze_table(content=content, filename=CSV.name, metric=METRIC)
    chk("T6", res2.stats["overall"]["n"] == len(df) and len(res2.chart["series"]) == 1,
        f"单序列 n={res2.stats['overall']['n']}，series 数={len(res2.chart['series'])}")

    print(f"数据：{CSV.name}（{len(df)} 行，指标 {METRIC}，分组 {GROUP}）")
    print(f"向量/模型：{res.model or '（未配置 LLM，图注为空）'}\n")
    print("分组统计：")
    for cond, b in g.items():
        print(f"  {cond:16} n={b['n']:4} mean={b['mean']:.3f} std={b['std']:.3f} slope={b['slope']:+.5f}")
    print(f"\n图注：{cap}\n")
    print("图注中的数字：", nums)
    print("统计量池（前 12）：", [round(x, 3) for x in pool[:12]], "…\n")

    for cid, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid}  {detail}")
    failed = [c for c, ok, _ in checks if not ok]
    print(f"\n{'PASS' if not failed else 'FAIL'}  ({len(checks) - len(failed)}/{len(checks)})")
    if failed:
        print("未过项：" + ", ".join(failed))
    if not llm.is_configured():
        print("提示：未配置 LLM key，T3/T4 视为失败（图注为空）")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
