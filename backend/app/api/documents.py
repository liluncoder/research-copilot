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
from app.rag import service as rag_service
from app.schemas import DedupResolveRequest
from app.services import dedup
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

        # S2：解析完立刻建检索索引（失败不阻塞上传 —— 但不能静默，记进 warnings）
        try:
            idx = rag_service.index_document(doc_id, parsed, filename=meta.filename)
            if idx.get("warning"):
                meta.warnings.append(f"检索索引：{idx['warning']}")
        except Exception as e:  # noqa: BLE001
            meta.warnings.append(f"检索索引构建失败（可稍后重建）：{type(e).__name__}: {e}")

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
    # ---- J1 去重预警：跟库里每一篇比一遍 ----
    parsed["doc_id"] = doc_id
    candidates = dedup.find_duplicates(
        parsed, meta.filename, storage.iter_parsed(), exclude_doc_id=doc_id
    )
    return {
        "meta": _meta_out(meta),
        "outline": build_outline_tree(flat),
        "outline_flat": flat,
        "references_preview": parsed["references"][:5],
        "dedup": {
            "has_warning": bool(candidates),
            "threshold": dedup.SIMILARITY_THRESHOLD,
            "metric": f"正文 {dedup.SHINGLE_N}-gram Jaccard",
            "candidates": [c.as_dict() for c in candidates],
            "exists_newer": any(c.existing_is_newer for c in candidates),
        },
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
        "tables": parsed.get("tables", []),
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
        if ok:
            try:
                rag_service.delete_document_index(doc_id)
            except Exception:  # noqa: BLE001 - 索引残留不影响删除主流程
                pass
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail=f"文献库中没有 {doc_id}")
    return {"deleted": doc_id}


@router.get(
    "/{doc_id}/compare/{other_id}",
    summary="J1：对比两版差异（结构化差异 + 文字摘要）",
)
def compare_documents(doc_id: str, other_id: str, use_llm: bool = Query(True)) -> dict:
    a, b = storage.get_parsed(doc_id), storage.get_parsed(other_id)
    ma, mb = storage.get_meta(doc_id), storage.get_meta(other_id)
    if a is None or b is None or ma is None or mb is None:
        raise HTTPException(status_code=404, detail="要对比的两篇必须都在文献库里")

    # 约定：doc_id 为"旧"，other_id 为"新"（调用方按版本号决定顺序）
    diff = dedup.diff_versions(a, b, old_label=ma.filename, new_label=mb.filename)
    summary = dedup.summarize_diff_with_llm(diff) if use_llm else ""
    return {
        "diff": diff,
        "summary": summary,
        "summary_source": "llm" if summary else "deterministic",
        "fallback_summary": dedup.deterministic_summary(diff),
    }


@router.post("/dedup/resolve", summary="J1：按用户选择处理重复（覆盖 / 保留 / 放弃）")
def resolve_dedup(req: DedupResolveRequest) -> dict:
    action = req.action
    if action not in {"keep_both", "replace_existing", "discard_new"}:
        raise HTTPException(
            status_code=400,
            detail="action 必须是 keep_both / replace_existing / discard_new",
        )
    if storage.get_meta(req.doc_id) is None:
        raise HTTPException(status_code=404, detail=f"文献库中没有 {req.doc_id}")

    if action == "keep_both":
        return {"action": action, "kept": req.doc_id, "deleted": None}

    if action == "discard_new":
        storage.delete_document(req.doc_id)
        return {"action": action, "kept": req.target_doc_id, "deleted": req.doc_id}

    # replace_existing：删掉库里那份，留下新的
    if not req.target_doc_id:
        raise HTTPException(status_code=400, detail="replace_existing 需要提供 target_doc_id")
    if storage.get_meta(req.target_doc_id) is None:
        raise HTTPException(status_code=404, detail=f"文献库中没有 {req.target_doc_id}")
    storage.delete_document(req.target_doc_id)
    return {"action": action, "kept": req.doc_id, "deleted": req.target_doc_id}
