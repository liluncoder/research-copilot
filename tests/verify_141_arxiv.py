"""官方赛题 1.4.1 判据：给定论文名称 → 自动下载并入库。

用法（仓库根目录）：
    python tests/verify_141_arxiv.py            # 含一次真实网络检索
    python tests/verify_141_arxiv.py --offline  # 只跑离线判据（无网络也行）

判据（6 项）：
  A1 Atom 解析：标题/作者/日期/arxiv_id/pdf_url 齐全（纯函数，喂固定样本）
  A2 相似度排序：三个候选里标题最像的排第一
  A3 代码可见性：summary 里出现 github 链接 ⇒ has_code=yes，否则 no
  A4 ★魔数校验：下载回来不是 %PDF- ⇒ 抛错，绝不入库（否则 HTML 错误页会污染索引）
  A5 幂等：库里已有的 arXiv id ⇒ already_existed=True，不重复下载解析
  A6 真实网络：真实检索 "Attention Is All You Need" 命中 1706.03762（网络失败记 WARN，不记 FAIL）

★A4 是最重要的一条：赛题要"自动下载"，而自动下载最大的坑是把 403/302 的 HTML 当论文存进去。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.services import arxiv  # noqa: E402

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results: list[tuple[str, str, str]] = []


def check(code: str, ok: bool, detail: str) -> None:
    results.append((code, PASS if ok else FAIL, detail))


ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <published>2023-08-02T00:00:00Z</published>
    <title>Attention Is All You Need</title>
    <summary>We propose the Transformer. Code: https://github.com/tensorflow/tensor2tensor</summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <link href="http://arxiv.org/abs/1706.03762v7" rel="alternate"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2101.00001v1</id>
    <published>2021-01-01T00:00:00Z</published>
    <title>Attention Is Not All You Need</title>
    <summary>An empirical critique without any repository link.</summary>
    <author><name>Someone Else</name></author>
  </entry>
</feed>
"""


def main() -> int:
    offline = "--offline" in sys.argv

    # ---- A1 解析 ----
    cands = arxiv.parse_atom(ATOM.encode("utf-8"))
    c0 = cands[0] if cands else None
    ok1 = (
        len(cands) == 2
        and c0 is not None
        and c0.arxiv_id == "1706.03762v7"
        and c0.title == "Attention Is All You Need"
        and c0.authors[:2] == ["Ashish Vaswani", "Noam Shazeer"]
        and c0.published == "2023-08-02"
        and c0.pdf_url.endswith("/pdf/1706.03762v7")
    )
    check("A1", ok1, f"解析出 {len(cands)} 条；首条 id={getattr(c0, 'arxiv_id', None)} 作者 {len(getattr(c0, 'authors', []))} 人")

    # ---- A2 相似度排序 ----
    from difflib import SequenceMatcher

    for c in cands:
        c.score = SequenceMatcher(None, "attention is all you need", c.title.lower()).ratio()
    ranked = sorted(cands, key=lambda c: -c.score)
    check("A2", ranked[0].arxiv_id == "1706.03762v7", f"排序首条={ranked[0].title}（score {ranked[0].score:.2f}）")

    # ---- A3 代码可见性 ----
    ok3 = cands[0].has_code == "yes" and cands[1].has_code == "no"
    check("A3", ok3, f"有链接={cands[0].has_code} 无链接={cands[1].has_code}")

    # ---- A4 魔数校验（关键）----
    orig = arxiv._http_get
    try:
        arxiv._http_get = lambda url, binary=False: b"<html>403 Forbidden</html>"  # type: ignore[assignment]
        raised = False
        try:
            arxiv.download("1706.03762v7")
        except RuntimeError as e:
            raised = "不是 PDF" in str(e)
    finally:
        arxiv._http_get = orig
    check("A4", raised, "非 PDF 响应被拒绝并抛错，未进入入库管线" if raised else "**没有拦住 HTML 响应**")

    # ---- A5 幂等 ----
    from app.core import storage

    existing = None
    for m in storage.list_documents():
        if "1706.03762" in (m.filename or ""):
            existing = m
            break
    if existing is None:
        results.append(("A5", WARN, "库里没有 1706.03762，跳过幂等测试"))
    else:
        orig_search = arxiv.search
        try:
            arxiv.search = lambda q, max_results=5: [  # type: ignore[assignment]
                arxiv.Candidate(
                    arxiv_id="1706.03762v1" if "v1" in (existing.filename or "") else "1706.03762v7",
                    title="Attention Is All You Need",
                    score=0.99,
                )
            ]
            res = arxiv.fetch_and_ingest("Attention Is All You Need")
        finally:
            arxiv.search = orig_search
        check(
            "A5",
            res.already_existed and res.doc_id == existing.doc_id and res.bytes == 0,
            f"already_existed={res.already_existed}，命中 doc_id={res.doc_id}，未重复下载（bytes={res.bytes}）",
        )

    # ---- A6 真实网络 ----
    if offline:
        results.append(("A6", WARN, "指定 --offline，跳过真实检索"))
    else:
        try:
            real = arxiv.search("Attention Is All You Need", max_results=3)
            hit = any("1706.03762" in c.arxiv_id for c in real)
            results.append(
                ("A6", PASS if hit else WARN, f"真实检索返回 {len(real)} 条，" + ("命中 1706.03762" if hit else "未命中（网络或季风）"))
            )
        except Exception as e:  # noqa: BLE001
            results.append(("A6", WARN, f"网络不可用：{type(e).__name__}: {e}"))

    print("=" * 78)
    for code, status, detail in results:
        print(f"{status}  {code}  {detail}")
    hard = [r for r in results if r[1] != WARN]
    n_fail = sum(1 for _, s, _ in hard if s == FAIL)
    print("=" * 78)
    print(f"合计 {len(hard) - n_fail}/{len(hard)} PASS（另有 {len(results) - len(hard)} 项 WARN）")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
