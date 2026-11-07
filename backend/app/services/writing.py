"""S6 · 论文框架生成 + 无幻觉 References（J8）。

★核心机制：**参考文献不是"让模型写"，而是"让模型点名"**。
   给模型的候选清单只有库内文献（每篇带一个 `[[ref:<doc_id>]]` 标记），
   模型只能引用清单里的 id；它写不出一个不存在的文献。
   生成后我们再把标记换成 [1][2]…，参考文献条目**完全由本地元数据渲染**，
   模型连标题都没机会编。

★被判定为"编造"的标记（不在候选清单里的）会被**直接从正文删除**并计入
   `invalid_refs` —— 宁可掉一处引用，也不让假引用留在论文里。
   这是与 J7"图注只看统计量"同源的设计：把幻觉堵在信息通道上，不靠提示词求它别编。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core import llm
from app.core import storage
from app.rag import service

REF_MARK = re.compile(r"\[\[ref:([a-zA-Z0-9_\-]{4,32})\]\]")

FRAMEWORK_PROMPT = """你在帮研究者起草一篇论文的框架。主题：{topic}

只依据下面给出的【库内文献候选】写作，**不得引用候选之外任何文献**。

写作要求：
1. 三个小节，中文：
   - `## Abstract`：120~180 字，说明问题、方法思路、预期贡献
   - `## Introduction`：180~260 字，交代背景与动机，指出研究空白
   - `## Related Work`：180~260 字，按"流派"归纳候选文献，不要逐篇罗列
2. **凡提到某篇候选文献的工作，必须在该句末尾写 `[[ref:<id>]]`**（id 用候选清单里给出的）
3. 不要在正文里写作者名、年份、期刊名 —— 那些由系统自动生成参考文献表
4. 不要写"本文将"以外的承诺，不要编造实验数字
5. 候选清单为空时：只写方法思路，**一个 `[[ref:...]]` 都不要写**
6. 候选文献与该句内容**不相关就不要引用**——宁可这一句没有引用，也不要硬挂一篇

【库内文献候选】
{candidates}
"""

TRANSLATE_PROMPT = """把下面的中文摘要译成**学术英文摘要**（信息论文体）。

要求：
- 200 words 以内，单段
- 用被动语态与名词化表达（如 "is proposed"、"experimental results indicate"）
- 专业术语保留通行英文（SNN、eligibility trace、credit assignment、BPTT 等）
- 不添加原文没有的结论或数据
- 只输出英文正文，不要标题、不要解释

