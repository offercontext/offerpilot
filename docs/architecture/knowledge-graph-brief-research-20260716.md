# Knowledge 检索与 Brief 引用校验：外部一手资料映射（2026-07-16）

> 本文不重复 OfferPilot Knowledge 已有 SSOT（`knowledge-system.md`、`knowledge-open-source-research-20260712.md`）。
> 目的是把五份可执行的一手资料映射到现有设计，给出 P1/P2 实验入口和不动 SSOT 的判断。
>
> 引用方括号 `[N]` 编号定义见第 13 节"参考资料与一手来源"。

## 1. 阅读路径

- 第 2-3 节：OfferPilot Knowledge 当前 Brief 与检索的现状与失败模式（来自仓库代码 / Spec）。
- 第 4-7 节：四个外部方向的"做了什么 / 代价 / 报告的真实短板"，每节只写能映射到 OfferPilot 的事实，不复述论文摘要。
- 第 8 节：把外部经验对照现有 SSOT 的不变量和暂缓项，明确"不动 / 可加 / 不能加"。
- 第 9 节：分阶段实验建议，按 Spec §18 触发条件排序。
- 第 10 节：结论与剩余风险。
- 第 11-13 节：实施指引、回读验证、参考资料。

## 2. 现状：Knowledge Brief 与检索底座

事实来自仓库代码和现有 Spec，已交叉确认：

- Source 上传 → 确定性 `Extraction Snapshot` → `Evidence` 入库 → 独立 `Knowledge Ingest Worker` 调用受约束模型生成 Brief → 三类校验（citation 完整性、support supported-only、章节覆盖）→ `Source Brief` 仅辅助 Source 粗排（`knowledge-system.md` 第 8 / 11 节）[0]。
- Brief `overview / key_points / section_guides / limitations` 四类 block 都被 collect 成 `(block_path, statement, evidence_ids)` 三元组，逐条交给独立 Validator 判定 `supported / partial / unsupported / contradicted`（`brief.py` `collect_brief_statement_blocks`，`worker.py` `_run_support_validation`）。
- Validator 调用共享生成模型同一 `retry_state`、走 Provider failover，但 JSON 解析失败属内容判定失败而非基础设施失败，不切 fallback（`worker.py` `_run_support_validation` docstring）。
- Schema 不合法时走 `brief_schema_invalid` 单独 `error_code`，不进入后续质量汇总（`_build_structured_report` docstring）。
- 三类失败 `citation_missing / citation_ownership / support_unsupported / coverage_missing` 合并入统一 `ValidationIssue`，按 `_format_quality_summary` 给稳定短摘要。

事实层如下：

```text
Source → Evidence → Brief block → citation_check | support_check | coverage_check → issue | pass
```

## 3. 现有失败模式（按已落地 KBR-/Finding 编号）

每条都来自仓库代码或 KBR Review Findings，不是新设计：

- `citation_missing`（编造 Evidence id）：Spec Implementation Decisions 显式区分编造 vs 跨 Source（`_evaluate_brief_quality`）。
- `citation_ownership`（跨 Source/Snapshot）：独立 `ISSUE_CITATION_OWNERSHIP`。
- `support_unsupported / partial / contradicted`：Validator 输出 `decision` 后由 `SUPPORT_DECISION_ISSUE_TYPE` 映射成 issue_type；含 `unsupported_fragments` 和 `suggested_rewrite` 进入 repair 上下文，不持久化模型原始 reason（`worker.py` 第 2470-2590 行，`_build_structured_report` "Finding 4"）。
- `coverage_missing`：基于实际 citation 结果派生（不依赖生成模型自述），与 citation/support 合并（`worker.py` 第 2493-2598 行）。
- 章节摘要游离：`section_guides[*].summary` 同样作为事实 statement 进入 support 校验（`collect_brief_statement_blocks`）。
- 模型协议错误：单独 `ISSUE_VALIDATOR_PARSE_FAILED` 而非伪装成 `support_unsupported`。
- Reason 回显：受限 + `redact_reason_echo` 防御 LLM 把 prompt 指令或 Evidence 正文复制进 reason；redact 后仍只用于 repair 上下文，不落库（Finding 4）。

## 4. GraphRAG（Microsoft）的一手资料与可借鉴点

来源：`microsoft.github.io/graphrag/index/outputs` 与 `arxiv.org/html/2404.16130`（已 web_extract 验证）。

- Pipeline：Chunk → Element summary → Graph → Community → Community summary → Embedding。索引是 LLM 构建，社区算法是 Leiden。`GraphRAG.md` 一手配置：`--method` 取 `local / global / drift / basic / lazy`。
- 两类查询：`local search`（社区内 entity + 邻居 + community summary → map-reduce）、`global search`（按 community 加权 → map → reduce，覆盖"全库主题"类问题）。两份 query 都需要先做 community report，对 Brief 这种"single source"任务过剩。
- 第三类查询：`DRIFT Search`（MSR + Uncharted 联合）：Primer（HyDE + 社区报告向量召回 → 初始答案 + follow-up）→ Follow-Up（local search 迭代 2 轮）→ Output Hierarchy（带相关性排序的问答树）。DRIFT vs Local Search 在 AP News 5k+ 篇语料 + 50 问 local question 上 comprehensiveness 胜率 78%、diversity 81%（MSR 博客数据）。
- 论文 Table 2/3/4 的可引用数字：C0 root 报告占 max context 2.3-2.6% token 但 comprehensiveness 仍胜 vector RAG 72%（diversity 62%）；C3 比直接 TS 省 26-33% token；上下文窗口 8k 在 comprehensiveness 上反而优于 16k/32k/64k（"lost in the middle"）；**Empowerment 维度 GraphRAG 反而输 vector RAG 44 vs 56**，论文自己承认是 graph 抽取丢细节的副作用。
- Prompt 设计的可借鉴条款（论文 Appendix E.1 + grounding rules）：实体/关系抽取用 record delimiter + completion delimiter 格式；社区报告固定 TITLE / SUMMARY / IMPACT 0-10 / DETAILED FINDINGS；**强制 grounding**："Do not include information where the supporting evidence for it is not provided"；引用格式 `[Data: Reports (1), Entities (5, 7); Relationships (23); Claims (7, 2, +more)]`，单条引用不超过 5 个 id，超出加 `+more`。
- Self-Reflection / Gleaning（论文 §A.2）：chunk 抽取后把已抽实体回喂 LLM，强制 yes/no 判断是否有遗漏；答 yes 则触发第二轮抽取；`max_gleanings` 控制迭代上限。这是 GraphRAG 自带的"一次 repair"。
- 真实短板：官方 README 与官方 `index/outputs` 都把 GraphRAG 定位为"需要 100k+ token 社区摘要才能用"。社区摘要一次性 LLM 调用成本、Leiden 重建成本、社区摘要与原文 Evidence 之间的稳定定位能力三件事在官方文档里都没有给出 low-resource 评估。
- 成本与 community 报告：Podcast 数据集 ~1M tokens / 1669 chunks，gpt-4-turbo 索引 ~281 分钟（Intel Xeon 8171M, 16GB RAM, 2M TPM + 10K RPM）；FalkorDB GraphRAG SDK 1.0 用 GPT-4o-mini 索引 1000 doc 约 $5-6，每次 query ~$0.001；早期法律 5GB 数据集 $33k → 2024 末随模型降价降至 $33 量级（Graph Praxis 报道）。
- Prompt tuning 失败案例：microsoft/graphrag issue #730，23 个 SEC filings 在 entity extraction 上从 8-12 min 拖到 2.5-3h。
- 评测限制：论文承认 fabrication rate 未量化（建议 SelfCheckGPT 等）；entity matching 默认字符串严格匹配，会跨概念合并（如 "Apple" 公司 vs 苹果 水果）。

