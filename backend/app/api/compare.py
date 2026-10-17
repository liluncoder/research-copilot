"""S2 · 多文对比 API（J2 的"多文对比问答"判据）。

POST /api/v1/compare
  { "question": "...", "doc_ids": ["id1","id2", ...], "per_doc_k": 4 }
→ { answer(表格+要点), docs, hits, citations, invalid_citations, covered_docs, steps }
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core import storage
from app.rag import compare

router = APIRouter(prefix="/api/v1/compare", tags=["compare"])


class CompareRequest(BaseModel):
    question: str = Field(..., min_length=1)
    doc_ids: list[str] = Field(..., min_length=2, description="至少两篇")
    per_doc_k: int = Field(default=4, ge=1, le=8)


@router.post("", summary="多文对比问答（按文献分路召回 + 表格化回答，逐格挂出处）")
def do_compare(req: CompareRequest) -> dict:
    missing = [d for d in req.doc_ids if storage.get_parsed(d) is None]
    if missing:
        raise HTTPException(status_code=404, detail=f"文献库中没有：{missing}")
    return compare.compare_question(req.question, req.doc_ids, per_doc_k=req.per_doc_k).as_dict()
