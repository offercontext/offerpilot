# KBR-07 Knowledge Reset 完整建模 Grill 启动文档

**日期**：2026-07-17
**状态**：访谈输入，不是已批准 Spec，不授权修改代码
**目标**：在新会话中使用 `$grill-me`，重新建立 KBR-07 的完整状态机、崩溃恢复协议和故障验证矩阵，停止按单个 Finding 继续打补丁。

## 新会话启动指令

将本文件作为新会话的首要上下文，并发送下面这段指令：

```text
请使用 $grill-me，围绕 docs/architecture/kbr07-reset-modeling-grill-brief.md 对 KBR-07 进行完整建模。

严格执行 grilling 工作流：

1. 一次只问一个决策问题，每题都给出你的推荐答案和理由，等待我回答后再继续。
2. 能从仓库、Git 历史、测试或运行时查到的事实由你自己核实，不要问我。
3. 事实与决策必须分开记录；发现现有 Spec 内部矛盾时直接指出，不能静默选边。
4. 沿本文的决策树逐层推进，前置决策未冻结前不得跳到实现细节。
5. 主动构造最坏情况，包括进程崩溃、断电、目录项未持久化、重复 reset、并发、symlink、路径逃逸、旧 quarantine 残留、DB 与文件状态冲突。
6. 不得修改、格式化、提交或清理任何文件。不要更新 Spec、tickets 或代码。
7. 在我明确确认“我们已经达到共享理解”之前，不得给出实施计划，不得开始实现。
8. 访谈结束时，先输出待我确认的建模成果：术语表、不变量、状态机、恢复决策表、崩溃点矩阵、测试模型、开放问题和推荐方案。

开始前先完成本文“必须自行核实的事实”，然后只问“第一问”，不要一次列出后续所有问题。
```

## 为什么重新建模

KBR-07 需要同时改变 SQLite 数据和 Knowledge 文件目录。这两个资源没有共同事务边界，单靠“先移动目录、再提交数据库”不能自动获得原子性。

此前三轮修复分别加入了 quarantine、generation manifest、启动恢复、symlink 守卫和 intent-first 写入，但每次局部修复都会扩大状态空间。测试验证了已知例子，却没有证明协议在所有持久状态组合下都满足核心不变量。

本轮建模必须先回答“系统承诺什么、谁是权威、每个持久状态如何恢复”，再讨论函数和文件布局。

## 必须自行核实的事实

新会话 Agent 应先只读核实以下内容。事实发生变化时，以实际仓库为准，并在访谈记录中标出差异。

### 事实源

- `AGENTS.md`
- `docs/architecture/knowledge-system.md`
- `docs/architecture/decisions/0007-use-sqlite-as-knowledge-wiki-ssot.md`
- `docs/superpowers/specs/2026-07-15-knowledge-evidence-metadata-and-brief-repair-design.md`
- `tickets.md` 中 KBR-07、KBR-08
- `src/offerpilot/knowledge/reset.py`
- `src/offerpilot/db.py`
- `tests/test_knowledge_reset.py`
- KBR-07 及其 Review 修复提交历史

### 当前实现事实

开始访谈前至少核实：

- SQLite 数据库路径、连接初始化和启动恢复调用顺序。
- Knowledge 文件根目录、canonical Source、Asset、staging、delete quarantine 的真实布局。
- `knowledge_sources` 与磁盘 Source 目录之间的所有权关系。
- reset 覆盖的表闭集、FTS、Job、日志和文件范围。
- reset API/CLI 的运行模式与确认门禁。
- 当前 quarantine root、child、manifest 的命名和持久化顺序。
- 当前 generation 的唯一性机制。
- manifest 是否同步文件和父目录。
- DB commit 前后每个文件操作的顺序。
- 启动恢复如何判断 DB 有无 Source、`knowledge/` 是否存在、quarantine 数量和路径安全性。
- 哪些服务会在启动或运行时自动创建空 `knowledge/`。
- reset 是否可能并发执行，是否有跨进程锁或 lease。
- Windows、macOS、Linux 上实际支持和依赖的 rename/fsync 语义。

### 当前已观察到的失败模式

这些是访谈输入，不代表完整集合：

