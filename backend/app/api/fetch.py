"""S7 · arXiv 自动下载 / 推荐 API（官方 1.4.1 / 1.4.3 降级版）。

    GET  /api/v1/arxiv/search?q=标题&max_results=5     只检索，不落盘
    POST /api/v1/arxiv/fetch                           标题 → 下载 → 入库（幂等）
    GET  /api/v1/arxiv/related/{doc_id}                按库内这篇找同类新论文（标有无 GitHub 代码）

★1.4.2（sickle 定时刷新）与 1.4.3 的协同过滤未做，见技术文档的已知限制。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import arxiv

router = APIRouter(prefix="/api/v1/arxiv", tags=["arxiv"])


@router.get("/search", summary="按标题检索 arXiv（不下载）")
def search(q: str = Query(..., min_length=2), max_results: int = Query(5, ge=1, le=10)) -> dict:
    try:
        cands = arxiv.search(q, max_results=max_results)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"arXiv 不可达：{type(e).__name__}: {e}") from e
    return {"query": q, "n": len(cands), "candidates": [c.as_dict() for c in cands]}


class FetchRequest(BaseModel):
    query: str = Field(..., min_length=2, description="论文标题（或关键词）")
    arxiv_id: str | None = Field(default=None, description="已知 arXiv id 时直接下这一篇，跳过标题筛选")
    max_results: int = Field(default=5, ge=1, le=10)


@router.post("/fetch", summary="给定论文名称 → 自动下载并入库")
def fetch(req: FetchRequest) -> dict:
    res = arxiv.fetch_and_ingest(req.query, arxiv_id=req.arxiv_id, max_results=req.max_results)
    if res.error and not res.doc_id:
        raise HTTPException(status_code=400, detail=res.error)
    return res.as_dict()


@router.get("/related/{doc_id}", summary="同类新论文推荐（标有无 GitHub 代码）")
def related(doc_id: str, max_results: int = Query(5, ge=1, le=10)) -> dict:
    cands = arxiv.recommend_related(doc_id, max_results=max_results)
    return {"doc_id": doc_id, "n": len(cands), "candidates": [c.as_dict() for c in cands]}
