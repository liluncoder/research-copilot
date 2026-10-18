"""重建全部文献的检索索引（换环境/换卷之后用一次）。

用它的场景：
  · 从本地开发切到 Docker（索引目录不同：本地 `backend/chroma_data`，容器内命名卷）
  · 换了 embedding 后端（比如从 hash 换成 BGE-M3）—— 向量维度变了，必须重建
  · 索引目录被清掉、或者上传时索引构建失败过

用法（仓库根目录，二选一）：
    python backend\\tools\\reindex_all.py
    docker compose exec backend python tools/reindex_all.py

★只重建索引，不重新解析 PDF（解析结果在 data/uploads/<id>/parsed.json）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from app.core import storage
    from app.rag import service

    docs = storage.list_documents()
    if not docs:
        print("文献库是空的 —— 先在 /library 上传 PDF，或确认 UPLOAD_DIR 指向正确目录。")
        print(f"当前 UPLOAD_DIR = {storage._root()}")
        return 1

    st = service.index_status()
    print(f"向量后端 {st['embedding_backend']}｜索引后端 {st['store_backend']}｜目录 {st['persist_dir']}")
    print(f"待重建 {len(docs)} 篇\n")

    total = 0
    failed: list[str] = []
    for meta in docs:
        parsed = storage.get_parsed(meta.doc_id)
        if parsed is None:
            failed.append(f"{meta.filename}（缺 parsed.json）")
            continue
        try:
            r = service.index_document(meta.doc_id, parsed, filename=meta.filename)
            total += int(r.get("chunks") or 0)
            print(f"  {meta.filename[:42]:42} {r.get('chunks', 0):4} 块")
        except Exception as e:  # noqa: BLE001
            failed.append(f"{meta.filename}：{type(e).__name__}: {e}")

    print(f"\n合计 {total} 块；失败 {len(failed)} 篇")
    for f in failed:
        print(f"  ! {f}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
