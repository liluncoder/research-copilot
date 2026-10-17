from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """★密钥只从这里读环境变量；.env 不进仓库（见根 .gitignore）。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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

    # 服务
    backend_port: int = 8000

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
