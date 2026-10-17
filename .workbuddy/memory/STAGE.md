# STAGE — 阶段级当前状态

**当前阶段：S3（阅读器）—— J5 已过** · 2026-10-18 01:20 更新 · 距省赛截止 31 天

```
S0骨架 ██完成(10-16) → S1解析 ██收官(10-17) → S2 RAG ██J4已过 → S3阅读器(10-29~11-02)
→ S5图谱(11-03~06) → S6写作(11-07~10) → S7收尾(11-11~17) → 11-17 提交
（S4 arXiv 补充线，夹在 S3 后，可裁剪）
```

**S2 已落（判词 `report/S2_判词.md` 第 1 段，7/7 PASS）**：
- 结构化切块：以标题树为边界，每块带 `section_path / page_start / page_end`（J4 出处锚点的前提）
- 混合检索：BM25 稀疏 + 稠密向量 → **RRF 融合**（零调参，量纲无关）
- 可插拔：向量档 bge-m3 / hash(auto 降档不静默)；索引档 Chroma / numpy
- API：`POST /api/v1/search`（带出处）、`GET /api/v1/search/status`、`POST /api/v1/search/index/{id}`
- 实测：v1 → 49 块；β1/β2 命中 p7 5.3、GPU 命中 p7 5.2、BLEU 命中 p1 摘要

**卡点（要李论动手）**：
1. 下模型：`backend\tools\fetch_models.py`（2.2GB，可续传，走 hf-mirror）
2. 装依赖：`pip install chromadb sentence-transformers`
3. 复跑：`python tests\verify_s2_retrieval.py --backend bge-m3`（含中文跨语言查询）

**J4 已过（10-17 晚，10/10）**：LangGraph 1.2.16 四节点 plan→retrieve→answer→verify；
三连问全中且出处正确（0.9/0.98/10⁻⁹ @p7·5.3；8 块 P100；28.4 BLEU @p1 摘要）；库里没有的问题正确拒答。
判词 `report/S2_判词.md` 第 2 段
★两条反幻觉闸：检索空 ⇒ 不调 LLM；回答后逐条核对出处，编造的剔除并计入 invalid_citations
★查询改写（中文 → 英文检索词）是当前 vector 档下的命门，换 BGE-M3 后仍然有用

**问答界面已落（10-17 深夜）**：`/ask` 单列极简风；出处渲染成小标签，
四步思考过程做成时间线（含耗时与检索词），依据片段可折叠并标注 dense#/sparse# 名次。

**J2 最后一块已过（10-17 深夜，15/15）**：多文对比问答 `app/rag/compare.py`
（按文献分路召回 + 表格化回答，逐格挂出处）；语料 BERT/GPT-1/GPT-2/GPT-3 已入库 `tests/fixtures/papers/`

**S3 已落（10-18 凌晨，J5 7/7）**：`/reader/[id]` 双栏（原文/中文）+ 标题树 + 引用双向跳转 + 段落级联动；
后端 `reader.py`（段落 id + 双向索引）+ `translate.py`（段落级翻译 + 哈希缓存）

**语料已扩充（10-18 凌晨）**：李论桌面 `snn/` 的 8 篇局部学习规则论文 8/8 解析成功并全部入库
（9 篇 / 845 块）；修掉作者-年份引用、连字符分词、拒答判定三个真问题（判词 `report/S3_判词.md` 第六节）

**下一步开发**：S5 引用图谱（J6：NetworkX + PageRank/度中心性 + G6 20 节点渲染）
★图规模已够：单 08 NeuroTrain 就有 196 条参考文献，9 篇合计引用关系数百条

**判据状态**：J1 过 ｜ J2 过 ｜ J3-a/J3-b 过 ｜ J4~J8 未测（检索层已具备，回答层未做）

**详情**：`../../计划表.md` · `../../路线/02 路线图与逐模块计划.md` · `../../路线/06 小阶段目标.md`
