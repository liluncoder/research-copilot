"""S2 检索判据：结构化切块 + 混合检索能否把 J4 要的三类事实捞出来。

用法（仓库根目录）：
    python tests/verify_s2_retrieval.py
    python tests/verify_s2_retrieval.py --backend bge-m3     # 强制用 BGE-M3（没模型会报错）

判据（写死在本文件，改判据必须说明理由）：
  R1 切块带出处元数据：每块都有 section_label / page_start，且块长 ≤ 限制的 1.6 倍
  R2 每篇至少切出 20 块（v1 有 7 节 + 摘要，太少了说明切块逻辑坏了）
  R3 优化器事实：query 命中含 0.9 / 0.98 的块，且出处页为 p7（5.3 Optimizer）
  R4 硬件事实：query 命中含 "P100" 的块，出处 p7（5.2 Hardware and Schedule）
  R5 BLEU 事实：query 命中含 28.4 的块，出处 p1~p2（摘要/6.1）
  R6 稀疏通道确实起作用：至少一条命中同时有 dense_rank 与 sparse_rank（RRF 融合有效）
  R7 拒答能力：问一个库里绝不存在的事实（量子退火公司名），top1 也不该"自信命中"
     —— 这里只检查能返回结果但不崩；真正拒答在回答层（J8 反幻觉）实现

★判据只测"检索层"，不测"LLM 回答"——后者属 J4 的回答契约，见下一轮。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
# 索引写到 tests/out，避免污染开发用的 chroma_data
os.environ.setdefault("CHROMA_PERSIST_DIR", str(ROOT / "tests" / "out" / "index_verify"))

PDF = ROOT / "tests" / "fixtures" / "pdf" / "1706.03762v1.pdf"

QUERIES = [
    {
        "id": "R3",
        "q": "What values of beta1, beta2 and epsilon were used in the Adam optimizer?",
        "must_contain": ["0.9", "0.98"],
        "page_any": [7],
        "why": "β1/β2 设置（5.3 Optimizer, p7）",
    },
    {
        "id": "R4",
        "q": "How many GPUs and which GPU model were used for training?",
        "must_contain": ["P100"],
        "page_any": [7],
        "why": "GPU 型号与数量（5.2 Hardware and Schedule, p7）",
    },
    {
        "id": "R5",
        "q": "What BLEU score does the Transformer achieve on WMT 2014 English-to-German?",
        "must_contain": ["28.4"],
        "page_any": [1, 2],
        "why": "BLEU 分数（摘要 / 6.1, p1~2）",
    },
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default=None, help="auto | bge-m3 | hash")
    ap.add_argument("--top-k", type=int, default=5)
    a = ap.parse_args()
    if a.backend:
        os.environ["EMBEDDING_BACKEND"] = a.backend

    from app.rag import service
    from app.rag.chunker import chunk_document
    from app.services.pdf_parser import parse_pdf

    doc = parse_pdf(PDF)
    chunks = chunk_document(doc, "verify-doc", max_chars=900, overlap=120)
    status = service.index_status()

    checks: list[tuple[str, bool, str]] = []
    def chk(cid: str, ok: bool, detail: str) -> None:
        checks.append((cid, ok, detail))

    # R1 元数据齐全
    bad = [c.chunk_id for c in chunks if not c.section_label or not c.page_start]
    long_bad = [c.chunk_id for c in chunks if c.n_chars > 900 * 1.6]
    chk("R1", not bad and not long_bad, f"缺元数据 {len(bad)} 块，超长 {len(long_bad)} 块，共 {len(chunks)} 块")

    # R2 块数
    chk("R2", len(chunks) >= 20, f"{len(chunks)} 块")

    # 建索引
    stats = service.index_document("verify-doc", doc.as_dict(), filename=PDF.name)
    print(f"索引进度：{stats}")
    print(f"后端：store={status['store_backend']} embedding={status['embedding_backend']}"
          + (f"（降档原因：{status['embedding_fallback_reason']}）" if status.get("embedding_fallback_reason") else ""))
    print()

    both_channel = 0
    for spec in QUERIES:
        res = service.search(spec["q"], doc_ids=["verify-doc"], top_k=a.top_k)
        hits = [h.as_dict() for h in res.hits]
        print(f"[{spec['id']}] {spec['q']}")
        print(f"   期望：{spec['why']}")
        for i, h in enumerate(hits[:3], 1):
            ranks = f"dense#{h['dense_rank']} sparse#{h['sparse_rank']}"
            print(f"   {i}. {h['page']} · {h['section'][:44]} · {ranks} · score={h['score']}")
        if not hits:
            chk(spec["id"], False, "无命中")
            continue

        top3_text = " \n".join(h["text"] for h in hits[:3])
        top3_pages = {int(h["page"].split("-")[0].lstrip("p")) for h in hits[:3]}
        top3_pages |= {int(p) for h in hits[:3] for p in h["page"].replace("p", "").split("-")}

        missing = [k for k in spec["must_contain"] if k not in top3_text]
        page_ok = bool(top3_pages & set(spec["page_any"]))
        chk(spec["id"], not missing and page_ok,
            f"缺关键词={missing}；页码命中={sorted(top3_pages)}（期望 ∈ {spec['page_any']}）")

        both_channel += sum(1 for h in hits if h["dense_rank"] is not None and h["sparse_rank"] is not None)
        print()

    chk("R6", both_channel > 0, f"双通道同时命中的条数={both_channel}")

    # R7 库外问题：不应崩，允许返回低相关结果
    outside = service.search("What is the market share of D-Wave quantum annealers in 2023?", doc_ids=["verify-doc"], top_k=3)
    chk("R7", isinstance(outside.hits, list), f"库外查询返回 {len(outside.hits)} 条（不崩即过）")

    print()
    for cid, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid}  {detail}")
    failed = [c for c, ok, _ in checks if not ok]
    print(f"\n{'PASS' if not failed else 'FAIL'}  ({len(checks) - len(failed)}/{len(checks)})")
    print(f"本次使用的向量后端：{stats['embedding_backend']} / 索引后端：{stats['store_backend']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
