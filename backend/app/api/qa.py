"""S2 · 问答 API（J4 入口）。

POST /api/v1/qa
  { "question": "...", "doc_ids": null, "top_k": 5 }
→ { answer, refused, citations, invalid_citations, hits, steps, orchestrator }

`steps` 就是前端要展示的"AI 思考过程"（plan → retrieve → answer → verify 各步的耗时与结论）。
`invalid_citations` 是被校验剔除的编造出处 —— 前端可以红色提示，评委也看得见我们做了反幻觉。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.rag import answer as qa

router = APIRouter(prefix="/api/v1/qa", tags=["qa"])


class QARequest(BaseModel):
    question: str = Field(..., min_length=1, description="自然语言问题（中英文均可）")
    doc_ids: list[str] | None = Field(default=None, description="限定文献范围；空=全库")
    top_k: int = Field(default=5, ge=1, le=10)


@router.post("", summary="抗幻觉问答（只依据库内文献，逐句挂出处）")
def ask(req: QARequest) -> dict:
    res = qa.answer_question(req.question, doc_ids=req.doc_ids, top_k=req.top_k)
    return res.as_dict()
