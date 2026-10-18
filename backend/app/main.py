"""FastAPI 应用入口（/health + /api/v1/modules）。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import compare, documents, graph, qa, reader, search, writing
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="科研助手 Agent API",
    version="0.1.0",
    description="全流程科研助手 Agent — 文献解析 / 抗幻觉 RAG / 联动翻译 / 检索推荐 / 引用图谱 / 写作辅助",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(search.router)
app.include_router(qa.router)
app.include_router(compare.router)
app.include_router(reader.router)
app.include_router(graph.router)
app.include_router(writing.router)


@app.get("/health")
def health() -> dict:
    """全栈闭环自检：前端顶栏的服务状态点与部署探针都读这里。"""
    return {
        "status": "ok",
        "version": "0.1.0",
        "stage": "S7",
        "llm_provider": settings.llm_provider,
        "llm_configured": settings.llm_configured(),
        "embedding_backend": settings.embedding_backend,
    }


@app.get("/api/v1/modules")
def modules() -> dict:
    """六大模块当前状态（与路线/06 的小阶段目标对应）。"""
    return {
        "modules": [
            {"id": "M1", "name": "PDF 解析与语义去重", "stage": "S1", "state": "done", "judges": ["J1", "J2", "J3"]},
            {"id": "M2", "name": "抗幻觉 RAG 问答", "stage": "S2", "state": "done", "judges": ["J4"]},
            {"id": "M3", "name": "中英联动阅读", "stage": "S3", "state": "done", "judges": ["J5"]},
            {
                "id": "M4",
                "name": "arXiv 检索推荐",
                "stage": "S4",
                "state": "supplemental",
                "judges": [],
                "note": "补充线，按赛程裁剪；不计入九项判据",
            },
            {"id": "M5", "name": "引用图谱挖掘", "stage": "S5", "state": "done", "judges": ["J6"]},
            {"id": "M6", "name": "写作与可视化 Copilot", "stage": "S6", "state": "done", "judges": ["J7", "J8"]},
        ]
    }