- metadata 目录先移动、manifest 后写，崩溃时恢复找不到唯一副本。
- 多个 quarantine 仅凭遍历顺序恢复，可能恢复错误代际。
- 仅凭目录名前缀清理，可能删除非 Knowledge 文件。
- quarantine root、child 或 manifest 为 symlink 时可能越界操作。
- intent 文件只 fsync 内容、不 fsync 父目录，断电后目录项可能消失。
- DB 有 Source 且 `knowledge/` 已被重建为空或变为不可信路径时，清理 verified quarantine 可能删除唯一 canonical。
- 秒级时间戳加 PID 会碰撞，后一次 reset 可能覆盖或删除前一代 manifest。
- “多 quarantine 保守拒绝”避免误删，但可能长期保留不可用半状态，需要明确产品和运维语义。

## 当前冻结 Spec 声称的约束

以下是现有 Spec 的当前声明。Grill 必须逐项验证它们是否一致、可实现、足够精确；不能因为文档已写就跳过决策。

- reset 只作用于 Knowledge 数据域。
- 保留数据库 Schema、迁移记录、AI 配置、Memory、Application、Conversation、Interview、Resume 及其他非 Knowledge 数据和文件。
- canonical Source 和原始文件是必须保护的资料。
- DB 提交被定义为 reset 的逻辑完成点。
- DB 有 Source 时不得失去其唯一可恢复文件副本。
- DB 已清空时不得重新暴露旧 Knowledge。
- 清理失败应可恢复或明确进入需要人工介入的状态，不能静默误删。
- 无法证明属于 Knowledge reset 的路径不得移动或删除。
- 多 quarantine 不得通过猜测时间或目录遍历顺序选择。
- reset 后允许从零重新导入相同 Source，并生成新的 Snapshot、Evidence 和 Brief。

## Grill 过程规则

### 一次只解决一个决策节点

每轮必须采用下面的格式：

```text
问题 N：<一个决策问题>

为什么现在必须决定：<它阻塞哪些后续设计>

已核实事实：<只写仓库可观察事实>

可选方案：
- A：...
- B：...
- C：...

推荐：<明确推荐一个方案>

推荐理由：<最坏情况、代价和被放弃的能力>

请你裁决：<只问这一题>
```

用户回答后，Agent 必须复述冻结结论及其后果，再进入下一题。如果回答引入矛盾，先解决矛盾，不得继续向下。

### 不允许的行为

- 不得一次抛出问题清单要求用户批量回答。
- 不得把代码现状冒充产品决策。
- 不得把测试通过当作协议正确性的证明。
- 不得用“极端情况概率低”代替最坏情况分析。
- 不得靠“取最新目录”“按名字排序”或“通常只有一个”解决代际归属。
- 不得在歧义状态下删除任何可能是唯一副本的目录。
- 不得为了让当前实现通过而修改约束措辞。

## 决策树

以下是访谈顺序，不是一次性问题列表。Agent 必须按依赖逐题推进。

### 1. 保证边界与故障模型

首先裁决系统需要覆盖哪些故障：

- 普通函数异常。
- 进程在任意两个持久化步骤之间终止。
- 主机断电或内核崩溃，已返回的写入是否必须 durable。
- 文件系统返回部分失败、只读、空间不足或权限变化。
- 同进程重复 reset、跨进程并发 reset。
- 本地非恶意损坏与主动构造的 symlink/path escape。

**推荐起点**：保证普通异常、任意进程崩溃和主机断电；串行化 reset；对 symlink 和越界路径 fail closed。若某个平台无法提供所需 durability，reset 应明确拒绝，而不是降级为弱保证。

### 2. 核心不变量

逐项定义可以被测试和证明的不变量。至少讨论：

- `DB_HAS_SOURCES` 时是否必须存在且能唯一确定一份 canonical 副本。
- `DB_EMPTY` 时是否允许 quarantine 保留，但绝不能被产品读取。
- 何时允许删除 canonical 的最后一份副本。
- 歧义状态是自动修复、只读降级、阻止启动，还是人工介入。
- “逻辑完成”和“物理清理完成”分别意味着什么。

**推荐起点**：任何自动操作都必须保持“DB 有 Source => 至少一份可唯一恢复的 canonical”；无法证明时保留所有候选并阻止 destructive cleanup。

