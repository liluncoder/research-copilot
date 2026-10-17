# 科研助手 Agent（Research Copilot）

> 全国高校 AI 大模型挑战赛 ·「智领科研·意图驱动」赛项参赛作品（个人 · B 组）  
> 全流程科研助手 Agent：文献智能解析 → 抗幻觉问答 → 联动翻译阅读 → 检索推荐 → 引用图谱 → 写作辅助

## 一句话架构

```
Next.js 14 (前端)  ──HTTP──►  FastAPI (后端)  ──►  LangGraph Agent 编排
      │                              │                    ├─ RAG: BGE-M3 + Chroma 混合检索 + 出处锚点
      │                              │                    ├─ 解析: Marker + PaddleOCR
      │                              │                    └─ 工具: arXiv API / 代码执行 / 图谱计算(NetworkX)
      └─ PDF.js 阅读器 / G6 图谱 / ECharts 图表        LLM: DeepSeek-V4.1（主）+ 智谱/通义（备）
```

## 快速开始

### 方式一：Docker（推荐，评审复现用）

```bash
cp .env.example .env   # 然后填入至少一个 LLM_API_KEY
docker compose up --build
# 前端 http://localhost:3000   后端文档 http://localhost:8000/docs
```

### 方式二：本地开发

```bash
# 后端（Python 3.11 + uv）
cd backend && uv sync && uv run uvicorn app.main:app --reload

# 前端（Node 20+）
cd frontend && pnpm install && pnpm dev
```

### 判据复跑（一条命令验一个判据）

| 判据 | 命令（在仓库根目录） |
|---|---|
| J1 语义去重 | `python tests/verify_j1.py` |
| J2 解析（标题树/公式/参考文献） | `python tests/verify_j2.py` |
| J2 表格（4 张表结构 + 关键数值） | `python tests/verify_j2_tables.py` |
| J3 扫描件 OCR + 541 页内存 | Windows：`backend\tools\run_j3.cmd`　Linux/macOS：`python backend/tools/run_j3.py` |
| S1 文献库 API | `python tests/verify_s1_api.py` |

> ★Windows 用户注意：PowerShell 5.1 **不支持** `cd a && b` 这种写法，
> 请一行一行执行；J3 脚本已内置解释器自动选择，不需要设 `PYTHONPATH`。

## 目录结构

```
├── 计划表.md            ★项目管理入口（只放指针，内容在 路线/）
├── 路线/                计划分篇（方向 / 主路线 / 判据 / 风险 / 提交清单）
├── frontend/            Next.js 14 + TypeScript + Tailwind + shadcn/ui
├── backend/             FastAPI + LangGraph + Chroma
├── tests/fixtures/      官方测试集（pdf/）+ 判据复跑输入
├── docs/demo/           各阶段演示 gif（视频原料）
└── report/              判词存档
```

## 环境变量

见 `.env.example`。★API 密钥只进环境变量，不要提交进仓库。

## 团队信息

- 李论，北华航天工业学院（普通本科 · B 组），个人参赛
- 学号 202501001224

## 开发方法

本项目采用「判据先行」工作法：每个功能发车前先在 `路线/04 判据与验收纪律.md` 登记 J 编号判据，  
开发循环见 `路线/09 一次循环操作清单.md`。AI 辅助编程（Vibe Coding）的使用方式与 Prompt 调优  
记录在技术文档中，Git 提交历史保留完整开发过程。
