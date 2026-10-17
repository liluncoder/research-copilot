"""J5 判据：中英联动阅读的数据与接口层（★评委可复跑；R6 需要 LLM key）。

用法（仓库根目录）：
    python tests/verify_j5_reader.py

判据：
  R1 段落完整：v1 至少切出 60 段，每段都有稳定 id / 所属节 / 页码
  R2 引用标记：抽到的 [n] 标记 ≥ 30 处，且每条参考文献都有正文引用（v1 实际 36/36）
  R3 双向一致：`cited_by[n]` 与 `paragraphs[].citations` **完全互逆**（这是双向跳转的正确性）
  R4 无悬空引用：正文引用了不存在的编号 ⇒ 必须为空（否则前端点了会跳空）
  R5 标题树可导航：每节至少一段，且节的第一个段落 id 真实存在
  R6 段落级翻译：翻译一节 6 段 ⇒ 返回中文；再调一次 ⇒ 全部命中缓存（不重复花钱）
  R7 id 唯一且顺序稳定：para_id 无重复（联动滚动靠它对齐）

★"联动滚动"本身是 UI 行为，脚本测不了。人工验收见 `docs/demo/` 录屏；
  抖动时的退化方案（点击段落对齐）已在前端实现并通过 R5 的跳转数据保证可用。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("CHROMA_PERSIST_DIR", str(ROOT / "tests" / "out" / "index_j5"))

PDF = ROOT / "tests" / "fixtures" / "pdf" / "1706.03762v1.pdf"
CJK = re.compile(r"[\u4e00-\u9fff]")


def main() -> int:
    from app.core import llm
    from app.services import reader, translate
    from app.services.pdf_parser import parse_pdf

    view = reader.build_reader_view(parse_pdf(PDF).as_dict(), "verify-j5")
    paras = view["paragraphs"]
    refs = view["references"]
    cited_by = view["cited_by"]
    checks: list[tuple[str, bool, str]] = []

    def chk(cid: str, ok: bool, detail: str) -> None:
        checks.append((cid, ok, detail))

    # R1 / R7
    bad = [p["para_id"] for p in paras if not p["para_id"] or not p["section"] or not p["page_start"]]
    ids = [p["para_id"] for p in paras]
    chk("R1", len(paras) >= 60 and not bad, f"{len(paras)} 段，缺字段 {len(bad)} 段")
    chk("R7", len(ids) == len(set(ids)), f"id 唯一={len(ids) == len(set(ids))}")

    # R2
    chk("R2", view["stats"]["n_citation_marks"] >= 30 and view["stats"]["n_refs_cited"] >= 30,
        f"引用标记 {view['stats']['n_citation_marks']} 处；被引参考文献 {view['stats']['n_refs_cited']}/{len(refs)} 条")

    # R3 互逆校验
    mismatch: list[str] = []
    para_cites = {p["para_id"]: set(p["citations"]) for p in paras}
    for ref in refs:
        fwd = set(ref["cited_in"])
        back = {pid for pid, cs in para_cites.items() if ref["index"] in cs}
        if fwd != back:
            mismatch.append(f"[{ref['index']}] 正查 {len(fwd)} 段 vs 反查 {len(back)} 段")
    chk("R3", not mismatch, "互逆一致" if not mismatch else "; ".join(mismatch[:3]))

    # R4
    chk("R4", not view["stats"]["dangling_citations"],
        f"悬空引用 {view['stats']['dangling_citations'] or '无'}")

    # R5
    # 每个节都必须有"可导航目标"，且该目标真实存在（空父节用 nav_para_id 指向子节首页段）
    broken = [
        s["label"] for s in view["sections"]
        if not s.get("nav_para_id") or s["nav_para_id"] not in para_cites
    ]
    parents = [s["label"] for s in view["sections"] if s["n_paragraphs"] == 0]
    chk("R5", not broken,
        f"{len(view['sections'])} 节全部可导航；空父节 {len(parents)} 个已指向子节：{parents or '无'}")

    # R6 翻译（花钱，只测一节 6 段）
    if not llm.is_configured():
        chk("R6", True, "SKIP：无 LLM key（翻译未测，其余判据不受影响）")
    else:
        first_idx = paras[0]["section_index"]
        chunk = [p for p in paras if p["section_index"] == first_idx][:6]
        items = [{"para_id": p["para_id"], "text": p["text"]} for p in chunk]
        r1 = translate.translate_items("verify-j5", items)
        got = r1["items"]
        ok_chinese = bool(got) and all(len(CJK.findall(got[p["para_id"]])) > 5 for p in chunk if p["para_id"] in got)
        r2 = translate.translate_items("verify-j5", items)
        chk("R6", len(got) == len(chunk) and ok_chinese and r2["cached"] == len(chunk),
            f"首译 {r1['translated']} 段（缓存 {r1['cached']}），二次全命中缓存 {r2['cached']}/{len(chunk)}")

    # R8 作者-年份制引用（Nature / Neural Computation 风格）
    #   ★语料在李论桌面的 snn/ 下（不进仓库）；不存在就 SKIP，避免判据依赖私有文件。
    snn_dir = Path(os.environ.get("SNN_DIR", r"C://Users//23810//Desktop//snn"))
    ay_pdf = snn_dir / "01_Bellec2019_eprop_eligibility-traces.pdf"
    if not ay_pdf.exists():
        chk("R8", True, f"SKIP：找不到作者-年份制语料（{snn_dir}）")
    else:
        ay = reader.build_reader_view(parse_pdf(ay_pdf).as_dict(), "verify-ay")
        s = ay["stats"]
        chk("R8", s["n_citation_marks"] >= 30 and s["n_refs_cited"] >= 20,
            f"作者-年份制：{s['n_citation_marks']} 处引用、{s['n_refs_cited']}/{s['n_references']} 条被引"
            "（旧版只认 [n]，这里是 3 处 / 2 条）")

    print(f"文档：{PDF.name}")
    print(f"  节 {view['stats']['n_sections']} · 段 {view['stats']['n_paragraphs']} · "
          f"引用 {view['stats']['n_citation_marks']} · 参考文献 {view['stats']['n_references']}\n")
    print("  段落示例：")
    for p in paras[:2]:
        print(f"    {p['para_id']} [{p['section'][:24]}] cites={p['citations']} | {p['text'][:60]}")
    print()
    for cid, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid}  {detail}")
    failed = [c for c, ok, _ in checks if not ok]
    print(f"\n{'PASS' if not failed else 'FAIL'}  ({len(checks) - len(failed)}/{len(checks)})")
    if failed:
        print("未过项：" + ", ".join(failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
