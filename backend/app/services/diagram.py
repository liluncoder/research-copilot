"""S7 · 论文架构拓扑图生成（官方赛题 1.6.2）。

官方原文：「让 Agent 可以根据论文逻辑，直接生成高质量的 TikZ（LaTeX 绘图代码）、
Graphviz（DOT）或 Mermaid / Python Matplotlib 绘图脚本。」

★核心设计（与 J8 参考文献同源）：**结构由本地解析器给，模型只许"连线"不许"造节点"。**
   1. 节点 = 论文自己的章节树（`parsed["sections"]` 的 label + level），本地生成，模型没机会发明章节；
   2. 父子连线 = 按 level 栈**确定性**推出（1 Introduction → 3.1 …），不经过模型；
   3. 逻辑连线 = 模型只能输出 `{"from": "n3", "to": "n7"}` 这种**引用既有节点 id** 的边，
      指向不存在的 id 一律丢弃并计入 `invalid_edges`；
   4. 三种格式（Mermaid / DOT / TikZ）由本地渲染器拼字符串，模型不产出任何一行绘图代码
      ⇒ 不会出现"语法对不上"的图，也不会出现论文里没有的章节。

为什么不让模型直接写 Mermaid/DOT 源码：实测它会在标签里塞括号、冒号、中文引号，
前端渲染器直接报错；而"只给边"的输出可以被 schema 校验。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.core import llm, storage

MAX_NODES = 24

EDGE_PROMPT = """你在分析一篇论文的**章节逻辑关系**，只为下面的节点之间连线。

论文标题：{title}

可选节点（只能用这些 id，不许新增节点、不许改标题）：
{nodes}

请输出 JSON（不要 markdown 代码块、不要解释）：
{{"edges": [{{"from": "n0", "to": "n3", "label": "方法基础"}}]}}

