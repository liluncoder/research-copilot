"""S2 · 回答层（J4 的正面战场）。

流水线（LangGraph 形状；未装 langgraph 时退到等价的顺序执行器）：
    plan    —— 判意图 + 查询改写（中文问题 → 英文检索词，解决跨语言召回）
    retrieve—— 多 query 混合检索 + RRF 合并
    answer  —— 只依据片段作答，每个论断挂 [来源: 文件·页码·章节]
    verify  —— 逐条核对出处是否真实存在于检索结果（★反幻觉的第二道闸）

★两条硬规矩（对应回答契约）：
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

from app.core import llm, storage
from app.rag import service

CITE_RE = re.compile(r"\[来源[:：]\s*([^·\]]+?)\s*·\s*([^·\]]+?)\s*·\s*([^\]]+?)\s*\]")


# ★换模型（qwen-plus）后实测它会用 `<来源…>` 或反引号包裹出处，
#   格式漂移会让 verify 一条都认不出来（回答内容对、出处 0 条 ⇒ 判据误判成不过）。
#   处理原则：**宽容输入格式，不宽容页码真假** —— 括号统一，页码照样逐条核对。
def _normalize_cites(text: str) -> str:
    text = re.sub(r"【\s*来源([^】]*)】", lambda m: "[来源" + m.group(1) + "]", text)
    text = re.sub(r"<\s*来源([^>]*)>", lambda m: "[来源" + m.group(1) + "]", text)
    return text.replace("`", "")

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
   —— 只能使用片段里给出的 `[来源: ...]` 标记，**整段原样复制**，不得改写页码、不得改变章节名，
   不得用反引号、尖括号、书名号包裹。
   正确示例：`[来源: 1706.03762v1.pdf·p8·Table 2]`
   错误示例：`<来源: …>`、`【来源: …】`、`（来源：…）`、`[来源: 该论文]`（缺页码/章节）。
2. 片段里查不到的信息，直接回答：`库中未找到相关内容。` 不要推测、不要补全。
3. 数字、超参数、硬件型号、指标必须与片段**逐字一致**，不得换算或四舍五入。
4. 用中文回答（专有名词保留英文），分点列出，简洁，不要客套话。
   **只输出答案要点**：不要输出自我检查、自我纠错、格式说明（例如"错误：该处未使用指定格式…"），
   这些内容由系统自动处理。
5. 【题录】片段给的是**作者署名顺序与单位**，问"第 N 作者是谁、在哪个机构"时按序号数，逐字照抄姓名与单位。
6. 【References】片段给的是**参考文献条目原文**，问某文献的作者与年份时直接照抄条目里的姓名与年份。
7. 问"提升了多少"时，必须同时给出本模型数值与对照数值，并写出两者的差。
8. 问"当时的 State-of-the-art 是多少"时：若片段里有 Scores 对比表格，**必须从表格里读出除本模型外的最高分**
   （连同模型名一起写），不允许只写"超过 N BLEU"这种没有对照数值的说法。

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
    aux: list[dict[str, Any]]
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
    state["aux"] = _aux_hits(state["question"], state.get("queries") or [], state.get("doc_ids"))
    _step(
        state,
        "retrieve",
        f"{len(state.get('queries') or [])} 条检索词 → 合并后 {len(hits)} 块"
        + (f" + 题录/参考文献 {len(state['aux'])} 条" if state["aux"] else "")
        + (f"；top1={hits[0]['page']} {hits[0]['section']}" if hits else "；无命中"),
        (time.perf_counter() - t0) * 1000,
    )
    return state


# ---------------------------------------------------------------- 题录 / 参考文献直取
#
# ★为什么需要这两块：正文切块检索天生漏两类事实 ——
#   ① 作者署名与单位（在首页题录区，通常不落在任何正文段落里）
#   ② 参考文献条目（在 References 节，与问题里的术语只有弱词面重叠）
#   官方 1.2.1 的第 1 题（第 6 作者 + 机构）和第 5 题（LayerNormalization 参考文献的作者与年份）
#   都正好落在这两个盲区里，实测纯向量+BM25 召回为零 ⇒ 直接拒答。
#   解决办法不是让模型"努力回忆"，而是**把确定的结构化字段直接喂进上下文**。

_STOP = {
    "the", "and", "for", "with", "paper", "this", "that", "what", "which", "how", "many",
    "much", "was", "were", "are", "is", "of", "in", "on", "by", "to", "a", "an", "at",
    "reference", "references", "author", "authors", "paper", "论文", "作者", "参考",
}
_NAME_RE = re.compile(r"^[A-ZŁ][\w.\-']*(?:\s+[A-ZŁ][\w.\-']*){1,3}$")


def _strip_marks(s: str) -> str:
    return re.sub(r"[∗†‡§¶*0-9]+$", "", s).strip()


def _author_affils(full_text: str) -> list[tuple[str, str]]:
    """从首页署名区解析（姓名, 单位）对。失败返回空列表，绝不猜。"""
    lines = [ln.strip() for ln in (full_text or "")[:3000].splitlines() if ln.strip()]
    out: list[tuple[str, str]] = []
    for i, ln in enumerate(lines[:-1]):
        name = _strip_marks(ln)
        if not _NAME_RE.match(name) or "arXiv" in name or len(name) > 40:
            continue
        aff = _strip_marks(lines[i + 1])
        if "@" in aff or aff.endswith(".") or len(aff) > 60 or not aff:
            continue
        if (name, aff) not in out:
            out.append((name, aff))
    return out[:24]


def _item_hit(doc_id: str, page: int, section: str, text: str) -> dict[str, Any]:
    meta = storage.get_meta(doc_id)
    fname = meta.filename if meta else doc_id
    return {
        "chunk_id": f"aux:{doc_id}:{section}",
        "filename": fname,
        "page": f"p{page}",
        "section": section,
        "citation": f"[来源: {fname}·p{page}·{section}]",
        "text": text,
        "score": 0.0,
        "aux": True,
    }


def _aux_hits(question: str, queries: list[str], doc_ids: list[str] | None) -> list[dict[str, Any]]:
    metas = {m.doc_id: m for m in storage.list_documents()}
    ids = [d for d in (doc_ids or list(metas.keys())) if d in metas][:3]
    # ★原来只收 4 字母以上的词，把 "GPU" 这类 3 字母缩写漏掉了 ——
    #   而官方第 3 题的原话就是"用了多少个 GPU"，漏掉它会让 5.2 Hardware 这一节进不了路由。
    toks = {
        w.lower()
        for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}|[A-Z]{2,4}", question + " " + " ".join(queries))
        if w.lower() not in _STOP
    }
    out: list[dict[str, Any]] = []
    for did in ids:
        parsed = storage.get_parsed(did)
        if not parsed:
            continue
        meta = metas[did]
        authors = list(getattr(meta, "authors", []) or parsed.get("authors") or [])
        affils = _author_affils(str(parsed.get("full_text") or ""))

        # ① 题录块：作者顺序 + 单位（官方 Q1 的唯一可靠来源）
        if authors:
            aff_map = {n: a for n, a in affils}
            lines = []
            for i, name in enumerate(authors, 1):
                aff = aff_map.get(name) or aff_map.get(_strip_marks(name)) or ""
                lines.append(f"{i}. {name}" + (f" —— {aff}" if aff else ""))
            title = str(parsed.get("title") or meta.title or "").strip()
            out.append(
                _item_hit(
                    did,
                    1,
                    "题录",
                    f"标题：{title}\n作者（按署名顺序）：\n" + "\n".join(lines),
                )
            )

        # ② 参考文献命中块：按问题里的英文术语匹配条目（官方 Q5）
        refs = parsed.get("references") or []
        ref_page = 1
        for sec in parsed.get("sections") or []:
            if "reference" in str(sec.get("label") or "").lower():
                ref_page = int(sec.get("page_start") or 1)
                break
        if refs and toks:
            scored = []
            for r in refs:
                raw = str(r.get("raw") or "")
                low = raw.lower()
                hit = sum(1 for t in toks if t in low)
                if hit:
                    scored.append((hit, raw, r.get("year")))
            scored.sort(key=lambda x: -x[0])
            if scored:
                body = "\n".join(
                    f"[{i}] {raw}" + (f" ({yr})" if yr else "") for i, (_, raw, yr) in enumerate(scored[:4], 1)
                )
                out.append(_item_hit(did, ref_page, "References", "参考文献条目（按问题术语命中）：\n" + body))

        # ③ 表格块：数字类问题（BLEU/参数量/GPU）的答案常常只在表格里（官方 Q4 的对照 SOTA）
        tables = parsed.get("tables") or []
        if tables and toks:
            scored_t = []
            for t in tables:
                blob = (str(t.get("caption") or "") + " " + str(t.get("markdown") or "")).lower()
                hit = sum(1 for tk in toks if tk in blob)
                if hit:
                    scored_t.append((hit, t))
            scored_t.sort(key=lambda x: -x[0])
            for _, t in scored_t[:2]:
                cap = str(t.get("caption") or "").strip()
                md = str(t.get("markdown") or "").strip()
                if not md:
                    continue
                label = f"Table {t.get('number')}" if t.get("number") else "Table"
                out.append(
                    _item_hit(
                        did,
                        int(t.get("page") or 1),
                        label,
                        f"{label}：{cap}\n{md}",
                    )
                )

        # ④ 关键节路由：把"章节标题 + 前两段"当作结构化片段。
        #    理由：数字型问题（多少 GPU / 什么型号 / 超参）的答案常常集中在一个小节里，
        #    纯切片检索容易被邻近章节抢走（实测同一问题两种召回落点不同 ⇒ 答案时好时坏）。
        #    ★两处修正：① 匹配用的文本要**带上章节标题**（"Hardware" 这种词只在标题里）；
        #      ② 取 top-2 而不是 top-1 —— 同分竞争时（6.1 抢走 5.2）只注入一个会把正确答案挤掉。
        scored_sec: list[tuple[int, int, dict[str, Any]]] = []
        for sec in parsed.get("sections") or []:
            paras = [str(p) for p in (sec.get("paragraphs") or []) if str(p).strip()]
            if not paras:
                continue
            label = str(sec.get("label") or "")
            blob = (" ".join(paras)).lower()
            # ★修正打分方式：原来按"命中次数"排，长章节（6.1/Abstract）靠字数优势
            #   总赢过短章节，于是 5.2 Hardware（"8 块 P100"真正的出处）永远进不了前 3。
            #   改为：标题命中权重 3、正文按**去重 token** 计 1，同分时短章节优先（更具体）。
            label_hit = sum(1 for tk in toks if tk in label.lower())
            body_hit = sum(1 for tk in toks if tk in blob)
            if label_hit == 0 and body_hit < 2:
                continue
            scored_sec.append((label_hit * 3 + body_hit, -len(blob), sec))
        scored_sec.sort(key=lambda x: (-x[0], x[1]))
        # 注入前 3 节：同分竞争时给得太少会把正确答案挤掉；
        # 页码选错的风险由 `_repair_anchors` 用证据反查兜住，越界锚点仍会被 verify 剔除。
        for _, _, sec in scored_sec[:3]:
            paras = [str(p).strip() for p in (sec.get("paragraphs") or []) if str(p).strip()][:3]
            out.append(
                _item_hit(
                    did,
                    int(sec.get("page_start") or 1),
                    str(sec.get("label") or "").strip() or "正文",
                    f"章节『{str(sec.get('label') or '').strip()}』原文：\n" + "\n".join(paras),
                )
            )
    return out


NUM_RE = re.compile(r"\d+(?:\.\d+)?")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-]{3,}")
_CITE_INNER = re.compile(r"\[来源[:：]\s*([^·\]]+?)\s*·\s*([^·\]]+?)\s*·\s*([^\]]+?)\s*\]")


def _repair_anchors(text: str, sources: list[dict[str, Any]]) -> tuple[str, int]:
    """把**对不上号**的出处，按句子里的数字/术语重新锚定到真正包含它的片段。

    ★为什么需要这一步（实测）：换 qwen-plus 后，模型偶尔把 β 值那两句锚到
      `p2·1 Introduction`（内容对、页码错）。这类错误会被 verify 判为"编造出处"并剔除，
      结果是"答案正确但一条出处都不剩"。与其靠提示词求它别错，不如**用证据反查锚点**：
      · 只在句子与候选片段都出现的数字/长词上做匹配（数字权重更高）；
      · 一个都对不上就保持原样（让 verify 正常剔除，绝不硬凑一个）。
    返回 (新文本, 修复条数)。
    """
    allowed: dict[tuple[str, str], str] = {}
    for s in sources:
        allowed[(str(s.get("filename")), _norm_page(str(s.get("page"))))] = str(s.get("citation") or "")
    if not allowed:
        return text, 0

    fixed = 0
    out_lines: list[str] = []
    for line in text.splitlines():
        def repl(m: re.Match[str]) -> str:
            nonlocal fixed
            key = (m.group(1).strip(), _norm_page(m.group(2)))
            if key in allowed:  # 本来就是对的
                return m.group(0)
            # 这句除了出处之外的部分，用来反查
            sentence = line[: m.start()]
            nums = set(NUM_RE.findall(sentence))
            words = {w.lower() for w in WORD_RE.findall(sentence)} - set()
            best: tuple[int, str] | None = None
            for cand in sources:
                body = str(cand.get("text") or "")
                n_hit = sum(1 for n in nums if n in body)
                w_hit = sum(1 for w in words if w in body.lower())
                score = n_hit * 3 + w_hit
                if n_hit == 0 and w_hit < 2:
                    continue  # 证据不足，不硬凑
                if best is None or score > best[0]:
                    best = (score, str(cand.get("citation") or ""))
            if best is None or not best[1]:
                return m.group(0)  # 交给 verify 剔除
            fixed += 1
            return best[1]

        out_lines.append(_CITE_INNER.sub(repl, line))
    return "\n".join(out_lines), fixed


def answer_node(state: QAState) -> QAState:
    t0 = time.perf_counter()
    hits = state.get("hits") or []
    aux = state.get("aux") or []
    if not hits and not aux:
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

    # ★题录/参考文献块排在正文片段之前：作者与文献条目属于"结构化事实"，
    #   放在最前面可避免被长正文挤掉注意力。
    ordered = aux + hits
    sources = "\n\n".join(
        f"【片段{i + 1}】{h['citation']}\n{h['text']}" for i, h in enumerate(ordered)
    )
    prompt = ANSWER_PROMPT.replace("{sources}", sources).replace("{question}", state["question"])
    try:
        reply = llm.chat([{"role": "user", "content": prompt}], temperature=0.1, max_tokens=900)
        answer, n_fixed = _repair_anchors(reply.text, ordered)
        state["answer"] = answer
        state["refused"] = _looks_refused(reply.text)
        _step(
            state,
            "answer",
            f"{reply.model}；{len(answer)} 字；输入 {reply.prompt_tokens} / 输出 {reply.completion_tokens} tokens"
            + (f"；**重锚 {n_fixed} 条出处**" if n_fixed else ""),
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
    aux = state.get("aux") or []
    allowed = {(h["filename"], _norm_page(h["page"])) for h in hits + aux}
    valid: list[str] = []
    invalid: list[str] = []
    for m in CITE_RE.finditer(_normalize_cites(state.get("answer") or "")):
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
