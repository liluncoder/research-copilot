"""S5 · 引用知识图谱（J6）。

三件事：
1. **建图**：库内文献 → 它引用的每条参考文献。参考文献按"标题规范化"去重，
   所以同一篇经典工作被多篇论文引用时，会合并成一个节点、入度累加（这才是"基石论文"的信号）。
2. **基石挖掘**：PageRank + 入度中心性双指标（对应评分细则原文的 PageRank/Centrality），
   并给出"为什么它是基石"的可解释依据（被几篇本库论文引用、是否在库内）。
3. **匹配率**：参考文献与库内论文做标题匹配；匹配上的边目标指向库内节点，
   这样图上能看出"我这 9 篇之间谁引了谁"。

★标题匹配为什么用"规范化子串"而不是纯模糊相似度：
  参考文献原文是 `Vaswani, A., et al. Attention is all you need. NIPS 2017.`，
  库内标题是 `Attention Is All You Need`。规范化（小写、去标点、压空格）后
  前者包含后者 —— 这种包含关系比 difflib 分数更可靠，也不会被作者名干扰。
  仅当包含失败时才退到 difflib（阈值 0.86，宁严不宽）。
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from app.core import storage

STOP = {
    "a", "an", "the", "of", "for", "and", "to", "in", "on", "with", "by", "from",
    "is", "are", "as", "at", "via", "using", "towards", "toward", "into",
}



def pagerank_simple(g: nx.DiGraph, alpha: float = 0.85, tol: float = 1e-10, max_iter: int = 200) -> dict[str, float]:
    """Power-iteration PageRank。

    ★为什么不用 `nx.pagerank`：它会去 import scipy（~40MB），而这里只需要一个
      几十行就能算对的幂迭代。少一个重依赖，Docker 镜像也小一点。
      公式与 networkx 一致：PR = (1-d)/N + d * (悬挂节点均摊 + Σ 入边 PR/出度)。
    """
    import numpy as np

    nodes = list(g.nodes())
    n = len(nodes)
    if n == 0:
        return {}
    idx = {nid: i for i, nid in enumerate(nodes)}
    out_deg = np.array([g.out_degree(nid) for nid in nodes], dtype=float)
    dangling = out_deg == 0
    m = np.zeros((n, n), dtype=float)
    for src, dst in g.edges():
        i, j = idx[src], idx[dst]
        m[j, i] = 1.0 / max(1.0, out_deg[i])   # 列随机：从 i 指向 j 的概率

    pr = np.full(n, 1.0 / n)
    for _ in range(max_iter):
        dangling_mass = pr[dangling].sum()
        new = (1.0 - alpha) / n + alpha * (m @ pr + dangling_mass / n)
        if np.abs(new - pr).sum() < tol:
            pr = new
            break
        pr = new
    return {nid: float(pr[idx[nid]]) for nid in nodes}


def norm(text: str) -> str:
    """小写、去标点、压空格 —— 用于标题匹配。"""
    t = text.lower()
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def content_tokens(text: str) -> set[str]:
    return {w for w in norm(text).split() if w not in STOP and len(w) > 1}


QUOTED_RE = re.compile(r"[“\"']([^”\"']{12,200})[”\"']")


def guess_title(raw: str) -> str:
    """从参考文献原文里猜标题（用于给库外节点起名字）。

    顺序：引号内文 > 最长的"像标题"的片段 > 原文前 80 字。
    """
    m = QUOTED_RE.search(raw)
    if m:
        return " ".join(m.group(1).split())

    # 按句号切段，挑"词数够多、不像作者串"的最长段
    best = ""
    for seg in re.split(r"(?<=[.!?])\s+", raw):
        s = " ".join(seg.split())
        words = s.split()
        if len(words) < 4 or len(s) < 18:
            continue
        if re.search(r"\b(et al|and|pp\.|vol\.|conference|journal)\b", s, re.I):
            continue
        # 作者串特征：大量单个大写字母（首字母缩写）+ 逗号
        if len(re.findall(r"\b[A-Z]\.", s)) >= 2:
            continue
        if len(s) > len(best):
            best = s
    if best:
        return best[:160]
    return " ".join(raw.split())[:80]


def ref_year(raw: str) -> int | None:
    years = re.findall(r"\b(19|20)\d{2}\b", raw)
    if not years:
        return None
    return int(re.findall(r"\b((?:19|20)\d{2})\b", raw)[-1])


@dataclass
class Node:
    id: str
    label: str
    kind: str          # "local" | "external"
    year: int | None
    doc_id: str | None = None
    in_library: bool = False
    cited_by_local: int = 0      # 被库内几篇论文引用（= 入度，指 local→this）
    cites: int = 0               # 它引用了图上几篇（只有库内节点非 0）
    pagerank: float = 0.0
    pagerank_core: float = 0.0
    centrality: float = 0.0      # 无向图的度中心性
    venue_hint: str = ""


def _load_docs(doc_ids: list[str] | None) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for meta in storage.list_documents():
        if doc_ids and meta.doc_id not in doc_ids:
            continue
        parsed = storage.get_parsed(meta.doc_id)
        if parsed is None:
            continue
        out.append((meta.doc_id, {**parsed, "_filename": meta.filename, "_title": meta.title}))
    return out


def build_graph(
    doc_ids: list[str] | None = None,
    *,
    fuzzy_threshold: float = 0.86,
    top_n: int = 12,
    display_limit: int = 40,
) -> dict[str, Any]:
    docs = _load_docs(doc_ids)
    if not docs:
        return {
            "nodes": [], "edges": [], "stats": {"n_nodes": 0, "n_edges": 0},
            "foundational": {"pagerank": [], "in_degree": []},
        }

    # ---- 库内标题索引（用于匹配） ----
    local_index: list[tuple[str, str, set[str]]] = []
    for doc_id, parsed in docs:
        title = str(parsed.get("_title") or "").strip() or str(parsed.get("_filename") or "")
        local_index.append((doc_id, norm(title), content_tokens(title)))

    nodes: dict[str, Node] = {}
    for doc_id, parsed in docs:
        title = str(parsed.get("_title") or parsed.get("_filename") or doc_id)
        nodes[f"doc:{doc_id}"] = Node(
            id=f"doc:{doc_id}",
            label=title.strip()[:120],
            kind="local",
            year=None,
            doc_id=doc_id,
            in_library=True,
        )

    edges: dict[tuple[str, str], dict[str, Any]] = {}
    n_refs = 0
    n_matched_local = 0

    for doc_id, parsed in docs:
        src = f"doc:{doc_id}"
        for ref in parsed.get("references") or []:
            raw = str(ref.get("raw") or "").strip()
            if len(raw) < 10:
                continue
            n_refs += 1
            title = guess_title(raw)
            key = norm(title)

            # ---- ① 目标是库内论文？ ----
            target: str | None = None
            for other_id, other_norm, other_tokens in local_index:
                if other_id == doc_id or not other_norm:
                    continue
                if other_norm and (other_norm in norm(raw) or key == other_norm):
                    target = f"doc:{other_id}"
                    n_matched_local += 1
                    break
                if other_tokens and key:
                    a, b = content_tokens(title), other_tokens
                    if a and b and len(a & b) / max(1, len(a | b)) >= 0.8:
                        target = f"doc:{other_id}"
                        n_matched_local += 1
                        break
                    if difflib.SequenceMatcher(None, key, other_norm).ratio() >= fuzzy_threshold:
                        target = f"doc:{other_id}"
                        n_matched_local += 1
                        break

            # ---- ② 否则挂到"按标题去重"的库外节点 ----
            if target is None:
                nid = f"ref:{key[:80]}" if key else f"ref:{doc_id}:{ref.get('index')}"
                target = nid
                if nid not in nodes:
                    nodes[nid] = Node(
                        id=nid,
                        label=title[:120],
                        kind="external",
                        year=ref.get("year") or ref_year(raw),
                        in_library=False,
                    )

            if target == src:
                continue
            e = edges.setdefault((src, target), {"source": src, "target": target, "refs": 0})
            e["refs"] += 1

    # ---- 建图与指标 ----
    g = nx.DiGraph()
    for nid in nodes:
        g.add_node(nid)
    for (s, t) in edges:
        g.add_edge(s, t)

    pagerank = pagerank_simple(g, alpha=0.85) if g.number_of_nodes() else {}
    undirected = g.to_undirected()
    centrality = nx.degree_centrality(undirected) if g.number_of_nodes() > 1 else {}

    for nid, node in nodes.items():
        node.pagerank = round(float(pagerank.get(nid, 0.0)), 6)
        node.centrality = round(float(centrality.get(nid, 0.0)), 6)
        node.cited_by_local = int(g.in_degree(nid)) if nid in g else 0
        node.cites = int(g.out_degree(nid)) if nid in g else 0

    # ★全图 PageRank 会被"只被引一次"的长尾节点摊平（526 节点时 top 与均值只差 10%），
    #   排行榜看起来像随机的。所以在"核心子图"（被本库 ≥2 篇引用 + 全部库内文献）上再算一遍，
    #   这才是真正能解释"谁是基石"的指标。
    core_ids = [
        nid for nid, n in nodes.items()
        if n.in_library or (nid in g and g.in_degree(nid) >= 2)
    ]
    core = g.subgraph(core_ids).copy() if core_ids else g.copy()
    core_pr = pagerank_simple(core, alpha=0.85) if core.number_of_nodes() else {}
    for nid, node in nodes.items():
        node.pagerank_core = round(float(core_pr.get(nid, 0.0)), 6)

    node_list = sorted(nodes.values(), key=lambda n: -n.pagerank)

    def brief(n: Node) -> dict[str, Any]:
        return {
            "id": n.id,
            "label": n.label,
            "kind": n.kind,
            "year": n.year,
            "in_library": n.in_library,
            "pagerank": n.pagerank,
            "pagerank_core": n.pagerank_core,
            "centrality": n.centrality,
            "cited_by_local": n.cited_by_local,
            "cites": n.cites,
        }

    ext = [n for n in node_list if not n.in_library]
    pr_top = [brief(n) for n in sorted(node_list, key=lambda x: -x.pagerank_core)[:top_n]]
    deg_top = [brief(n) for n in sorted(node_list, key=lambda x: (-x.cited_by_local, -x.pagerank_core))[:top_n]]

    # ★展示子图：库内文献 + 外部按(入度, 核心PR)取前 display_limit 个，否则 526 个节点画不动
    keep = {n.id for n in nodes.values() if n.in_library}
    for n in sorted(ext, key=lambda x: (-x.cited_by_local, -x.pagerank_core)):
        if len(keep) >= display_limit + len(docs):
            break
        keep.add(n.id)
    display_nodes = [brief(nodes[nid]) for nid in keep]
    display_edges = [e for e in edges.values() if e["source"] in keep and e["target"] in keep]

    return {
        "nodes": [brief(n) for n in node_list],
        "edges": sorted(edges.values(), key=lambda e: -e["refs"]),
        "stats": {
            "n_nodes": len(nodes),
            "n_local": sum(1 for n in nodes.values() if n.in_library),
            "n_external": len(ext),
            "n_edges": len(edges),
            "n_reference_entries": n_refs,
            "n_matched_to_local": n_matched_local,
            "local_match_rate": round(n_matched_local / max(1, n_refs), 4),
            "density": round(nx.density(g), 5) if g.number_of_nodes() > 1 else 0.0,
        },
        "display": {
            "nodes": display_nodes,
            "edges": display_edges,
            "n_nodes": len(display_nodes),
            "n_edges": len(display_edges),
        },
        "foundational": {
            "pagerank": pr_top,
            "in_degree": deg_top,
            "note": (
                "PageRank 在**核心子图**（被本库 ≥2 篇引用的节点 + 全部库内文献）上计算，"
                "否则长尾节点会把分数摊平；"
                "入度看被本库几篇论文直接引用。两者都高 ⇒ 基石论文。"
                "仅统计本库文献的参考文献，不代表全领域引用数。"
            ),
        },
    }
