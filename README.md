# 科研助手 Agent（Research Copilot）

> 全国高校 AI 大模型挑战赛 · AI 大模型创新应用挑战赛（科研助手赛项）
> 个人参赛 · 普通本科组（B 组）

从一篇 PDF 到可信的科研结论：结构化解析 → 抗幻觉问答 → 中英联动阅读 → 引用图谱 → 数据出图与写作。

核心不是"让大模型多写"，而是**每个论断都能追到原文页码与章节；查不到就明确拒答**。

- 代码仓库：<https://github.com/liluncoder/research-copilot>
- 在线演示：<https://lixinci-research-copilot.ms.show>（公网可访问，无需登录）

## 一、系统架构

```
Next.js 14 (App Router)  ──HTTP──►  FastAPI  ──►  LangGraph 状态机（plan→retrieve→answer→verify）
      │                                │             ├─ 检索：本地向量 + BM25 → RRF 融合，每句挂出处
      │                                │             ├─ 解析：PDF 结构化 / 标题树 / 表格 / 参考文献 / 扫描件 OCR
      │                                │             └─ 工具：引用图谱 / 数据出图 / 论文框架
      └─ 中英双栏阅读器 / 图谱与图表可视化
```

六个模块：文献解析与内容去重（M1）、抗幻觉问答（M2）、中英联动阅读（M3）、
arXiv 检索入库（M4，补充线）、引用图谱与未来工作（M5）、写作 Copilot（M6）。

三道防幻觉闸：图注只喂统计量、参考文献只"点名"不"编写"、
架构拓扑图节点只取自论文章节树。检索为空时不调用大模型，回答生成后逐条回查出处。

存储可插拔：装了 Chroma 用 Chroma，否则退到等价的 numpy 索引；
向量与 OCR 均在本地 CPU 运行，无 GPU 也能跑完整流程。

## 二、安装与运行

### 方式 A：Docker（推荐）

```bash
cp .env.example .env          # 填入任意一家 LLM 的 key（不填也可运行离线功能）
docker compose up --build
# 前端 http://localhost:3000　后端接口文档 http://localhost:8000/docs
```

### 方式 B：本机 Python + Node（不装 Docker）

1. 安装 Python 3.11+ 与 Node.js 18+，均勾选加入 PATH。
2. 安装后端依赖：`cd backend && python -m pip install -r requirements-demo.txt`
   （轻量集，几分钟；完整 `requirements.txt` 含向量模型与 OCR 依赖）。
3. 双击根目录 `启动本地演示.bat`，脚本会自动探测 Python / Node、
   等待后端健康检查通过后打开 <http://localhost:3010>。
4. 页面顶部显示「已连接」即可开始使用；`停止本地演示.bat` 可关闭服务。

两套端口不要混用：Docker 为 3000 / 8000，本机脚本为 3010 / 8010。
排障步骤见压缩包内 `提交说明.txt`。

## 三、判据复跑

每条判据都配了可复跑脚本，不靠口头声明：

| 判据 | 内容 | 命令 |
|---|---|---|
| J1 | PDF 语义去重 | `python tests/verify_j1.py` |
| J2 | 标题树 / 公式 / 表格 / 参考文献 | `python tests/verify_j2.py`、`verify_j2_tables.py` |
| J4 | 中文问答 + 逐句出处 + 拒答 | `python tests/verify_j4_qa.py`（需 LLM key） |
| J5 | 双栏对照 / 引用双向跳转 | `python tests/verify_j5_reader.py` |
| J6 | 引用图谱 / 核心子图 PageRank | `python tests/verify_j6_graph.py` |
| J7 | CSV 出图 + 图注只看统计量 | `python tests/verify_j7_chart.py` |
| J8 | 论文框架 + References 只点名 | `python tests/verify_j8_refs.py` |
| 补充 | 官方例题 / 架构拓扑图 / arXiv 入库 | `verify_official_qa5.py`、`verify_163_diagram.py`、`verify_141_arxiv.py --offline` |

J5 / J6 / J8 依赖文献库内容，复跑前在 `/library` 上传 PDF；J4 自带 fixture。

## 四、环境变量

见 `.env.example`。**API 密钥只进环境变量**，仓库与作品包内只有模板，没有任何真实 key。
可选 provider：DeepSeek / 通义千问 / 智谱，走 OpenAI 兼容协议，靠一个环境变量切换。
未配置 LLM 时，解析、检索、阅读器、图谱照常可用，问答与图注会明确提示「未配置 LLM」。

## 五、团队信息

- 李论，北华航天工业学院，个人参赛（普通本科组 B 组）
- 联系方式见官网报名信息

## 六、已知限制

- 在线演示为裁剪过的预置语料；本地完整语料规模更大，两者是同一套代码的不同数据规模。
- 在线实例无持久盘，容器重启后新上传的 PDF 不保留，预置文献不受影响。
- 定时刷新（1.4.2）未实现，已在《作品介绍文档》中列明。
