# GitHub 开源知识库调研：OfferPilot Knowledge 后续设计

> **历史调研快照**：本文的“Wiki Page + Evidence”建议已被后续访谈修正。当前架构方向以
> [Knowledge 系统主文档](./knowledge-system.md) 为准。

**Date**: 2026-07-12  
**Scope**: 为 OfferPilot 当前 Knowledge Wiki 实现选择可借鉴的开源知识库/RAG/Agent Memory 设计。  
**Current branch**: `feat/20260710-knowledge-wiki`

## 1. 结论摘要

1. Karpathy LLM Wiki 的强项是“把知识编译成持续维护的 Page”，但它默认有人类和 Agent 共同维护 Markdown Wiki；OfferPilot 当前把它产品化成一次性自动 Ingest Pipeline 后，缺少检索兜底、质量评估和领域模板，容易出现“写成了 Page，但不好找、不好用”。
2. 主流开源知识库没有放弃原始资料检索：Dify、RAGFlow、Open WebUI、AnythingLLM 都保留 chunk/evidence 级检索、关键词/语义混合检索、引用回指和检索测试。
3. GraphRAG / LightRAG / Graphiti / Cognee 的启发不是“马上上图数据库”，而是：实体、事实、关系、时间和来源应结构化保存，搜索时用多信号融合，而不是只搜生成后的文章。
4. OfferPilot 更适合“Wiki 编译层 + Evidence 检索层”的双层架构：Wiki Page 仍是最终知识成果，但 Evidence/Source 必须作为可搜索、可定位、可调试的事实底座。

## 2. 当前实现观察

- 运行时 SSOT 是 SQLite，而不是 Markdown vault；原始 Source 和附件在文件系统，关系数据在 SQLite。
- Ingest Runner 是三步：Analysis → Page Generation → Index Summarization；正式写入在一次 SQLite 事务中提交。
- Search 当前只搜索 `knowledge_wiki_pages_fts`，再做一跳 Wikilink 扩展；不会搜索原始 Source/Evidence。
- 默认 Purpose/Schema 很薄，只定义了语言、Page Type、citation 和 wikilink 规则，没有具体求职知识本体和 Page 模板。
- Chat Agent 只暴露 `add_to_wiki` 和 `search_wiki`，且搜索结果只返回 Page 级 summary，不返回正文 excerpt 或 Evidence。

## 3. 为什么“LLM Wiki 思想”落地后效果可能不好

Karpathy 原文描述的是一种“Agent + Obsidian + 人类持续参与”的工作方式，不是一个自动化知识库产品规格。把它直接产品化成自动 Ingest，会暴露几个落差：

1. **Wiki Page 是编译产物，不是检索底座**  
   当前 `search_wiki` 只搜生成后的 Page summary/content。若 Ingest 没把某个细节写进 Page，用户查询时就完全召回不到；这正是旧 Page-only 检索决策已经暴露的负面后果。

2. **搜索结果过度压缩**  
   Chat Tool 现在只返回 `slug/title/section/summary`，不返回正文片段、citation 或 Evidence 摘录。Agent 即使命中正确 Page，也缺少足够上下文回答细节问题，容易继续猜。

3. **Schema 太薄，无法稳定驱动 Page 质量**  
   默认 Schema 只规定中文、Page Type、citation 和 wikilink。对求职场景真正关键的 Page 模板（公司、岗位、面试主题、项目、八股题、投递策略）没有结构化约束，所以模型每次自由发挥，长期会变成“风格相似的摘要集合”，而不是可复用知识资产。

4. **Evidence 只作为引用校验存在，没有成为可搜索对象**  
   系统已经有 `KnowledgePageEvidence`、`Extraction Snapshot` 和 citation 校验，但没有 Evidence FTS / snippets / search API。主流 RAG 系统都会让 chunk/evidence 成为检索、调试和引用的基本单位。

5. **没有检索评估闭环**  
   Dify/FastGPT 等产品都有“知识库单点搜索测试 / retrieval records / 应用评测”。当前 OfferPilot 没有 gold queries、召回记录、bad case 标注和回归测试，调 prompt 只能靠体感。

6. **缺少 metadata/filtering**  
   求职知识天然有公司、岗位、轮次、技术栈、时间、来源类型、可信度、关联投递等过滤维度。当前 Page 只有 `page_type/subtype/section`，Source metadata 也很薄，后续规模稍大就会混在一起。

## 4. 开源项目横向调研