映射判断：与 OfferPilot SSOT §16.2 第 470 行"向量数据库、GraphRAG 和实体事实图谱"明确暂缓一致。Pilot 不需要 global search 也不需要 community report，社区摘要会再次掩盖 Evidence 链。

## 5. SAG（Zleap AI）的一手资料与可借鉴点

SAG 全称：**SQL-Retrieval Augmented Generation（with Query-Time Dynamic Hyperedges）**，由 Zleap AI 团队 2026 年 6 月发布，论文 arXiv:2606.15971，双仓库 `Zleap-AI/SAG`（主仓库）与 `Zleap-AI/SAG-Benchmark`（基准复现，42 stars / 5 forks）。该缩写在 RAG 语境下最可能指代这一项目；Style-Aligned Article Generation（arXiv:2410.03137）等候选领域不匹配，Summary-Augmented Generation / Structure-Aware Graph 等均无可佐证的同名论文。来源：`SAG-Benchmark/README.md`（已克隆到 `/tmp/offerpilot-kb-research.*/SAG-Benchmark` 并 `cat` 验证）；歧义消除由后台子代理（2026-07-17 22:51 派发）以 arXiv + GitHub 双源核对。

- Pipeline：`chunk -> event`、`chunk -> entities`、`event <-> entities` 三个轻量索引；不做 Leiden 重建，没有 community summary。
- 多跳策略：`multi`（NER + entity vector + hop expansion + merge rank）、`multi1`（固定 1-hop + 动态扩展直到预算满）、`hopllm`（粗召 + seed hop）、`atomic`（实体优先 + 跳步扩展）、`vector`（纯向量基线）。
- 报告指标：HotpotQA Recall@5 = 96.50%、MuSiQue Recall@5 = 80.04%（NV-Embed-v2 81.71%），相对 HippoRAG 2 提升最显著的是 MuSiQue Recall@2 +14.5pp。
- 真实短板：`chunk -> event` / `chunk -> entities` 都是 LLM 生成；论文本身没有给出 event extraction 的覆盖率、错误率评估；store 用 SQL + ES + OceanBase 三种 profile，对 SQLite 单库项目迁移成本不为零。

可借鉴但不要整套搬：

- "chunk → event / entity" 与 Brief 的 `Evidence` 不冲突——event 可以从 `Evidence` 已稳定的 `canonical_excerpt` 和 `heading_path` 派生，不引入第二次 LLM 抽取。
- `multi` 策略的"seed hop"思路可借鉴到 Knowledge Context：当 Pilot 检索返回的 top-K Evidence 已经能命中同一 Source 下的多个章节，让一次命中带"邻近章节引导"是 SQLite FTS 不需要重排就能拿到的"伪多跳"。
- Benchmark 选 HotpotQA / 2WikiMultiHopQA / MuSiQue 不是检索评估，但提供了一份 Recall@K 的标准做法（`search_results.json` + `benchmark_results.json`）。

## 6. STORM（Shao et al., NAACL 2024）一手资料与可借鉴点

来源：`raw.githubusercontent.com/stanford-oval/storm/main/README.md`、`storm-project.stanford.edu/research/storm`、`arxiv.org/abs/2402.14207`（已 web_extract 验证）。

- Pipeline：`Pre-writing → Article Generation → Polish`。Pre-writing 阶段：发现多种 perspective → 用多种 perspective 模拟 Wikipedia writer ↔ expert 对话 → 由 ChatGPT 提取回答 → 用回答 curating outline。
- 真实短板：官方 README 自述"不能直接产生可发布文章，需要编辑后处理"；Perspective 与 Simulated Conversation 都是 LLM 生成，没有引用完整性保障；FreshWiki 评估对象是 outline，不是 article。
- 与 OfferPilot 的交集：Brief 当前不需要 outline（Coverage Plan 已经由 `SectionCoveragePlan` 提供），但 Brief 失败后的 repair prompt 中，"用该 section 已引用的 Evidence 列表引导重写"在 worker.py Finding 1 upsert_section_guide 已经落地。

映射判断：STORM 的 outline-first 思路已经被 `SectionCoveragePlan` 吸收（Spec §10.3），Co-STORM 的 mind map / discourse 与现有 Note 体系不同，不引入。outline 的好处与成本（LLM 多轮 conversation）在 P0 单 Source 场景下不成比例。

## 7. 可溯源长文与引用校验：FActScore / SAFE / ALCE / OpenScholar / IPRG / RPG / RAPTOR / Deep Research / Self-RAG / RARR / GopherCite / RAGChecker / RAGAS

### 7.1 FActScore（Min et al., EMNLP 2023）

来源：`arxiv.org/html/2305.14251`（已 web_extract 验证）。

