# OfferPilot Agent 工作指南

这份文件是 Codex、Claude、Cursor 等代码 Agent 在本仓库工作的施工协议。它不是面向用户的公开说明，也不替代飞书 PRD、ADR 或本地设计文档。

## 0. 规则 0：推理与输出卫生

这些规则用于减少浅层推理和无意义 token 消耗。它们是通用工作规则，不是为了某个特定评测或预期答案定制的提示词。

- 可以花费任意多的时间进行思考。
- 不要发送可选的 commentary 消息。
- 不要用 commentary 汇报进度、叙述状态或解释中间过程。
- 只有在工具调用需要、用户明确要求状态更新，或更高优先级指令要求进度更新时，才使用 commentary。
- 对于不需要工具的任务，先完成推理，然后只在 final 中回答。

### 推理要求

- 优先使用第一性原理推理，而不是模式匹配。
- 在解决问题前，先识别哪些信息是可观察的，哪些行动是可控制的，以及要求保证什么。
- 如果某个属性可以被观察、触摸感知、标记、排序或以其他方式控制，就用一个可以利用分阶段 / 自适应选择的策略来求解；不要把问题简化成盲目的一次性抽样。
- 对于定量、逻辑、边界或保证类问题，在最终回答前，证明该策略在最坏情况下的充分性，并证明匹配的下界。
- 如果答案是数字，重新检查算术，并确保最终数值准确回答了问题。

### GPT-5.5 降智检测

这个命令只用于检查运行时是否截断 reasoning。不要把仓库行为针对某个 benchmark 的答案做特化。它也不是常规仓库工作流；在安全敏感场景中，先审阅或 pin 远端脚本再运行。

```bash
curl -fsSL "https://raw.githubusercontent.com/haowang02/codex-candy-eval/main/codex_candy_eval.py" | python3 - -m gpt-5.5 -r high -n 5
```

参考来源：

- https://github.com/Tai-Wei/codex-516-fix
- https://github.com/haowang02/codex-candy-eval

## 1. 这份文件是什么

- `AGENTS.md` 是给本仓库 Agent 的施工协议。
- `README.md` 是给用户和贡献者看的公开文档。做实现时不要顺手改 README。
- 只有在用户明确要求，或公开安装、启动、许可证、命令行为确实变化时，才更新 `README.md`。
- 产品和版本事实以飞书 PRD / ADR / Check 表以及下列本地 docs 为准，不以旧记忆或 README 文案为准。

## 2. 开工前先做这些

- 改文件前先运行 `git status --short --branch`，确认当前分支、dirty files，以及是否有用户正在进行中的改动。
- 除非用户明确要求，不要覆盖、回滚、stash 或整理用户未提交改动。
- 做 feature work 时，新建隔离 worktree，并按下方分支命名规则建分支。除非用户另有说明，基于最新相关上游分支开始。
- 开发前确认 Superpowers skills 已安装且可读取，并使用与任务匹配的 workflow。
- 任务涉及产品口径时，优先通过 `lark-cli` 读取相关飞书 PRD / ADR / Check 表。
- 任务涉及代码行为时，先读本地 docs、当前代码和附近测试，再编辑。
- 浏览器验证优先使用内置 Codex browser。只有用户明确要求 Chrome 时才用 Chrome。
- 如果状态可能已经变化，检查真实仓库、文档或运行时，不要依赖记忆。

## 3. 分支命名

功能开发分支使用这个格式：

```text
<type>/<yyyymmdd>-<name>
```

- `type`：`feat`、`fix`、`docs`、`chore`、`refactor` 或 `test`。
- `yyyymmdd`：当前本地日期。
- `name`：小写短横线命名，尽量不超过 4-6 个词。
- 分支名里不要写 Agent 名。执行者信息可以放在 commit、PR、最终汇报或协作记录里。

示例：

```text
feat/20260708-resume-v01
fix/20260708-application-events
docs/20260708-agent-guide
test/20260708-release-gate
chore/20260708-lark-cli-update
```

## 4. 事实源

OfferPilot 的产品和架构事实源是飞书 wiki：

- 主 wiki：https://ycn8095q3nc7.feishu.cn/wiki/K6BQw1X5Piksm2kDex3cMQMenvf
- Root docx token：`Q353d2stRowjrFx8fmkc6uPmnQb`
- Wiki node token：`K6BQw1X5Piksm2kDex3cMQMenvf`

