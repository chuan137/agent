# 双智能体系统设计 - 最终版总结

## 背景与场景

在 Manila 稳定分支管理的自动化流程中，使用两个 Claude CLI 会话协同工作——一个负责架构决策和文档（Architect），一个负责执行开发任务（Developer）。工作模式是**人在环路中央**：多个 tmux 窗口同时开着，人类作为项目经理在窗口间穿梭，随时观察、干预、调整模型和努力程度，热插拔新 agent 加入团队。

## 设计取舍的核心论证

**为什么不用单智能体 + Task 工具**：长项目对话过长导致频繁 compress，关键信息反复输入；无法做模型分级（Architect 用 Opus，Developer 用 Sonnet）；多 repo 场景下顶层设计、业务逻辑、基础设施天然适合分配给不同 agent。

**为什么不用 Python 编排器 + 无状态 worker**：失去多窗口工作面板的可观察性；无法热插拔新 agent；不支持人类随时介入对话；无法运行时调整 effort 或切换模型。

**为什么保留双 CLI**：CLI 会话不只是"执行体"，更是"可观察的工作面板"；消息总线不只是"通信机制"，更是"协作记录 + 协调点"；tmux 是"多窗口工作环境"。这套基础设施的真实价值是支撑工作室式的人机协作。

## 核心架构

**MCP Server 作为通信桥**：两个 Claude 会话通过 MCP server 读写 SQLite，工具语义为 `send_message`、`read_messages`、`set_shared_state`，消息类型区分 `task / result / escalate`。

**角色分离**：
- Agent A（Architect，Opus）：设计 → 写前置文档 → 派发任务 → 审查 → 写后置文档
- Agent B（Developer，Sonnet）：专注执行，完成发 result，遇阻塞发 escalate

**文档生命周期**：每个任务产生 `doc:design:<id>`（前置）和 `doc:impl:<id>`（后置），存入共享状态形成可追溯决策链。规则放宽为"B 可在 escalate 中附带技术细节，但 impl doc 最终版本由 A 整合"。

**tmux 多窗口**：每个 agent 一个窗口，加一个状态面板窗口作为控制塔。

## 关键设计决策：去掉自动调度器，改为状态面板

### 为什么去掉调度器

原设计中调度器（5 秒轮询 + tmux send-keys 注入 prompt）有三个问题：时序不可靠（注入到正在交互的 pane 会冲突）、污染对话上下文、解决错对象（真实目的是"防止人类漏掉状态变化"，这是注意力问题不是协作问题）。调度器试图替人类驱动 agent，剥夺了人类想保留的把关位置。

### 状态面板的定位

**仪表盘，不是副驾驶**。只读、不决策、不自动触发任何动作。把状态可视化呈现给人类，由人类决定推进节奏。

### 状态面板展示内容

**Agent 状态**：每个 agent 是 idle 还是 working、当前任务、上次活动时间。数据来源是 MCP server 在工具调用时自动更新 `agent_status` 表，不需要 agent 显式上报。

**未读消息**：按 (from, to) 分组的未读计数，按消息类型区分。escalate 类高亮优先。新到 escalate 红色高亮，超过 10 分钟未处理变深红或闪烁——区分新到积压。

**当前任务**：从 shared state 的 `doc:design:*` 和 `doc:impl:*` 对应关系推断任务状态——已派发未完成 / 已完成未审查 / 已闭环。

**最近消息预览**：每个 agent 行旁显示最后一条消息前 60 字符。

**任务时长**：working 状态显示已工作时长，帮助发现"没有变化的异常"（如 B 卡了 20 分钟）。

### 技术选型

`rich` 库的 `Live` + `Table`，跑在独立 tmux 窗口（命名为 `status`）。代码量约 100-150 行。`textual` 太重，`watch + print` 太丑，`rich.Live` 是甜点。监听 `r` 键做强制刷新。

### 不要做的事

- 不让面板自动发消息给任何 agent
- 不在面板里做决策建议
- 不让面板解析 agent 对话内容，只看 SQLite 里结构化的部分

