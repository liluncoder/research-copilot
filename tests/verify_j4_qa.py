"""J4 判据：单篇细粒度问答带出处（★评委 clone 后可复跑，需要 .env 里的 LLM key）。

用法（仓库根目录）：
    python tests/verify_j4_qa.py
    python tests/verify_j4_qa.py --doc tests/fixtures/pdf/1706.03762v1.pdf

判据（写死在本文件，改判据必须说明理由）：
  Q1 β1/β2 设置   —— 回答含 0.9 与 0.98，且至少一条出处指向 p7
  Q2 GPU 型号与数量—— 回答含 P100 与 8，出处 p7
  Q3 指定任务 BLEU —— 回答含 28.4，出处 p1 或 p2
  Q4 反幻觉        —— 问库里不存在的事实，必须拒答（出现"未找到"且不挂出处）
  Q5 出处可信      —— 三道题的 invalid_citations 必须为空（编造出处被 verify 节点剔除后不该有残留）
  Q6 可解释        —— steps 里 plan/retrieve/answer/verify 四步齐全（前端"思考过程"要用）

★若三项事实题失败，先看回答里的"检索词"那一步：
  中文问题靠 plan 节点改写成英文检索词去召回英文论文，改写失败会直接导致召回空 ⇒ 拒答。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("CHROMA_PERSIST_DIR", str(ROOT / "tests" / "out" / "index_j4"))

CASES = [
    {
        "id": "Q1",
        "q": "这篇论文里 Adam 优化器的 β1、β2 和 ε 分别设成多少？",
        "must": [["0.9", "0.98"]],
        "page_any": ["7"],
    },
    {
        "id": "Q2",
        "q": "训练用了多少块 GPU？什么型号？",
        "must": [["P100"], ["8"]],
        "page_any": ["7"],
    },
    {
        "id": "Q3",
        "q": "在 WMT 2014 英德翻译任务上，BLEU 分数是多少？",
        "must": [["28.4"]],
        "page_any": ["1", "2"],
    },
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default=str(ROOT / "tests" / "fixtures" / "pdf" / "1706.03762v1.pdf"))
    a = ap.parse_args()

    from app.core import llm
    from app.rag import answer as qa
    from app.rag import service
    from app.services.pdf_parser import parse_pdf

    if not llm.is_configured():
        print("[SKIP] 未配置 LLM key（.env 的 DEEPSEEK_API_KEY 等），J4 无法测")
        return 2

    pdf = Path(a.doc)
    doc = parse_pdf(pdf)
    idx = service.index_document("j4-doc", doc.as_dict(), filename=pdf.name)
    print(f"索引：{idx['chunks']} 块；向量档={idx['embedding_backend']}；索引档={idx['store_backend']}\n")

    checks: list[tuple[str, bool, str]] = []
    def chk(cid: str, ok: bool, detail: str) -> None:
        checks.append((cid, ok, detail))

    for case in CASES:
        res = qa.answer_question(case["q"], doc_ids=["j4-doc"], top_k=5)
        print(f"[{case['id']}] {case['q']}")
        print(f"  编排={res.orchestrator}  拒答={res.refused}  出处={len(res.citations)} 条"
              f"  编造剔除={len(res.invalid_citations)} 条")
        print(f"  回答：{res.answer[:220].replace(chr(10), ' ')}")
        for s in res.steps:
            print(f"    · {s['node']:9s} {s['ms']:7.1f}ms  {s['detail'][:96]}")
        print()

        missing = [g for g in case["must"] if not any(x in res.answer for x in g)]
        pages = {p for c in res.citations for p in _pages(c)}
        page_ok = bool(pages & set(case["page_any"]))
        chk(case["id"], not missing and page_ok and not res.refused,
            f"缺={missing}；出处页={sorted(pages) or '无'}（期望 ∈ {case['page_any']}）；拒答={res.refused}")
        chk(case["id"] + "-nofake", not res.invalid_citations,
            f"编造出处={res.invalid_citations or '无'}")
        nodes = {s["node"] for s in res.steps}
        chk(case["id"] + "-steps", {"plan", "retrieve", "answer", "verify"} <= nodes, f"步骤={sorted(nodes)}")

    # Q4 反幻觉：库里没有的事实
    q4 = qa.answer_question("这篇论文里用的量子退火机器是哪家公司生产的？", doc_ids=["j4-doc"], top_k=5)
    print(f"[Q4] 反幻觉：{q4.answer[:160].replace(chr(10), ' ')}")
    refused_ok = q4.refused or ("未找到" in q4.answer) or not q4.citations
    chk("Q4", refused_ok, f"拒答={q4.refused}；出处={q4.citations}")

    print()
    for cid, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid:14s} {detail}")
    failed = [c for c, ok, _ in checks if not ok]
    print(f"\n{'PASS' if not failed else 'FAIL'}  ({len(checks) - len(failed)}/{len(checks)})")
    if failed:
        print("未过项：" + ", ".join(failed))
    return 0 if not failed else 1


def _pages(cite: str) -> set[str]:
    """从 [来源: xxx·p7·5.3 Optimizer] 里抠出页码，归一成 '7' / '7-8'。"""
    m = re.search(r"·\s*([^·\]]+?)\s*·", cite)
    if not m:
        return set()
    raw = m.group(1).lower().lstrip("p").replace("–", "-")
    out: set[str] = set()
    if "-" in raw:
        a, b = raw.split("-", 1)
        if a.strip().isdigit() and b.strip().isdigit():
            out.update(str(i) for i in range(int(a), int(b) + 1))
    elif raw.strip().isdigit():
        out.add(str(int(raw)))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