### 3. 权威来源

裁决以下冲突由谁决定：

- SQLite 行。
- `knowledge/` 当前目录。
- active reset journal。
- generation quarantine。
- 文件系统实际内容和摘要。

**推荐起点**：SQLite 决定 reset 是否逻辑提交；durable active journal 决定哪个 quarantine 属于当前 reset；文件存在性不能单独证明代际归属。

### 4. 并发与唯一 active reset

裁决是否允许多个 reset 同时存在，以及如何阻止：

- 进程内 mutex 是否足够。
- 是否需要跨进程文件锁或 DB 锁记录。
- 发现已有 active intent 时，新 reset 是恢复、拒绝还是排队。

**推荐起点**：同一 data directory 只允许一个 active reset；使用跨进程排他机制；发现 active intent 时先恢复或明确拒绝，绝不创建第二代。

### 5. Generation 与所有权证明

裁决 generation 的生成、排他预留和验证：

- UUID/随机值还是时间戳。
- 如何保证不覆盖已有 manifest 或 child。
- manifest 与 child、data directory、协议版本如何绑定。
- manifest 是否需要内容摘要或 Source 集合摘要。

**推荐起点**：UUID + 排他创建；manifest 绑定 protocol version、generation 和规范化 data-root identity；已有名字一律视为冲突，不覆盖。

### 6. Durable journal 与状态机

先定义持久状态，再定义函数。候选状态至少包括：

- `IDLE`
- `INTENT_DURABLE`
- `FILES_QUARANTINED`
- `DB_COMMITTED`
- `CLEANUP_PENDING`

必须逐条回答：

- 哪些状态需要真实持久化，哪些可以由 DB 和文件布局派生。
- 每次状态更新需要同步哪个文件和哪个父目录。
- 状态更新与目录 rename 的顺序。
- 在任意两个步骤之间崩溃，重启会观察到什么。
- 状态机是否存在无法区分“提交前”和“提交后”的窗口。

**推荐起点**：只持久化恢复决策真正需要的最小状态；每个 destructive step 之前必须已有 durable intent；DB 状态用于判定 commit，active generation 用于判定文件代际。

### 7. Reset 正常路径

为每一步明确前置条件、持久化效果、失败补偿和下一状态：

- 获取排他权。
- 建立安全 quarantine root。
- 排他生成 generation。
- durable 写 active intent。
- rename `knowledge/`。
- 同步相关父目录。
- 提交 Knowledge 表删除事务。
- 重建安全空目录。
- 标记或派生 committed。
- 物理清理 quarantine。
- 清除 active journal 和释放锁。

### 8. 启动恢复决策表

不得用嵌套 if 临时推导。先穷举以下维度：

- DB：有 Source / 空 / 不可读。
- `knowledge/`：缺失 / 安全空目录 / 安全非空目录 / symlink / 非目录。
- active journal：无 / 有效 / 损坏 / symlink。
- active child：无 / 一个安全目录 / symlink / generation 不匹配。
- 其他 quarantine：无 / 一个 / 多个 / 无 manifest。

每个组合必须给出：

- 自动恢复。
- 自动清理。
- 保留并告警。
- 阻止 Knowledge 功能或阻止应用启动。
- 需要人工介入。

**推荐起点**：DB 有 Source 时，任何可能包含对应 canonical 的 verified quarantine 都不得删除；`knowledge/` 非空且代际不明时保留双方并阻止自动 destructive action。

### 9. 路径与删除安全

逐项裁决：

- data root、quarantine root、child、manifest、`knowledge/` 的 symlink 策略。
- resolved containment 与直接父子关系。
- manifest 普通文件校验。
- TOCTOU 能防到什么程度。
- cleanup helper 是否必须再次独立验证。
- 日志允许暴露哪些定位信息。

**推荐起点**：所有 destructive helper 自己 fail closed；不依赖调用方已校验；无法安全使用 descriptor-relative API 时，明确记录残余 TOCTOU 风险。

### 10. 平台语义

核实并裁决 macOS、Linux、Windows：

- 同文件系统原子 rename。
- 文件 `fsync`。
- 目录 `fsync` 或平台等价物。
- SQLite commit durability 配置。
- 文件锁行为。

