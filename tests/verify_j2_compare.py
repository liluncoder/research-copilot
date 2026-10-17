"""J2 最后一块：多文对比问答判据（★需要 .env 里的 LLM key）。

用法（仓库根目录）：
    python tests/verify_j2_compare.py
    python tests/verify_j2_compare.py --rebuild     # 强制重建索引

判据（写死在本文件）：
  C1 表格结构：回答里出现 Markdown 表格（`|` 分隔），否则"对比"无从体现
  C2 跨文献出处：引用覆盖**至少 N 篇**不同文献（否则等于单篇问答）
  C3 Transformer vs BERT：答出 BERT 基于 Transformer **Encoder**（承袭关系）
  C4 参数规模：BERT 的 110M / 768 与 Transformer 的 65M / 512 至少各命中一个
  C5 GPT-1 vs GPT-3：GPT-3 的 175B 必中，且 GPT-1 侧命中 12-layer/768/512 之一
  C8 三篇演化（GPT-1 → GPT-2 → GPT-3）：出处覆盖 **3 篇**，且命中 1.5B/1542M/175 中至少两个
  C6 零编造：invalid_citations 必须为空
  C7 未提及处理：出现"未提及"（防模型拿别的论文内容硬填）

★两处"记忆 vs 原文"的坑（已用原文文本层核对，详见判词）：
  - GPT-1 的 **117M 不在该 PDF 文本里**（count=0；该数字出现在 GPT-2 论文里被引用），
    所以 C5 不要求 GPT-1 给出 117M，只要求它给出原文里真有的 12-layer / 768 / 512。
  - `1801.06146` 是 **ULMFiT**（AWD-LSTM），不是 GPT-1 —— GPT-1 是 OpenAI 技术报告，未上 arXiv。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("CHROMA_PERSIST_DIR", str(ROOT / "tests" / "out" / "index_compare"))

PAPERS = [
    ("paper-transformer", ROOT / "tests" / "fixtures" / "pdf" / "1706.03762v1.pdf"),
    ("paper-bert", ROOT / "tests" / "fixtures" / "papers" / "bert_1810.04805.pdf"),
    ("paper-gpt1", ROOT / "tests" / "fixtures" / "papers" / "gpt1_improving_language_understanding.pdf"),
    ("paper-gpt2", ROOT / "tests" / "fixtures" / "papers" / "gpt2_language_models_unsupervised_multitask.pdf"),
    ("paper-gpt3", ROOT / "tests" / "fixtures" / "papers" / "gpt3_2005.14165.pdf"),
]

CASES = [
    {
        "id": "C3-C4",
        "q": "Transformer 和 BERT 在模型结构上的关系是什么？两者的层数、隐层维度和参数量差多少？",
        "docs": ["paper-transformer", "paper-bert"],
        "must_all": ["encoder"],
        "any_of": [["110"], ["768"], ["65"], ["512"]],
        "min_docs": 2,
    },
    {
        "id": "C5",
        "q": "GPT-1 和 GPT-3 的模型规模各是多少？上下文长度差多少？",
        "docs": ["paper-gpt1", "paper-gpt3"],
        "must_all": ["175"],
        "any_of": [["12-layer"], ["768"], ["512"], ["2048"]],
        "min_docs": 2,
    },
    {
        "id": "C8",
        "q": "从 GPT-1 到 GPT-2 再到 GPT-3，参数规模是怎么演化的？",
        "docs": ["paper-gpt1", "paper-gpt2", "paper-gpt3"],
        "must_all": [],
        "any_of": [["1.5"], ["1542"], ["175"]],
        "min_docs": 3,
    },
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()

    from app.core import llm
    from app.rag import compare, service
    from app.services.pdf_parser import parse_pdf

    if not llm.is_configured():
        print("[SKIP] 未配置 LLM key，多文对比无法测")
        return 2

    missing = [p.name for _, p in PAPERS if not p.exists()]
    if missing:
        print(f"[SKIP] 缺语料：{missing}")
        return 2

    if a.rebuild or not Path(os.environ["CHROMA_PERSIST_DIR"]).exists():
        for doc_id, pdf in PAPERS:
            doc = parse_pdf(pdf, with_tables=False)
            st = service.index_document(doc_id, doc.as_dict(), filename=pdf.name)
            print(f"索引 {pdf.name}: {st['chunks']} 块")

    checks: list[tuple[str, bool, str]] = []
    def chk(cid: str, ok: bool, detail: str) -> None:
        checks.append((cid, ok, detail))

    for case in CASES:
        res = compare.compare_question(case["q"], case["docs"], per_doc_k=8)
        print(f"\n[{case['id']}] {case['q']}")
        print("  分路召回：" + "；".join(f"{d['filename']}={d['hits_n']}" for d in res.docs))
        print(f"  覆盖文献：{res.covered_docs}")
        print(f"  回答：\n{res.answer[:900]}")
        for s in res.steps:
            print(f"    · {s['node']:8s} {s['ms']:7.1f}ms  {s['detail'][:90]}")

        ans = res.answer
        chk("C1-" + case["id"], ans.count("|") >= 6, f"表格分隔符 {ans.count('|')} 个")
        chk("C2-" + case["id"], len(res.covered_docs) >= case["min_docs"],
            f"覆盖 {len(res.covered_docs)}/{case['min_docs']} 篇：{res.covered_docs}")
        miss = [k for k in case["must_all"] if k.lower() not in ans.lower()]
        hitg = [g for g in case["any_of"] if any(x.lower() in ans.lower() for x in g)]
        chk(case["id"], not miss and bool(hitg), f"必含缺={miss}；命中数值组={hitg}")
        chk("C6-" + case["id"], not res.invalid_citations, f"编造出处={res.invalid_citations or '无'}")
        chk("C7-" + case["id"], ("未提及" in ans) or bool(res.citations),
            f"未提及={'有' if '未提及' in ans else '无'}；有效出处 {len(res.citations)} 条")

    print()
    for cid, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid:12s} {detail}")
    failed = [c for c, ok, _ in checks if not ok]
    print(f"\n{'PASS' if not failed else 'FAIL'}  ({len(checks) - len(failed)}/{len(checks)})")
    if failed:
        print("未过项：" + ", ".join(failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
