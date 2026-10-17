"""S2 · 检索 API（前端问答/阅读器都要用）。

端点：
    POST /api/v1/search        混合检索，返回带出处的命中
    GET  /api/v1/search/status 索引状态（用了哪个向量后端 / 有多少块）
    POST /api/v1/search/index/{doc_id}  手动重建某篇文献的索引
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core import storage
from app.rag import service

router = APIRouter(prefix="/api/v1/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="自然语言问题（中英文均可）")
    doc_ids: list[str] | None = Field(default=None, description="限定在这些文献内检索；空=全库")
    top_k: int = Field(default=5, ge=1, le=20)


@router.post("", summary="混合检索（Dense + BM25 → RRF），每条命中带出处")
def do_search(req: SearchRequest) -> dict:
    res = service.search(req.query, doc_ids=req.doc_ids, top_k=req.top_k)
    return {
        "query": res.query,
        "confident": res.confident,
        "count": len(res.hits),
        "backend": {"store": res.backend, "embedding": res.embedding_backend},
        "hits": [h.as_dict() for h in res.hits],
    }


@router.get("/status", summary="索引状态")
def status() -> dict:
    return service.index_status()


@router.post("/index/{doc_id}", summary="重建某篇文献的索引")
def reindex(doc_id: str) -> dict:
    parsed = storage.get_parsed(doc_id)
    meta = storage.get_meta(doc_id)
    if parsed is None or meta is None:
        raise HTTPException(status_code=404, detail=f"文献库中没有 {doc_id}")
    return service.index_document(doc_id, parsed, filename=meta.filename)
