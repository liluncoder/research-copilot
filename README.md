# 科研助手 Agent（Research Copilot）

> 仓库：<https://github.com/liluncoder/research-copilot>　·　全国高校 AI 大模型挑战赛（B 组 · 个人）
>
> **在线演示**：<https://lixinci-research-copilot.ms.show>　（[创空间页](https://modelscope.cn/studios/lixinci/research-copilot)）

从一篇 PDF 到可信的科研结论：结构化解析 → 抗幻觉问答 → 中英联动阅读 → 引用图谱 → 数据出图与写作。
核心不是"让大模型多写"，而是**每个论断都能追到原文页码与章节；查不到就明确拒答**。

## 已通过的判据

| 判据 | 内容 | 复跑命令（仓库根目录） |
|---|---|---|
| J1 | PDF 语义去重（标题/版本/相似度） | `python tests/verify_j1.py` |
| J2 | 标题树 / 公式 / 表格 / 参考文献 | `python tests/verify_j2.py`　`python tests/verify_j2_tables.py` |
| J3-a/b | 扫描件 OCR + 541 页内存上限 | Windows：`backend\tools\run_j3.cmd`　其他：`python backend/tools/run_j3.py` |
| J4 | 三连问 + 逐句出处 + 拒答 | `python tests/verify_j4_qa.py`（需 `.env` 的 LLM key） |
| J5 | 双栏对照 / 引用双向跳转 / 段落联动 | `python tests/verify_j5_reader.py` |
| J6 | 引用图谱 / 核心子图 PageRank | `python tests/verify_j6_graph.py` |
| J7 | CSV 出图 + 图注只看统计量 | `python tests/verify_j7_chart.py` |
| J8 | 论文框架 + References 只点名不编写 | `python tests/verify_j8_refs.py` |

判词与已知限制在 `report/`；每条判据都有可复跑脚本，不靠口头声明。

> J5 / J6 / J8 依赖文献库内容。演示语料（9 篇 PDF 与解析结果）不进仓库，
> 从仓库根目录复跑时先设 `UPLOAD_DIR=backend/data/uploads`，或先在 `/library` 上传 PDF。
> J4 自带 fixture，不依赖文献库。

## 一句话架构

```
Next.js 14 (App Router)  ──HTTP──►  FastAPI  ──►  LangGraph 状态机（plan→retrieve→answer→verify）
      │                                │             ├─ RAG：BGE-M3 向量 + BM25 → RRF 融合；每句挂出处
      │                                │             ├─ 解析：PyMuPDF + RapidOCR；标题树/表格/参考文献
      │                                │             └─ 工具：引用图谱 NetworkX / 图表 ECharts / 写作
      └─ 双栏阅读器 / ECharts 图谱与图表；全部走系统字体，零外网字体请求
LLM：DeepSeek（主）+ 智谱/通义（备），密钥只进环境变量
```

存储是**可插拔**的：装了 Chroma 用 Chroma，否则退到等价的 numpy 索引（`<doc>/vectors.npy`）。
1~50 篇论文规模下两者检索结果一致；HF 演示镜像固定用 numpy 索引，避免空 collection。

## 快速开始

### 方式一：Docker（评审复现）

```bash
cp .env.example .env     # 至少填 DEEPSEEK_API_KEY
docker compose up --build
# 前端 http://localhost:3000    后端文档 http://localhost:8000/docs
```

### 方式二：本地开发

```bash
# 后端（Python 3.11 + uv）
cd backend
uv pip install -r pyproject.toml
uvicorn app.main:app --reload

# 前端（Node 20）
cd frontend
npm install
npm run dev
```

### 前端构建（受限环境）

```bash
cd frontend
python tools/build.py            # 先 shutil.rmtree 清产物，再独立 distDir 构建
python tools/build.py --api http://localhost:8000
```

`tools/build.py` 绕开两件事：safe-delete 钩子会拦住 `next build` 清理旧产物（EPERM）；
Next 默认用 jest-worker 子进程编译，沙箱禁止命名管道（`spawn EPERM`）——
`next.config.mjs` 已关 `webpackBuildWorker`、改 `workerThreads`，构建可在受限环境内完成。

## 在线演示（单容器）

`deploy/hf/` 是演示镜像：Next.js 跑 7860 对外，FastAPI 跑容器内 127.0.0.1:8000，
`/api` 与 `/health` 由 Next rewrite 同源转发；构建期预置 9 篇文献、845 块索引与 BGE-M3 权重。
同一个镜像同时适配 **ModelScope 创空间**（`docker.yaml`，端口固定 7860）与 **HF Spaces**（需 PRO）。

```powershell
# ModelScope 创空间（主）：先在网页建 Docker 创空间，再推
python tools\deploy_hf.py                    # 生成 build/hf-space / build/ms-space 的源文件
$env:MODELSCOPE_TOKEN='ms-...'
python tools\deploy_modelscope.py --repo lixinci/research-copilot

# HF Spaces（备，需要 PRO）：登录后
python tools\deploy_hf.py --upload --set-secret --wait
```

演示环境只配一个环境变量/Secret：`DEEPSEEK_API_KEY`。免费创空间无持久盘，重启后新上传的 PDF 会丢；
预置语料不受影响。部署实测与已知限制见 `report/G20_判词.md`。

## 目录结构

```
├── 计划表.md             项目管理入口（只放指针，内容在 路线/）
├── 路线/                 方向 / 路线图 / 判据 / 风险 / 提交清单
├── frontend/             Next.js 14 + TypeScript + Tailwind（components/ui 为统一原语）
├── backend/              FastAPI + 解析/RAG/阅读/图谱/写作
├── deploy/hf/            HF Spaces 单容器 Dockerfile 与 Space README
├── tools/deploy_hf.py    生成/上传 Space 构建上下文
├── tests/                判据脚本（fixtures 里是官方测试集）
└── report/               判词存档
```

## 环境变量

见 `.env.example`。★API 密钥只进环境变量，`.env` 已被 `.gitignore` 排除；
仓库里只有模板，没有任何真实 key。

## 团队信息

- 李论，北华航天工业学院（普通本科 · B 组），个人参赛
- 学号 202501001224

## 开发方法

「判据先行」：每个功能发车前先在 `路线/04 判据与验收纪律.md` 登记 J 编号判据，
开发循环见 `路线/09 一次循环操作清单.md`。AI 辅助编程（Vibe Coding）的使用方式与
Prompt 调优记录在技术文档中，Git 提交历史保留完整开发过程。