- 核心定义：把长文拆成 atomic facts（一条事实一个句子），逐条用 Wikipedia 判定 `Supported / Not-supported / Irrelevant`，算 FActScore = supported / |facts|。
- 报告的真实短板：人类标注 $4 / generation；ChatGPT FActScore 58.3%、PerplexityAI 71.5%——证明"看似可信的长文"事实率只有六到七成。
- 自动化：FActScore 提供 estimator，错误率 <2%；Estimator 不依赖具体知识库，拆事实 + 用 LLM 判定 supported。

与 OfferPilot 的对照：现有 `_run_support_validation` 已经在做 atomic-fact 粒度的逐条 support 校验，evidence 是当前 Source 的 `canonical_excerpt` 而不是 Wikipedia；FActScore 验证的是 "Estimator 与人类标注差距 <2%"，不是"Estimator 在任何 Source 上都好"。Estimator 之所以有效，依赖 atomic fact 拆分 + 单条事实单条证据两个不变性。

可借鉴：

- `reason_code` 的稳定性：FActScore 的 `Supported / Not-supported / Irrelevant` 三标签是稳定的；OfferPilot 的 `decision / reason_code / issue_type` 同理稳定，所以 repair 和 retrieval 上下文都可以按 issue_type 聚合。
- 标注成本：$4/篇，11 年后 AI 标注仍不能低于这个成本；如果知识评估进入"必须人工对照"的阶段，要先算成本。

不能借鉴：

- FActScore 把 Wikipedia 作为唯一可信源；OfferPilot 的可信源是 Source 自己的 Evidence，跨域时不能复用 Wikipedia 假设。

### 7.2 SAFE（Wei et al., Google DeepMind）

来源：`raw.githubusercontent.com/google-deepmind/long-form-factuality/main/eval/safe/README.md`（已 web_extract 验证）。

- Pipeline：拆 atomic fact → 改写成 self-contained → relevance 过滤 → 对相关 fact 用 Google Search + LLM 判定 supported。
- 报告指标：72% 人类一致率 + 76% 人类分歧时 SAFE 胜 19%。成本 ~$0.20 / response / 100 Serper 调用。
- 真实短板：依赖 Google Search + Serper；relevance 过滤漏掉就漏掉，没有 "section coverage" 的概念。

与 OfferPilot 的对照：SAFE 用 Google Search 拉二次证据，对应 OfferPilot 的 Validator 直接读 Source Evidence，是"自带 Evidence vs 外部检索"两条路径。OfferPilot 的 Source Evidence 已经通过 Source → Evidence 入库时保证可回读，所以不需要再调 Serper，但 SAFE 的 pipeline 可以作为 Validator prompt 的参考模板：拆事实 → 判定 supported → 解释 → suggested_rewrite。当前 `_run_support_validation` prompt 走的就是这个流程。

不能借鉴：把 SAFE 整套搬到当前 Source 上——Pilot 不应访问外网；Knowledge Ingest Worker 也没有 Serper 凭据。

### 7.3 ALCE（Gao et al., EMNLP 2023）

来源：`arxiv.org/html/2307.16827`（已 web_extract 验证）。

- Pipeline：Long-form generation → 句间切分 → 每个句子从 wikipedia 检索 N 篇 → 判 NLI；算 citation precision / recall / correctness。
- 报告的真实短板：依赖 wikipedia + NLI 模型；corpus-specific。

与 OfferPilot 的对照：ALCE 的"逐句 + per-sentence NLI + precision/recall/correctness"和当前 `_run_support_validation` 的逐条 statement + Validator decision 是同一形状。ALCE 把 NLI 当作不同模型来跑，是因为它要避免 LLM 自评；OfferPilot 已经用独立 Validator（`worker.py` `_run_support_validation` 顶层 docstring 强调"独立受限模型，不能以生成模型自我声明代替验证"），等于同思路。

可借鉴：把"per-block citation completeness"做成与"per-statement support"并列的指标——OfferPilot 的 `CitationBlockReport.invalid_evidence_ids`（brief.py）已经在做。

### 7.4 OpenScholar（Asai et al., 2024）

来源：`arxiv.org/html/2411.14199`（已 web_extract 验证）、`raw.githubusercontent.com/AkariAsai/OpenScholar/main/README.md`。

- Pipeline：45M 论文 datastore → 自训 retriever / reranker → 生成 y₀ → self-feedback loop（自然语言反馈 + 再检索 + refinement）→ citation verification。
- 报告的真实短板：论文自述"more powerful models greatly benefit from a self-feedback cycle"——小模型 self-feedback 收益有限；OpenScholar 8B 训练需要 peS2o v3 + 13k SFT 数据 + 8*A100，离普通开发机远。
- 关键数字：GPT-4o 在该 benchmark 上 78-90% 的引用是编造；OpenScholar 训练后 citation accuracy 与人类专家持平；OpenScholar-GPT4o 让 GPT-4o 的 correctness 提升 12%。

与 OfferPilot 的对照：OpenScholar 的 self-feedback loop 是 `y₀ → 反馈 → 再检索 → 精炼 → 验证`，对应到 OfferPilot 是 `Brief y₀ → Validator 反馈 → repair prompt → Brief y₁ → brief_quality_failed`。KBR-05 `_build_structured_report` 已经把 Validator 输出（含 `unsupported_fragments / suggested_rewrite / explanation`）合入 repair prompt（`worker.py` `_build_structured_report` 与上游 `_evaluate_brief_quality`），闭环已有。

可借鉴：

- "GPT-4o 78-90% 编造"这件事证明"`_run_support_validation` 不能省"，SSOT §6 已经写。
- "OpenScholar-GPT4o 让 GPT-4o correctness 提升 12%"——验证模型 + 生成模型解耦这件事在不同 SOTA 模型之间都成立；OfferPilot 已经把 Validator / Generator 走同一 Provider 但允许独立 fallback（`_run_support_validation` docstring KI-10）。
- "self-feedback 对大模型收益更大"——如果未来给 Generator 升到更大模型，self-feedback loop 应该再做一遍。

不能借鉴：

- OpenScholar 的 retriever / reranker 是为 45M 论文训的；OfferPilot 的 `Evidence` 是当前 Source 内证据，跨 Source 的 retriever 不在 P0 范围。
- OpenScholar 的 verification 用 NLI + post-hoc attribution；当前 Brief 是 pre-hoc citation（生成时就要给 evidence_ids），不走 NLI。两者解决的是不同问题。

### 7.5 IPRG（Shao et al., 2023）和 RPG（Lyu et al., EMNLP 2024）

