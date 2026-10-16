"""S1 · 文献库 API（上传 / 列表 / 详情 / 删除）。

这是 S1 之前缺的那个"出口"：解析结果过去只能在命令行打印，前端拿不到。
有了它，S3 阅读器才有东西可读，J1 去重才有上传入口。

端点：
    POST   /api/v1/documents              上传 PDF（落盘 + 解析 + 返回标题树）
    GET    /api/v1/documents              文献库列表
    GET    /api/v1/documents/{doc_id}     详情（标题树 + 章节 + 参考文献 + 公式行）
    GET    /api/v1/documents/{doc_id}/pdf 取原始 PDF 字节（S3 阅读器渲染用）
    DELETE /api/v1/documents/{doc_id}     删除
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.core import storage
from app.services.pdf_parser import build_outline_tree, parse_pdf

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

# 每页文字少于这个数 ⇒ 判定为"无文本层的扫描件"（J3 才接 OCR）
SCANNED_CHARS_PER_PAGE = 50


def _meta_out(meta: storage.DocumentMeta) -> dict:
    return meta.as_dict()


@router.post("", summary="上传 PDF 并解析")
async def upload_document(
    file: UploadFile = File(..., description="学术 PDF（含双栏/公式/扫描件）"),
    force: bool = Query(False, description="同内容已存在时也强制重新解析"),
) -> dict:
    content = await file.read()
    try:
        doc_id, meta = storage.save_upload(file.filename or "upload.pdf", content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # 同一份文件（内容哈希相同）已解析过 ⇒ 直接返回，不重复花时间
    parsed = storage.get_parsed(doc_id)
    if parsed is None or force:
        pdf_path = storage.original_path(doc_id)
        assert pdf_path is not None
        t0 = time.perf_counter()
        parsed_doc = parse_pdf(pdf_path)
        meta.parse_seconds = round(time.perf_counter() - t0, 3)

        parsed = parsed_doc.as_dict()
        storage.save_parsed(doc_id, parsed)

        # 用解析结果补全元数据
        meta.page_count = parsed_doc.page_count
        meta.title = parsed_doc.title
        meta.authors = parsed_doc.authors
        meta.abstract_chars = parsed_doc.stats.get("abstract_chars", 0)
        meta.n_headings = parsed_doc.stats.get("headings", 0)
        meta.n_references = parsed_doc.stats.get("references", 0)
        meta.n_math_lines = parsed_doc.stats.get("math_lines", 0)
        meta.warnings = list(parsed_doc.warnings)
        chars = parsed_doc.stats.get("text_chars", 0)
        pages = max(parsed_doc.page_count, 1)
        meta.doc_type = "text"
        if chars / pages < SCANNED_CHARS_PER_PAGE:
            meta.doc_type = "scanned"
            meta.warnings.append(
                f"疑似无文本层的扫描件（每页仅 {chars // pages} 字符）—— 需 OCR，J3 阶段接入 PaddleOCR"
            )
        storage.save_meta(meta)

    flat = parsed["outline"]
    return {
        "meta": _meta_out(meta),
        "outline": build_outline_tree(flat),
        "outline_flat": flat,
        "references_preview": parsed["references"][:5],
    }


@router.get("", summary="文献库列表")
def list_documents() -> dict:
    items = storage.list_documents()
    return {"count": len(items), "items": [_meta_out(m) for m in items]}


@router.get("/{doc_id}", summary="文献详情（标题树 / 章节 / 参考文献 / 公式行）")
def get_document(doc_id: str) -> dict:
    meta = storage.get_meta(doc_id)
    parsed = storage.get_parsed(doc_id)
    if meta is None or parsed is None:
        raise HTTPException(status_code=404, detail=f"文献库中没有 {doc_id}")
    return {
        "meta": _meta_out(meta),
        "outline": build_outline_tree(parsed["outline"]),
        "outline_flat": parsed["outline"],
        "references": parsed["references"],
        "sections": parsed["sections"],
        "math_lines": parsed["math_lines"],
        "abstract": parsed["abstract"],
    }


@router.get("/{doc_id}/pdf", summary="取原始 PDF 字节")
def get_pdf(doc_id: str) -> FileResponse:
    path: Path | None = storage.original_path(doc_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"文献库中没有 {doc_id}")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.delete("/{doc_id}", summary="删除一篇文献")
def delete_document(doc_id: str) -> dict:
    try:
        ok = storage.delete_document(doc_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail=f"文献库中没有 {doc_id}")
    return {"deleted": doc_id}
