"""文献库存储层（S1）：磁盘上的"一个文档一个目录"，不引入数据库。

为什么不用数据库：一个人 33 天，文献库的量级是几十篇。用文件系统 + JSON
少一层依赖、评审 clone 下来直接能跑、出问题能肉眼查。等 S5 图谱需要关系查询
再说（届时 Chroma 已经在跑，够用）。

目录结构（根目录取 `settings.upload_dir`，Docker 里是 /app/data/uploads）：
    <doc_id>/
        original.pdf     原始上传件（永不改写）
        parsed.json      结构化解析结果（标题树/章节/参考文献/公式行）
        meta.json        元数据 + 解析摘要（列表页只读这个，快）

doc_id = 文件内容的 sha256 前 12 位。
  ★顺带起到"完全相同文件"的去重作用：同一份 PDF 传两次得到同一个 id。
  但注意这只解决**逐字节相同**；J1 要的是**语义去重**（v1 vs v7 正文高度重合但
  字节完全不同），那一层在 S1 后续用 embedding 余弦相似度做，不走这里。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings

SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z._\u4e00-\u9fff-]+")


@dataclass
class DocumentMeta:
    """列表页/详情页要用的元数据（parsed.json 的摘要，不塞全文）。"""

    doc_id: str
    filename: str
    size_bytes: int
    sha256: str
    uploaded_at: str
    doc_type: str  # "text"（有文本层） | "scanned"（无文本层，待 OCR）
    page_count: int
    title: str | None
    authors: list[str] = field(default_factory=list)
    abstract_chars: int = 0
    n_headings: int = 0
    n_references: int = 0
    n_math_lines: int = 0
    warnings: list[str] = field(default_factory=list)
    parse_seconds: float = 0.0
    # 完全相同文件重复上传时为 True（区别于 J1 的语义去重）
    duplicate_of: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _root() -> Path:
    root = Path(get_settings().upload_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _doc_dir(doc_id: str) -> Path:
    return _root() / doc_id


def doc_id_for(content: bytes) -> str:
    """内容哈希前 12 位 ⇒ 同一份文件永远同一个 id。"""
    return hashlib.sha256(content).hexdigest()[:12]


def safe_filename(name: str) -> str:
    """只看扩展名和一份安全的主干名，防止 `../../etc/passwd` 这类路径穿越。"""
    base = Path(name or "upload.pdf").name  # 先砍掉任何目录部分
    cleaned = SAFE_NAME_RE.sub("_", base).strip("._") or "upload.pdf"
    return cleaned[:120]


def exists(doc_id: str) -> bool:
    return (_doc_dir(doc_id) / "meta.json").exists()


# ---------------------------- 写入 ----------------------------


def save_upload(filename: str, content: bytes) -> tuple[str, DocumentMeta]:
    """落盘上传件。已存在（同内容）则直接返回既有元数据，不重复写。"""
    if not content:
        raise ValueError("空文件")
    if not content[:5].startswith(b"%PDF"):
        raise ValueError("不是 PDF（文件头缺少 %PDF）")

    doc_id = doc_id_for(content)
    meta_path = _doc_dir(doc_id) / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["duplicate_of"] = doc_id
        return doc_id, DocumentMeta(**meta)

    d = _doc_dir(doc_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "original.pdf").write_bytes(content)

    meta = DocumentMeta(
        doc_id=doc_id,
        filename=safe_filename(filename),
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        uploaded_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        doc_type="text",
        page_count=0,
        title=None,
    )
    save_meta(meta)
    return doc_id, meta


def save_meta(meta: DocumentMeta) -> None:
    _doc_dir(meta.doc_id).mkdir(parents=True, exist_ok=True)
    (_doc_dir(meta.doc_id) / "meta.json").write_text(
        json.dumps(meta.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def save_parsed(doc_id: str, parsed: dict[str, Any]) -> None:
    (_doc_dir(doc_id) / "parsed.json").write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------- 读取 ----------------------------


def get_meta(doc_id: str) -> DocumentMeta | None:
    p = _doc_dir(doc_id) / "meta.json"
    if not p.exists():
        return None
    return DocumentMeta(**json.loads(p.read_text(encoding="utf-8")))


def get_parsed(doc_id: str) -> dict[str, Any] | None:
    p = _doc_dir(doc_id) / "parsed.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def list_documents() -> list[DocumentMeta]:
    metas: list[DocumentMeta] = []
    for d in _root().iterdir():
        if d.is_dir() and (d / "meta.json").exists():
            try:
                metas.append(DocumentMeta(**json.loads((d / "meta.json").read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, TypeError):
                continue  # 半成品目录（解析中途崩过）跳过，不影响列表
    metas.sort(key=lambda m: m.uploaded_at, reverse=True)
    return metas


def original_path(doc_id: str) -> Path | None:
    p = _doc_dir(doc_id) / "original.pdf"
    return p if p.exists() else None


def iter_parsed() -> list[tuple[dict[str, Any], str]]:
    """遍历全库的解析结果 ⇒ [(parsed_dict, filename)]，供 J1 去重逐篇比对。"""
    out: list[tuple[dict[str, Any], str]] = []
    for meta in list_documents():
        parsed = get_parsed(meta.doc_id)
        if parsed:
            parsed["doc_id"] = meta.doc_id  # 便于去重结果回指来源
            out.append((parsed, meta.filename))
    return out


# ---------------------------- 删除 ----------------------------


def delete_document(doc_id: str) -> bool:
    """删除一篇文献的整个目录。★只允许删 upload_dir 下的直接子目录。"""
    d = _doc_dir(doc_id)
    root = _root().resolve()
    if not d.exists():
        return False
    if d.resolve().parent != root or d.resolve() == root:
        # 双保险：doc_id 被构造过时（含 .. / 绝对路径）一律拒绝
        raise ValueError(f"拒绝删除 upload_dir 之外的路径：{d}")
    shutil.rmtree(d)
    return True