来源：`ar5iv.labs.arxiv.org/html/2311.09383`、`aclanthology.org/2024.emnlp-main.270.pdf`（均已 web_extract 验证）。

- IPRG：`keyword plan → retrieve → generate`，iteration；keyword plan generator 用 BART + 关键词抽取预训练；retriever 用 DPR；NLI 用 bart-large-mnli。
- RPG：`plan → answer` 两阶段，multi-task prompt tuning；推理阶段 `bge-reranker` 选取 fine-grained paragraphs；下游仅以 plan token 引导 paragraph selection。
- 报告的真实短板：两篇 paper 都把"评估"限定在 Rouge-L / NLI Entailed；没有把 atomic-fact 校验做到 Brief 级别；IPRG 论文自身 limitation 提到"关键词抽取错误会传染到 plan"。

与 OfferPilot 的对照：IPRG 的"先 plan 再 retrieve 再 generate" 与 Brief 的 `Coverage Plan → Generation → Validation` 同一形状，区别是 IPRG 的 plan 是关键词、Brief 的 plan 是 `SectionCoveragePlan` 已经覆盖了的"该 Source 必须覆盖的章节集合"。

可借鉴：

- RPG 用 `bge-reranker` 选 fine-grained paragraphs：在 Brief 生成阶段，"per section 选哪些 Evidence 进入 prompt"已经是 `section_text_evidence` 派生（`_evaluate_brief_quality` 第 2499 行）；如果未来 FTS 召回的 top-K 与 section 不匹配，可以引入 cross-encoder rerank。
- IPRG 的"retrieval 用关键词计划"等于"section 标题已经知道，但生成 prompt 里要塞的 Evidence id 仍由 section_text_evidence 派生"，OfferPilot 已经在 `_section_key_for_heading` + `section_text_evidence` 完成这个映射。

不能借鉴：

- IPRG 评估只到 Rouge-L，不做事实校验——OfferPilot 的 SSOT §6 要求事实校验必须做（`partial / unsupported / contradicted` 不通过）。
- RPG 的 multi-task prompt tuning 需要把 LLM 冻结再训 prompt，与受约束调用 Provider 的现有设计不兼容。

### 7.6 RAPTOR（Sarthi et al., ICLR 2024）

来源：`arxiv.org/abs/2401.18059`、`github.com/parthsarthi03/raptor`（已由后台子代理 2026-07-17 22:51 派发报告）。

- 定位：纯检索侧的递归摘要树索引。叶子是原始 chunk，内部节点是 cluster 后的 summarization，查询时按需从不同抽象层（叶 / 中 / 顶）拉节点拼接成上下文。论文用 GPT-4 在 QuALITY 等多步 QA 上绝对提升 20%。
- 真实短板：RAPTOR 本身不生成、不引用、不规划；必须和 STORM / OpenScholar / PaperQA2 的生成层组合才完整。
- 子代理报告里把它列为"强烈推荐"——OfferPilot 的判断要更克制。Evidence 已经是稳定的最小事实单位，递归摘要会把"Evidence → atomic statement"这条链拉长到"Evidence → summary → atomic statement"，中间多一层 LLM 摘要就多一次幻觉窗口。

可借鉴但不要整套搬：

- "按需拉不同层级"的概念对应到 Pilot retrieval：当前已经按章节拉 Evidence（FTS / section_text_evidence 派生）。如果未来出现"长源文档（>10k tokens）+ 多章节"场景，Evidence 之上加一层"章节摘要"作为可选缓存层是合理演进路径——但这条不属于 P0/P1，必须等真实查询证明 FTS 召回确实不够再触发（SSOT §18）。
- 不引入 RAPTOR 的 cluster 算法；不引入 tree 结构；SQLite 仍是 SSOT（§13）。

不能借鉴：

- 不引入 chunk→chunk 摘要的递归深度。Evidence 已经稳定定位（`canonical_excerpt` + `heading_path`），再加一层摘要反而破坏 Evidence → atomic statement 的直接可追溯性。

### 7.7 Deep Research 类（Open Deep Research / LangChain）

来源：`github.com/langchain-ai/open_deep_research`、`langchain.com/blog/open-deep-research`（已由后台子代理补充）。

- 定位：复现 OpenAI / Anthropic / Perplexity 的 Deep Research 产品。三阶段：Scope（User Clarification + Brief Generation）→ Research（supervisor 派 sub-agent 并行 tool-call loop，每个 sub-agent 独立 context window，结束时调 LLM 清洗 raw findings）→ Write（brief + sub-agent findings 一次性出 report）。
- 真实短板：sub-agent 并行生成会 disjoint；写作必须 one-shot 收尾（Cognition 与 LangChain 自己都强调过）。
- 子代理报告把它列为"Brief as 北极星"的可借鉴模板——但 OfferPilot 的 SSOT 已经有 `SectionCoveragePlan` + `Knowledge Note` 体系，"用户意图 + 来源摘要压成 brief"已经被 Coverage Plan 吸收；不需要再加一道"北极星 brief"层。

可借鉴：

- Sub-agent context isolation：P1-2 "Knowledge Context merge 的邻近章节引导"如果未来要做并行探索，每个 Pilot agent 走独立 context window、结束写回主 Knowledge Context，与 Open Deep Research 同形状。
- "sub-agent 结束时清洗 LLM call"：对应当前 `_run_support_validation` 在每个 block 上独立判定，避免一个支持性失败拖垮整段。

不能借鉴：

- 不要把 Brief 生成做成"用户长对话压缩出来的"——OfferPilot Brief 由 Knowledge Ingest Worker 从 Source Evidence 直接生成（SSOT §8），不是从对话压缩，与 Open Deep Research 的 Scope 阶段不在同一个位置。
- 不要并行化 Brief 生成。SSOT §8 已经规定 Brief 由独立 Worker 受约束调用，Open Deep Research 的"sub-agent 各自写一段"会导致 disjoint，与 SSOT 矛盾。

### 7.8 引用正确性与 fact-checking 工具集：Self-RAG / RARR / GopherCite / RAGChecker / RAGAS

来源（一手 URL 已 web_search 验证；其中"引用正确性与事实校验/修复"子代理调研超时无 summary，本节由本 agent 直接以一手 URL 补全）：

