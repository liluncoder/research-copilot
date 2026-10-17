"""S3 · 阅读器 API（J5）。

GET  /api/v1/documents/{doc_id}/reader     阅读视图：段落 + 引用索引 + 参考文献反查
POST /api/v1/documents/{doc_id}/translate  段落级翻译（带磁盘缓存）

设计说明：阅读视图一次给全（v1 只有 60 段左右，一次传完约 40KB，比边滚边取稳），
翻译则按需批量取——它是唯一花钱的部分，必须能懒加载 + 缓存命中。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core import storage
from app.services import reader, translate

router = APIRouter(prefix="/api/v1/documents", tags=["reader"])


@router.get("/{doc_id}/reader", summary="阅读视图（段落 / 引用双向索引 / 参考文献）")
def get_reader(doc_id: str) -> dict:
    parsed = storage.get_parsed(doc_id)
    meta = storage.get_meta(doc_id)
    if parsed is None or meta is None:
        raise HTTPException(status_code=404, detail=f"文献库中没有 {doc_id}")
    view = reader.build_reader_view(parsed, doc_id)
    view["meta"] = {
        "filename": meta.filename,
        "title": meta.title,
        "page_count": meta.page_count,
        "doc_type": meta.doc_type,
    }
    return view


class TranslateRequest(BaseModel):
    para_ids: list[str] | None = Field(
        default=None, description="要翻译的段落 id；不传则翻译第一节"
    )
    limit: int = Field(default=6, ge=1, le=12)


@router.post("/{doc_id}/translate", summary="段落级翻译（中文，带缓存）")
def translate_section(doc_id: str, req: TranslateRequest) -> dict:
    parsed = storage.get_parsed(doc_id)
    if parsed is None:
        raise HTTPException(status_code=404, detail=f"文献库中没有 {doc_id}")

    view = reader.build_reader_view(parsed, doc_id)
    paras = view["paragraphs"]
    if not paras:
        return {"items": {}, "cached": 0, "translated": 0, "failed": 0, "errors": []}

    if req.para_ids:
        wanted = set(req.para_ids)
        chosen = [p for p in paras if p["para_id"] in wanted][: req.limit]
    else:
        first_idx = paras[0]["section_index"]
        chosen = [p for p in paras if p["section_index"] == first_idx][: req.limit]

    out = translate.translate_items(
        doc_id, [{"para_id": p["para_id"], "text": p["text"]} for p in chosen]
    )
    out["requested"] = [p["para_id"] for p in chosen]
    return out