## 性能测量基础设施

**核心理念**：在做任何性能优化之前，先建立测量。没有数据的优化是猜测。

### 测量数据的采集

MCP server 在每次工具调用时记录到一个 `tool_metrics` 表：

- `timestamp`
- `agent_id`（哪个 agent 调用的）
- `tool_name`（调用的工具）
- `latency_ms`（工具执行耗时）
- `context_token_count`（调用时该 agent 的上下文 token 数，如果可获取）
- `model_name`（当前使用的模型）
- `task_id`（如果该调用关联到某个任务）

agent 回合级别的数据记录到 `turn_metrics` 表：

- `timestamp`
- `agent_id`
- `turn_duration_ms`（从该 agent 开始思考到完成回合的总时长）
- `input_tokens` / `output_tokens`
- `model_name`
- `task_id`

回合数据需要 agent 在回合开始/结束时通过专门的 MCP 工具上报（如 `report_turn_start` / `report_turn_end`），或者由 MCP server 通过其他手段推断。

### 测量数据的展示

**状态面板加 "today's stats" 视图**，作为面板的可切换标签页（按某个键切换）。展示：

- A 和 B 各自今天的总推理时间
- 平均回合时长
- token 消耗（输入 / 输出分别统计）
- 工具调用次数 top 5（看哪些工具最频繁，是否有优化空间）
- 任务平均耗时
- escalate 次数

### 用数据驱动后续优化

未来当系统体感"慢"时，先看测量数据再决定动手方向。常见情况和对应优化方向（**未来再做，本次不实施**）：

- A 的平均上下文 token 数持续增长 → 精简 Architect 上下文（工具返回值区分 summary/full）
- B 的回合时长方差大 → 任务粒度拆分不均匀，调整 `queue_builder.py`
- 某个工具调用频次远高于其他 → 该工具可能需要批量化或合并
- A 的审查回合时长 > 派发回合时长 → A/B 流水线化，让审查和下一个执行重叠
- 大量例行审查回合 token 数低 → 这些回合可以降级到 Sonnet

## 实施时需要确认的点

下一个对话实施时，需要先明确：

1. **SQLite schema** ——messages 表、shared state 表、新增的 `agent_status` / `tool_metrics` / `turn_metrics` 表的具体列定义
2. **agent 状态自动更新逻辑**——在 MCP server 哪些工具的调用路径上更新 `agent_status`
3. **回合级测量的上报机制**——是新增 MCP 工具让 agent 显式上报，还是从其他信号推断
4. **token 计数来源**——Claude CLI 是否暴露当前上下文 token 数；如果不暴露，是否需要本地估算（tiktoken 之类）
5. **状态面板运行环境**——macOS / Linux，影响未来是否加桌面通知
6. **stats 视图的切换方式**——快捷键 / 自动轮播 / 始终显示

## 暂未涉及的话题

- **Checkpoint / revert 机制**：当前状态分散在 Claude 会话历史、SQLite、文件系统三处，要做真正的 checkpoint 需要三层协同回滚。本次不处理。
- **性能优化的具体动作**：精简上下文、模型分层、流水线化、工具批量化等。等测量数据积累一周后基于数据决策，本次不实施。
- **快捷导航键**：从面板按数字键 tmux select-window 跳到对应 agent 窗口。第一版不做。
- **无人值守场景**：用 `claude -p --resume` 做一次性非交互调用。作为补充手段，主流程不依赖。

## 一周试用观察信号

跑一周后通过以下信号判断下一步：

- **几乎不看面板，agent 自己跑得挺好** → 角色分离和消息总线本身够用，面板可能多余
- **经常想从面板触发动作** → 考虑加快捷动作或轻度自动化，这才是引入有限调度的合适时机
- **焦虑地频繁查看** → agent 回合粒度太细或通知设计有问题，需调整
- **stats 视图揭示明显瓶颈** → 启动针对性优化
