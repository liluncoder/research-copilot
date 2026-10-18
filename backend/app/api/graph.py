"""S5 · 引用图谱 API（J6）。

GET  /api/v1/graph              全图 + 展示子图 + 双指标排行
POST /api/v1/graph/review       自动综述（★LLM 只读"结构化排行数据"，不读全文）

★自动综述为什么必须只喂结构化数据：
  如果让模型读原文再总结，它会自由发挥、编造"某某论文提出某某方法"。
  这里只给它：标题、年份、被本库几篇引用、PageRank 值、是否在库内。
  它只能在这些字段之间做归纳 ⇒ 结构性防幻觉（技术文档里的设计亮点，S6 的 J8 同源）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core import llm
from app.services import graph

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])

REVIEW_PROMPT = """你是文献计量分析助手。下面是一张引用图谱的**结构化统计结果**（不是论文原文）。

只依据这些字段写一段 4~6 句的中文综述，要求：
1. 只能提到下面出现过的论文标题，**不得虚构任何论文、作者或方法**
2. 必须点明：哪几篇是本库内的文献、哪几篇是它们共同引用的外部基石文献
3. 解释"为什么它是基石"时只能用给出的数字（被引次数 / PageRank 值）
4. 最后一句指出这个领域的一条主线（依据标题与年份推断，不要编方法细节）
5. 不要写"根据您提供的数据"这类客套话

【统计表】
{rows}

【图谱规模】
节点 {n_nodes}（库内 {n_local} / 外部 {n_external}），边 {n_edges}，
参考文献条目 {n_refs}，其中 {n_matched} 条匹配到库内论文。
"""


@router.get("", summary="引用图谱（全图统计 + 可渲染的展示子图 + 双指标排行）")
def get_graph(limit: int = 40, top: int = 12) -> dict:
    limit = max(10, min(limit, 120))
    return graph.build_graph(display_limit=limit, top_n=max(3, min(top, 30)))


class ReviewRequest(BaseModel):
    top: int = Field(default=8, ge=3, le=20)


@router.post("/review", summary="基石论文自动综述（只依据结构化统计，不读原文）")
def graph_review(req: ReviewRequest) -> dict:
    g = graph.build_graph(display_limit=40, top_n=req.top)
    if not g["nodes"]:
        raise HTTPException(status_code=400, detail="文献库为空，无法生成综述")
    if not llm.is_configured():
        return {"review": "", "error": "未配置 LLM key", "facts": []}

    # 只取结构化字段，绝不把正文塞进去
    rows = []
    seen: set[str] = set()
    for bucket in ("pagerank", "in_degree"):
        for n in g["foundational"][bucket]:
            if n["id"] in seen:
                continue
            seen.add(n["id"])
            rows.append(
                f"- {n['label']}｜年份 {n['year'] or '未知'}｜本库内：{'是' if n['in_library'] else '否'}"
                f"｜被本库引用 {n['cited_by_local']} 次｜PageRank(核心) {n['pagerank_core']:.4f}"
            )

    prompt = REVIEW_PROMPT.format(
        rows="\n".join(rows),
        n_nodes=g["stats"]["n_nodes"],
        n_local=g["stats"]["n_local"],
        n_external=g["stats"]["n_external"],
        n_edges=g["stats"]["n_edges"],
        n_refs=g["stats"]["n_reference_entries"],
        n_matched=g["stats"]["n_matched_to_local"],
    )
    try:
        reply = llm.chat([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=700)
    except Exception as e:  # noqa: BLE001
        return {"review": "", "error": str(e), "facts": rows}

    # ★把"允许提到的标题"原样返回，前端/判据可以核对综述里有没有编造论文
    return {
        "review": reply.text,
        "facts": rows,
        "allowed_titles": [n["label"] for n in g["foundational"]["pagerank"]]
        + [n["label"] for n in g["foundational"]["in_degree"]],
        "stats": g["stats"],
        "model": reply.model,
    }
