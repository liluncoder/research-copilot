"""S7 · 未来工作探索（官方赛题 1.5.4）。

官方原文：「根据多篇论文的 Future Work 部分，Agent 提出一些下一步值得继续探索的方向，
要考虑论文的时间以及最新的工作，**不要提出已经被最新论文尝试过的 idea**。」

★三个诚实性约束（这是本模块全部的设计难度所在）：
  1. **素材只能来自原文**：方向必须由各篇论文里真实存在的 Future Work / Limitation 句子支撑，
     每条都回挂一个 `[[ref:doc_id]]`；模型点名不存在的 id ⇒ 丢进 `invalid_refs`，绝不留在正文。
  2. **"是否已有人做"只在库内判定**：我们没有全 arXiv 的阅读记录，所以能判定的只有"本库这些论文
     有没有把这件事做了"。判不了就写"库内未见"，**不许断言"全球还没人做"** —— 这是能力边界，写进 notes。
  3. **时间感知**：每条方向带最新Evidence 的年份；若提出该方向的论文年份晚于库内所有相关工作，
     标 `freshness=新`，否则标 `已被覆盖`（依据库内年份，不猜外部文献）。

★与 J6 自动综述同源：模型读的是**抽好的句子 + 元数据**，不是全文，因此它编不出原文没有的 idea。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.core import llm, storage

# 章节标题里出现这些词 ⇒ 候选来源节
FUTURE_LABEL = re.compile(
    r"future|future\s+work|future\s+direction|open\s+(problem|question)|limitation|"
    r"discussion|conclusion|outlook|perspective",
    re.I,
)
# 句子里出现这些 ⇒ 真的是在说"以后做什么"
FUTURE_SENT = re.compile(
    r"future\s+work|in\s+the\s+future|future\s+research|further\s+(work|study|investigation|research)|"
    r"we\s+(plan|intend|leave|hope|expect)\s+to|promising\s+(direction|avenue|future)|"
    r"remains?\s+(open|unexplored|an\s+open)|open\s+(problem|question)|can\s+be\s+extended|"
    r"not\s+(yet\s+)?addressed|worth\s+(exploring|investigating)|"
    r"值得|未来工作|有待|进一步研究|尚未|下一步",
    re.I,
)
SENT_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")

MAX_DOCS = 12
MAX_PER_DOC = 3

PROMPT = """你在帮研究者找"下一步值得做什么"。下面是若干论文里**原文摘出的** Future Work / Limitation 句子
（每条带一个 id 标记，年份是该论文的发表年）。

要求输出 JSON（不要 markdown 代码块、不要解释）：
{{"directions": [{{"idea": "方向，一句话", "why": "为什么值得做，一句话",
  "basis": "[[ref:doc_id]]", "status": "库内未见 | 库内已有人做"}}]}}

硬性规则：
1. `basis` **必须**是下面出现过的 id，不许编 id、不许写"某研究"：
2. 只能根据给出的句子提方向，**不许引入这些句子之外的 idea**；
3. 3~5 条即可，优先"多篇共同指向"的方向；
4. `status` 只能写"库内未见"或"库内已有人做"。如果你在下面这些论文的句子里看到有人已经在做，
   写"库内已有人做"；看不出来就写"库内未见"——不要猜。
5. 不要写"根据您提供的内容"这类客套话。

