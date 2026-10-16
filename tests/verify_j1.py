"""J1 判据复跑脚本（语义去重）—— 离线可跑，不依赖任何私有文件。

覆盖判据原文的三个层次：
  1) 先传 v7、后传 v1 ⇒ 弹去重预警
  2) 用户可圈"覆盖 / 保留"
  3) 高级表现：提示"库中已有较新版本" + 给出两版主要修订差异摘要

负样本（"内容完全不同"的那篇）由脚本用 pymupdf 现场生成，
所以复跑者不需要额外的 PDF —— 这也是"判据可复跑"该有的样子。

用法：
    python tests/verify_j1.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

_TMP = tempfile.mkdtemp(prefix="verify_j1_")
os.environ["UPLOAD_DIR"] = _TMP

import pymupdf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import dedup  # noqa: E402

PDF_DIR = ROOT / "tests" / "fixtures" / "pdf"
V1 = PDF_DIR / "1706.03762v1.pdf"
V7 = PDF_DIR / "1706.03762v7.pdf"


def make_unrelated_pdf(path: Path) -> None:
    """现场造一篇"内容完全不同"的论文，作为去重的负样本。"""
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72.0
    for line in [
        "Sourdough Fermentation Kinetics of Highland Barley",
        "Abstract. This study models the water absorption of hulless barley",
        "flour during sourdough fermentation at controlled temperatures.",
        "1 Introduction",
        "Baking quality depends on starch gelatinisation and gluten hydration.",
        "2 Materials and Methods",
        "Dough samples were proofed at 22, 28 and 34 degrees Celsius for nine hours.",
        "3 Results",
        "Water absorption increased monotonically with proofing time in all batches.",
        "4 Conclusion",
        "A first order kinetic model fitted the observations with R squared 0.94.",
    ]:
        page.insert_text((72, y), line, fontsize=11)
        y += 22
    doc.set_metadata({"title": "Sourdough Fermentation Kinetics of Highland Barley"})
    doc.save(path)
    doc.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    for p in (V1, V7):
        if not p.exists():
            print(f"✗ 缺少测试输入：{p}")
            return 2

    client = TestClient(app)
    bad = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal bad
        print(f"  {'✓' if cond else '✗'} {label}" + ("" if cond else f"  {extra}"))
        if not cond:
            bad += 1

    def upload(path: Path) -> dict:
        with path.open("rb") as fh:
            r = client.post("/api/v1/documents", files={"file": (path.name, fh, "application/pdf")})
        if r.status_code != 200:
            raise RuntimeError(f"上传 {path.name} 失败：{r.status_code} {r.text[:300]}")
        return r.json()

    print(f"临时文献库：{_TMP}")
    print(f"阈值：{dedup.SIMILARITY_THRESHOLD}（指标：正文 {dedup.SHINGLE_N}-gram Jaccard）\n")

    # ---- 1. 先传 v7（此时库是空的，不该有任何预警）----
    print("[1] 先传 v7 —— 库里没有别的东西，不应预警")
    up7 = upload(V7)
    check("无去重预警", up7["dedup"]["has_warning"] is False)
    v7_id = up7["meta"]["doc_id"]
    print(f"      v7 doc_id={v7_id}  标题数={up7['meta']['n_headings']}  参考文献={up7['meta']['n_references']}")

    # ---- 2. 后传 v1 ⇒ ★必须弹预警 ----
    print("\n[2] 后传 v1 —— 必须识别为同一篇论文的旧版本")
    up1 = upload(V1)
    d = up1["dedup"]
    v1_id = up1["meta"]["doc_id"]
    check("弹出去重预警 has_warning", d["has_warning"] is True)
    if d["candidates"]:
        c = d["candidates"][0]
        print(f"      候选：{c['filename']}  相似度={c['similarity']:.3f}  依据：{c['reason']}")
        check("相似度 ≥ 阈值", c["similarity"] >= dedup.SIMILARITY_THRESHOLD)
        check("命中的是 v7", c["doc_id"] == v7_id)
        check("识别为同一 arXiv id", c["same_arxiv_id"] is True)
        check("★提示库中已有较新版本", c["existing_is_newer"] is True)
        check("版本号解析正确 (库 v7 / 新来 v1)",
              (c["existing_version"], c["incoming_version"]) == (7, 1),
              f"实得 {c['existing_version']} / {c['incoming_version']}")
    else:
        check("有候选", False, "candidates 为空")
    check("顶层 exists_newer 标记", d["exists_newer"] is True)

    # ---- 3. 负样本：内容完全不同的一篇，不该报警 ----
    print("\n[3] 负样本 —— 现场生成一篇无关论文，不应误报")
    neg = Path(_TMP) / "unrelated_barley.pdf"
    make_unrelated_pdf(neg)
    upn = upload(neg)
    check("无关论文不触发预警", upn["dedup"]["has_warning"] is False,
          f"误报 {upn['dedup']['candidates']}")

    # ---- 4. 两版差异摘要（高级表现）----
    print("\n[4] 两版主要修订差异摘要")
    r = client.get(f"/api/v1/documents/{v1_id}/compare/{v7_id}", params={"use_llm": "false"})
    check("对比接口 HTTP 200", r.status_code == 200, r.text[:200])
    cmp = r.json()
    diff = cmp["diff"]
    print(f"      正文长度 {diff['text_len']['old']} → {diff['text_len']['new']} ({diff['text_len']['delta']:+d})")
    print(f"      参考文献 {diff['references']['old']} → {diff['references']['new']}"
          f"（新增 {len(diff['references']['added'])}、删除 {len(diff['references']['removed'])}）")
    print(f"      摘要：{cmp['fallback_summary'][:160]}")
    check("给出确定性摘要", len(cmp["fallback_summary"]) > 40, cmp["fallback_summary"][:80])
    check("含长度变化", diff["text_len"]["delta"] != 0 or diff["text_len"]["old"] > 0)
    check("含章节级改动", isinstance(diff["changed_sections"], list))

    # ---- 5. 用户选择"保留"（两份都留）----
    print('\n[5] 用户圈"保留" ⇒ keep_both，两份都在')
    r = client.post("/api/v1/documents/dedup/resolve",
                    json={"doc_id": v1_id, "target_doc_id": v7_id, "action": "keep_both"})
    check("HTTP 200", r.status_code == 200, r.text[:200])
    check("库里仍是 3 篇", client.get("/api/v1/documents").json()["count"] == 3)

    # ---- 6. 用户选择"覆盖" ⇒ 删掉库中旧版、留新的 ----
    print('\n[6] 用户圈"覆盖" ⇒ replace_existing，删掉 v7 留下 v1')
    r = client.post("/api/v1/documents/dedup/resolve",
                    json={"doc_id": v1_id, "target_doc_id": v7_id, "action": "replace_existing"})
    check("HTTP 200", r.status_code == 200, r.text[:200])
    ids = {m["doc_id"] for m in client.get("/api/v1/documents").json()["items"]}
    check("v7 已被删除", v7_id not in ids)
    check("v1 仍在", v1_id in ids)

    # ---- 7. 放弃本次上传 ----
    print("\n[7] 用户选“放弃本次上传” ⇒ discard_new")
    up8 = upload(V7)
    v7b = up8["meta"]["doc_id"]
    r = client.post("/api/v1/documents/dedup/resolve",
                    json={"doc_id": v7b, "target_doc_id": v1_id, "action": "discard_new"})
    check("HTTP 200", r.status_code == 200, r.text[:200])
    check("新传的那份已删除", v7b not in {m["doc_id"] for m in client.get("/api/v1/documents").json()["items"]})

    # ---- 8. 参数校验 ----
    print("\n[8] 异常路径")
    check("非法 action 返回 400",
          client.post("/api/v1/documents/dedup/resolve",
                      json={"doc_id": v1_id, "action": "nonsense"}).status_code == 400)
    check("replace_existing 缺 target 返回 400",
          client.post("/api/v1/documents/dedup/resolve",
                      json={"doc_id": v1_id, "action": "replace_existing"}).status_code == 400)
    check("不存在的 doc_id 返回 404",
          client.post("/api/v1/documents/dedup/resolve",
                      json={"doc_id": "deadbeef", "action": "keep_both"}).status_code == 404)

    print()
    if bad == 0:
        print("PASS —— J1 全部通过（预警 / 较新版本提示 / 差异摘要 / 覆盖·保留 / 无误报）")
        return 0
    print(f"FAIL —— {bad} 项不符")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
