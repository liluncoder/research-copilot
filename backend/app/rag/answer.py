"""S2 · 回答层（J4 的正面战场）。

流水线（LangGraph 形状；未装 langgraph 时退到等价的顺序执行器）：
    plan    —— 判意图 + 查询改写（中文问题 → 英文检索词，解决跨语言召回）
    retrieve—— 多 query 混合检索 + RRF 合并
    answer  —— 只依据片段作答，每个论断挂 [来源: 文件·页码·章节]
    verify  —— 逐条核对出处是否真实存在于检索结果（★反幻觉的第二道闸）

★两条硬规矩（对应 路线/02 的"回答契约"）：
1. **检索为空 ⇒ 直接拒答**，不调 LLM（省一次幻觉的机会）
2. **出处必须能被检索结果验证**；验证不通过的出处会被剔除并计入 `invalid_citations`，
   而不是留在回答里冒充证据 —— 这是 J8「无幻觉 References」的地基。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, TypedDict

from app.core import llm
from app.rag import service

CITE_RE = re.compile(r"\[来源[:：]\s*([^·\]]+?)\s*·\s*([^·\]]+?)\s*·\s*([^\]]+?)\s*\]")

PLAN_PROMPT = """你是科研文献检索助手。把用户的中文问题转成 2~4 条**英文检索词**（用于在英文学术论文里召回相关段落）。

只输出 JSON，不要任何解释：
{"intent": "fact|compare|summary", "queries": ["...", "..."]}

要求：
- 检索词用论文里可能出现的**术语/数字/专名**，不要写成问句
- 例子：问"β1 β2 设成多少" → ["Adam optimizer beta1 beta2 epsilon 0.9 0.98"]
- 例子：问"用了多少 GPU" → ["Number of GPUs used for training NVIDIA P100"]
"""

ANSWER_PROMPT = """你是严谨的科研文献问答助手。**只依据下面给出的【资料片段】回答**，禁止使用外部知识。

硬性要求：
1. 每一句事实性陈述后面必须紧跟出处，格式严格为 `[来源: 文件名·p页码·章节名]`
   —— 只能使用片段里给出的 `[来源: ...]` 标记，不得自己编造文件名、页码或章节名。
2. 片段里查不到的信息，直接回答：`库中未找到相关内容。` 不要推测、不要补全。
3. 数字、超参数、硬件型号、指标必须与片段**逐字一致**，不得换算或四舍五入。
4. 用中文回答（专有名词保留英文），分点列出，简洁，不要客套话。

【资料片段】
{sources}