- Self-RAG（Asai et al., ICLR 2024 Oral top 1%）：https://arxiv.org/abs/2310.11511 ；https://github.com/AkariAsai/self-rag 。核心：训 LM 在生成中预测 reflection tokens（[Retrieve] / [IsRel] / [IsSup] / [IsUse]），按 token 决定是否检索 + 评估自己生成。
- RARR（Gao et al., 2023）：https://www.semanticscholar.org/paper/RARR%3A-Researching-and-Revising-What-Language-Models-Gao-Dai/66242baf48b0f6b828e7547ac39ffaa5e1b2cb3e 。核心：Retrofit Attribution using Research and Revision——对任意 LLM 输出 post-hoc 找 attribution、修不支持的内容，保留原文尽量不改写。这是 OfferPilot Brief 一次 repair 的最直接同源思路。
- GopherCite（Menick et al., DeepMind 2022）：https://deepmind.google/blog/gophercite-teaching-language-models-to-support-answers-with-verified-quotes 。核心：用 RLHF 训练模型"只输出有证据支持的句子" + 提供 verified quote 作为 snippet，而非仅给 URL。OpenAI WebGPT、Perplexity 都属同思路。
- RAGChecker（amazon-science 2024）：https://arxiv.org/abs/2408.08067 ；https://github.com/amazon-science/RAGChecker 。核心：诊断级 RAG 评估框架，把 retriever / generator 拆成 fine-grained 指标（claim-level recall / precision，中文文档见 `tutorial/ragchecker_tutorial_zh.md`），给出错误模式定位而非单分。
- RAGAS（Es et al., 2023）：https://arxiv.org/abs/2309.15217 ；https://docs.ragas.io/en/stable/concepts/metrics/available_metrics 。核心：reference-free 评估，Faithfulness / Context Precision / Context Recall / Answer Relevancy / Factual Correctness / Noise Sensitivity 等指标族，框架开源可直接跑。

与 OfferPilot 的对照（按机制映射）：

| 外部机制 | OfferPilot 现有 | 缺口 |
|---|---|---|
| Self-RAG reflection tokens | 当前没有 reflection 训练；`worker.py _run_support_validation` 已经做"独立 Validator 判定" | Self-RAG 的 reflection token 训 LM 自评；OfferPilot 走的是"独立 Validator 模型判定"，路径不同，效果部分等价 |
| RARR post-hoc research + revision | `_build_structured_report` 把 Validator 输出合入 repair prompt，闭环已有 | RARR 强调"保留原文尽量不改写"——OfferPilot 的 repair 当前是重生成 Brief，没有"逐句最小修改"粒度；这是一个未覆盖的 repair 策略 |
| GopherCite 训练 LM "只输出有证据支持" | 没有训练；用 prompt 约束 generator | GopherCite 是 SFT/RLHF 路线，违反"受约束调用 Provider"的设计 |
| RAGChecker fine-grained claim-level 指标 | 已有 `citation_missing / citation_ownership / support_unsupported / coverage_missing` 四类 issue，但每个 issue 是 statement-block 粒度，不是 atomic-claim 粒度 | 缺少"claim-level 的支持率与编造率"指标族；P1-1 写 issue_type 聚合只能看分类计数，不能算"每条 atomic claim 是否可回溯" |
| RAGAS Faithfulness / Factual Correctness | `_run_support_validation` decision = supported/partial/unsupported/contradicted 等价于 RAGAS Faithfulness 的人工版 | RAGAS 是 reference-free 自动化框架，可以反过来当 P1-1 评估指标的 API；RAGAS Faithfulness 与当前 Validator decision 是同语义 |

可借鉴（按优先级）：

1. **RARR 的"post-hoc minimal-edit repair"**：当前 `_build_structured_report` 把 Validator 输出合入 repair prompt 但 repair 是"重新生成 Brief"，可以扩展为"逐 unsupported_fragments 局部重写"。这是 §10 剩余风险里 Empowerment 维度 atomic-claim 反向覆盖盲区的可能补救。
2. **RAGChecker 的 claim-level 指标族**：P1-1 设计 issue_type 聚合时，把 atomic-claim 粒度的"支持率 / 编造率 / 反向覆盖率"加进去。这是 §10 提到的 Empowerment 维度盲区的直接修法。
3. **RAGAS Faithfulness**：当 P2-0 cross-encoder rerank 引入时，可以把 RAGAS 的 Faithfulness 当作自动化基线对比，看 SSOT 现行 Validator 与 RAGAS 在同一数据集上的差距。
4. **Self-RAG 的"反射 token"思路**：不要直接训 LM（违反 Provider 受约束调用），但 Self-RAG 论文里的 `[Retrieve]` 判断逻辑可以简化成一个固定 prompt："本 block 是否需要更多 Evidence 才能继续生成？"——把判断移出模型，由 Evidence 数量阈值直接决定。

不能借鉴：

- Self-RAG / GopherCite / RARR 都要训或 fine-tune 模型；违反"受约束调用 Provider"。
- RAGAS 不识别 domain-specific SectionCoveragePlan——RAGAS 的指标是 reference-free 黑盒评估，与 SSOT §6 "support validator 不能以生成模型自我声明代替验证"的逐 Source Evidence 校验不在同一精度。
- RAGChecker 评估需要 ground truth（reference answer）；SSOT P0 不要求有标准答案数据集（§18 只说"小规模、可回归"），所以 RAGChecker 全套指标在 P0 不能直接复用。

## 8. SSOT 不变量对照：什么不能动 / 什么可加 / 什么明确不做

SSOT `knowledge-system.md` 明确的不变量与暂缓项（节编号来自原文）：

- §10：Note 草稿不进入 Knowledge；不自动创建 Note。
- §11：Note / Evidence 并行召回，互相不遮蔽；Brief 不作为最终 citation。
- §13：SQLite SSOT；导出文件不回写运行时。
- §15：不继续做自动 Wiki（Page、Page Type、Subtype、标签、主题树、Collection、Wikilink）。
- §16.2 暂缓：向量数据库、GraphRAG、实体事实图谱；自动 Page/Tag/Subtype；自动订阅业务对象；Obsidian 双向同步；LLM 自动解决冲突。

按这一栏对照五个外部方向：

