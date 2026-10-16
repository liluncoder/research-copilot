FROM python:3.11-slim

# uv：快速装依赖
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# ★构建期索引源。默认走阿里云镜像 —— 国内直连 PyPI 实测极慢
#   （踩坑：pydantic-core 一个包下了 18 分钟还没走完，整层超过 20 分钟），
#   换镜像后是同数量级地快。
#   海外构建 / 镜像不可用时，切回官方源：
#     docker compose build --build-arg PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_HTTP_TIMEOUT=120

COPY pyproject.toml ./
RUN uv pip install --system --index-url "${PIP_INDEX_URL}" -r pyproject.toml

COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
