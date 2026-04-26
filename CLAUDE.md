# Agent Comms MCP Server

双智能体协作系统。两个 Claude CLI 会话通过 SQLite 共享状态和消息，第三个 tmux 窗口运行只读状态面板。

## 快速启动

```bash
./launch.sh          # 创建 tmux session，打开三个窗口
```

在 `agent_a` 和 `agent_b` 窗口中分别运行 `claude`，然后通过 `/mcp add` 或用户设置加载 MCP server（见下方配置）。

### MCP 配置

将 `claude_mcp_config.json` 的内容合并到你的 Claude Code 用户设置（`~/.claude/settings.json`）或项目设置（`.claude/settings.json`）的 `mcpServers` 字段下。

或者用命令行方式注册：

```bash
claude mcp add agent-comms python3 /home/chuan/mcp/server.py \
  -e AGENT_DB_PATH=/home/chuan/mcp/data/agent_comms.db
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AGENT_DB_PATH` | `./data/agent_comms.db` | SQLite 数据库路径 |

---

## MCP 工具参考

### 消息传递

#### `send_message`
向另一个 agent 发送消息。调用后自动将自身状态设为 `working`。

| 参数 | 类型 | 说明 |
|------|------|------|
| `from_agent` | str | 发送方 ID（如 `"agent_a"`） |
| `to_agent` | str | 接收方 ID |
| `type` | str | `"task"` / `"result"` / `"escalate"` |
| `content` | str | 消息正文 |
| `task_id` | str? | 关联任务 ID（可选） |

```
→ {"ok": true, "message_id": 42}
```

#### `read_messages`
读取发给自己的消息。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `agent_id` | str | — | 自己的 ID |
| `unread_only` | bool | `true` | 只返回未读消息 |
| `limit` | int | `20` | 最多返回条数 |

```
→ [{"id": 1, "from_agent": "agent_a", "type": "task", "content": "...", ...}]
```

#### `mark_messages_read`
将指定消息标记为已读。只能标记发给自己的消息。

| 参数 | 类型 | 说明 |
|------|------|------|
| `agent_id` | str | 自己的 ID |
| `message_ids` | list[int] | 要标记的消息 ID 列表 |

```
→ {"ok": true, "marked": 3}
```

---

### 共享状态

用于存储设计文档（`doc:design:<task_id>`）和实现文档（`doc:impl:<task_id>`）。状态面板从这些 key 推断任务生命周期。

#### `set_shared_state`

| 参数 | 类型 | 说明 |
|------|------|------|
| `key` | str | 如 `"doc:design:t001"` |
| `value` | str | 文档内容（建议 JSON 或 Markdown） |
| `agent_id` | str | 写入方 ID |

#### `get_shared_state`

| 参数 | 类型 | 说明 |
|------|------|------|
| `key` | str | 精确匹配 key |

#### `list_shared_state`

| 参数 | 类型 | 说明 |
|------|------|------|
| `prefix` | str? | key 前缀过滤（可选） |

---

### 性能指标

#### `report_turn_start`
在每个回合开始时调用。返回 `turn_id`，传给 `report_turn_end`。

| 参数 | 类型 | 说明 |
|------|------|------|
| `agent_id` | str | 自己的 ID |
| `model_name` | str | 当前使用的模型名 |
| `task_id` | str? | 关联任务 ID（可选） |
| `context_tokens` | int? | 当前上下文 token 数（可选，如可获取） |

```
→ {"turn_id": 7}
```

#### `report_turn_end`
在回合结束时调用，填入 token 消耗。不更新 agent 状态。

| 参数 | 类型 | 说明 |
|------|------|------|
| `agent_id` | str | 自己的 ID |
| `turn_id` | int | `report_turn_start` 返回的 ID |
| `input_tokens` | int | 输入 token 数 |
| `output_tokens` | int | 输出 token 数 |

#### `report_idle`
标记自己为空闲状态，清空当前任务。在没有待处理工作时调用。

| 参数 | 类型 | 说明 |
|------|------|------|
| `agent_id` | str | 自己的 ID |

```
→ {"ok": true, "agent_id": "agent_b", "status": "idle"}
```

---

## 推荐工作流

### Architect (agent_a, Opus)

```
每个任务：
1. report_turn_start
2. 写设计文档 → set_shared_state("doc:design:<id>", ...)
3. send_message(to="agent_b", type="task", content=..., task_id=<id>)
4. report_turn_end
5. （等待）read_messages → 收到 result 后审查
6. 写实现文档 → set_shared_state("doc:impl:<id>", ...)
7. 无待处理工作时 → report_idle
```

### Developer (agent_b, Sonnet)

```
每个任务：
1. read_messages → mark_messages_read
2. report_turn_start
3. 执行任务
4. 遇到阻塞 → send_message(type="escalate")
5. 完成 → send_message(type="result")
6. report_turn_end
7. 无待处理工作时 → report_idle
```

---

## 状态面板

```bash
python3 panel.py          # 启动面板（已在 status 窗口自动运行）
```

| 按键 | 功能 |
|------|------|
| `r` | 强制刷新 |
| `s` | 切换 stats 视图（今日 token / 工具调用统计） |
| `q` / Ctrl-C | 退出 |

escalate 消息颜色说明：
- 亮红：刚到（<2 分钟）
- 红：积压中（2–10 分钟）
- **粗红 `!!`**：需要立即处理（>10 分钟未读）

---

## 开发

```bash
pip install -e ".[dev]"
python3 -m pytest tests/ -v
```
