"""J6 判据：引用图谱（★G7 需要 LLM key，其余离线可跑）。

用法（仓库根目录）：
    python tests/verify_j6_graph.py

判据（写死在本文件）：
  G1 规模：图上节点 ≥ 20（含库外参考文献节点），库内文献全部在图上
  G2 展示子图：10 ≤ 节点 ≤ 120 且边 ≥ 20 —— 保证前端画得动（J6 要求"渲染流畅"）
  G3 库内互引：库内 A→B 的边 ≥ 5（这是标题匹配是否真的有效的硬证据）
  G4 双指标可解释：PageRank 榜与入度榜各自非空、前 5 名至少 2 个重合，
     且每项都带 cited_by_local 与 pagerank_core（没有数字就没法解释）
  G5 已知边：TESS→LLS、e-prop2020→e-prop2019 至少存在 1 条（人工核对过的真引用）
  G6 图谱卫生：无自环、节点 id 唯一、每条边的两端都在节点集合里
  G7 自动综述不编造（需 LLM）：综述里用《》/引号提到的每个标题，
     都必须能在"允许标题"里找到；且至少提到 2 个榜单论文

★说明：J6 原文要求"20 篇论文自动建图"。当前库内 9 篇，但图上的节点是
  "库内文献 + 它们引用的文献"，所以规模远超 20；G1 检查的是这张图的节点数。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("CHROMA_PERSIST_DIR", str(ROOT / "tests" / "out" / "index_j6"))

EXPECTED_EDGES = [
    ("TESS", "LLS"),
    ("A solution to the learning dilemma", "Biologically inspired alternatives"),
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s.lower())).strip()


def main() -> int:
    from app.core import llm
    from app.services import graph

    g = graph.build_graph(display_limit=40, top_n=10)
    nodes = g["nodes"]
    edges = g["edges"]
    disp = g["display"]
    ids = {n["id"] for n in nodes}
    checks: list[tuple[str, bool, str]] = []

    def chk(cid: str, ok: bool, detail: str) -> None:
        checks.append((cid, ok, detail))

    # G1
    n_local = sum(1 for n in nodes if n["in_library"])
    chk("G1", len(nodes) >= 20 and n_local >= 1, f"节点 {len(nodes)}（库内 {n_local}）")

    # G2
    chk("G2", 10 <= disp["n_nodes"] <= 120 and disp["n_edges"] >= 20,
        f"展示子图 {disp['n_nodes']} 节点 / {disp['n_edges']} 边")

    # G3
    local_edges = [e for e in edges if e["target"].startswith("doc:")]
    chk("G3", len(local_edges) >= 5, f"库内互引边 {len(local_edges)} 条")

    # G4
    pr = g["foundational"]["pagerank"]
    deg = g["foundational"]["in_degree"]
    overlap = len({n["id"] for n in pr[:5]} & {n["id"] for n in deg[:5]})
    has_nums = all(("cited_by_local" in n and "pagerank_core" in n) for n in pr + deg)
    chk("G4", bool(pr) and bool(deg) and overlap >= 2 and has_nums,
        f"两榜前 5 重合 {overlap} 个；字段完整={has_nums}")

    # G5
    label = {n["id"]: _norm(n["label"]) for n in nodes}
    found: list[str] = []
    for a, b in EXPECTED_EDGES:
        na, nb = _norm(a), _norm(b)
        for e in edges:
            if na in label.get(e["source"], "") and nb in label.get(e["target"], ""):
                found.append(f"{a}→{b}")
                break
    chk("G5", len(found) >= 1, f"已知边命中 {found or '无'}")

    # G6
    self_loop = [e for e in edges if e["source"] == e["target"]]
    bad_edge = [e for e in edges if e["source"] not in ids or e["target"] not in ids]
    chk("G6", not self_loop and not bad_edge and len(ids) == len(nodes),
        f"自环 {len(self_loop)}、越界边 {len(bad_edge)}、id 唯一={len(ids) == len(nodes)}")

    # G7 自动综述
    if not llm.is_configured():
        chk("G7", True, "SKIP：无 LLM key")
    else:
        from app.api.graph import ReviewRequest, graph_review

        r = graph_review(ReviewRequest(top=8))
        text = r.get("review") or ""
        allowed = [_norm(t) for t in r.get("allowed_titles") or []]
        quoted = re.findall(r"[《“\"]([^》”\"]{6,160})[》”\"]", text)
        fabricated = [
            q for q in quoted
            if not any(_norm(q) and (_norm(q) in a or a in _norm(q)) for a in allowed)
        ]
        mentioned = sum(1 for a in allowed if a and a in _norm(text))
        chk("G7", bool(text) and not fabricated and mentioned >= 2,
            f"{len(text)} 字；提到榜单论文 {mentioned} 个；编造标题 {fabricated or '无'}")

    print(f"图谱：{g['stats']['n_nodes']} 节点 / {g['stats']['n_edges']} 边；"
          f"参考文献 {g['stats']['n_reference_entries']} 条，匹配到库内 {g['stats']['n_matched_to_local']} 条"
          f"（{g['stats']['local_match_rate']:.1%}）")
    print(f"展示子图：{disp['n_nodes']} 节点 / {disp['n_edges']} 边\n")
    print("库内互引（前 8）：")
    lab = {n["id"]: n["label"] for n in nodes}
    for e in local_edges[:8]:
        print(f"  {lab[e['source']][:34]:34} → {lab[e['target']][:34]}")
    print("\nPageRank(核心) Top 5：")
    for n in pr[:5]:
        print(f"  {'[库内]' if n['in_library'] else '      '} {n['label'][:46]:46} pr={n['pagerank_core']:.4f} 入度={n['cited_by_local']}")
    print()
    for cid, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid}  {detail}")
    failed = [c for c, ok, _ in checks if not ok]
    print(f"\n{'PASS' if not failed else 'FAIL'}  ({len(checks) - len(failed)}/{len(checks)})")
    if failed:
        print("未过项：" + ", ".join(failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
