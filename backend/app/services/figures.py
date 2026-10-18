"""S6 · 表格 → 图表 + 图注（J7）。

★★这一条判据的核心不是"能画图"，而是**结构性防幻觉**：
   LLM 看到的只有统计量（n / mean / std / min / max / 首末值 / 斜率），
   **看不到任何原始数据点**。所以它物理上无法编造"第 137 次试验突然下降"这种细节。
   判据 J7 会逐个核对：图注里出现的每个数字，必须能在统计量里找到。

为什么这比"提示词要求它别编"强：
   提示词是软约束，模型可以无视；数据隔离是硬约束，模型没有信息可编。
   技术文档里这一条要单独写（这是 S6 的设计亮点，与 J8 的 References 同源思路）。
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.core import llm

CAPTION_PROMPT = """你是科研写作助手，正在为一张图表写图注（caption）。

下面给出这张图的**统计量**（不是原始数据点）。请写 2~3 句中文图注：
1. 先描述趋势：用"首值 → 末值"或"斜率"说明总体走向
2. 再描述组间差异：用"均值 ± 标准差"对比各组
3. 句尾写明样本量，格式 `(n = 数字)`

硬性要求：
- **只能使用下面给出的数字**，不得出现任何未给出的数值（包括百分比、次数、p 值）
- 不解释机制、不推测原因、不谈显著性（数据里没有的东西一律不写）
- 不要写"这张图展示了"这类空话，直接说结论

【图表信息】
指标：{metric}
图形类型：{kind}
分组：{groups}

【统计量】
{stats}
"""


@dataclass
class FigureResult:
    stats: dict[str, Any]
    chart: dict[str, Any]
    caption: str = ""
    warnings: list[str] = field(default_factory=list)
    model: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "stats": self.stats,
            "chart": self.chart,
            "caption": self.caption,
            "warnings": self.warnings,
            "model": self.model,
        }


def _stats_of(series: pd.Series, x: pd.Series) -> dict[str, float]:
    vals = series.astype(float).to_numpy()
    xs = np.arange(len(vals), dtype=float)
    slope = 0.0
    if len(vals) >= 2:
        try:
            slope = float(np.polyfit(xs, vals, 1)[0])
        except Exception:  # noqa: BLE001
            slope = 0.0
    return {
        "n": int(len(vals)),
        "mean": round(float(np.mean(vals)), 4),
        "std": round(float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0, 4),
        "min": round(float(np.min(vals)), 4),
        "max": round(float(np.max(vals)), 4),
        "first": round(float(vals[0]), 4),
        "last": round(float(vals[-1]), 4),
        "slope": round(slope, 6),
    }


def analyze_table(
    *,
    content: bytes | str,
    filename: str = "data.csv",
    metric: str | None = None,
    group_by: str | None = None,
    kind: str = "line",
    max_points: int = 400,
) -> FigureResult:
    """CSV → 统计量 + ECharts 配置（+ 可选图注）。"""
    raw = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    df = pd.read_csv(io.StringIO(raw))
    if df.empty:
        raise ValueError("表格是空的")
    if len(df) > 200_000:
        raise ValueError("表格太大（>20 万行），请先聚合")

    # 选指标列：优先用户指定，否则第一个数值列
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    bool_cols = [c for c in df.columns if df[c].dtype == bool]
    if metric and metric in df.columns:
        y_col = metric
    elif numeric_cols:
        y_col = numeric_cols[0]
    elif bool_cols:
        y_col = bool_cols[0]
    else:
        raise ValueError(f"表里没有数值列（列名：{list(df.columns)[:8]}）")

    y = df[y_col]
    if y.dtype == bool:
        y = y.astype(int)

    groups: list[str] = []
    if group_by and group_by in df.columns:
        groups = [str(g) for g in df[group_by].dropna().unique()][:8]
    else:
        group_by = None

    stats: dict[str, Any] = {"metric": y_col, "n_rows": int(len(df)), "groups": {}}
    chart_series: list[dict[str, Any]] = []
    x_axis: list[Any] = []

    if group_by:
        longest = 0
        for g in groups:
            sub = df[df[group_by].astype(str) == g]
            ys = sub[y_col].astype(float)
            stats["groups"][g] = _stats_of(ys, sub.index.to_series())
            longest = max(longest, len(ys))
        x_axis = list(range(longest))
        for g in groups:
            sub = df[df[group_by].astype(str) == g][y_col].astype(float)
            chart_series.append(
                {
                    "name": g,
                    "type": kind,
                    "showSymbol": False,
                    "smooth": kind == "line",
                    "data": [round(float(v), 4) for v in sub.to_list()[:max_points]],
                }
            )
        # 组间整体统计（供图注使用）
        all_vals = df[y_col].astype(float)
        stats["overall"] = _stats_of(all_vals, df.index.to_series())
    else:
        ys = y.astype(float)
        stats["overall"] = _stats_of(ys, df.index.to_series())
        chart_series.append(
            {
                "name": y_col,
                "type": kind,
                "showSymbol": False,
                "smooth": kind == "line",
                "data": [round(float(v), 4) for v in ys.to_list()[:max_points]],
            }
        )
        x_axis = list(range(min(len(ys), max_points)))

    chart = {
        "title": {"text": f"{y_col} over {'trial' if 'trial' in df.columns else 'index'}", "left": "center"},
        "tooltip": {"trigger": "axis"},
        "legend": {"show": bool(group_by), "bottom": 0},
        "grid": {"left": 48, "right": 24, "top": 48, "bottom": 40},
        "xAxis": {"type": "category", "data": x_axis, "name": "index"},
        "yAxis": {"type": "value", "name": y_col},
        "series": chart_series,
    }

    warnings: list[str] = []
    if group_by and len(groups) > 6:
        warnings.append(f"分组数 {len(groups)} 较多，图例可能拥挤")
    if len(df) > max_points:
        warnings.append(f"原始 {len(df)} 行，图上仅绘制前 {max_points} 点（统计量按全量算）")

    res = FigureResult(stats=stats, chart=chart, warnings=warnings)
    res.caption, res.model = _make_caption(stats, y_col, kind, groups)
    return res


def _make_caption(stats: dict[str, Any], metric: str, kind: str, groups: list[str]) -> tuple[str, str | None]:
    """只把统计量交给 LLM。"""
    if not llm.is_configured():
        return "", None
    prompt = CAPTION_PROMPT.format(
        metric=metric,
        kind=kind,
        groups="、".join(groups) if groups else "无",
        stats=json.dumps(stats, ensure_ascii=False, indent=2),
    )
    try:
        reply = llm.chat([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=320)
        return reply.text.strip(), reply.model
    except Exception:  # noqa: BLE001
        return "", None


def numbers_in(text: str) -> list[float]:
    """抽出文本里的数字（判据用）：把 0.42 / 1,024 / -3.5 / 12% 都抓出来。"""
    import re

    out: list[float] = []
    for m in re.finditer(r"-?\d+(?:[.,]\d+)?", text):
        s = m.group(0).replace(",", "")
        try:
            out.append(float(s))
        except ValueError:
            continue
    return out


def numbers_in_stats(stats: dict[str, Any]) -> list[float]:
    """把统计量摊平成数字列表（判据用）。"""
    out: list[float] = []
    for block in [stats.get("overall") or {}] + list((stats.get("groups") or {}).values()):
        for v in block.values():
            if isinstance(v, (int, float)):
                out.append(float(v))
    out.append(float(stats.get("n_rows") or 0))
    return out