连线规则：
1. 只连**语义上真的有依赖**的两节，例如"方法"依赖"问题定义"、"实验"验证"方法"；
2. `label` 用 2-6 个中文字，说明这条边代表什么关系（如"提出"、"验证"、"扩展"）；
3. 最多 12 条边，宁少勿滥；父子层级关系不用你连（系统已自动生成）；
4. 不确定的边就不要输出。
"""


@dataclass
class Node:
    id: str
    label: str
    level: int


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""
    kind: str = "tree"  # tree | logic


@dataclass
class DiagramResult:
    title: str = ""
    doc_id: str | None = None
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    invalid_edges: list[str] = field(default_factory=list)
    mermaid: str = ""
    dot: str = ""
    tikz: str = ""
    model: str | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "doc_id": self.doc_id,
            "nodes": [n.__dict__ for n in self.nodes],
            "edges": [e.__dict__ for e in self.edges],
            "n_nodes": len(self.nodes),
            "n_tree_edges": sum(1 for e in self.edges if e.kind == "tree"),
            "n_logic_edges": sum(1 for e in self.edges if e.kind == "logic"),
            "invalid_edges": self.invalid_edges,
            "mermaid": self.mermaid,
            "dot": self.dot,
            "tikz": self.tikz,
            "model": self.model,
            "notes": self.notes,
            "error": self.error,
        }


# ---------- 1. 节点：取自论文自己的章节树 ----------


def _shorten(label: str, limit: int = 46) -> str:
    s = re.sub(r"\s+", " ", label).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def nodes_from_doc(doc_id: str) -> tuple[str, list[Node]]:
    parsed = storage.get_parsed(doc_id) or {}
    meta = storage.get_meta(doc_id)
    title = str(parsed.get("title") or (meta.title if meta else "") or (meta.filename if meta else "")).strip()
    nodes: list[Node] = []
    for sec in parsed.get("sections") or []:
        label = _shorten(str(sec.get("label") or "").strip())
        if not label:
            continue
        if len(nodes) >= MAX_NODES:
            break
        nodes.append(Node(id=f"n{len(nodes)}", label=label, level=int(sec.get("level") or 1)))
    return title, nodes


# ---------- 2. 父边：由 level 栈确定性推导 ----------


def tree_edges(nodes: list[Node]) -> list[Edge]:
    edges: list[Edge] = []
    stack: list[Node] = []
    for n in nodes:
        while stack and stack[-1].level >= n.level:
            stack.pop()
        if stack:
            edges.append(Edge(src=stack[-1].id, dst=n.id, label="", kind="tree"))
        stack.append(n)
    return edges


# ---------- 3. 逻辑边：模型只许在已有节点之间连线 ----------

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _parse_json(text: str) -> dict[str, Any] | None:
    m = _FENCE.search(text)
    raw = (m.group(1) if m else text).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def logic_edges(
    title: str, nodes: list[Node], res: DiagramResult
) -> list[Edge]:
    if not llm.is_configured():
        res.notes.append("未配置 LLM key ⇒ 只输出章节树（父子边），逻辑连线为空")
        return []
    node_lines = "\n".join(f"{n.id}: [{n.level}] {n.label}" for n in nodes)
    prompt = EDGE_PROMPT.format(title=title or "(未命名)", nodes=node_lines)
    try:
        reply = llm.chat(
            [
                {"role": "system", "content": "你是科研论文结构分析助手，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=800,
        )
    except Exception as e:  # noqa: BLE001
        res.notes.append(f"逻辑连线生成失败（{type(e).__name__}: {e}）⇒ 退化为纯章节树")
        return []
    res.model = reply.model
    obj = _parse_json(reply.text)
    if obj is None:
        res.notes.append("模型输出不是合法 JSON ⇒ 退化为纯章节树")
        return []

    valid = {n.id for n in nodes}
    seen: set[tuple[str, str]] = set()
    out: list[Edge] = []
    for item in obj.get("edges") or []:
        if not isinstance(item, dict):
            continue
        src, dst = str(item.get("from")), str(item.get("to"))
        if src not in valid or dst not in valid or src == dst:
            res.invalid_edges.append(f"{src}->{dst}")
            continue
        if (src, dst) in seen:
            continue
        seen.add((src, dst))
        out.append(Edge(src=src, dst=dst, label=_shorten(str(item.get("label") or ""), 12), kind="logic"))
    return out[:12]


# ---------- 4. 三种格式的本地渲染 ----------


def _mq(text: str) -> str:
    """Mermaid 标签安全化：引号统一成单引号，去掉会破坏语法的方括号。"""
    s = text.replace('"', "'").replace("[", "（").replace("]", "）")
    return re.sub(r"[`{}()<>|]", " ", s).strip()


def _dq(text: str) -> str:
    """DOT 标签安全化：转义双引号与反斜杠。"""
    return text.replace("\\", "/").replace('"', '\\"')


def _tq(text: str) -> str:
    """TikZ 标签安全化：花括号、百分号、& 都是语法字符。"""
    return re.sub(r"([{}%&#_$])", r"\\\1", text)


def render_mermaid(res: DiagramResult) -> str:
    shapes = {1: ("[[", "]]"), 2: ("[", "]"), 3: ("(", ")")}
    lines = ["flowchart TD"]
    for n in res.nodes:
        open_s, close_s = shapes.get(n.level, ("[", "]"))
        lines.append(f'  {n.id}{open_s}"{_mq(n.label)}"{close_s}')
    for e in res.edges:
        if e.kind == "tree":
            lines.append(f"  {e.src} --> {e.dst}")
        else:
            lab = f"|{_mq(e.label)}|" if e.label else "|逻辑|"
            lines.append(f"  {e.src} -.->{lab} {e.dst}")
    return "\n".join(lines)


def render_dot(res: DiagramResult) -> str:
    lines = [
        "digraph paper {",
        "  rankdir=TB;",
        '  node [shape=box, style="rounded", fontname="Helvetica"];',
        '  edge [fontname="Helvetica", fontsize=10];',
    ]
    for n in res.nodes:
        shape = "box" if n.level <= 1 else ("box" if n.level == 2 else "ellipse")
        lines.append(f'  {n.id} [label="{_dq(n.label)}", shape={shape}];')
    for e in res.edges:
        if e.kind == "tree":
            lines.append(f"  {e.src} -> {e.dst};")
        else:
            lab = f'label="{_dq(e.label)}", ' if e.label else ""
            lines.append(f'  {e.src} -> {e.dst} [{lab}style=dashed, color=gray40];')
    lines.append("}")
    return "\n".join(lines)


def render_tikz(res: DiagramResult) -> str:
    """网格布局的 TikZ：一级标题占一行主链，子节点挂在其右侧。"""
    lines = [
        "% 由 Research Copilot 生成；需要 \\usepackage{tikz}",
        "\\begin{tikzpicture}[",
        "  every node/.style={draw, rounded corners, align=left, font=\\small, inner sep=4pt},",
        "  edge/.style={->, >=stealth, thin},",
        "  logic/.style={->, >=stealth, dashed, gray},",
        "]",
    ]
    row_of: dict[str, int] = {}
    col_of: dict[str, int] = {}
    row = 0
    for n in res.nodes:
        if n.level <= 1:
            row += 1
            col_of[n.id] = 0
        else:
            col_of[n.id] = 1
        row_of[n.id] = row
    for n in res.nodes:
        x = 0.0 if col_of[n.id] == 0 else 6.4
        y = -1.5 * (row_of[n.id] - 1)
        lines.append(f"  \\node ({n.id}) at ({x:.1f},{y:.1f}) {{{_tq(n.label)}}};")
    for e in res.edges:
        style = "edge" if e.kind == "tree" else "logic"
        lab = f" node[above, font=\\scriptsize, draw=none] {{{_tq(e.label)}}}" if e.label else ""
        lines.append(f"  \\draw[{style}] ({e.src}) --{lab} ({e.dst});")
    lines.append("\\end{tikzpicture}")
    return "\n".join(lines)


# ---------- 5. 入口 ----------


def build(doc_id: str | None = None, *, allow_llm: bool = True) -> DiagramResult:
    res = DiagramResult(doc_id=doc_id)
    if not doc_id:
        res.error = "缺少 doc_id：拓扑图必须基于库内已解析的论文（节点取自该论文的章节树）"
        return res
    if storage.get_parsed(doc_id) is None:
        res.error = f"库中没有 {doc_id} 的解析结果"
        return res

    title, nodes = nodes_from_doc(doc_id)
    if len(nodes) < 2:
        res.error = "这篇论文解析出的章节不足 2 个，无法成图"
        return res
    res.title, res.nodes = title, nodes
    res.edges = tree_edges(nodes)
    if allow_llm:
        res.edges += logic_edges(title, nodes, res)
    res.mermaid = render_mermaid(res)
    res.dot = render_dot(res)
    res.tikz = render_tikz(res)
    return res
