"""PDF 入库的唯一入口（S1 上传 与 S7 自动下载 共用）。

★为什么单独抽一层：官方赛题 1.4.1 要求"给定论文名称自动下载论文并入库"，
   如果下载路径另写一份"存盘 + 解析 + 建索引 + 补元数据"，两份逻辑迟早不一致
   （比如扫描件判定的阈值、索引失败的 warning 处理）。所以统一收在这里。

对外只暴露一个函数：`ingest_pdf(filename, content, force=False)`
  → (doc_id, meta, parsed)
"""

from __future__ import annotations

import time
from typing import Any

from app.core import storage
from app.rag import service as rag_service
from app.services.pdf_parser import parse_pdf

# 每页文字少于这个数 ⇒ 判定为"无文本层的扫描件"
SCANNED_CHARS_PER_PAGE = 50


def ingest_pdf(filename: str, content: bytes, *, force: bool = False) -> tuple[str, storage.DocumentMeta, dict[str, Any]]:
    doc_id, meta = storage.save_upload(filename, content)

    parsed = storage.get_parsed(doc_id)
    if parsed is None or force:
        pdf_path = storage.original_path(doc_id)
        assert pdf_path is not None
        t0 = time.perf_counter()
        parsed_doc = parse_pdf(pdf_path)
        meta.parse_seconds = round(time.perf_counter() - t0, 3)

        parsed = parsed_doc.as_dict()
        storage.save_parsed(doc_id, parsed)

        # 解析完立刻建检索索引（失败不阻塞入库 —— 但不能静默，记进 warnings）
        try:
            idx = rag_service.index_document(doc_id, parsed, filename=meta.filename)
            if idx.get("warning"):
                meta.warnings.append(f"检索索引：{idx['warning']}")
        except Exception as e:  # noqa: BLE001
            meta.warnings.append(f"检索索引构建失败（可稍后重建）：{type(e).__name__}: {e}")

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
                f"疑似无文本层的扫描件（每页仅 {chars // pages} 字符）—— 需 OCR"
            )
        storage.save_meta(meta)

    return doc_id, meta, parsed