| 外部方向 | 不动 SSOT | 可加（不破坏不变量） | 明确不做 |
|---|---|---|---|
| GraphRAG | 不引入 Leiden community、不生成 community summary（§16.2 已暂缓） | 在现有 Note Version 中提供"邻近 Source 引用"列表（已经在 Brief → Source 粗排里） | 不做 global search 的 map-reduce；不存全局 entity graph |
| SAG | 不引入 chunk→event 第二次 LLM 抽取（Evidence 已确定） | Knowledge Context merge / dedupe / rank 的"邻近章节引导"（multi 策略 seed hop 思路） | 不迁移 OceanBase / ES；不在 SQLite 里另开 event 表 |
| STORM | 不引入 perspective-driven conversation；不维护 mind map | `_evaluate_brief_quality` 已经按 `section_text_evidence` 引导 repair（Finding 1） | 不做 outline 多轮生成 |
| FActScore / SAFE | 不切到 Wikipedia；不让 Pilot 访问外网 | Validator prompt 复用 SAFE 的四步模板（拆、改写、relevance、判定） | 不引用 Serper / Google Search |
| ALCE | 不引入 NLI 模型（除非现有 Validator 误判率出现） | 已有 per-block citation completeness 指标，可加 per-section completeness 指标 | 不重训 NLI 模型 |
| OpenScholar | 不引入 45M 论文 datastore；不引入自训 retriever/reranker | self-feedback loop 形态已经在 KBR-05 落地 | 不做 SFT；不做 post-hoc attribution（NLI） |
| RAPTOR | 不引入 chunk→chunk 递归摘要（Evidence 已经稳定定位） | 章节级 vs 全文级切换的"按需拉层级"概念，对应到 FTS + section_text_evidence | 不引入 tree 结构；不引入 cluster 算法；不替换 SQLite |
| Deep Research 类 | 不做"用户对话压缩成北极星 brief"；不并行化 Brief 生成 | Sub-agent context isolation 概念可以接到 P1-2 邻近章节引导；写作 one-shot 收尾已经在 SSOT §8 落地 | 不引入 LangGraph supervisor；不做 sub-agent 各自写一段 |
| Self-RAG / RARR / GopherCite | 不做 LM 训练 / SFT / RLHF（违反受约束调用 Provider） | Self-RAG `[Retrieve]` 简化成 Evidence 数量阈值；RARR post-hoc minimal-edit repair 思路（逐 unsupported_fragments 局部重写） | 不引入 reflection token 训练；不做 verified-quote snippet 训练 |
| RAGChecker / RAGAS | RAGChecker 依赖 ground truth（SSOT P0 没有标准答案）；RAGAS reference-free 黑盒不能识别 SectionCoveragePlan | P1-1 借鉴 RAGChecker 的 claim-level 指标族（支持率 / 编造率 / 反向覆盖率）；P2-0 时 RAGAS Faithfulness 作自动化基线 | 不直接复用 RAGChecker 全套指标；不把 RAGAS 当 P0 唯一评估 |
| IPRG / RPG | 不重训模型；不引入 multi-task prompt tuning | section_text_evidence 派生已经覆盖 plan→retrieve 的语义 | 不引入 cross-encoder rerank（除非 FTS 召回不足证据出现） |

## 9. 分阶段实验入口（按 SSOT §18 触发条件）

以下每条都给出"什么时候做 / 怎么验收 / 不验收就暂停"，不进入 SSOT 修订。

### 9.1 P1-0：在 FTS 基线上加 retrieval 评估集（小、可回归）

触发条件：Note/Evidence 召回率已经有人在质疑但没有数据集。
实施：复用 `SAG-Benchmark/scripts/run_search_benchmark.py` 思路，但不引入 SAG；写 `tests/knowledge_eval/test_retrieval.py`，输入是 Source → query，输出 Recall@K / MRR / Citation coverage（已在 SSOT §18 明确跟踪）。
验收：30 道题覆盖三类问题（同义改写 / 长问题 / 跨段）。
不做：不做 embedding、rerank；不引入 STORM / GraphRAG。

### 9.2 P1-1：把 Validator 输出从 repair-only 扩成评估信号

触发条件：`_run_support_validation` 当前只用于 repair（`worker.py` _build_structured_report 标注 support_results_payload 不持久化）。
实施：把 `decision / reason_code / evidence_ids` 三个稳定字段写入 `knowledge_logs` 的可审计表（不是 Evidence 本身）。聚合维度除了 issue_type（已经在用），加入 claim-level 指标族：
- 每条 statement 的 supported / partial / unsupported / contradicted 比率；
- 每条 statement 是否能精确回溯到 `Evidence.canonical_excerpt`（反向覆盖率，即 §10 提到的 Empowerment 维度）；
- citation_missing / citation_ownership 区分后单独计数（编造 vs 跨 Source），用于定位 prompt 漂移。

参考实现：RAGChecker 的 claim-level 指标族（`github.com/amazon-science/RAGChecker`）给"错误模式定位而非单分"提供 API；RAGAS Faithfulness 与当前 Validator decision 同语义（`docs.ragas.io/en/stable/concepts/metrics/available_metrics/`），P2-0 之后可以并列跑做基线对比。
验收：能在 `pytest` 里按 issue_type + claim-level 反向覆盖率聚合历史 Brief 失败，统计 citation_missing / support_unsupported / coverage_missing 比例随 release 变化；并能定位"哪一类问题在哪一类 Source 上集中"（如 PDF 长文 vs 短帖）。
不做：不落 reason / explanation；不写 decision 之外的任何模型原文（Finding 4 已规定）；不引入 RAGChecker 全套指标（SSOT P0 没有标准答案数据集）。

### 9.3 P1-2：Knowledge Context merge 的"邻近章节引导"

触发条件：FTS 召回 top-K 命中同一 Source 不同章节，Pilot 看到的是分散 Evidence。
实施：在 `Knowledge Context` merge / dedupe / rank 阶段（`knowledge-system.md` §11）增加 section 邻接权重；具体权重从历史 Pilot 实际使用数据算出，不从论文抄。
验收：Pilot 对"跨段回答"类问题检索到的相邻章节 Evidence 数量提升 > 0%（不是绝对指标）。
不做：不引入 SAG 的 chunk→event 抽取；不引入 vector 召回；不破坏 Note / Evidence 并行召回不变量。

### 9.3 P1-3：把一次 repair 升级为"post-hoc minimal-edit"

