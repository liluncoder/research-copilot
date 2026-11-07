"""S1 API 复跑脚本（★评委 clone 后可离线跑，不需要起服务）。

用 FastAPI 的 TestClient 直接打内存里的应用，覆盖：
    上传 → 解析 → 入库 → 列表 → 详情 → 取原始 PDF → 重复上传（精确去重）→ 删除

用法：
    python tests/verify_s1_api.py

★故意把 UPLOAD_DIR 指到临时目录，避免污染你本机真实的文献库（data/uploads）。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# ★必须在 import app 之前改掉存储目录（config 是 lru_cache 的，导入后就定死了）
_TMP = tempfile.mkdtemp(prefix="verify_s1_api_")
os.environ["UPLOAD_DIR"] = _TMP

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PDF = ROOT / "tests" / "fixtures" / "pdf" / "1706.03762v1.pdf"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not PDF.exists():
        print(f"✗ 找不到输入 PDF：{PDF}")
        return 2

    client = TestClient(app)
    bad = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal bad
        if cond:
            print(f"  ✓ {label}")
        else:
            print(f"  ✗ {label} {extra}")
            bad += 1

    print(f"临时文献库：{_TMP}")
    print(f"输入：{PDF.name}")

    # ---- 1. 上传 + 解析 ----
    print("\n[1] POST /api/v1/documents")
    with PDF.open("rb") as fh:
        r = client.post("/api/v1/documents", files={"file": (PDF.name, fh, "application/pdf")})
    check("HTTP 200", r.status_code == 200, f"实得 {r.status_code} {r.text[:200]}")
    if r.status_code != 200:
        return 1
    up = r.json()
    meta = up["meta"]
    doc_id = meta["doc_id"]
    print(f"      doc_id={doc_id}  解析 {meta['parse_seconds']}s")
    check("标题正确", meta["title"] == "Attention Is All You Need", f"实得 {meta['title']!r}")
    check("页数 15", meta["page_count"] == 15, f"实得 {meta['page_count']}")
    check("判定为文本层 PDF", meta["doc_type"] == "text", f"实得 {meta['doc_type']}")
    check("标题数 25", meta["n_headings"] == 25, f"实得 {meta['n_headings']}")
    check("参考文献 36", meta["n_references"] == 36, f"实得 {meta['n_references']}")
    check("公式行 102", meta["n_math_lines"] == 102, f"实得 {meta['n_math_lines']}")
    check("无警告", meta["warnings"] == [], f"实得 {meta['warnings']}")

    # ---- 2. 标题树结构 ----
    print("\n[2] 标题树嵌套结构")
    tree = up["outline"]
    check("顶层 10 个节点", len(tree) == 10, f"实得 {len(tree)}")
    by_label = {n["label"]: n for n in tree}
    check("含 '3 Model Architecture'", "3 Model Architecture" in by_label)
    if "3 Model Architecture" in by_label:
        subs = by_label["3 Model Architecture"]["children"]
        check("其下 5 个二级", len(subs) == 5, f"实得 {len(subs)}")
        att = next((c for c in subs if c["label"].startswith("3.2 ")), None)
        check("3.2 Attention 存在", att is not None)
        if att:
            check("其下 3 个三级", len(att["children"]) == 3, f"实得 {len(att['children'])}")

    # ---- 3. 重复上传：精确去重 ----
    print("\n[3] 同内容重复上传（精确去重，不重新解析）")
    with PDF.open("rb") as fh:
        r2 = client.post("/api/v1/documents", files={"file": (PDF.name, fh, "application/pdf")})
    check("HTTP 200", r2.status_code == 200)
    check("doc_id 相同", r2.json()["meta"]["doc_id"] == doc_id)
    check("标记 duplicate_of", r2.json()["meta"]["duplicate_of"] == doc_id)
    check("列表仍只有 1 篇", client.get("/api/v1/documents").json()["count"] == 1)

    # ---- 4. 详情 ----
    print("\n[4] GET /api/v1/documents/{id}")
    det = client.get(f"/api/v1/documents/{doc_id}").json()
    check("章节数 25", len(det["sections"]) == 25, f"实得 {len(det['sections'])}")
    check("参考文献 36", len(det["references"]) == 36, f"实得 {len(det['references'])}")
    check("摘要非空", len(det["abstract"]) > 500, f"实得 {len(det['abstract'])} 字符")
    sec = next((s for s in det["sections"] if s["label"].startswith("3.2.1")), None)
    check("找得到 3.2.1 章节", sec is not None)
    if sec:
        check("该章节有正文段落", len(sec["paragraphs"]) > 0, f"实得 {len(sec['paragraphs'])} 段")

    # ---- 5. 取原始 PDF ----
    print("\n[5] GET /api/v1/documents/{id}/pdf")
    r5 = client.get(f"/api/v1/documents/{doc_id}/pdf")
    check("HTTP 200", r5.status_code == 200)
    check("字节数与源文件一致", len(r5.content) == PDF.stat().st_size,
          f"实得 {len(r5.content)} vs {PDF.stat().st_size}")

    # ---- 6. 异常路径 ----
    print("\n[6] 异常路径")
    r6 = client.post("/api/v1/documents", files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    check("非 PDF 返回 400", r6.status_code == 400, f"实得 {r6.status_code}")
    check("不存在的 id 返回 404", client.get("/api/v1/documents/deadbeef").status_code == 404)

    # ---- 7. 删除 ----
    print("\n[7] DELETE /api/v1/documents/{id}")
    check("删除返回 200", client.delete(f"/api/v1/documents/{doc_id}").status_code == 200)
    check("列表变空", client.get("/api/v1/documents").json()["count"] == 0)
    check("重复删除返回 404", client.delete(f"/api/v1/documents/{doc_id}").status_code == 404)

    print()
    if bad == 0:
        print("PASS —— S1 文献库 API 全链路通过（上传/解析/入库/列表/详情/取字节/去重/异常/删除）")
        return 0
    print(f"FAIL —— {bad} 项不符")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
