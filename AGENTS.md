# OfferPilot Agent 说明

这份文件沉淀后续 Agent 处理 OfferPilot 项目时必须知道的上下文与踩坑经验。产品文档、ADR、子 PRD 都在飞书 wiki（`Q353d2stRowjrFx8fmkc6uPmnQb` 是根 docx token，`K6BQw1X5Piksm2kDex3cMQMenvf` 是同一节点的 wiki node token），本文件只记 Agent 在**工具层面**踩过的坑，避免下次重犯。

## 飞书文档 / 画板操作经验

编辑 OfferPilot 主 wiki 及其 9 个子 PRD 页时踩过几个坑，直接抄这里的做法就行，不用重新试错。

### 跨文档画板引用

- **`docs +update --command block_insert_after --content '<whiteboard token="X"></whiteboard>'`** 是**唯一**能跨文档复用画板的路径 —— 服务端会把源画板 clone 成新 token 插入到目标位置。
- **不要用 `block_replace`** 复用已有画板 token —— 服务端会返回 `Whiteboard clone failed. Retry later` 并生成空块。要"替换"就先 insert_after 拿到新块，再 block_delete 原块。
- 这是一次性**快照**，不是 live link：源画板后续更新不会同步过来。真需要同步就 `whiteboard +query --output_as svg` 拉源 SVG，然后 `whiteboard +update --whiteboard-token 目标 --input_format svg --overwrite --source @./svg` 手动推。

### Mermaid subgraph 中文名不能直接用作 style 目标

```mermaid
%% ❌ 无效 —— 中文名不匹配
subgraph 只读来源
  ...
end
style 只读来源 fill:#f0f4ff

%% ✅ 有效 —— 先给 subgraph 赋 ASCII ID，标签放方括号
subgraph SOURCE[只读来源]
  ...
end
style SOURCE fill:#f0f4ff,stroke:#d1d5db
```

Node 也一样：定义时用 `NODE_ID["中文标签"]`，style 只认 `NODE_ID`。

### 只改色不改布局：直接改 renderer 输出的 SVG

`whiteboard +query --output_as svg` 返回的是飞书 renderer 已经渲染好的 SVG（不是作者原始 SVG）。想批量归一化配色时**不必重画**，Python 一行 `str.replace('#e8eefc', '#f5f5f7')` 改完再 `whiteboard +update --input_format svg --overwrite` 推回去即可。

同理：想清 emoji 装饰，直接对 SVG 做 `for e in ['🔍','📌','💰']: svg = svg.replace(e, '')`，然后 push 回去。比重画整张 SVG 快一个数量级。

只有涉及**结构改动**（加/删元素、改布局）时才需要重画整张 SVG。

### `docs +update str_replace` 的四个雷区

批量修文档正文时踩过一次很惨的坑：一个 `str_replace` 把两个 `<pre><code>` 提示词模板整个删掉了。总结出这些硬性规则，绕开就行：

1. **绝不用 `str_replace` 改 `<pre><code>` 块内的行**。pattern 一旦匹配到 pre 内的 rendered 文本，服务端会把**整个 pre 块删掉**（不是替换那一行），且返回 `success` 静默无告警。改 pre 内的行必须 `block_replace` 整块换掉。
2. **pattern 里含 `</code>` / `</b>` 等闭合标签时会拆坏内联结构**。比如 pattern `salary_negotiation</code> 归档` + content `negotiation</code> 归档`，替换后变成 `<code>conversations.mode=</code>negotiation 归档` —— 值对了但 code 标签跑外面去了。稳妥做法：pattern 用**纯 rendered 文本**（不含标签），要改样式就走 `block_replace` 整块提供正确 XML。
3. **`--content @file` / `--source @file` 传大内容会 silent no-op**（几 KB 起）。CLI 返回 `success`、`revision_id` 也变了，但服务端啥也没写。改用 **stdin**（`cat file | ... --content -`）就正常。
4. **`str_replace` 匹配失败也返回 `success`**。pattern 拼错、上下文对不上、含不该有的标签，全都静默通过。每次改完必须 `docs +fetch --scope full` 再 grep 一遍确认新旧字符串数量，不能只看 CLI 返回。

**推荐工作流**：批量改一个文档前，先用 `--scope keyword --detail with-ids` 拿目标 block-id 一次；然后能 `block_replace` 就 `block_replace`，能 `str_replace` 就只用**纯文本、短、绝对唯一**的 pattern；改完立刻 fetch full 校验；被删掉的 pre / whiteboard 要能从上次 fetch 的备份里 recover 出来（每次大改前把 full fetch 存一份到 `/tmp`）。
