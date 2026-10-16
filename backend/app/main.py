"""FastAPI 应用入口（S0 骨架：/health + /api/v1/modules）。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="科研助手 Agent API",
    version="0.1.0",
    description="全流程科研助手 Agent — 文献解析 / 抗幻觉 RAG / 联动翻译 / 检索推荐 / 引用图谱 / 写作辅助",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """S0 出口判据：前端据此判断全栈闭环是否通。"""
    return {
        "status": "ok",
        "version": "0.1.0",
        "stage": "S0",
        "llm_provider": settings.llm_provider,
        "llm_configured": settings.llm_configured(),
    }


@app.get("/api/v1/modules")
def modules() -> dict:
    """六大模块当前状态（与路线/06 的小阶段目标对应）。"""
    return {
        "modules": [
            {"id": "M1", "name": "PDF 解析与语义去重", "stage": "S1", "state": "pending"},
            {"id": "M2", "name": "抗幻觉 RAG 问答", "stage": "S2", "state": "pending"},
            {"id": "M3", "name": "中英联动阅读", "stage": "S3", "state": "pending"},
            {"id": "M4", "name": "arXiv 检索推荐", "stage": "S4", "state": "pending"},
            {"id": "M5", "name": "引用图谱挖掘", "stage": "S5", "state": "pending"},
            {"id": "M6", "name": "写作与可视化 Copilot", "stage": "S6", "state": "pending"},
        ]
    }
