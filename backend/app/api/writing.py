"""S6 · 写作 Copilot API（J7 / J8）。

POST /api/v1/writing/figure      表格 → 图表 + 图注（图注只基于统计量）
POST /api/v1/writing/framework   论文框架 + 只从库内选的 References
POST /api/v1/writing/translate   中文摘要 → 学术英文摘要
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.services import figures, writing

router = APIRouter(prefix="/api/v1/writing", tags=["writing"])

MAX_CSV_BYTES = 8 * 1024 * 1024


@router.post("/figure", summary="CSV → 图表 + 图注（图注只看统计量）")
async def make_figure(
    file: UploadFile = File(..., description="CSV（第一行是表头）"),
    metric: str | None = None,
    group_by: str | None = None,
    kind: str = "line",
) -> dict:
    content = await file.read()
    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV 太大（上限 8MB）")
    try:
        res = figures.analyze_table(
            content=content,
            filename=file.filename or "data.csv",
            metric=metric,
            group_by=group_by,
            kind=kind if kind in {"line", "bar", "scatter"} else "line",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return res.as_dict()


class FrameworkRequest(BaseModel):
    topic: str = Field(..., min_length=2, description="论文主题/研究问题")
    doc_ids: list[str] | None = Field(default=None, description="限定候选文献；空=全库")
    use_evidence: bool = Field(default=True, description="是否把库内相关片段作为归纳材料")


@router.post("/framework", summary="论文框架 + 无幻觉 References（只从库内文献选）")
def make_framework(req: FrameworkRequest) -> dict:
    return writing.build_framework(req.topic, req.doc_ids, use_evidence=req.use_evidence).as_dict()


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=10)
    target: str = Field(default="en", description="目前只支持 zh→en")


@router.post("/translate", summary="中文摘要 → 学术英文摘要")
def translate(req: TranslateRequest) -> dict:
    out = writing.translate_abstract(req.text)
    out["target"] = req.target
    return out
