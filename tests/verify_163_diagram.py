"""官方赛题 1.6.2 判据：论文架构拓扑图（Mermaid / Graphviz DOT / TikZ）。

用法（仓库根目录）：
    python tests/verify_163_diagram.py            # 自动挑库内一篇论文
    python tests/verify_163_diagram.py <doc_id>   # 指定论文

判据（8 项）：
  D1 节点只取自章节树：每个节点 label 都能在 parsed["sections"] 里找到原文，节点数 ≤ 24
  D2 父子边完备：树边数 == 节点数 − 根节点数（每个非根节点恰好一条父边），且无环
  D3 Mermaid 可渲染：首行 flowchart TD、每个节点声明一次、每条边两端都声明过
  D4 DOT 可解析：digraph 包裹、括号配平、引号配平、节点/边数与数据一致
  D5 TikZ 完整：\\begin{tikzpicture} … \\end{tikzpicture}，节点数一致
  D6 ★零杜撰节点：模型返回 n999→n3 这种不存在的 id ⇒ 进 invalid_edges、图里不出现
  D7 合法逻辑边落地：注入 2 条合法边 ⇒ n_logic_edges==2 且 Mermaid 出现虚线箭头
  D8 标签安全化：标题里带 " [ ] { } 时，三种格式都不产生语法破坏字符

★核心机制与 J8 同源：**结构是本地解析器给的，模型只许连线**。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("CHROMA_PERSIST_DIR", str(ROOT / "tests" / "out" / "index_j163"))
os.chdir(ROOT / "backend")  # upload_dir 是相对路径 ./data/uploads

from app.core import llm, storage  # noqa: E402
from app.services import diagram  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(code: str, ok: bool, detail: str) -> None:
    results.append((code, PASS if ok else FAIL, detail))


def pick_doc() -> str | None:
    docs = [d for d in storage.list_documents() if storage.get_parsed(d.doc_id)]
    if not docs:
        return None
    # 优先 1706.03762（章节树最典型），否则取章节最多的一篇
    for d in docs:
        if "1706.03762" in (d.filename or ""):
            return d.doc_id
    return max(docs, key=lambda d: len((storage.get_parsed(d.doc_id) or {}).get("sections") or [])).doc_id


class _FakeLLM:
    """不联网的假模型：返回预设 JSON。"""

    def __init__(self, payload: str):
        self.payload = payload

    def __call__(self, messages, **kwargs):
        return llm.LLMReply(text=self.payload, model="fake-llm")


def run(doc_id: str) -> None:
    parsed = storage.get_parsed(doc_id) or {}
    sections = [s for s in (parsed.get("sections") or []) if str(s.get("label") or "").strip()]
    labels = {re.sub(r"\s+", " ", str(s.get("label"))).strip() for s in sections}

    # 关掉 LLM：纯章节树，结果必须确定性
    base = diagram.build(doc_id, allow_llm=False)

    # ---- D1 节点来源 ----
    bad = [n.label for n in base.nodes if n.label.rstrip("…") not in {b[: len(n.label.rstrip("…"))] for b in labels}]
    check(
        "D1",
        bool(base.nodes) and len(base.nodes) <= 24 and not bad,
        f"节点 {len(base.nodes)} 个（上限 24），全部来自章节树，越界 {len(bad)} 个"
        + (f"：{bad[:3]}" if bad else ""),
    )

    # ---- D2 父子边 ----
    roots = sum(1 for n in base.nodes if not any(e.dst == n.id for e in base.edges if e.kind == "tree"))
    tree = [e for e in base.edges if e.kind == "tree"]
    parents_ok = len(tree) == len(base.nodes) - roots
    # 无环：沿父指针上溯不得回到自己
    parent = {e.dst: e.src for e in tree}
    acyclic = True
    for n in base.nodes:
        seen, cur = set(), n.id
        while cur in parent:
            if cur in seen:
                acyclic = False
                break
            seen.add(cur)
            cur = parent[cur]
    check("D2", parents_ok and acyclic, f"树边 {len(tree)} 条 / 节点 {len(base.nodes)} / 根 {roots}，无环={acyclic}")

    # ---- D3 Mermaid ----
    mm = base.mermaid
    decl = re.findall(r"^\s{2}(n\d+)[\[\(]", mm, re.M)
    edges_n = re.findall(r"^\s{2}(n\d+)\s+(?:-->|-\..*?->)\s*(n\d+)", mm, re.M)
    m_ok = (
        mm.splitlines()[0].strip() == "flowchart TD"
        and len(decl) == len(base.nodes)
        and len(set(decl)) == len(decl)
        and all(a in decl and b in decl for a, b in edges_n)
    )
    check("D3", m_ok, f"flowchart 首行 ✓，节点声明 {len(decl)}/{len(base.nodes)}，边 {len(edges_n)} 条且两端均声明")

    # ---- D4 DOT ----
    dot = base.dot
    dot_nodes = len(re.findall(r"^\s{2}n\d+ \[label=", dot, re.M))
    dot_edges = len(re.findall(r"^\s{2}n\d+ -> n\d+", dot, re.M))
    bare = re.sub(r'"(?:[^"\\]|\\.)*"', '""', dot)  # 去掉引号内的标签内容再数括号
    bal = bare.count("{") == bare.count("}") and bare.count("[") == bare.count("]")
    quotes = dot.count('"') % 2 == 0
    check(
        "D4",
        dot.startswith("digraph") and dot_nodes == len(base.nodes) and dot_edges == len(base.edges) and bal and quotes,
        f"digraph ✓ 节点 {dot_nodes}/{len(base.nodes)} 边 {dot_edges}/{len(base.edges)} 结构括号配平={bal} 引号配平={quotes}",
    )

    # ---- D5 TikZ ----
    tk = base.tikz
    tk_nodes = len(re.findall(r"\\node \(n\d+\)", tk))
    tk_ok = "\\begin{tikzpicture}" in tk and "\\end{tikzpicture}" in tk and tk_nodes == len(base.nodes)
    check("D5", tk_ok, f"tikzpicture 完整 ✓ 节点 {tk_nodes}/{len(base.nodes)}")

    # ---- D6 幻觉节点被拦（关键） ----
    orig_chat, orig_conf = llm.chat, llm.is_configured
    try:
        llm.is_configured = lambda: True  # type: ignore[assignment]
        llm.chat = _FakeLLM('{"edges":[{"from":"n999","to":"n3","label":"伪造"},{"from":"n1","to":"n9999"}]}')  # type: ignore[assignment]
        halluc = diagram.build(doc_id, allow_llm=True)
    finally:
        llm.chat, llm.is_configured = orig_chat, orig_conf
    no_fake = not any("n999" in (e.src + e.dst) for e in halluc.edges) and "n999" not in halluc.mermaid
    check(
        "D6",
        no_fake and len(halluc.invalid_edges) == 2 and halluc.error is None,
        f"伪造边 2 条全部拦下（invalid_edges={len(halluc.invalid_edges)}），图里无 n999={no_fake}，图仍可渲染={bool(halluc.mermaid)}",
    )

    # ---- D7 合法逻辑边落地 ----
    try:
        llm.is_configured = lambda: True  # type: ignore[assignment]
        llm.chat = _FakeLLM('{"edges":[{"from":"n0","to":"n2","label":"提出"},{"from":"n1","to":"n3","label":"验证"}]}')  # type: ignore[assignment]
        logic = diagram.build(doc_id, allow_llm=True)
    finally:
        llm.chat, llm.is_configured = orig_chat, orig_conf
    n_logic = sum(1 for e in logic.edges if e.kind == "logic")
    check(
        "D7",
        n_logic == 2 and "-.->" in logic.mermaid and "style=dashed" in logic.dot and not logic.invalid_edges,
        f"逻辑边 {n_logic} 条，Mermaid 虚线 ✓，DOT dashed ✓，非法 {len(logic.invalid_edges)}",
    )

    # ---- D8 标签安全化 ----
    dirty = diagram.DiagramResult(
        nodes=[diagram.Node("n0", 'Weird "title" [x] {y} 100%', 1), diagram.Node("n1", "Child (sub)", 2)],
        edges=[],
    )
    dirty.edges = diagram.tree_edges(dirty.nodes)
    m2, d2, t2 = diagram.render_mermaid(dirty), diagram.render_dot(dirty), diagram.render_tikz(dirty)
    m_label = re.search(r'^\s{2}n0(?:\[\[|\[|\()(.*?)(?:\]\]|\]|\))$', m2, re.M)
    label_txt = (m_label.group(1) if m_label else "").strip('"')
    label_safe = bool(label_txt) and "[" not in label_txt and "]" not in label_txt and '"' not in label_txt
    check(
        "D8",
        m2.count('"') % 2 == 0 and label_safe and d2.count('"') % 2 == 0 and "\\{" in t2 and "\\%" in t2,
        f"Mermaid 引号配平、标签内无裸方括号={label_safe}；DOT 引号配平；TikZ 已转义 {{ 与 %",
    )


def main() -> int:
    doc_id = sys.argv[1] if len(sys.argv) > 1 else pick_doc()
    if not doc_id:
        print("FAIL 库里没有已解析文献，先入库一篇（见 docs/本机启动手册.md）")
        return 1
    meta = storage.get_meta(doc_id)
    print(f"文献：{meta.filename if meta else doc_id}  doc_id={doc_id}")
    run(doc_id)

    print("\n" + "=" * 72)
    for code, status, detail in results:
        print(f"{status}  {code}  {detail}")
    n_fail = sum(1 for _, s, _ in results if s == FAIL)
    print("=" * 72)
    print(f"合计 {len(results) - n_fail}/{len(results)} PASS")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
