"""官方赛题 1.2.1 判据：单篇论文问答的**官方五道例题**逐条跑。

用法（仓库根目录，需配好 LLM key，需库内有 1706.03762v1）：
    python tests/verify_official_qa5.py
    python tests/verify_official_qa5.py <doc_id>

判据（每题四件事）：
  · 答案命中关键事实（见下方 EXPECT）
  · 至少一条出处锚点（citations 非空）
  · 零编造出处（invalid_citations 为空）
  · 不许拒答（refused 为 False）

★为什么单独写这份：J4 只测了 Q2/Q3/Q4（β、GPU、BLEU）。
  官方原文 1.2.1 一共 5 道，Q1（第 6 作者 + 机构）和 Q5（Layer Normalization 参考文献的完整作者与年份）
  此前**从未测过**，而评委最可能照官方原题点。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")  # 用仓库里已建好的索引（./chroma_data 与 ./data/uploads 都是相对 backend 的）

from app.core import storage  # noqa: E402
from app.rag import answer as rag_answer  # noqa: E402

PASS, FAIL = "PASS", "FAIL"

QUESTIONS = [
    (
        "Q1 第 6 作者与机构",
        "论文 Attention Is All You Need 的第 6 作者是谁，在哪个公司/机构工作？",
        [
            ("第6作者=Gomez", r"gomez"),
            ("机构=Toronto", r"toronto"),
        ],
    ),
    (
        "Q2 Adam 超参",
        "这篇论文中 Adam 优化器的 β1 和 β2 分别被设置为了多少？",
        [
            ("β1", r"0\.9(?!\d)"),
            ("β2", r"0\.98"),
        ],
    ),
    (
        "Q3 训练 GPU",
        "Transformer 架构在训练 Base 模型时使用了多少个 GPU？具体是什么型号？",
        [
            ("数量", r"8\s*(块|个|张)?|eight"),
            ("型号", r"p100"),
        ],
    ),
    (
        "Q4 BLEU 与 SOTA",
        "Transformer (big) 模型在 English-to-German 任务上的 BLEU 分数是多少？当时的 State-of-the-art 是多少？提升了多少？",
        [
            ("本模型", r"28\.4"),
            ("前 SOTA", r"26\.3|26\.36"),
        ],
    ),
    (
        "Q5 LayerNorm 参考文献",
        "请列出论文中引用的关于 Layer Normalization 的参考文献（References）的完整作者和年份。",
        [
            ("第一作者", r"\bba\b|jimmy"),
            ("第二作者", r"kiros"),
            ("第三作者", r"hinton"),
            ("年份", r"2016"),
        ],
    ),
]


def pick_doc() -> str | None:
    for d in storage.list_documents():
        if "1706.03762v1" in (d.filename or "") and storage.get_parsed(d.doc_id):
            return d.doc_id
    return None


def main() -> int:
    doc_id = sys.argv[1] if len(sys.argv) > 1 else pick_doc()
    if not doc_id:
        print("FAIL 库里没有 1706.03762v1 的解析结果，先上传该 PDF")
        return 1

    rows: list[tuple[str, str, str]] = []
    for name, q, expects in QUESTIONS:
        res = rag_answer.answer_question(q, doc_ids=[doc_id], top_k=6)
        text = (res.answer or "").lower()
        missing = [label for label, pat in expects if not re.search(pat, text, re.I)]
        cites = len(res.citations or [])
        ok = not missing and cites > 0 and not res.invalid_citations and not res.refused and not res.error
        detail = (
            f"命中 {len(expects) - len(missing)}/{len(expects)}"
            + (f"（缺 {'、'.join(missing)}）" if missing else "")
            + f"，出处 {cites} 条，编造出处 {len(res.invalid_citations or [])}，拒答={res.refused}"
        )
        if res.error:
            detail += f"，error={res.error[:60]}"
        rows.append((PASS if ok else FAIL, name, detail))
        print(f"\n----- {name} -----\nQ: {q}\nA: {res.answer[:400]}")
        if res.citations:
            c = res.citations[0]
            print(f"   出处示例：{c}" if isinstance(c, str) else f"   出处示例：{c}")

    print("\n" + "=" * 76)
    for status, name, detail in rows:
        print(f"{status}  {name:<22} {detail}")
    n_fail = sum(1 for s, _, _ in rows if s == FAIL)
    print("=" * 76)
    print(f"合计 {len(rows) - n_fail}/{len(rows)} PASS")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