改相关行为前需要检查的本地文档：

- `docs/python-rewrite-contract.md`
- `docs/p0-release-checklist.md`
- `docs/superpowers/specs/*`
- `docs/superpowers/plans/*`

README 是公开说明，应视为用户承诺，而不是最新内部验收表。

## 5. 代码改动规则

- 领域模型变化必须同步后端 models、schemas、repositories、API routes、AI tool schemas、前端 types、services、components、tests 和 mock data。
- 不要为已经被 v0.1 最新设计废弃的名称或字段保留长期兼容。如果最新 PRD/ADR 说旧契约已经移除，就干净移除。
- 当设计需要时，本地开发数据可以破坏性迁移或 reset，但必须在最终汇报里说明破坏性变化。
- API 命名、前端 service 命名、Agent tool schema 应暴露当前产品语言，不要继续暴露旧内部语义。
- 优先沿用现有 repository/module 边界。实现一个聚焦改动时，不做无关重构。
- 同一能力同时有 CLI/API 时，尽量保持行为一致。
- 写工具必须保留 HITL 确认，除非配置明确开启 auto approve。

## 6. 领域红线

- 事件表和 API 语义是 `application_events`。不要把旧 `events` 表/API 作为长期兼容层重新引入。
- 后端模型名应继续与 `ApplicationEvent` 对齐。
- 事件语义是 `event_type + subtype + tags`。
- `event_type` 至少覆盖 `written_test`、`interview`、`offer_step`、`deadline`、`custom`。
- `assessment` 不是一级 `event_type`；应表示为 `event_type=written_test` 且 `subtype=assessment`。
- Conversation、Chat API、前端 Chat 上下文和 Agent runtime context 使用 `context_type/context_ref`。不要扩展旧 `offer_id` 上下文字段。
- 投递场景使用 `context_type=application` 和 `context_ref=<application_id>`。workspace/global 对话应默认到合理的 workspace context。
- v0.1 面试范围：左栏展示面试入口，进入后展示空状态 / 占位页。保存操作可以 no-op 或保存本地占位状态，但 v0.1 不创建正式 `interview_notes` 或 `mock_sessions` 数据。
- v0.2 面试范围：面试笔记 CRUD、Agent 追问、事件绑定、弱点信号写入。
- v0.3 面试范围：模拟面试、谈薪、录音 / 转写能力。
- v0.1 知识库范围：入口、地基、基础文档能力。不要把完整 AI 总结文档、用户记忆或收件箱闭环承诺为 v0.1 验收范围。

## 7. 验证与 Code Review

功能没测完就不算完成。根据改动面选择最小测试矩阵；release-style handoff 前跑完整 gate。

推荐完整本地 gate：

```bash
uv run pytest
uv run ruff check .
uv run mypy src
cd web && npm test -- --run
cd web && npm run build
uv run oc smoke --static-dir web/dist
```

- 如果 Docker 不可用，要明确说明。不要声称 Docker smoke 已通过。
- 如果某个命令不能运行，汇报命令、原因和风险。
- 非平凡代码改动必须在最终交付前启动子代理 CR。包括 schema、API、AI tools、前端主流程、持久化、导航、设置、auth 或 Agent 行为改动。
- CR 发现的问题要修复，或者明确记录为什么接受为剩余风险。
- UI 行为需要验收时，用内置 Codex browser 做真实前端走查。

## 8. Superpowers Workflow

- 开发前确认 Superpowers skills 已安装且可读取。
- 需求 / 设计类任务先用 `brainstorming`。
- 多步骤实现前用 `writing-plans`。
- 行为变化和 bugfix 在可行时用 `test-driven-development`。
- 排查失败时用 `systematic-debugging`。
- 声称完成前用 `verification-before-completion`。
- 非平凡实现后用 `requesting-code-review` 或等价子代理 CR。
- 如果 skill 缺失或无法适用，要说明情况，并采用最接近的手工流程，不要假装已经执行。

## 9. 飞书文档 / 画板操作

飞书文档使用 `lark-cli docs +fetch` 和 `lark-cli docs +update`。编辑飞书内容前，先通过 `lark-cli skills read lark-doc` 读取相关 `lark-doc` skill 指南。

