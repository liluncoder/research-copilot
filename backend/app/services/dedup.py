"""S1 · J1 语义去重：判断"这次上传的是不是库里已有论文的另一个版本"。

## 判据（`路线/04` J1）
先传 v7、后传 v1 ⇒ 系统弹去重预警；用户可圈"覆盖/保留"；
高级表现：提示"库中已有较新版本" + 给出两版主要修订差异摘要。

## 为什么不用"全文 embedding 余弦 > 0.95"（原计划）
实测推翻了它（脚本 `_sim_probe.py` 的结论，见 `report/J1_判词.md`）：

    A                B                      jac5   cont5  char4  tfcos
    1706.03762v1     1706.03762v7           0.684  0.837  0.718  0.997   ← 目标
    main3-02         main3-04（真近重复）     0.987  0.994  0.988  1.000
    药材烘干·提交包     建模 main3-02（无关）    0.257  0.826  0.272  0.948   ← 危险
    药材烘干·第一版     药材烘干·提交包（无关）    0.017  0.048  0.029  0.840
    v1               中文论文（无关）           0.000  0.000  0.000  0.160

⇒ **词频余弦（tfcos）完全分不开**：两篇毫不相干的中文论文就有 0.948，
  0.95 这条阈值正好卡在误报线上。它的数值被"学术套话"顶起来了。
⇒ **包含度（cont5 = 交集/较小集合）也危险**：无关文档若长度悬殊，能到 0.826。
⇒ 只有 **5-gram Jaccard** 有干净的间隔：最难的真正例 0.684，最高误报 0.262。

结论：用 5-gram Jaccard，阈值取 0.45（两边各留约 0.19 的余量）。
这条修正同时是技术文档"AI 选型理由 / 优化策略"的现成素材：
**阈值是量出来的，不是拍出来的。**

## 与"精确去重"的分工
`storage.doc_id` 用内容哈希 ⇒ 逐字节相同的文件（重复提交）天然同 id。
本模块只解决**字节不同、内容高度重合**的情况（v1 vs v7）。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

# ---------------- 阈值（★全部来自 _sim_probe.py 的实测，勿凭感觉改） ----------------
SIMILARITY_THRESHOLD = 0.45  # 5-gram Jaccard：≥ 此值 ⇒ 弹去重预警
TITLE_MATCH_MIN_SIM = 0.15  # 标题归一化完全一致时的兜底阈值（防"改名换姓"的版本）
SHINGLE_N = 5

TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")
# arXiv 文件名里的 id 与版本号：1706.03762v7.pdf
ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v(\d+))?", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    """英文按词、中文按字切，统一小写。中英混排都能算。"""
    return TOKEN_RE.findall(text.lower())


def shingles(tokens: list[str], n: int = SHINGLE_N) -> set[str]:
    return {" ".join(tokens[i : i + n]) for i in range(max(len(tokens) - n + 1, 0))}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def normalize_title(title: str | None) -> str:
    """标题归一化：只留字母数字与汉字，去空格、去被 PDF 拆行造成的差异。"""
    return "".join(TOKEN_RE.findall((title or "").lower()))


def parse_arxiv(filename: str) -> tuple[str | None, int | None]:
    """从文件名里取 arXiv id 与版本号。取不到返回 (None, None)。"""
    m = ARXIV_RE.search(filename or "")
    if not m:
        return None, None
    return m.group(1), int(m.group(2)) if m.group(2) else None


@dataclass
class DupCandidate:
    """疑似同一篇论文的另一个版本。"""

    doc_id: str
    filename: str
    similarity: float
    title_match: bool
    same_arxiv_id: bool
    existing_version: int | None
    incoming_version: int | None
    existing_is_newer: bool  # ★"库中已有更新版本"提示
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _title_of(parsed: dict[str, Any]) -> str | None:
    return parsed.get("title")


def compare_against(
    incoming: dict[str, Any],
    incoming_filename: str,
    existing: dict[str, Any],
    existing_filename: str,
) -> DupCandidate | None:
    """拿一篇新入库的文档跟库里一篇已有文档比。不像则返回 None。"""
    inc_tokens = tokenize(incoming.get("full_text", ""))
    exi_tokens = tokenize(existing.get("full_text", ""))
    if not inc_tokens or not exi_tokens:
        return None

    sim = jaccard(shingles(inc_tokens), shingles(exi_tokens))
    t_inc, t_exi = normalize_title(_title_of(incoming)), normalize_title(_title_of(existing))
    # 标题很短时（比如解析失败只剩一两个词）不算"匹配"，否则会误触发
    title_match = bool(t_inc) and t_inc == t_exi and len(t_inc) >= 8

    if sim < SIMILARITY_THRESHOLD and not (title_match and sim >= TITLE_MATCH_MIN_SIM):
        return None

    id_inc, ver_inc = parse_arxiv(incoming_filename)
    id_exi, ver_exi = parse_arxiv(existing_filename)
    same_id = bool(id_inc) and id_inc == id_exi

    parts = [f"正文 5-gram 重合度 {sim:.0%}"]
    if title_match:
        parts.append("标题完全一致")
    if same_id:
        parts.append(f"同为 arXiv {id_inc}")

    newer = False
    if same_id and ver_inc is not None and ver_exi is not None:
        newer = ver_exi > ver_inc
        parts.append(f"库中为 v{ver_exi}、本次为 v{ver_inc}")

    return DupCandidate(
        doc_id=existing.get("doc_id", ""),
        filename=existing_filename,
        similarity=round(sim, 4),
        title_match=title_match,
        same_arxiv_id=same_id,
        existing_version=ver_exi,
        incoming_version=ver_inc,
        existing_is_newer=newer,
        reason="；".join(parts),
    )


def find_duplicates(
    incoming: dict[str, Any],
    incoming_filename: str,
    library: Iterable[tuple[dict[str, Any], str]],
    exclude_doc_id: str | None = None,
) -> list[DupCandidate]:
    """扫描整个文献库，返回所有疑似同源文档（按相似度降序）。

    exclude_doc_id：把自己排掉，避免"新上传的文档跟它自己比"。
    """
    out: list[DupCandidate] = []
    for parsed, filename in library:
        if exclude_doc_id and parsed.get("doc_id") == exclude_doc_id:
            continue
        c = compare_against(incoming, incoming_filename, parsed, filename)
        if c is not None:
            out.append(c)
    out.sort(key=lambda c: -c.similarity)
    return out


# ============================ 两版差异摘要（J1 高级表现） ============================


def _ref_key(raw: str) -> str:
    """文献条目归一化成"第一作者姓+年份"这类粗粒度键，用于判断新增/删除。"""
    first = re.split(r"[,.]", raw.strip())[0].strip().lower()
    year = re.findall(r"\b((?:19|20)\d{2})\b", raw)
    return f"{first}|{year[-1] if year else ''}"


def diff_versions(old: dict[str, Any], new: dict[str, Any], *, old_label: str, new_label: str) -> dict[str, Any]:
    """给出两个版本的结构化差异（确定性、可复跑；LLM 只负责把它写成话）。"""
    old_labels = [h["title"] for h in old.get("outline", [])]
    new_labels = [h["title"] for h in new.get("outline", [])]
    added = [t for t in new_labels if t not in old_labels]
    removed = [t for t in old_labels if t not in new_labels]

    old_refs = {_ref_key(r["raw"]): r["raw"] for r in old.get("references", [])}
    new_refs = {_ref_key(r["raw"]): r["raw"] for r in new.get("references", [])}
    refs_added = [v for k, v in new_refs.items() if k not in old_refs]
    refs_removed = [v for k, v in old_refs.items() if k not in new_refs]

    old_secs = {s["label"]: s["n_chars"] for s in old.get("sections", [])}
    changed_sections = []
    for s in new.get("sections", []):
        before = old_secs.get(s["label"])
        if before is None:
            continue
        delta = s["n_chars"] - before
        if abs(delta) >= max(60, int(before * 0.15)):  # 变化超过 15% 或 60 字符才算"改了"
            changed_sections.append(
                {"label": s["label"], "before": before, "after": s["n_chars"], "delta": delta}
            )
    changed_sections.sort(key=lambda d: -abs(d["delta"]))

    old_len = len(old.get("full_text", ""))
    new_len = len(new.get("full_text", ""))
    return {
        "old_label": old_label,
        "new_label": new_label,
        "text_len": {"old": old_len, "new": new_len, "delta": new_len - old_len},
        "headings": {"old": len(old_labels), "new": len(new_labels), "added": added, "removed": removed},
        "references": {
            # ★报数要用真实条数。old_refs/new_refs 是按"第一作者+年份"聚合的字典，
            #   撞键会把两条合成一条（实测：v7 真值 40 条，写进摘要成了 39 条，
            #   跟详情接口的 40 自相矛盾）。字典只用于判断新增/删除。
            "old": len(old.get("references", [])),
            "new": len(new.get("references", [])),
            "added": refs_added,
            "removed": refs_removed,
        },
        "changed_sections": changed_sections,
        "math_lines": {
            "old": old.get("stats", {}).get("math_lines", 0),
            "new": new.get("stats", {}).get("math_lines", 0),
        },
    }


SUMMARY_SYSTEM_PROMPT = (
    "你是学术文献版本对比助手。下面给你两个版本的**结构化差异数据**（不是全文）。"
    "请只用这些数据写一段 3-5 句的中文说明，讲清两版的主要修订差异与是否建议保留新版。"
    "★严禁编造数据里没有的内容（比如具体改动了哪个公式、哪句话）。数据没提到就不许说。"
)


def summarize_diff_with_llm(diff: dict[str, Any]) -> str:
    """让 LLM 把结构化差异写成一段人话。★只喂统计数据，不喂原文（结构性防幻觉）。

    失败（没配 key / 网络不通）时返回空串，调用方回落到确定性摘要。
    """
    import json as _json
    import urllib.error
    import urllib.request

    from app.core.config import get_settings

    s = get_settings()
    base, key, model = {
        "deepseek": (s.deepseek_base_url, s.deepseek_api_key, s.deepseek_model),
        "zhipu": (s.zhipu_base_url, s.zhipu_api_key, s.zhipu_model),
        "dashscope": (s.dashscope_base_url, s.dashscope_api_key, s.dashscope_model),
    }.get(s.llm_provider, ("", "", ""))
    if not key:
        return ""

    payload = _json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": _json.dumps(diff, ensure_ascii=False)},
            ],
            "temperature": 0.2,
            "max_tokens": 400,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            body = _json.loads(resp.read().decode("utf-8", errors="replace"))
        return body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    except (urllib.error.URLError, KeyError, ValueError, TimeoutError):
        return ""


def deterministic_summary(diff: dict[str, Any]) -> str:
    """不依赖大模型的兜底摘要（LLM 不通时照样能给评委看东西）。"""
    d = diff["text_len"]["delta"]
    parts = [
        f"正文长度 {diff['text_len']['old']} → {diff['text_len']['new']} 字符（{d:+d}）",
        f"标题 {diff['headings']['old']} → {diff['headings']['new']} 个",
        f"参考文献 {diff['references']['old']} → {diff['references']['new']} 条"
        f"（新增 {len(diff['references']['added'])}、删除 {len(diff['references']['removed'])}）",
        f"公式行 {diff['math_lines']['old']} → {diff['math_lines']['new']} 行",
    ]
    if diff["headings"]["added"]:
        parts.append("新增章节：" + "、".join(diff["headings"]["added"][:5]))
    if diff["headings"]["removed"]:
        parts.append("删除章节：" + "、".join(diff["headings"]["removed"][:5]))
    if diff["changed_sections"]:
        top = diff["changed_sections"][:3]
        parts.append(
            "改动最大的章节："
            + "、".join(f"{c['label']}（{c['delta']:+d} 字符）" for c in top)
        )
    return "；".join(parts) + "。"
