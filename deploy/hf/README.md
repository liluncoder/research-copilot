---
title: 科研助手 Agent · Research Copilot
emoji: 📚
colorFrom: indigo
colorTo: green
sdk: docker
app_port: 7860
pinned: false
short_description: 从 PDF 到可信科研结论：解析 / 抗幻觉问答 / 联动阅读 / 引用图谱 / 写作
---

# 科研助手 Agent · 在线演示

> 全国高校 AI 大模型挑战赛（B 组）参赛作品 · 李论（北华航天工业学院）
>
> 本地完整版：`docker compose up`；本 Space 是**单容器演示**（Next.js 前端 + FastAPI 后端 + 预置 9 篇文献索引）。

## 这是什么

一条从论文 PDF 到可信科研结论的闭环：解析结构化、混合检索问答、中英双栏对照、
引用图谱、数据出图与论文框架。核心不是"让大模型多写"，而是**每个论断都能追到原文，
查不到就拒答**。

| 模块 | 能做什么 | 入口 |
|---|---|---|
| M1 解析 | 标题树 / 公式 / 表格 / 参考文献；跨出版社适配；语义查重 | 文献库 |
| M2 问答 | 混合召回（Dense + BM25）→ 逐句出处 → 对不上就剔除 | 问答 |
| M3 阅读 | 原文 / 中文双栏、引用与参考文献双向跳转、段落级联动滚动 | 阅读器 |
| M5 图谱 | 引文网络 + 核心子图 PageRank，找"基石论文" | 图谱 |
| M6 写作 | CSV 出图；图注只喂统计量；References 只点名不编写 | 写作 |

M4（arXiv 检索推荐）是补充线，按赛程裁剪，不计入九项判据。

## 上手（30 秒）

1. 打开 **问答**，点示例问题（Adam 超参 / GPU 型号 / BLEU 分数）——看回答里的出处标签。
2. 打开 **阅读器**，任选一篇：左侧点 `[11]` 跳到参考文献，右侧点条目反查正文。
3. 打开 **图谱**，点节点看引用邻域，右侧按 PageRank 排序；可生成自动综述。
4. 打开 **写作**，点"用示例数据"生成图表与图注；切到"论文框架"生成带库内引用的框架。

预置语料：9 篇（SNN 局部学习规则 / e-prop / DECOLLE / SuperSpike / DRTP / TESS / LLS / NeuroTrain 等）。

## 配置

本 Space 需要以下 **Secret**（Settings → Variables and secrets）：

| 名称 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥；不配置时检索与解析仍可用，问答/图注/综述会明确报"未配置 LLM" |

可选变量：`LLM_PROVIDER`（deepseek / zhipu / dashscope）、`ZHIPU_API_KEY`、`DASHSCOPE_API_KEY`。

## 实现要点（为什么这样做）

- **单容器同源**：Next.js 以 standalone 跑在 7860，`/api` 与 `/health` 由 rewrite 转发到
  容器内 127.0.0.1:8000 的 FastAPI；公网只暴露一个端口，也避免 CORS。
- **预置索引**：镜像构建期用 BGE-M3（CPU）为 9 篇文献重建向量索引，首次问答不必等索引。
- **无外网字体**：前端用系统字体栈，构建与运行都不请求 Google Fonts。
- **判据可复跑**：九项判据脚本与判词在仓库 `tests/`、`report/`；本 Space 只做演示，不替代判据。

## 已知限制（如实列出）

- 预置 9 篇为演示语料；上传新 PDF 可解析，但容器重启后新上传件会丢失（免费 Space 无持久盘）。
- BGE-M3 在 2 核 CPU 上首次加载约 20–60 秒；已用启动预热降低首问等待。
- 图表解析对低置信度表格可能错位，界面会标黄提示。
- 免费 Space 长时间无访问会休眠，首次唤醒需 1–2 分钟。
- 问答不覆盖库外知识；"未找到依据"是设计特性，不是故障。

## 仓库

源码、判据脚本、技术文档：<https://github.com/liluncoder/research-copilot>