【原文摘句】
{snippets}
"""


@dataclass
class Snippet:
    doc_id: str
    title: str
    year: int | None
    section: str
    text: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "year": self.year,
            "section": self.section,
            "text": self.text,
        }


@dataclass
class Direction:
    idea: str
    why: str = ""
    doc_id: str = ""
    title: str = ""
    year: int | None = None
    status: str = "库内未见"

    def as_dict(self) -> dict[str, Any]:
        return {
            "idea": self.idea,
            "why": self.why,
            "doc_id": self.doc_id,
            "source": f"{self.title}（{self.year}）" if self.year else self.title,
            "year": self.year,
            "status": self.status,
        }


@dataclass
class FutureWorkResult:
    n_docs: int = 0
    snippets: list[Snippet] = field(default_factory=list)
    directions: list[Direction] = field(default_factory=list)
    invalid_refs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    model: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_docs": self.n_docs,
            "n_snippets": len(self.snippets),
            "snippets": [s.as_dict() for s in self.snippets],
            "directions": [d.as_dict() for d in self.directions],
            "n_directions": len(self.directions),
            "invalid_refs": self.invalid_refs,
            "notes": self.notes,
            "model": self.model,
            "error": self.error,
        }


def _year(parsed: dict[str, Any]) -> int | None:
    head = str(parsed.get("full_text") or "")[:4000]
    years = [int(y) for y in re.findall(r"\b(19[89]\d|20[0-2]\d)\b", head)]
    years = [y for y in years if 1990 <= y <= 2026]
    return max(years) if years else None


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(text or "") if s.strip()]


def collect(doc_ids: list[str] | None, res: FutureWorkResult) -> None:
    metas = {m.doc_id: m for m in storage.list_documents()}
    ids = doc_ids or list(metas.keys())
    for did in ids[:MAX_DOCS]:
        parsed = storage.get_parsed(did)
        if not parsed:
            continue
        meta = metas.get(did)
        title = str(parsed.get("title") or (meta.title if meta else "") or (meta.filename if meta else did)).strip()
        year = _year(parsed)
        picked = 0
        # ① 先找标题命中的节（Future Work / Limitation / Conclusion…）
        sections = parsed.get("sections") or []
        ordered = [s for s in sections if FUTURE_LABEL.search(str(s.get("label") or ""))]
        ordered += [s for s in sections if s not in ordered]  # 兜底：全文再扫一遍
        for sec in ordered:
            for para in sec.get("paragraphs") or []:
                for sent in _sentences(str(para)):
                    if not FUTURE_SENT.search(sent):
                        continue
                    if len(sent) < 24 or len(sent) > 480:
                        continue
                    res.snippets.append(
                        Snippet(
                            doc_id=did,
                            title=title,
                            year=year,
                            section=str(sec.get("label") or ""),
                            text=re.sub(r"\s+", " ", sent),
                        )
                    )
                    picked += 1
                    if picked >= MAX_PER_DOC:
                        break
                if picked >= MAX_PER_DOC:
                    break
            if picked >= MAX_PER_DOC:
                break
        if picked:
            res.n_docs += 1


REF = re.compile(r"\[\[ref:([a-zA-Z0-9_\-]{4,32})\]\]")
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _parse(text: str) -> dict[str, Any] | None:
    m = _FENCE.search(text)
    raw = (m.group(1) if m else text).strip()
    i, j = raw.find("{"), raw.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        obj = json.loads(raw[i : j + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def ask_llm(res: FutureWorkResult) -> None:
    if not res.snippets:
        res.error = "库里没有抽到任何 Future Work 句（需要英文 future work / limitation 段，或中文『未来工作』段）"
        return
    if not llm.is_configured():
        res.notes.append("未配置 LLM key ⇒ 只返回原文摘句，不生成方向")
        return

    lines = []
    for s in res.snippets:
        lines.append(f"[[ref:{s.doc_id}]] ({s.year or 'n.a.'}) 〔{s.title}·{s.section}〕{s.text}")
    prompt = PROMPT.format(snippets="\n".join(lines))
    try:
        reply = llm.chat(
            [
                {"role": "system", "content": "你是科研选题助手。只输出 JSON，不解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=900,
        )
    except Exception as e:  # noqa: BLE001
        res.error = f"LLM 调用失败：{type(e).__name__}: {e}"
        return
    res.model = reply.model

    obj = _parse(reply.text)
    if obj is None:
        res.error = "模型输出不是合法 JSON"
        return

    by_doc = {s.doc_id: s for s in res.snippets}
    for item in obj.get("directions") or []:
        if not isinstance(item, dict):
            continue
        idea = str(item.get("idea") or "").strip()
        if not idea:
            continue
        basis = str(item.get("basis") or "")
        ids = REF.findall(basis) or REF.findall(str(item))
        valid = [i for i in ids if i in by_doc]
        for bad in [i for i in ids if i not in by_doc]:
            res.invalid_refs.append(bad)
        if not valid:
            # 没有合法出处 ⇒ 这条方向不许进结果（与 J8 同一条纪律）
            res.invalid_refs.append(f"(无出处){idea[:20]}")
            continue
        src = by_doc[valid[0]]
        res.directions.append(
            Direction(
                idea=idea,
                why=str(item.get("why") or "").strip(),
                doc_id=src.doc_id,
                title=src.title,
                year=src.year,
                status="库内已有人做" if "已有人做" in str(item.get("status") or "") else "库内未见",
            )
        )


def build(doc_ids: list[str] | None = None) -> FutureWorkResult:
    res = FutureWorkResult()
    collect(doc_ids, res)
    if res.n_docs == 0:
        res.error = "选定文献里没有可用的 Future Work 段落（可换一批论文，或确认解析结果含正文）"
        return res
    res.notes.append(
        "能力边界：'是否已有人做'只在**本库**范围内判断；没有全 arXiv 阅读记录，"
        "因此不承诺'全球尚无人做'。"
    )
    ask_llm(res)
    # 按年份倒序：新论文的 future work 优先呈现
    res.directions.sort(key=lambda d: (d.year or 0), reverse=True)
    return res