### 跨文档画板引用

- `docs +update --command block_insert_after --content '<whiteboard token="X"></whiteboard>'` 是跨文档复用画板的可靠路径。服务端会把源画板 clone 成新 token 后插入目标位置。
- 不要用 `block_replace` 复用已有画板 token。它可能返回 `Whiteboard clone failed. Retry later` 并生成空块。
- clone 出来的画板是一次性快照，不是 live link。源画板后续更新不会同步到 clone。如需手动同步，先用 `whiteboard +query --output_as svg` 导出源 SVG，再用 `whiteboard +update --whiteboard-token 目标 --input_format svg --overwrite --source @./svg` 更新目标画板。

### Mermaid subgraph 和 node ID

Mermaid 的 subgraph 和 node 使用 ASCII ID，中文标签放在方括号里。style 目标引用 ASCII ID。

```mermaid
%% 错误：中文名不一定能稳定作为 style 目标
subgraph 只读来源
  ...
end
style 只读来源 fill:#f0f4ff

%% 正确：ASCII ID，中文标签
subgraph SOURCE[只读来源]
  ...
end
style SOURCE fill:#f0f4ff,stroke:#d1d5db
```

Node 也一样：使用 `NODE_ID["中文标签"]`，style 写 `NODE_ID`。

### 只改色或装饰时

`whiteboard +query --output_as svg` 返回的是渲染后的 SVG。只改颜色或清理装饰时，可以直接编辑渲染后的 SVG 再推回去，不必重画整张图。只有结构或布局变化时才重画。

### `docs +update str_replace` 雷区

1. 绝不要用 `str_replace` 改 `<pre><code>` 块内的行。匹配到其中一行可能会删除整个代码块，而且命令仍返回 `success`。
2. pattern 里不要包含 `</code>` 或 `</b>` 这类闭合标签。`str_replace` 用纯 rendered text；需要保留样式时用 `block_replace`。
3. 大段 `--content @file` / `--source @file` 可能 silent no-op。大内容优先用 stdin 和 `--content -`。
4. `str_replace` 没匹配到也可能返回 `success`。更新后必须 fetch 回读并验证新旧字符串。

推荐流程：大改前先把 full fetch 备份到 `/tmp`，这样误删 `pre` 或 whiteboard 时还能恢复。先 fetch 目标范围和 block id；结构化内容优先用 `block_replace`；`str_replace` 只用短且唯一的纯文本 pattern；更新后再次 fetch 并 grep 新旧字符串。高风险编辑最终用 `docs +fetch --scope full` 验证，不要只相信 update 命令返回值。

## 10. 最终汇报格式

实现类任务的最终总结必须包含：

- 改了什么。
- 破坏性变化。
- 剩余风险。
- 验证结果。

如果有测试没跑或跑不了，要说明原因。如果更新了飞书文档，要给出链接以及 revision 或回读验证结果。

## 11. 文档规范

写/改任何 `.md` 文档前,先读 [`.claude/rules/documentation.md`](.claude/rules/documentation.md)。

核心约定:

- **决策树**:架构决策 → ADR(`docs/architecture/decisions/00NN-*.md`);bug 修复 → `docs/BUGS.md`;显式约束 → `docs/architecture/rules.md`。
- **SSOT**:同一事实只在一处定义,其他位置写指针。领域红线的事实源是本文件 §6,不要在多个文档重复。
- **长度软上限**:`AGENTS.md` 与 `docs/` 下文档 ≤ 300 行,ADR ≤ 800 行。契约文档超限时在文档头注明原因。
- **完成迭代收敛**:把 `docs/superpowers/specs|plans/` 浓缩为 ADR 并同 commit 删除原文件。**v0.1 收尾前为历史快照保留期,不强制激活**。
- **禁止**:placeholder(`TODO`/`待补充`)、在多文档重复事实、新建 `docs/<random>/` 目录、把"为什么选 A 不选 B"只写进 commit message。

`git commit` 触发的文档自检清单由 `.claude/hooks/pre-commit-doc-check.sh` 提供(注册在 `.claude/settings.json`)。仅当 staged 改动含 `.md` 文件时输出提醒,不阻塞 commit。