**推荐起点**：先定义正式支持的平台保证；无法实现等价 durability 的平台拒绝执行 destructive reset，并返回稳定错误码。

### 11. 人工介入与可观测性

裁决保守拒绝之后用户如何恢复：

- 是否需要只读诊断命令。
- 是否输出 generation、状态和安全摘要。
- 是否需要显式选择某一代恢复。
- 什么条件允许人工清理。
- 是否阻止新的 ingest/reset。

**推荐起点**：提供只读诊断和显式恢复入口；人工动作也必须复用相同路径守卫，不允许让用户手工删目录作为正式流程。

### 12. 测试模型

测试必须从状态机生成，而不是从已知 bug 列表追加。至少冻结：

- 每个持久化步骤之前和之后注入崩溃。
- 每个 I/O 调用失败。
- 进程重启一次和连续重启两次的幂等性。
- generation 碰撞和已有 active reset。
- DB 有 Source时 `knowledge/` 的全部形态。
- DB 空时 `knowledge/` 的全部形态。
- 单/多/损坏/无 manifest quarantine。
- root、child、manifest、knowledge symlink 和外部 sentinel。
- cleanup 失败后重新启动。
- reset 后重新导入相同 Source 的端到端路径。

**推荐起点**：建立参数化 transition/fault matrix；每个 case 统一验证不变量，而不是只断言某个 helper 被调用。

## 第一问

新会话完成事实核实后，只能先问这一题：

```text
问题 1：KBR-07 必须承诺的故障模型是否包含“主机断电/内核崩溃后的持久性”，还是只保证进程级崩溃和普通 I/O 异常？

为什么现在必须决定：这会直接决定 manifest、目录 rename、SQLite commit 和父目录是否都需要 durable sync；不先冻结，后续状态机没有统一正确性标准。

推荐：包含主机断电/内核崩溃。KBR-07 是破坏性 reset，只保证进程异常会留下最危险的未定义窗口。如果正式支持的平台无法提供所需目录持久化语义，则该平台应拒绝执行 reset，而不是静默降级。

请你裁决这一保证边界。
```

## 访谈结束前必须形成的建模成果

在用户确认共享理解前，不得进入实施。最终至少提交以下内容供用户逐项确认：

1. **术语表**：Source、canonical、active reset、generation、intent、quarantine、logical commit、cleanup pending、ambiguous state。
2. **事实与决策记录**：每项注明事实证据或用户裁决。
3. **不变量列表**：每条可被最坏情况证明和测试。
4. **持久状态机**：状态、事件、前置条件、持久效果、补偿、终态。
5. **正常路径时序**：文件、目录、DB、journal、锁的操作顺序和 sync 点。
6. **启动恢复决策表**：覆盖 DB、knowledge、journal、quarantine 的状态组合。
7. **崩溃点矩阵**：每个持久步骤前后崩溃的可观察状态和恢复动作。
8. **路径安全模型**：信任边界、symlink、containment、TOCTOU 和删除权限。
9. **并发模型**：单 active reset 的实现与锁失效恢复。
10. **平台支持矩阵**：macOS、Linux、Windows 的保证或明确不支持项。
11. **人工介入流程**：诊断、恢复、清理和审计信息。
12. **参数化测试模型**：由状态转换和故障点派生，而不是按 Finding 堆叠。
13. **被拒绝方案**：说明为什么不采用目录排序、最新时间猜测、多代自动选择、无目录 fsync 等方案。
14. **剩余风险**：无法完全消除的风险及其产品后果。

## 进入下一阶段的门禁

只有用户明确确认“我们已经达到共享理解”，才可以结束 grill。结束时仍不直接实现，而是询问用户是否要把建模结果转成新的 Spec/ADR。

后续 Spec/ADR 至少必须满足：

- 不依赖当前函数结构描述协议。
- 每个删除动作都能追溯到明确的所有权证明。
- 每个 crash point 都有唯一或保守的恢复结果。
- DB 有 Source 时不会自动删除唯一可能副本。
- DB 空时不会重新发布旧 Knowledge。
- 不靠概率、时间排序或目录遍历顺序保证正确性。
- 测试矩阵能直接映射状态机的边和不变量。