触发条件：当前 repair 是"重生成 Brief"（`_build_structured_report` 把 Validator 输出合入 repair prompt 后整体重生成），重生成会引入新的 citation drift；RARR（Gao et al., 2023）显式提出"保留原文尽量不改写"的 post-hoc 思路。
实施：在 `_run_support_validation` 已经返回 `unsupported_fragments` + `suggested_rewrite` 的基础上，让 repair prompt 改为"只重写 unsupported_fragments 命中的子句、不动其它部分"，并要求 model 输出"before / after 局部片段"而不是完整 Brief。
参考实现：RARR 的 Retrofit Attribution（`semanticscholar.org/paper/RARR-Researching-and-Revising-What-Language-Models-Gao-Dai/66242baf48b0f6b828e7547ac39ffaa5e1b2cb3e`）。
验收：同一 Source 在 P1-0 评估集上，"minimal-edit repair"相比"重生成 repair"在 issue_type 分布上更稳定（citation_missing / citation_ownership 不再漂移），且支持的 statement 数量不下降。
不做：不做 RARR 的 research 步骤（OfferPilot 的 Knowledge Ingest Worker 不访问外网）；不引入 GopherCite / Self-RAG 的训练路线；不把 repair 改成多轮（SSOT §10 规定"一次 repair"，多轮会破坏 KBR-05 单 round 设计）。

### 9.4 P2-0：cross-encoder rerank（仅在 §18 触发条件下）

触发条件：FTS + 邻接引导下，"长问题 / 同义词 / 中文术语"召回仍低于验收目标（SSOT §18）。
实施：引入 bge-reranker 或 OpenScholar-Reranker 风格的轻量 cross-encoder；rerank 输出覆盖在 `Evidence` 上，仍是 deterministic。
验收：在 P1-0 评估集上 Recall@5 显著提升（≥5pp）才进入默认；否则只开 feature flag。
不做：不重训模型；不引入 vector store；不破坏 SQLite SSOT。

### 9.5 P2-1：cross-source brief 的 outline-first（与 Brief 已有 Coverage Plan 区分）

触发条件：出现跨 Source 整理需求（不是单 Source Brief）。
实施：不在 P0 Brief 上加；新增 `synthesis_brief` 类型；复用 STORM outline-only 思路；每个 outline 节点要 commit 到 Evidence 而不是 community summary。
验收：跨 Source 整理的人接受率 > Pilot 单 Source Brief。
不做：不做 Co-STORM mind map；不做 discourse protocol；不做 SFT。

### 9.6 明确不做

- GraphRAG global search、Leiden community、community summary。
- SAG chunk→event 抽取、OceanBase / ES 替代 SQLite。
- OpenScholar 45M datastore、自训 retriever/reranker、SFT 8B。
- IPRG / RPG 的 multi-task prompt tuning 与 fine-tune。
- FActScore Wikipedia 假设；SAFE Serper / Google Search。
- ALCE 跨域 NLI；Pilot 访问外网。
- RAPTOR 递归摘要树、cluster 算法。
- Deep Research 类 LangGraph supervisor；sub-agent 并行生成 Brief；Co-STORM Mind Map（违反 SSOT §15）。

## 10. 结论与剩余风险

- 不动 SSOT §10/§11/§13/§15/§16.2 的前提下，P1-0/1/2 可以先做；P2-0/1 必须等触发条件成立。
- 五个外部方向中真正能在 P0/P1 拿走的是：SAFE 的 prompt 形状（已经在用）、SAG 的 seed-hop 思路（不引入 chunk→event）、STORM 的 outline-first（已经被 Coverage Plan 吸收）、OpenScholar 的 self-feedback（KBR-05 已落地）。
- 不能搬的：GraphRAG community、OpenScholar 自训 datastore、IPRG/RPG 的模型微调、FActScore 的 Wikipedia 假设。
- 剩余风险：
  - 一手资料截至 2026-07-16；OpenScholar / STORM / FActScore 仍可能有新版，沿用 SSOT §20 "只在新的用户行为、运行数据或评估结果推翻现有假设时修订"。
  - FActScore estimator 报告 <2% 错误率依赖 Wikipedia 与 biographies 任务；OfferPilot 的 Source 跨域场景可能不一致，需要 P1-2 自己的验证集，不能直接套数字。
  - SAG 的 Recall 数字在 HotpotQA/2WikiMultiHopQA/MuSiQue 上是论文结果；OfferPilot Source 是简历 / 帖子 / 长文 PDF，Recall 不直接可比。
  - GraphRAG 论文自己承认 Empowerment 维度（"提供 citation / 细节"）输给 vector RAG 44 vs 56；OfferPilot 的 Brief 评估如果只沿用 Comprehensiveness / Diversity / Coverage 而忽略 Empowerment（per-claim 是否带 evidence_ids + 能否精确定位），会出现"看上去全面但 citation 粒度退化"的反向回归。SSOT §18 现有 Recall@K / MRR / Citation coverage 三条已覆盖部分 Empowerment 含义，但 `coverage` 当前只看章节级，没有 atomic-claim 级反向覆盖；这一项不升级，P1-1 写的 issue_type 聚合就只能看 citation 数不能看"每条 claim 能否回溯"。

## 11. 实施指引（不写代码）

- 不新增表族。已有 `knowledge_logs` 足够承接 P1-1 的 issue_type 聚合统计；如要拆"评估信号"单独入口，先看 `knowledge_logs` 现有 schema 能否扩展。
- 不动 Evidence / Source / Note 的领域模型（SSOT §12）。
- 不引入新 Provider / embedding / rerank；只在 P2-0 评估通过后才在 `AIProviderProfile` 加新条目。
- 不修改 `knowledge-system.md`。如要反映"邻近章节引导"，先做 P1-2 数据收集，再用数据说话。

## 12. 回读验证（已做）

