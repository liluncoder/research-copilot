"""API 出入参模型（只放前端要用的形状，不做过度建模）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class OutlineNode(BaseModel):
    """标题树节点（前端导航栏直接递归渲染）。"""

    label: str = Field(description="如 '3.2.1 Scaled Dot-Product Attention'")
    level: int = Field(description="1/2/3")
    page: int
    children: list["OutlineNode"] = Field(default_factory=list)


class DocumentMetaOut(BaseModel):
    doc_id: str
    filename: str
    size_bytes: int
    sha256: str
    uploaded_at: str
    doc_type: str = Field(description="text=有文本层；scanned=无文本层待 OCR")
    page_count: int
    title: str | None
    authors: list[str]
    abstract_chars: int
    n_headings: int
    n_references: int
    n_math_lines: int
    warnings: list[str]
    parse_seconds: float
    duplicate_of: str | None = None


class UploadResult(BaseModel):
    """上传响应：meta + 标题树一次给全，前端上传完立刻能画导航。"""

    meta: DocumentMetaOut
    outline: list[OutlineNode] = Field(default_factory=list)
    outline_flat: list[dict] = Field(
        default_factory=list, description="扁平版（含 level/number/page），便于列表渲染"
    )
    references_preview: list[dict] = Field(default_factory=list)


class DocumentDetail(BaseModel):
    meta: DocumentMetaOut
    outline: list[OutlineNode]
    references: list[dict]
    sections: list[dict]
    math_lines: list[dict]
    abstract: str


class DedupResolveRequest(BaseModel):
    """J1：用户在"覆盖 / 保留"之间做选择。"""

    doc_id: str = Field(description="本次新上传的文档")
    target_doc_id: str | None = Field(
        default=None, description="预警里指出的库中已有版本（keep_both 时可省略）"
    )
    action: str = Field(
        description="keep_both=两份都留；replace_existing=删掉库中旧版、留新的；"
        "discard_new=放弃本次上传（删掉新的）"
    )