| 类别 | 项目 | 关键设计 | 对 OfferPilot 的启发 |
|---|---|---|---|
| 产品化 RAG/知识库 | Dify | Knowledge Base、Knowledge Pipeline、metadata、文档/chunk 管理、retrieval testing；chunk 可编辑/禁用/摘要/关键词；支持 metadata filter。 | 不一定采用 Dify 的 RAG，但应借鉴“metadata + chunk 管理 + retrieval testing”。 |
| 产品化 RAG/知识库 | RAGFlow | 强调 Deep Document Understanding、模板化 chunking、可视化 chunk、人类干预、grounded citations、multiple recall + fused reranking。 | 对复杂文档先不要急着“生成 Page”，应先保证 extraction/chunk 质量可检查。 |
| 本地/团队知识库 | Open WebUI Knowledge | 区分 Notes（全量注入）和 Knowledge（RAG）；Focused Retrieval / Full Context；hybrid BM25 + vector + rerank；agentic tools 包含 list/search/query/grep/view_file；目录增量同步。 | 强烈建议 OfferPilot 增加“搜索后查看正文/片段”的工具形态；精确 grep 和语义 query 应分开。 |
| 本地/团队知识库 | AnythingLLM | Local-first 桌面/自托管形态；workspace + document pipeline；支持多向量库、source citation、workspace memory、agent workflow。 | 适合借鉴“workspace 作用域”和“记忆/文档分层”，但其平台形态比 OfferPilot 当前需求重。 |
| 个人 Second Brain | Khoj | 文档同步后用 bi-encoder 建向量，查询时 cross-encoder rerank；支持 query filters；Chat 会展示 reference notes。 | 对个人知识库，引用笔记/片段比只给 Page summary 更重要；中文/英文混合场景要考虑 rerank。 |
| 中文生态知识库 | FastGPT / MaxKB / QAnything | 支持知识库单点搜索测试、调用链路日志、chunk 修改/删除、QA 拆分、混合检索与重排；QAnything 明确采用两阶段 retrieval + rerank。 | 中文求职知识存在术语不一致问题，两阶段检索/重排会比纯 FTS 稳定。 |
| RAG 框架 | LlamaIndex | Document → Node → Index → Retriever → Query/Chat Engine；强调低层可组合 retriever。 | 可借鉴抽象名称：Source/Evidence 类似 Document/Node，但不必引入整个框架。 |
| RAG 框架 | Haystack | Component/Pipeline/Document Store/Retriever；支持 sparse、dense、hybrid、multi-retriever、multi-query。 | 搜索应是 pipeline：多路召回、融合、重排，而不是单个 SQL。 |
| 图谱 RAG | Microsoft GraphRAG | TextUnit → entity/relationship/claim → Leiden community → community summary；Global/Local/DRIFT/Basic Search。 | 适合大规模静态材料的“全局综合问题”，但 indexing 成本高，不适合作为 OfferPilot 当前基础方案。 |
| 轻量图谱 RAG | LightRAG | 图谱 + KV/vector/doc status，多种 chunk 策略，citation，删除时 KG regeneration，RAGAS/Langfuse tracing/eval。 | 适合借鉴“双层检索 + 评估 + 删除一致性”，暂不必上完整 KG。 |
| Agent Memory/Temporal KG | Graphiti / Zep | Context Graph：Entity、Fact/Relationship、Episode；事实带 validity window；增量更新；semantic + keyword + graph traversal；自动 fact invalidation。 | 求职知识有时间性（岗位、面经、公司状态），未来可把“事实”从 Page 中抽出来结构化保存。 |
| Agent Memory | Mem0 / Cognee | Mem0 新算法强调 ADD-only fact、entity linking、semantic+BM25+entity matching、temporal reasoning；Cognee 提供 remember/recall/forget/improve，构建 graph/vector memory。 | 记忆系统的重点不是写长文，而是事实级存储、实体链接、时间和召回融合。 |

## 5. 建议的目标架构：Wiki 编译层 + Evidence 检索层

不要完全回到传统 RAG，也不要继续只有 Page 搜索。更合适的形态是双层：

```text
Source / Bundle
  ↓ deterministic extraction
Extraction Snapshot
  ├─ Evidence FTS / snippets / metadata / optional embeddings   ← 检索底座
  ↓ LLM compile
Wiki Page / Index / Wikilink / Review                           ← 知识成果
```

核心原则：

