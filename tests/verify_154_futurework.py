"""官方赛题 1.5.4 判据：未来工作探索（Future Work 挖掘）。

用法（仓库根目录）：
    python tests/verify_154_futurework.py

判据（7 项）：
  F1 摘句可溯源：每条 snippet 的句子必须能在该文献 parsed 全文里原样找到（子串匹配）
  F2 只收未来向句子：每条 snippet 都命中 FUTURE_SENT（不许把普通正文当 Future Work）
  F3 方向必带出处：每个 direction 的 doc_id 必须属于本次摘句的文献集合
  F4 ★零杜撰出处：模型给出 [[ref:fake123]] ⇒ 进 invalid_refs，该方向被丢弃
  F5 合法方向落地：给合法 id ⇒ 方向保留，status 只能是「库内未见 / 库内已有人做」
  F6 时间感知：产出按年份倒序（未知年份排最后）
  F7 边界声明：notes 里必须写明「是否已有人做只在本库判定」
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("CHROMA_PERSIST_DIR", str(ROOT / "tests" / "out" / "index_j154"))
os.chdir(ROOT / "backend")

from app.core import llm, storage  # noqa: E402
from app.services import futurework as fw  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(code: str, ok: bool, detail: str) -> None:
    results.append((code, PASS if ok else FAIL, detail))


class _FakeLLM:
    def __init__(self, payload: str):
        self.payload = payload

    def __call__(self, messages, **kwargs):
        return llm.LLMReply(text=self.payload, model="fake-llm")


def full_text(doc_id: str) -> str:
    parsed = storage.get_parsed(doc_id) or {}
    if parsed.get("full_text"):
        return str(parsed["full_text"])
    # 有的解析结果只存 sections.paragraphs
    return "\n".join(p for s in (parsed.get("sections") or []) for p in (s.get("paragraphs") or []))


def main() -> int:
    docs = [d.doc_id for d in storage.list_documents() if storage.get_parsed(d.doc_id)]
    if not docs:
        print("FAIL 库为空")
        return 1

    base = fw.build(docs)
    print(f"文献 {base.n_docs} 篇，摘句 {len(base.snippets)} 条，方向 {len(base.directions)} 条")

    # ---- F1 摘句可溯源 ----
    bad = []
    texts = {d: full_text(d) for d in {s.doc_id for s in base.snippets}}
    for s in base.snippets:
        probe = s.text[:60].replace(" ", " ")
        if probe and probe not in texts.get(s.doc_id, ""):
            # 句子可能跨行，退一步按前 30 字符去空白匹配
            compact = "".join(probe.split())
            if compact not in "".join(texts.get(s.doc_id, "").split()):
                bad.append(s.doc_id)
    check("F1", bool(base.snippets) and not bad, f"摘句 {len(base.snippets)} 条，全部能在原文定位，失败 {len(bad)}")

    # ---- F2 只收未来向句子 ----
    off = [s.text[:40] for s in base.snippets if not fw.FUTURE_SENT.search(s.text)]
    check("F2", not off, f"全部命中 future/limitation 关键词，跑偏 {len(off)} 条" + (f"：{off[:2]}" if off else ""))

    # ---- F3 方向必带出处 ----
    docset = {s.doc_id for s in base.snippets}
    orphan = [d.idea[:20] for d in base.directions if d.doc_id not in docset]
    check("F3", not orphan, f"方向 {len(base.directions)} 条全部挂在已摘句文献上，孤儿 {len(orphan)}")

    # ---- F4 零杜撰出处（关键） ----
    orig_chat, orig_conf = llm.chat, llm.is_configured
    try:
        llm.is_configured = lambda: True  # type: ignore[assignment]
        llm.chat = _FakeLLM(  # type: ignore[assignment]
            '{"directions":['
            '{"idea":"用事件相机做低延迟信用分配","why":"延迟更低","basis":"[[ref:fake123]]","status":"库内未见"},'
            '{"idea":"把资格迹扩展到多分支","why":"覆盖更细","basis":"[[ref:%s]]","status":"库内未见"}]}'
            % (sorted(docset)[0] if docset else "none")
        )
        poisoned = fw.build([sorted(docset)[0]] if docset else docs)
    finally:
        llm.chat, llm.is_configured = orig_chat, orig_conf
    fake_gone = not any("事件相机" in d.idea for d in poisoned.directions)
    check(
        "F4",
        fake_gone and any("fake123" in x for x in poisoned.invalid_refs) and poisoned.directions,
        f"伪造 ref 被拦（invalid_refs={poisoned.invalid_refs[:2]}），伪造方向已丢弃={fake_gone}，合法方向保留 {len(poisoned.directions)} 条",
    )

    # ---- F5 合法方向字段合法 ----
    allowed = {"库内未见", "库内已有人做"}
    bad_status = [d.status for d in poisoned.directions if d.status not in allowed]
    check(
        "F5",
        bool(poisoned.directions) and not bad_status and all(d.doc_id for d in poisoned.directions),
        f"{len(poisoned.directions)} 条方向的 status 全在允许集内，失败 {len(bad_status)}",
    )

    # ---- F6 时间感知排序 ----
    years = [d.year or 0 for d in poisoned.directions]
    sorted_ok = years == sorted(years, reverse=True)
    check("F6", sorted_ok, f"年份序列 {years} 倒序={sorted_ok}")

    # ---- F7 边界声明 ----
    has_note = any("本库" in n for n in poisoned.notes)
    check("F7", has_note, "notes 已声明『是否已有人做只在本库判定』" if has_note else "缺少能力边界声明")

    print("\n" + "=" * 74)
    for code, status, detail in results:
        print(f"{status}  {code}  {detail}")
    n_fail = sum(1 for _, s, _ in results if s == FAIL)
    print("=" * 74)
    print(f"合计 {len(results) - n_fail}/{len(results)} PASS")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