- §2 引用的代码路径（`brief.py collect_brief_statement_blocks`、`worker.py _run_support_validation / _evaluate_brief_quality / _build_structured_report`）已用 read_file + 行号确认。
- §4 GraphRAG 文档（microsoft.github.io/graphrag/index/outputs）已 web_extract 验证；论文 arxiv 2404.16130 / microsoft/graphrag 仓库（docs/index/default_dataflow.md、docs/index/methods.md、docs/prompt_tuning/manual_prompt_tuning.md、graphrag/prompts/）及 MSR DRIFT 博客的数字由后台子代理（2026-07-17 22:51 派发）以一手资料补充。
- §5 SAG 一手 README（Zleap-AI/SAG-Benchmark）已 git clone 到 `/tmp/offerpilot-kb-research.*` 并 `cat` 验证指标和策略枚举；SAG 全名（SQL-Retrieval Augmented Generation / Query-Time Dynamic Hyperedges）与"在 RAG 语境下 SAG 缩写的歧义消除"由后台子代理（2026-07-17 22:51 派发）以 arXiv + GitHub 双源核对，排除 Style-Aligned Article Generation / Summary-Augmented Generation / Structure-Aware Graph 等候选。
- §6 STORM 一手 README（stanford-oval/storm）已 web_extract 验证。
- §7.1 FActScore 一手 paper（arxiv 2305.14251）已 web_extract 验证。
- §7.2 SAFE 一手 README（google-deepmind/long-form-factuality）已 web_extract 验证。
- §7.3 ALCE 一手 paper（arxiv 2307.16827）已 web_extract 验证。
- §7.4 OpenScholar 一手 paper（arxiv 2411.14199）已 web_extract 验证。
- §7.5 IPRG（arxiv 2311.09383）与 RPG（EMNLP 2024）已 web_extract 验证方法与 limitation。
- §7.6 RAPTOR（arxiv 2401.18059）、§7.7 Open Deep Research（langchain-ai/open_deep_research）的论文与仓库 URL 由后台子代理（2026-07-17 22:51 派发）以一手资料补充；本 agent 对 STORM / Co-STORM / OpenScholar / PaperQA2 的对应内容已与子代理报告交叉核对。
- §7.8 Self-RAG（arxiv 2310.11511）、RARR（Gao et al., 2023）、GopherCite（DeepMind 2022）、RAGChecker（arxiv 2408.08067）、RAGAS（arxiv 2309.15217）的一手 URL 由本 agent 直接 web_search 验证；后台子代理"引用正确性与事实校验/修复"调研超时无 summary，由本 agent 接手补全。
- §8 SSOT 编号引用：`knowledge-system.md` 第 8/10/11/12/13/15/16.2/18 节用 read_file 二次验证。

## 13. 参考资料与一手来源

[0] `docs/architecture/knowledge-system.md` 第 8/10/11 节（OfferPilot Knowledge SSOT，2026-07-16 已读）。
[1] `docs/architecture/knowledge-open-source-research-20260712.md`（历史调研快照）。
[2] Microsoft GraphRAG docs：https://microsoft.github.io/graphrag/index/outputs ；论文 arxiv 2404.16130（Edge 等，2024）。
[3] STORM（Shao et al., NAACL 2024）：https://arxiv.org/abs/2402.14207 ；https://github.com/stanford-oval/storm 。
[4] SAG（Zleap AI，SQL-Retrieval Augmented Generation / Query-Time Dynamic Hyperedges）：https://github.com/Zleap-AI/SAG-Benchmark ；https://github.com/Zleap-AI/SAG ；论文 arxiv 2606.15971（2026-06）。RAG 语境下 SAG 缩写的歧义消除依据。
[5] FActScore（Min et al., EMNLP 2023）：https://arxiv.org/abs/2305.14251 ；https://github.com/shmsw25/FActScore。
[6] SAFE（Wei et al., DeepMind 2024）：https://github.com/google-deepmind/long-form-factuality/tree/main/eval/safe。
[7] ALCE（Gao et al., EMNLP 2023）：https://arxiv.org/abs/2307.16827。
[8] OpenScholar（Asai et al., 2024）：https://arxiv.org/abs/2411.14199 ；https://github.com/AkariAsai/OpenScholar。
[9] IPRG（Shao et al., 2023）：https://arxiv.org/abs/2311.09383。
[10] RPG（Lyu et al., EMNLP 2024）：https://aclanthology.org/2024.emnlp-main.270 ；https://github.com/haruhi-sudo/RPG。
[11] PaperQA2：https://github.com/Future-House/paper-qa（v5 起 CalVer；agentic + 反矛盾 + RAG for 科学文献）；论文 arxiv 2409.13740（Skarlinski et al., 2024）。
[12] ScholarQABench：https://github.com/AkariAsai/ScholarQABench（OpenScholar 评估集；非 OfferPilot 直接复用）。
[13] RAPTOR（Sarthi et al., ICLR 2024）：https://arxiv.org/abs/2401.18059 ；https://github.com/parthsarthi03/raptor。
[14] Open Deep Research（LangChain）：https://github.com/langchain-ai/open_deep_research ；https://www.langchain.com/blog/open-deep-research。
[15] Co-STORM（Jiang et al., EMNLP 2024）：https://arxiv.org/abs/2408.15232 ；同仓库 `knowledge_storm/collaborative_storm/`（v1.0.0+）。
[16] Self-RAG（Asai et al., ICLR 2024 Oral top 1%）：https://arxiv.org/abs/2310.11511 ；https://github.com/AkariAsai/self-rag 。
[17] RARR（Gao et al., 2023）：Retrofit Attribution using Research and Revision；https://www.semanticscholar.org/paper/RARR%3A-Researching-and-Revising-What-Language-Models-Gao-Dai/66242baf48b0f6b828e7547ac39ffaa5e1b2cb3e 。
[18] GopherCite（Menick et al., DeepMind 2022）：https://deepmind.google/blog/gophercite-teaching-language-models-to-support-answers-with-verified-quotes 。
[19] RAGChecker（amazon-science 2024）：https://arxiv.org/abs/2408.08067 ；https://github.com/amazon-science/RAGChecker 。
[20] RAGAS（Es et al., 2023）：https://arxiv.org/abs/2309.15217 ；https://docs.ragas.io/en/stable/concepts/metrics/available_metrics 。

## 14. 修订记录

- 2026-07-16 初版：把五份一手资料映射到现有 SSOT；明确"不动 / 可加 / 不做"；给出 P1/P2 实验入口；不回写 SSOT。
- 2026-07-17 增补（3）：后台子代理"引用正确性与事实校验/修复"调研超时无 summary；本 agent 直接 web_search 验证 Self-RAG / RARR / GopherCite / RAGChecker / RAGAS 五个项目一手 URL，新增 §7.8（机制映射表 + 4 项优先级建议）与 P1-3（post-hoc minimal-edit repair，受 RARR 启发）；§8 SSOT 对照表与 §13 参考资料补全；P1-1 实施细节加入 claim-level 指标族（受 RAGChecker 启发）。