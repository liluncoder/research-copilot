"""S2 · 多文对比问答（J2 最后一块）。

与单篇问答（answer.py）的区别：
1. **检索是按文献分路做的**：每篇各召回 top-k，保证"每篇都有话说"，
   而不是让一篇的长段落把别的文献全挤掉（单库 top-k 最容易犯的错）。
2. **提示词要求成表**：维度 × 论文的对照表，每格必须挂出处，未提及就写"未提及"。
3. **出处校验按"文献集合"做**：只认本次真正召回的（文件名, 页码）组合。

复用 answer.py 的 `CITE_RE` / `_norm_page` / `_looks_refused`，避免两套规则漂移。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.core import llm
from app.rag import service
from app.rag.answer import CITE_RE, _norm_page, _parse_json

COMPARE_PROMPT = """你在做**多篇论文的对比问答**。只依据下面按论文分组给出的【资料片段】作答，禁止使用外部知识。

输出格式（严格遵守）：
1. 先给一张 Markdown 表格：第一列是"对比维度"，其余每列是**一篇论文**（列名用片段的文件名）。
   单元格内容必须以出处标记结尾，格式 `[来源: 文件名·p页码·章节名]`，只能引用片段里出现过的出处。
   某篇论文没有提到该维度时，写 `未提及`，**不要猜、不要用别的论文的内容填**。
2. 表格之后给 2~4 条「要点」，每条同样要挂出处。

要求：
- 数字、层数、参数量、上下文长度等必须与片段逐字一致，禁止换算或四舍五入
- 用中文（专有名词保留英文）
- 不要客套话，不要重复题目

【资料片段】
{sources}
"""


@dataclass
class CompareResult:
    question: str
    answer: str
    docs: list[dict[str, Any]] = field(default_factory=list)   # [{doc_id, filename, hits_n}]
    hits: list[dict[str, Any]] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    covered_docs: list[str] = field(default_factory=list)       # 出处在几篇文献里出现
    refused: bool = False
    steps: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "docs": self.docs,
            "hits": self.hits,
            "citations": self.citations,
            "invalid_citations": self.invalid_citations,
            "covered_docs": self.covered_docs,
            "refused": self.refused,
            "steps": self.steps,
            "error": self.error,
        }


def compare_question(
    question: str,
    doc_ids: list[str],
    *,
    per_doc_k: int = 8,
    rewrite: bool = True,
) -> CompareResult:
    steps: list[dict[str, Any]] = []

    def step(node: str, detail: str, t0: float) -> None:
        steps.append({"node": node, "detail": detail, "ms": round((time.perf_counter() - t0) * 1000, 1)})

    if len(doc_ids) < 2:
        return CompareResult(
            question=question, answer="多文对比至少需要两篇文献。", refused=True, steps=steps,
            error="doc_ids < 2",
        )

    # ---- ① 查询改写（复用单篇那套：中文 → 英文术语）----
    t0 = time.perf_counter()
    queries = [question]
    if rewrite and llm.is_configured():
        try:
            reply = llm.chat(
                [
                    {
                        "role": "system",
                        "content": '把用户的中文问题转成 2~3 条英文检索词，只输出 JSON：{"queries": ["...", "..."]}',
                    },
                    {"role": "user", "content": question},
                ],
                temperature=0.0,
                max_tokens=220,
            )
            data = _parse_json(reply.text)
            if data and data.get("queries"):
                queries = [str(x) for x in data["queries"]][:3]
        except Exception as e:  # noqa: BLE001
            step("plan", f"改写失败，用原问题：{e}", t0)

    # ★补一条"结构参数"通用检索词：问"参数量/层数/上下文"时，改写词常常只覆盖主题词，
    #   实测 GPT-1 的 117M 就因为没这条而漏召回（回答里写"未提及"，等于没答到）
    for extra in (
        "number of parameters layers hidden size context length tokens",
        "model specifications table dimensions context window parameters count",
    ):
        if extra not in queries:
            queries.append(extra)
    step("plan", f"每篇各取 {per_doc_k} 块；检索词={queries}", t0)

    # ---- ② 按文献分路召回 ----
    t0 = time.perf_counter()
    per_doc: list[dict[str, Any]] = []
    all_hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for did in doc_ids:
        merged: dict[str, dict[str, Any]] = {}
        for q in queries:
            res = service.search(q, doc_ids=[did], top_k=per_doc_k)
            for rank, h in enumerate(res.hits):
                d = h.as_dict()
                d["score"] = 1.0 / (60 + rank + 1)
                if d["chunk_id"] in merged:
                    merged[d["chunk_id"]]["score"] += d["score"]
                else:
                    merged[d["chunk_id"]] = d
        picked = sorted(merged.values(), key=lambda d: -d["score"])[:per_doc_k]
        per_doc.append(
            {
                "doc_id": did,
                "filename": picked[0]["filename"] if picked else did,
                "hits_n": len(picked),
            }
        )
        for d in picked:
            if d["chunk_id"] not in seen:
                seen.add(d["chunk_id"])
                all_hits.append(d)
    step("retrieve", "；".join(f"{d['filename']}={d['hits_n']} 块" for d in per_doc) or "无命中", t0)

    if not all_hits:
        return CompareResult(
            question=question,
            answer="库中未找到相关内容。",
            docs=per_doc,
            refused=True,
            steps=steps,
        )

    # ---- ③ 生成对比表 ----
    t0 = time.perf_counter()
    if not llm.is_configured():
        return CompareResult(
            question=question, answer="（未配置 LLM key，无法生成对比）",
            docs=per_doc, hits=all_hits, refused=True, steps=steps,
        )

    blocks: list[str] = []
    for d in per_doc:
        blocks.append(f"=== 论文：{d['filename']} ===")
        for h in all_hits:
            if h["doc_id"] == d["doc_id"]:
                blocks.append(f"{h['citation']}\n{h['text']}")
    prompt = COMPARE_PROMPT.replace("{sources}", "\n\n".join(blocks))

    answer = ""
    try:
        reply = llm.chat([{"role": "user", "content": prompt}], temperature=0.1, max_tokens=1100)
        answer = reply.text
        step("answer", f"{reply.model}；{len(answer)} 字；{len(all_hits)} 块输入", t0)
    except Exception as e:  # noqa: BLE001
        return CompareResult(
            question=question, answer=f"生成失败：{e}", docs=per_doc, hits=all_hits,
            refused=True, steps=steps, error=str(e),
        )

    # ---- ④ 出处校验（只认本次召回的 文件名+页码）----
    t0 = time.perf_counter()
    allowed = {(h["filename"], _norm_page(h["page"])) for h in all_hits}
    valid: list[str] = []
    invalid: list[str] = []
    covered: set[str] = set()
    for m in CITE_RE.finditer(answer):
        key = (m.group(1).strip(), _norm_page(m.group(2)))
        if key in allowed:
            if m.group(0) not in valid:
                valid.append(m.group(0))
            covered.add(key[0])
        else:
            invalid.append(m.group(0))
    step(
        "verify",
        f"有效出处 {len(valid)} 条，覆盖 {len(covered)} 篇"
        + (f"；**剔除编造 {len(invalid)} 条**" if invalid else "；无编造"),
        t0,
    )

    return CompareResult(
        question=question,
        answer=answer,
        docs=per_doc,
        hits=all_hits,
        citations=valid,
        invalid_citations=invalid,
        covered_docs=sorted(covered),
        refused=False,
        steps=steps,
    )