1. **Page 是给人读和长期沉淀的；Evidence 是给搜索、引用和调试的。**
2. **默认回答用 Page，但 Page 不足时允许 Evidence 兜底。**
3. **citation 不只是校验格式，应能反查 source title、snippet、位置和页面贡献。**
4. **搜索结果必须返回可回答问题的上下文，不只返回目录摘要。**
5. **所有新增能力先本地优先：SQLite FTS + BM25/RRF；embedding/rerank 放后续阶段。**

## 6. 具体建议

### 6.1 P0：先修搜索体验，不急着上向量库

当前最可能影响体感的是搜索返回内容不足。建议先做：

- 新增 Page snippet：`search_pages` 返回命中 Page 的正文片段和高亮/截断上下文。
- 对 FTS 使用字段权重：title > slug > summary > content。SQLite FTS5 `bm25()` 支持列权重。
- 修改多词查询策略：当前 `_format_fts_query` 用 OR，召回宽但噪声大；可增加 exact phrase、AND fallback、OR fallback 三阶段。
- Chat Tool 返回 `snippets` 和 `citations`，不要只给 summary。
- 为短中文查询增加 title/slug/summary/content 的 LIKE 兜底，而不是只搜 title/slug。

### 6.2 P0/P1：让 Evidence 成为一等搜索对象

在不引入新依赖的前提下，可以增加一张 FTS 表：

```text
knowledge_evidence_fts(
  evidence_id,
  source_id,
  page_id nullable,
  source_title,
  logical_path,
  text,
  metadata_json
)
```

索引内容来自 Extraction Snapshot 的 paragraphs 和图片视觉描述（图片描述可以后续补）。搜索时：

1. Page FTS 找“已经编译好的知识”。
2. Evidence FTS 找“原始事实片段”。
3. Wikilink 扩展找邻接 Page。
4. 用 RRF 或简单加权融合，返回统一结果：Page 命中 + Evidence snippets。

这样不会破坏 LLM Wiki 思想，因为正式知识仍是 Page；Evidence 只是检索和溯源底座。

### 6.3 P1：把 Purpose/Schema 从通用提示词升级为领域本体

建议默认 Schema 增加可执行 Page 模板，而不只是写作规则：

- `company`：业务/岗位方向、招聘偏好、面试风格、已知面经、风险点、关联 Application。
- `role`：岗位职责、常见要求、能力模型、准备清单。
- `interview-topic`：知识点定义、常见问法、答题框架、易错点、相关项目经验。
- `project`：背景、职责、技术栈、可讲故事线、STAR 素材、可关联八股主题。
- `question`：题目、考察点、答案框架、追问、引用来源。
- `strategy/synthesis`：结论、适用条件、反例、更新日期。

同时给 Analysis 明确 page threshold：什么情况创建 Page、什么情况只更新 source Page、什么情况进入 Review。否则模型会继续“见词建页”。

### 6.4 P1：增加 metadata/filtering

借鉴 Dify metadata，但保持轻量：

- Source metadata：`company`, `role`, `stage`, `tech_stack`, `source_date`, `source_type`, `confidence`, `application_id?`。
- Page metadata：`primary_entities`, `tech_stack`, `companies`, `roles`, `last_verified_at`, `confidence`。
- Evidence metadata：位置、来源、是否被 Page 当前引用、关联 Page slug。

搜索接口支持 filter：公司/岗位/技术栈/时间。求职知识库没有 filter，后期会非常难用。

### 6.5 P1/P2：加检索评估，而不是继续调 prompt 凭感觉

建立一个很小的本地评估集即可：

```text
query, expected_page_slugs, expected_evidence_ids, notes
```

每次改搜索或 Ingest prompt，跑：

- Recall@5：期望 Page/Evidence 是否出现。
- MRR：正确结果排第几。
- Citation coverage：回答使用的 citation 是否存在。
- Bad case record：把失败 query 写入表或 JSON，作为回归样例。

RAGAS 这类框架可以后续接；当前先用 deterministic 指标就够。

### 6.6 P2：再考虑本地 embedding + rerank

如果 P0/P1 后仍觉得“语义召回”弱，再加本地向量，不要一开始就上重型框架：

- 可选 SQLite 扩展（如 sqlite-vec）或轻量本地向量库。
- 模型优先本地多语种/中文友好 embedding。
- 检索用 FTS + vector 两路召回，RRF 融合。
- rerank 可选，本地 cross-encoder 成本可控时再加。

