# agent-comms-mcp

A dual-agent collaboration system. Two Claude CLI sessions share state and messages through SQLite via an MCP server. A third tmux window runs a read-only status dashboard.

```
┌─────────────┐   send_message / read_messages    ┌─────────────┐
│  agent_a    │ ────────────────────────────────► │  agent_b    │
│  Architect  │ ◄──────────────────────────────── │  Developer  │
│  (Opus)     │        result / escalate          │  (Sonnet)   │
└─────────────┘                                   └─────────────┘
       │                                                 │
       └──────────────────┬──────────────────────────────┘
                          │ SQLite (WAL)
                    ┌─────▼──────┐
                    │  panel.py  │
                    │  dashboard │
                    └────────────┘
```

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- [tmux](https://github.com/tmux/tmux)
- [Claude Code](https://claude.ai/code)

## Quickstart

`launch.sh` creates a tmux session with three windows — `agent_a`, `agent_b`, and `status` (dashboard starts automatically). In each agent window, run `claude`.

## Install the MCP server

Add to your Claude Code user settings (`~/.claude/settings.json`) or merge from the included config `claude_mcp_config.json`.  Or register via CLI:

```bash
claude mcp add agent-comms uv \
  -- run --project "$(pwd)" agent-comms-server \
  -e AGENT_DB_PATH="$(pwd)/data/agent_comms.db"
```

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_DB_PATH` | `./data/agent_comms.db` | SQLite database path |

## Agent workflow

### Architect (agent_a)

```
1. report_turn_start
2. set_shared_state("doc:design:<id>", ...)   ← write design doc
3. send_message(to="agent_b", type="task", task_id=<id>)
4. report_turn_end
5. read_messages → review result
6. set_shared_state("doc:impl:<id>", ...)     ← write impl doc
7. report_idle                                ← when no pending work
```

### Developer (agent_b)

```
1. read_messages → mark_messages_read
2. report_turn_start
3. execute task
4. send_message(type="escalate")  ← if blocked
5. send_message(type="result")    ← when done
6. report_turn_end
7. report_idle                    ← when no pending work
```

## Dashboard

```bash
uv run agent-comms-panel
```

| Key | Action |
|-----|--------|
| `r` | Force refresh |
| `s` | Toggle stats view (tokens, tool calls) |
| `q` / Ctrl-C | Quit |

Escalate message colours:
- Bright red — arrived < 2 min ago
- Red — waiting 2–10 min
- **Bold red `!!`** — unread > 10 min, needs attention

## MCP tools

| Tool | Description |
|------|-------------|
| `send_message` | Send task / result / escalate to another agent |
| `read_messages` | Read messages addressed to you |
| `mark_messages_read` | Mark specific messages as read |
| `set_shared_state` | Write a key-value entry (use `doc:design:<id>`, `doc:impl:<id>`) |
| `get_shared_state` | Read a key |
| `list_shared_state` | List keys, optionally filtered by prefix |
| `report_turn_start` | Record start of a turn; returns `turn_id` |
| `report_turn_end` | Record token usage for the turn |
| `report_idle` | Mark yourself idle when no work is pending |

## Development

```bash
uv sync --extra dev
uv run pytest tests/ -v
```
