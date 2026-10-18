from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# ★仓库根的 .env（backend/app/core/config.py → parents[3] = 仓库根）
#   踩过的坑：pydantic-settings 默认按**当前工作目录**找 .env，
#   从 backend/ 起服务时就读不到根目录的 .env ⇒ llm_configured 假 false。
ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """★密钥只从这里读环境变量；.env 不进仓库（见根 .gitignore）。"""

    # 两个都读：仓库根的 .env 优先（本地开发），其次当前目录（Docker 里通常直接注入环境变量）
    model_config = SettingsConfigDict(
        env_file=(str(ROOT_ENV), ".env"), extra="ignore"
    )

    # LLM
    llm_provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/paas/v4"
    zhipu_model: str = "glm-4-plus"
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen-plus"

    # 本地模型
    embedding_model: str = "BAAI/bge-m3"
    ocr_lang: str = "ch"

    # S2 检索
    # auto = 有 BGE-M3 就用，没有就退到离线 hash 向量（保证管线能跑、判据能复现）
    embedding_backend: str = "auto"  # auto | bge-m3 | hash
    embedding_device: str = "cpu"
    rag_chunk_chars: int = 900
    rag_chunk_overlap: int = 120
    rag_top_k: int = 5
    rag_dense_weight: float = 1.0
    rag_sparse_weight: float = 1.0

    # 存储
    chroma_persist_dir: str = "./chroma_data"
    upload_dir: str = "./data/uploads"
    # auto = 装了 chromadb 就用、否则 numpy；numpy = 强制读 <doc>/vectors.npy 索引。
    # ★HF 单容器用的是构建期预生成的 numpy 索引；chromadb 也在镜像依赖里，
    #   若保持 auto 会切到空的 Chroma collection ⇒ 检索零命中。所以 HF 固定 STORE_BACKEND=numpy。
    store_backend: str = "auto"  # auto | numpy | chroma

    # 服务
    backend_port: int = 8000
    # ★CORS：前端端口是活的（3000 Docker / 3010 dev / HF Spaces 域名），
    #   写死一个 origin 会让另一个端口直接 Failed to fetch（实测踩到：3010 被拦）。
    #   本地开发用正则放行任意 localhost 端口，线上用 CORS_ORIGINS 显式指定。
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    cors_origin_regex: str = r"http://(localhost|127\.0\.0\.1):\d+"

    def active_llm_key(self) -> str:
        return {
            "deepseek": self.deepseek_api_key,
            "zhipu": self.zhipu_api_key,
            "dashscope": self.dashscope_api_key,
        }.get(self.llm_provider, "")

    def llm_configured(self) -> bool:
        return bool(self.active_llm_key())


@lru_cache
def get_settings() -> Settings:
    return Settings()
