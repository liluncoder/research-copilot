# syntax=docker/dockerfile:1
#
# HF Spaces 单容器镜像：Next.js（7860，对外）+ FastAPI（8000，仅本机）+ 预置数据/索引。
#
# ★构建上下文 = deploy_hf.py 生成的 staging 目录（含 backend/ frontend/ deploy 文件），
#   不是仓库根目录。这样 Space 仓库只需要演示必需的文件，不会把 108MB 测试件传上去。
#
# 本地快速烟测（跳过 2.2GB 的 BGE-M3 与索引重建）：
#   docker build --build-arg WITH_BGE=0 -t research-copilot:lite .
#   docker run --rm -p 7860:7860 -e EMBEDDING_BACKEND=hash research-copilot:lite

# ---------- 1. 前端：standalone ----------
FROM node:20-bookworm-slim AS web

WORKDIR /src
ARG NPM_REGISTRY=https://registry.npmjs.org

COPY frontend/package.json frontend/package-lock.json ./
RUN npm config set registry "${NPM_REGISTRY}" \
 && npm ci --no-audit --no-fund

COPY frontend/ ./
# 同源部署：空串 ⇒ 浏览器发相对路径，由 rewrite 转发到容器内后端
ENV NEXT_PUBLIC_API_URL="" \
    INTERNAL_API_URL="http://127.0.0.1:8000" \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---------- 2. 模型：BGE-M3（独立 stage，改后端不会重下 2.2GB） ----------
FROM python:3.11-slim AS model

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG WITH_BGE=1
ENV PYTHONUNBUFFERED=1

# modelscope 的包体很小（核心是 modelscope-hub），带上 huggingface_hub 做备用源
RUN pip install --no-cache-dir -i "${PIP_INDEX_URL}" "modelscope==1.40.2" huggingface_hub

COPY fetch_bge.py /fetch_bge.py
RUN mkdir -p /app/models \
 && if [ "${WITH_BGE}" = "1" ]; then python /fetch_bge.py; fi

# ---------- 3. 运行时：Python + Node + 预置数据 ----------
FROM python:3.11-slim

# libgomp1：torch / onnxruntime 的 OpenMP 运行时
# OpenCV（RapidOCR 依赖）跑在无桌面的 slim 里，仍需要这些 X/GL 运行库；
# 否则 import cv2 会直接报 libxcb.so.1 / libGL.so.1 找不到。
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libgomp1 ca-certificates \
      libgl1 libglib2.0-0 libxcb1 libxext6 libsm6 libxrender1 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 依赖源：ModelScope 构建机在国内，默认走阿里云；HF 构建可传 --build-arg 覆盖
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

COPY backend/pyproject.toml ./pyproject.toml
# ★torch 必须 >=2.6：transformers 5.x 会拒绝加载更低版本（报
#   "Disabling PyTorch because PyTorch >= 2.6 is required"），BGE 随后 NameError。
#   仍用 CPU 轮子，避免 CUDA 依赖多出 2GB+。
RUN uv pip install --system --index-url "${TORCH_INDEX_URL}" "torch==2.6.0" \
 && uv pip install --system --index-url "${PIP_INDEX_URL}" -r pyproject.toml

COPY backend/app ./app
COPY backend/tools ./tools
COPY backend/data ./data
COPY backend/chroma_data ./chroma_data
COPY --from=model /app/models /app/models

# ---------- 3. 预置 BGE-M3 与向量索引（可关） ----------
# WITH_BGE=1：构建期下载 BGE-M3（约 2.2GB）并按 1024 维重建 9 篇文献的索引。
# WITH_BGE=0：保留仓库里的 hash 索引，镜像小、构建快，仅用于本地烟测。
ARG WITH_BGE=1
# ★STORE_BACKEND 必须在 reindex 之前设：镜像里装了 chromadb，
#   若走 auto 会把 BGE 向量写进 Chroma collection；而运行时我们读 numpy 索引
#   ⇒ 维度对不上、检索直接坏。这里强制 numpy，构建与运行用同一套索引。
ENV HF_HOME=/app/models/hf \
    STORE_BACKEND=numpy

RUN if [ "${WITH_BGE}" = "1" ]; then \
      EMBEDDING_BACKEND=bge-m3 BGE_M3_PATH=/app/models/bge-m3 python tools/reindex_all.py ; \
    fi

# ---------- 4. 前端产物与启动脚本 ----------
COPY --from=web /src/.next/standalone /app/web
COPY --from=web /src/.next/static /app/web/.next/static
COPY --from=web /src/public /app/web/public
COPY --from=web /usr/local/bin/node /usr/local/bin/node

COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

ENV PYTHONUNBUFFERED=1 \
    PORT=7860 \
    UPLOAD_DIR=/app/data/uploads \
    CHROMA_PERSIST_DIR=/app/chroma_data \
    EMBEDDING_BACKEND=bge-m3 \
    BGE_M3_PATH=/app/models/bge-m3 \
    STORE_BACKEND=numpy \
    LLM_PROVIDER=deepseek \
    NEXT_TELEMETRY_DISABLED=1

EXPOSE 7860
CMD ["/app/start.sh"]