中文摘要：
{text}
"""


@dataclass
class FrameworkResult:
    topic: str
    sections: dict[str, str] = field(default_factory=dict)
    references: list[dict[str, Any]] = field(default_factory=list)
    invalid_refs: list[str] = field(default_factory=list)
    n_candidates: int = 0
    n_citations: int = 0
    model: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "sections": self.sections,
            "references": self.references,
            "invalid_refs": self.invalid_refs,
            "n_candidates": self.n_candidates,
            "n_citations": self.n_citations,
            "model": self.model,
            "error": self.error,
        }


YEAR_RE = re.compile(r"\b(19[89]\d|20[0-2]\d)\b")


def _guess_year(parsed: dict[str, Any]) -> int | None:
    """从首页文本里猜发表年（arXiv 戳、版权行都带年份）。纯展示用，拿不准就 None。"""
    head = str(parsed.get("full_text") or "")[:4000]
    years = [int(y) for y in YEAR_RE.findall(head)]
    years = [y for y in years if 1990 <= y <= 2026]
    return max(years) if years else None


def _candidates(doc_ids: list[str] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for meta in storage.list_documents():
        if doc_ids and meta.doc_id not in doc_ids:
            continue
        parsed = storage.get_parsed(meta.doc_id)
        if parsed is None:
            continue
        out.append(
            {
                "doc_id": meta.doc_id,
                "title": (meta.title or meta.filename).strip(),
                "authors": meta.authors,
                "year": _guess_year(parsed),
                "filename": meta.filename,
            }
        )
    return out


def _evidence(topic: str, doc_ids: list[str]) -> str:
    """每篇候选文献抽 1 段相关证据，作为"只能依据这些内容写"的材料。"""
    blocks: list[str] = []
    for did in doc_ids[:8]:
        try:
            res = service.search(topic, doc_ids=[did], top_k=1)
        except Exception:  # noqa: BLE001
            continue
        if not res.hits:
            continue
        h = res.hits[0]
        blocks.append(f"（{h.chunk.filename}·{h.chunk.section_label}）{h.chunk.text[:420]}")
    return "\n\n".join(blocks[:8])


def build_framework(
    topic: str,
    doc_ids: list[str] | None = None,
    *,
    use_evidence: bool = True,
) -> FrameworkResult:
    cands = _candidates(doc_ids)
    res = FrameworkResult(topic=topic, n_candidates=len(cands))

    if not llm.is_configured():
        res.error = "未配置 LLM key"
        return res

    lines = []
    for c in cands:
        who = ", ".join(c["authors"][:3]) if c["authors"] else "（作者未知）"
        year_s = f" ({c['year']})" if c["year"] else ""
        lines.append("- [[ref:{}]] {} — {}{}".format(c["doc_id"], c["title"], who, year_s))
    cand_text = "\n".join(lines) if lines else "（空：库里没有文献）"

    prompt = FRAMEWORK_PROMPT.format(topic=topic, candidates=cand_text)
    if use_evidence and cands:
        ev = _evidence(topic, [c["doc_id"] for c in cands])
        if ev:
            prompt += f"\n\n【可用于归纳的片段】\n{ev}"

    try:
        reply = llm.chat([{"role": "user", "content": prompt}], temperature=0.35, max_tokens=1400)
    except Exception as e:  # noqa: BLE001
        res.error = str(e)
        return res
    res.model = reply.model

    text = reply.text
    # ---- 校验标记：不在候选里的直接删掉（不留假引用） ----
    valid_ids = {c["doc_id"] for c in cands}
    seen: dict[str, int] = {}
    invalid: list[str] = []

    def repl(m: re.Match[str]) -> str:
        rid = m.group(1)
        if rid not in valid_ids:
            invalid.append(rid)
            return ""   # ★删掉整条标记，宁缺毋滥
        if rid not in seen:
            seen[rid] = len(seen) + 1
        return f"[{seen[rid]}]"

    text = REF_MARK.sub(repl, text)

    # ---- 切分小节 ----
    sections: dict[str, str] = {}
    cur = None
    buf: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^\s*#{1,3}\s*(Abstract|Introduction|Related Work)\s*$", line, re.I)
        if m:
            if cur:
                sections[cur] = "\n".join(buf).strip()
            cur = m.group(1)
            buf = []
        elif cur:
            buf.append(line)
    if cur:
        sections[cur] = "\n".join(buf).strip()
    if not sections:  # 模型没按格式写 ⇒ 整篇当 Abstract，别丢内容
        sections = {"Abstract": text.strip()}

    # ---- 参考文献：完全由本地元数据渲染（按出现顺序编号） ----
    by_id = {c["doc_id"]: c for c in cands}
    references = []
    for did, n in sorted(seen.items(), key=lambda kv: kv[1]):
        c = by_id[did]
        references.append(
            {
                "n": n,
                "doc_id": did,
                "title": c["title"],
                "authors": c["authors"],
                "year": c["year"],
                "source": c["filename"],
            }
        )

    res.sections = sections
    res.references = references
    res.invalid_refs = invalid
    res.n_citations = len(seen)
    return res


def translate_abstract(zh: str) -> dict[str, Any]:
    if not llm.is_configured():
        return {"text": "", "error": "未配置 LLM key"}
    try:
        reply = llm.chat(
            [{"role": "user", "content": TRANSLATE_PROMPT.format(text=zh[:3000])}],
            temperature=0.2,
            max_tokens=700,
        )
        return {"text": reply.text.strip(), "model": reply.model}
    except Exception as e:  # noqa: BLE001
        return {"text": "", "error": str(e)}