这条路线比直接引入 RAGFlow/Dify/Haystack 更贴合 OfferPilot 的 SQLite-first、local-first 约束。

### 6.7 P3：事实图谱/时间性，先建结构别急着可视化

未来可借鉴 Graphiti/Mem0：

```text
knowledge_entities(id, name, type, aliases, summary)
knowledge_facts(id, subject_entity_id, predicate, object, valid_from, valid_to, confidence, evidence_id)
```

用途不是炫酷图谱 UI，而是解决：

- 同一公司/技术/岗位别名归一。
- 新 Source 说法冲突时不覆盖旧事实，而是标记失效或并列。
- 查询“现在有效的结论”和“过去某段时间的信息”时有结构化依据。

## 7. 不建议现在做的事

1. **不要直接接入 Dify/RAGFlow/MaxKB 作为内部依赖**：它们是完整平台，数据模型和部署面太重，会破坏 OfferPilot 当前 SQLite-first 单体结构。
2. **不要现在上 Microsoft GraphRAG 全套**：适合大规模静态语料的全局分析，但 indexing 成本高，且求职知识是持续变化的小规模个人知识库。
3. **不要继续只靠 prompt 改 Page 质量**：没有 retrieval snippets、metadata 和 eval，prompt 只能局部改善。
4. **不要把 Obsidian 双向编辑作为运行时主路径**：当前 SQLite SSOT 决策是合理的；Obsidian 保持 Export 即可。

## 8. 建议落地顺序

### Step 1：搜索结果变“可回答”

改动面：`knowledge/search.py`、`knowledge/api.py`、`ai/tools.py`、前端搜索展示。

- Page search 返回正文 excerpt。
- `search_wiki` 返回 summary + snippets + citation IDs。
- 增加测试覆盖：命中正文但没命中标题/summary 的查询必须能返回。

### Step 2：Evidence FTS

改动面：`models.py` / `db.py` schema、`repository.py` 提交/重建索引、`search.py`。

- 为 Extraction Snapshot paragraphs 建 FTS。
- 删除 Source/Page 时同步清理 Evidence FTS。
- Search API 返回 evidence hit。

### Step 3：领域 Schema 模板

改动面：`config_defaults.py`、runner prompt、测试 fixture。

- 默认 Purpose/Schema 增加求职知识本体和 Page 模板。
- Analysis 输出里增加 `page_template` 或 `subtype` 约束。
- 对“过度建页/缺少 source page/缺 citation”的 mock bad case 加测试。

### Step 4：检索评估集

改动面：新增 `tests/fixtures/knowledge_eval/*.json` 或 SQLite 表均可。

- 先写 20 条典型 query。
- 加 `uv run pytest tests/test_knowledge_search_eval.py`。
- 每次搜索策略调整用指标判断，而不是主观感受。

## 9. 参考链接

- Karpathy LLM Wiki：`docs/llm-wiki.md`
- Dify Knowledge：<https://docs.dify.ai/en/guides/knowledge-base>
- Dify metadata：<https://docs.dify.ai/en/cloud/use-dify/knowledge/metadata>
- Dify retrieval testing：<https://docs.dify.ai/en/cloud/use-dify/knowledge/test-retrieval>
- Dify chunk/content management：<https://docs.dify.ai/en/cloud/use-dify/knowledge/manage-knowledge/maintain-knowledge-documents>
- AnythingLLM README：<https://github.com/Mintplex-Labs/anything-llm>
- RAGFlow README：<https://github.com/infiniflow/ragflow>
- Open WebUI Knowledge：<https://docs.openwebui.com/features/workspace/knowledge/>
- Khoj search docs：<https://github.com/khoj-ai/khoj/blob/master/documentation/docs/features/search.md>
- FastGPT README：<https://github.com/labring/FastGPT>
- QAnything README：<https://github.com/netease-youdao/QAnything>
- LlamaIndex indexing/retriever docs：<https://docs.llamaindex.ai/en/stable/module_guides/indexing/>
- Haystack retrievers：<https://docs.haystack.deepset.ai/docs/retrievers>
- Microsoft GraphRAG：<https://github.com/microsoft/graphrag>
- LightRAG：<https://github.com/HKUDS/LightRAG>
- Graphiti：<https://github.com/getzep/graphiti>
- Mem0：<https://github.com/mem0ai/mem0>
- Cognee：<https://github.com/topoteretes/cognee>
