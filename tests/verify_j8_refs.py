"""J8 判据：无幻觉 References（★编造一条都算失败）。

用法（仓库根目录）：
    python tests/verify_j8_refs.py

判据：
  W1 框架完整：Abstract / Introduction / Related Work 三节都非空
  W2 参考文献可溯源：每条都能在文献库里按 doc_id 找到，且元数据齐全（标题/来源）
  W3 零编造：`invalid_refs` 必须为空（模型点名了不存在的 id 会被删除并记录，这里要 0）
  W4 编号自洽：正文里的 [n] 个数 == 参考文献条数，且编号从 1 连续
  W5 对抗测试：给一个库里完全没有的主题，仍必须 invalid_refs == 0
     （模型要么不引用，要么只引用真实文献；**不允许冒出任何一条假引用**）
  W6 正文不得自写引用格式：出现 "et al." / "(20xx)" 说明它在自己编引用格式
  W7 学术翻译：中文摘要 → 英文，无中日韩字符、≥120 字符、含关键术语

★J8 与 J7 同源：都靠"信息通道隔离"而不是"提示词禁止"。
  J7 是模型看不到原始数据点；J8 是模型拿不到自由写参考文献的能力 ——
  它只能从候选 id 里点名，条目由系统按本地元数据渲染。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("CHROMA_PERSIST_DIR", str(ROOT / "tests" / "out" / "index_j8"))

TOPIC = "局部学习规则在脉冲神经网络中的信用分配"
ADVERSARIAL = "量子退火在超导材料发现中的应用与稀释制冷机"
ZH_ABSTRACT = (
    "脉冲神经网络（SNN）的训练受制于时间维度的信用分配问题。本文在一个局部、生物学可行的学习规则框架下，"
    "研究单一标量第三因子的学习规则能否产生有方向的学习信号。我们给出一个构造性结论：当学习信号只以标量形式"
    "调制局部证据时，奖励符号反转不改变权重更新，因而学习信号不携带方向信息；把资格迹细化到逐突触或逐分支"
    "并不能打破这一性质。该结论说明现有以层内固定投影加全局标量调制为主的局部规则存在结构性上限。"
)

CJK = re.compile(r"[\u4e00-\u9fff]")


def main() -> int:
    from app.core import llm
    from app.core import storage
    from app.services import writing

    if not llm.is_configured():
        print("[SKIP] 未配置 LLM key，J8 无法测")
        return 2
    if not storage.list_documents():
        print("[SKIP] 文献库为空（先上传 PDF）")
        return 2

    checks: list[tuple[str, bool, str]] = []

    def chk(cid: str, ok: bool, detail: str) -> None:
        checks.append((cid, ok, detail))

    lib_ids = {m.doc_id for m in storage.list_documents()}

    # ---- 正常主题 ----
    res = writing.build_framework(TOPIC)
    secs = res.sections or {}
    chk("W1", all(secs.get(k, "").strip() for k in ("Abstract", "Introduction", "Related Work")),
        f"小节={ {k: len(v) for k, v in secs.items()} }")

    refs = res.references or []
    bad_meta = [r for r in refs if r["doc_id"] not in lib_ids or not r.get("title") or not r.get("source")]
    chk("W2", len(refs) >= 2 and not bad_meta,
        f"{len(refs)} 条；不可溯源/元数据缺失 {len(bad_meta)} 条")

    chk("W3", not res.invalid_refs, f"invalid_refs={res.invalid_refs or '无'}")

    body = "\n".join(secs.values())
    marks = sorted({int(x) for x in re.findall(r"\[(\d{1,2})\]", body)})
    chk("W4", len(marks) == len(refs) and marks == list(range(1, len(refs) + 1)),
        f"正文编号 {marks}；参考文献 {len(refs)} 条")

    # ---- 对抗主题 ----
    adv = writing.build_framework(ADVERSARIAL)
    adv_refs = adv.references or []
    adv_bad = [r for r in adv_refs if r["doc_id"] not in lib_ids]
    chk("W5", not adv.invalid_refs and not adv_bad,
        f"引用 {len(adv_refs)} 条（全部来自库内={not adv_bad}）；invalid_refs={adv.invalid_refs or '无'}")

    chk("W6", "et al." not in body and not re.search(r"\((19|20)\d{2}\)", body),
        "正文未自写作者-年份式引用")

    # ---- 学术翻译 ----
    tr = writing.translate_abstract(ZH_ABSTRACT)
    en = tr.get("text") or ""
    has_cjk = bool(CJK.search(en))
    kws = sum(1 for k in ("spiking", "credit assignment", "learning rule", "synaptic", "eligibility") if k in en.lower())
    chk("W7", bool(en) and not has_cjk and len(en) >= 120 and kws >= 2,
        f"{len(en)} 字符；含中文={has_cjk}；关键术语命中 {kws}")

    print(f"主题：{TOPIC}")
    print(f"小节字数：{ {k: len(v) for k, v in secs.items()} }")
    print(f"参考文献 {len(refs)} 条：")
    for r in refs[:6]:
        print(f"  [{r['n']}] {r['title'][:58]} · {r.get('year') or '年份未知'} · {r['source'][:26]}")
    print(f"\n对抗主题：{ADVERSARIAL}")
    print(f"  引用 {len(adv_refs)} 条，invalid_refs={adv.invalid_refs or '无'}")
    print(f"\n英译摘要（前 220 字符）：{en[:220]}\n")

    for cid, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid}  {detail}")
    failed = [c for c, ok, _ in checks if not ok]
    print(f"\n{'PASS' if not failed else 'FAIL'}  ({len(checks) - len(failed)}/{len(checks)})")
    if failed:
        print("未过项：" + ", ".join(failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
