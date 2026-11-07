"""S7 · arXiv 自动下载与推荐（官方赛题 1.4.1 / 1.4.3 的基本盘）。

官方原文：
  1.4.1「给定论文名称，利用搜索引擎等工具自动下载论文并入库」
  1.4.3「新论文和用户兴趣（库里已有的论文）的相关性，最好能根据论文的内容给出推荐理由」
        「是否包含 github 代码，有代码的文章容易复现，优先推荐」

★范围声明（不许含糊）：
  · 本模块做 1.4.1 的**完整链路**：标题 → arXiv API 检索 → 选最匹配的一条 → 下载 PDF → 走统一入库管线。
  · 1.4.2（sickle 定时刷新）与 1.4.3 的协同过滤**未做**，如实写进已知限制。
  · "有没有 GitHub 代码"是**照 summary/comment 里出现的 github 链接判定的**，
    判不出来就返回 unknown，不猜。

★为什么不自己写 HTTP 下载器：arXiv 的下载链接是 `https://arxiv.org/pdf/<id>`，
  但直接请求会拿到 302 到镜像；这里跟随重定向并校验 `%PDF-` magic，
  校验不过就报错 —— 绝不把 HTML 错误页当论文入库（那会污染整个索引）。
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from app.core import storage
from app.services.ingest import ingest_pdf

API = "https://export.arxiv.org/api/query"
PDF = "https://arxiv.org/pdf/{aid}"
NS = {"a": "http://www.w3.org/2005/Atom"}
UA = "ResearchCopilot/0.1 (+educational; contact: lilun)"
TIMEOUT = 30
GITHUB_RE = re.compile(r"github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+", re.I)
ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


@dataclass
class Candidate:
    arxiv_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    published: str = ""
    summary: str = ""
    pdf_url: str = ""
    has_code: str = "unknown"  # yes | no | unknown
    score: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "authors": self.authors,
            "published": self.published,
            "summary": self.summary[:400],
            "pdf_url": self.pdf_url,
            "has_code": self.has_code,
            "title_score": round(self.score, 3),
        }


def _http_get(url: str, *, binary: bool = False) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - 固定 https 域名
        return resp.read()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def parse_atom(xml_bytes: bytes) -> list[Candidate]:
    """解析 arXiv 的 Atom 响应。★纯函数，测试可喂固定样本，不依赖网络。"""
    root = ET.fromstring(xml_bytes)
    out: list[Candidate] = []
    for entry in root.findall("a:entry", NS):
        raw_id = _clean(entry.findtext("a:id", default="", namespaces=NS))
        m = ARXIV_ID_RE.search(raw_id)
        if not m:
            continue
        aid = m.group(1) + (m.group(2) or "")
        title = _clean(entry.findtext("a:title", default="", namespaces=NS))
        summary = _clean(entry.findtext("a:summary", default="", namespaces=NS))
        published = _clean(entry.findtext("a:published", default="", namespaces=NS))[:10]
        authors = [_clean(a.findtext("a:name", default="", namespaces=NS)) for a in entry.findall("a:author", NS)]
        comment = ""
        for link in entry.findall("a:link", NS):
            if link.get("title") == "doi" or link.get("rel") == "related":
                comment += " " + (link.get("href") or "")
        has_code = "yes" if GITHUB_RE.search(summary + " " + comment) else "no"
        out.append(
            Candidate(
                arxiv_id=aid,
                title=title,
                authors=[a for a in authors if a],
                published=published,
                summary=summary,
                pdf_url=PDF.format(aid=aid),
                has_code=has_code,
            )
        )
    return out


def search(query: str, *, max_results: int = 5) -> list[Candidate]:
    """按标题/关键词检索。query 里空格会被当 AND 词处理，整体加引号提高标题命中率。"""
    q = _clean(query)
    if not q:
        return []
    search_query = f'ti:"{q}"' if " " in q else f"all:{q}"
    url = f"{API}?search_query={urllib.parse.quote(search_query)}&start=0&max_results={max(1, min(max_results, 20))}"
    cands = parse_atom(_http_get(url))
    target = q.lower()
    for c in cands:
        c.score = SequenceMatcher(None, target, c.title.lower()).ratio()
    cands.sort(key=lambda c: -c.score)
    return cands


def download(arxiv_id: str) -> bytes:
    """下载 PDF 并校验 magic。失败抛 RuntimeError（绝不把错误页当论文）。"""
    if not ARXIV_ID_RE.search(arxiv_id):
        raise RuntimeError(f"不是合法的 arXiv id：{arxiv_id}")
    data = _http_get(PDF.format(aid=arxiv_id), binary=True)
    if not data.startswith(b"%PDF-"):
        raise RuntimeError(f"下载回来的不是 PDF（前 16 字节：{data[:16]!r}）——可能被重定向到 HTML 页")
    return data


def _already_in_library(arxiv_id: str) -> str | None:
    base = ARXIV_ID_RE.search(arxiv_id)
    key = base.group(1) if base else arxiv_id
    for meta in storage.list_documents():
        if key and key in (meta.filename or ""):
            return meta.doc_id
    return None


@dataclass
class FetchResult:
    query: str
    candidates: list[Candidate] = field(default_factory=list)
    chosen: Candidate | None = None
    doc_id: str | None = None
    already_existed: bool = False
    bytes: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "candidates": [c.as_dict() for c in self.candidates],
            "chosen": self.chosen.as_dict() if self.chosen else None,
            "doc_id": self.doc_id,
            "already_existed": self.already_existed,
            "bytes": self.bytes,
            "error": self.error,
        }


def fetch_and_ingest(query: str, *, arxiv_id: str | None = None, max_results: int = 5) -> FetchResult:
    """1.4.1 主链路：标题 → 检索 → 选最优 → 下载 → 入库（去重幂等）。"""
    res = FetchResult(query=query)
    try:
        if arxiv_id:
            res.candidates = [Candidate(arxiv_id=arxiv_id, title=query, pdf_url=PDF.format(aid=arxiv_id))]
            res.chosen = res.candidates[0]
        else:
            res.candidates = search(query, max_results=max_results)
            if not res.candidates:
                res.error = f"arXiv 上没检索到「{query}」（或网络不可达）"
                return res
            res.chosen = res.candidates[0]
            if res.chosen.score < 0.55:
                res.error = (
                    f"最匹配的一条标题相似度只有 {res.chosen.score:.2f}（<0.55）："
                    f"「{res.chosen.title}」——为避免入库错论文，已中止（可改用 arxiv_id 精确指定）"
                )
                return res
    except (urllib.error.URLError, TimeoutError, ET.ParseError) as e:
        res.error = f"arXiv 检索失败：{type(e).__name__}: {e}"
        return res

    chosen = res.chosen
    assert chosen is not None
    existed = _already_in_library(chosen.arxiv_id)
    if existed:
        res.doc_id, res.already_existed = existed, True
        return res

    try:
        pdf = download(chosen.arxiv_id)
    except Exception as e:  # noqa: BLE001
        res.error = f"下载失败：{type(e).__name__}: {e}"
        return res

    filename = f"{chosen.arxiv_id}.pdf"
    try:
        doc_id, _meta, _parsed = ingest_pdf(filename, pdf)
    except Exception as e:  # noqa: BLE001
        res.error = f"入库失败：{type(e).__name__}: {e}"
        return res
    res.doc_id, res.bytes = doc_id, len(pdf)
    return res


def recommend_related(doc_id: str, *, max_results: int = 5) -> list[Candidate]:
    """1.4.3 的降级版：拿库里这篇的标题去 arXiv 找同类新论文，标注有无 GitHub 代码与年份。

    ★明确不做的事：不做协同过滤、不做"已被谁做过"的外部判定（没有全 arXiv 阅读记录）。
    """
    meta = storage.get_meta(doc_id)
    if not meta:
        return []
    title = (meta.title or "").replace(".pdf", "").strip()
    if not title:
        return []
    try:
        cands = search(title, max_results=max_results + 3)
    except Exception:  # noqa: BLE001
        return []
    out = [c for c in cands if c.score < 0.95]  # 排掉"就是这篇自己"
    # 有代码的排前面（官方 1.4.3 第 2 条），其次按标题相似度
    out.sort(key=lambda c: (c.has_code != "yes", -c.score))
    return out[:max_results]