【问题】
{question}
"""


class QAState(TypedDict, total=False):
    question: str
    doc_ids: list[str] | None
    top_k: int
    intent: str
    queries: list[str]
    hits: list[dict[str, Any]]
    answer: str
    citations: list[str]
    invalid_citations: list[str]
    refused: bool
    steps: list[dict[str, Any]]
    error: str | None


def _step(state: QAState, node: str, detail: str, ms: float) -> None:
    state.setdefault("steps", []).append(
        {"node": node, "detail": detail, "ms": round(ms, 1)}
    )


# ---------------------------------------------------------------- 节点


def plan_node(state: QAState) -> QAState:
    """意图 + 查询改写。LLM 不可用时退化为原问题（仍然能跑，只是跨语言召回会差）。"""
    t0 = time.perf_counter()
    q = state["question"]
    queries = [q]
    intent = "fact"

    if llm.is_configured():
        try:
            reply = llm.chat(
                [
                    {"role": "system", "content": PLAN_PROMPT},
                    {"role": "user", "content": q},
                ],
                temperature=0.0,
                max_tokens=300,
            )
            data = _parse_json(reply.text)
            if data and isinstance(data.get("queries"), list) and data["queries"]:
                queries = [str(x) for x in data["queries"]][:4]
                intent = str(data.get("intent") or "fact")
        except Exception as e:  # noqa: BLE001 - 改写失败不该让整条链断
            state["error"] = f"plan: {e}"
    else:
        state["error"] = "plan: 未配置 LLM，使用原问题检索"

    state["intent"] = intent
    state["queries"] = queries
    _step(state, "plan", f"intent={intent}；检索词={queries}", (time.perf_counter() - t0) * 1000)
    return state


def retrieve_node(state: QAState) -> QAState:
    """多 query 检索 → 按 chunk_id 做 RRF 合并（不同 query 的名次各自贡献）。"""
    t0 = time.perf_counter()
    merged: dict[str, dict[str, Any]] = {}
    for qi, q in enumerate(state.get("queries") or [state["question"]]):
        res = service.search(q, doc_ids=state.get("doc_ids"), top_k=max(state.get("top_k", 5), 5))
        for rank, h in enumerate(res.hits):
            d = h.as_dict()
            score = 1.0 / (60 + rank + 1)
            if d["chunk_id"] in merged:
                merged[d["chunk_id"]]["score"] += score
                merged[d["chunk_id"]]["from_queries"].append(qi)
            else:
                d["score"] = score
                d["from_queries"] = [qi]
                merged[d["chunk_id"]] = d

    hits = sorted(merged.values(), key=lambda d: -d["score"])[: state.get("top_k", 5)]
    state["hits"] = hits
    _step(
        state,
        "retrieve",
        f"{len(state.get('queries') or [])} 条检索词 → 合并后 {len(hits)} 块"
        + (f"；top1={hits[0]['page']} {hits[0]['section']}" if hits else "；无命中"),
        (time.perf_counter() - t0) * 1000,
    )
    return state


def answer_node(state: QAState) -> QAState:
    t0 = time.perf_counter()
    hits = state.get("hits") or []
    if not hits:
        state["answer"] = "库中未找到相关内容。"
        state["refused"] = True
        state["citations"] = []
        _step(state, "answer", "检索为空 ⇒ 直接拒答（不调用 LLM）", (time.perf_counter() - t0) * 1000)
        return state

    if not llm.is_configured():
        state["answer"] = "（未配置 LLM key，无法生成回答；检索结果见 hits）"
        state["refused"] = True
        _step(state, "answer", "LLM 未配置", (time.perf_counter() - t0) * 1000)
        return state

    sources = "\n\n".join(
        f"【片段{i + 1}】{h['citation']}\n{h['text']}" for i, h in enumerate(hits)
    )
    prompt = ANSWER_PROMPT.replace("{sources}", sources).replace("{question}", state["question"])
    try:
        reply = llm.chat([{"role": "user", "content": prompt}], temperature=0.1, max_tokens=900)
        state["answer"] = reply.text
        state["refused"] = _looks_refused(reply.text)
        _step(
            state,
            "answer",
            f"{reply.model}；{len(reply.text)} 字；输入 {reply.prompt_tokens} / 输出 {reply.completion_tokens} tokens",
            (time.perf_counter() - t0) * 1000,
        )
    except Exception as e:  # noqa: BLE001
        state["answer"] = f"生成失败：{e}"
        state["refused"] = True
        state["error"] = f"answer: {e}"
        _step(state, "answer", f"失败：{e}", (time.perf_counter() - t0) * 1000)
    return state


def verify_node(state: QAState) -> QAState:
    """逐条核对出处：文件名 + 页码必须能在检索结果里找到，否则剔除。"""
    t0 = time.perf_counter()
    hits = state.get("hits") or []
    allowed = {(h["filename"], _norm_page(h["page"])) for h in hits}
    valid: list[str] = []
    invalid: list[str] = []
    for m in CITE_RE.finditer(state.get("answer") or ""):
        raw = m.group(0)
        key = (m.group(1).strip(), _norm_page(m.group(2)))
        if key in allowed:
            if raw not in valid:
                valid.append(raw)
        else:
            invalid.append(raw)

    state["citations"] = valid
    state["invalid_citations"] = invalid
    _step(
        state,
        "verify",
        f"有效出处 {len(valid)} 条" + (f"；**剔除编造出处 {len(invalid)} 条**：{invalid}" if invalid else "；无编造"),
        (time.perf_counter() - t0) * 1000,
    )
    return state


NODES = [("plan", plan_node), ("retrieve", retrieve_node), ("answer", answer_node), ("verify", verify_node)]


# ---------------------------------------------------------------- 执行器


def _run_sequential(state: QAState) -> QAState:
    for _, fn in NODES:
        state = fn(state)
    return state


def _run_langgraph(state: QAState) -> QAState:
    """用 LangGraph 的 StateGraph 跑同一组节点（装了 langgraph 就走这条）。"""
    from langgraph.graph import END, StateGraph

    g = StateGraph(QAState)
    for name, fn in NODES:
        g.add_node(name, fn)
    g.set_entry_point(NODES[0][0])
    for (a, _), (b, _) in zip(NODES, NODES[1:]):
        g.add_edge(a, b)
    g.add_edge(NODES[-1][0], END)
    return g.compile().invoke(state)  # type: ignore[return-value]


def _langgraph_available() -> bool:
    try:
        import langgraph.graph  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


@dataclass
class QAResult:
    question: str
    answer: str
    hits: list[dict[str, Any]] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    refused: bool = False
    steps: list[dict[str, Any]] = field(default_factory=list)
    orchestrator: str = "sequential"
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "refused": self.refused,
            "citations": self.citations,
            "invalid_citations": self.invalid_citations,
            "hits": self.hits,
            "steps": self.steps,
            "orchestrator": self.orchestrator,
            "error": self.error,
        }


def answer_question(
    question: str,
    *,
    doc_ids: list[str] | None = None,
    top_k: int = 5,
) -> QAResult:
    state: QAState = {"question": question, "doc_ids": doc_ids, "top_k": top_k, "steps": []}
    use_lg = _langgraph_available()
    final = (_run_langgraph if use_lg else _run_sequential)(state)
    return QAResult(
        question=question,
        answer=final.get("answer", ""),
        hits=final.get("hits", []),
        citations=final.get("citations", []),
        invalid_citations=final.get("invalid_citations", []),
        refused=bool(final.get("refused")),
        steps=final.get("steps", []),
        orchestrator="langgraph" if use_lg else "sequential",
        error=final.get("error"),
    )


# ---------------------------------------------------------------- 小工具


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                return None
    return None


def _norm_page(p: str) -> str:
    """把 p7 / p7-8 / 7 / 7-8 / 第7页 都归一成 '7' 或 '7-8'。"""
    s = str(p).strip().lower().replace("第", "").replace("页", "")
    s = s.lstrip("p").replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", "", s)
    return s


def _looks_refused(text: str) -> bool:
    """判定"拒答"。

    ★只看**开头**，且不再要求"没有出处"：
      实测出现过"先拒答、再解释为什么不答、并引用了片段"的回答，
      旧逻辑（必须有 key 且无引用）会把这种回答判成"已作答"，状态与内容矛盾。
    """
    head = text.strip()[:40]
    keys = ["库中未找到", "未找到相关", "无法回答", "没有相关信息", "无法依据片段"]
    return any(k in head for k in keys)
