# Dual-Agent MCP System — Implementation Plan

## Already Implemented (Baseline)

### MCP Server (`server.py`)
- FastMCP server, stdio transport
- SQLite WAL mode, thread-safe write lock
- `send_message` — sends task/result/escalate between agents
- `read_messages` — reads messages addressed to an agent (unread_only, limit)
- `mark_messages_read` — marks specific messages read (only own messages)
- `set_shared_state` / `get_shared_state` / `list_shared_state` — key-value store for design/impl docs
- `report_turn_start` / `report_turn_end` — explicit per-turn metrics reporting
- `agent_status` auto-set to `working` on every tool call
- `tool_metrics` latency row recorded on every tool call

### Database (`init_db.py`)
- 5 tables: `messages`, `shared_state`, `agent_status`, `tool_metrics`, `turn_metrics`
- Schema DDL duplicated between `init_db.py` and `server.py` (fixed in Cycle 1)

### Status Panel (`panel.py`)
- `rich.Live` at 2 s auto-refresh
- Normal view: agent status table, unread message counts, task lifecycle from `doc:*` keys, recent message preview
- Stats view (`s` key): per-agent turns / tokens / escalations, top-5 tools by call count
- Escalate messages highlighted red; agent working >20 min flagged bold red
- Keys: `r`=force refresh, `s`=toggle stats, `q`=quit

---

## Cycle 1 — Schema dedup + idle tracking + context tokens

**Goal:** close the two spec gaps (missing `context_token_count`, no way to mark agent idle) and eliminate duplicated DDL.

| # | Task | TDD? |
|---|------|------|
| 1 | Extract schema DDL to `schema.py`; import it in both `server.py` and `init_db.py` | no |
| 2 | Add `context_token_count INTEGER` column to `tool_metrics` in schema | no |
| 3 | Add optional `context_token_count` param to `report_turn_start`; store it in `turn_metrics` as `context_tokens` | no |
| 4 | Add `report_idle` MCP tool: sets agent status to `idle`, clears `current_task` | no |
| 5 | Expose `_reset_connection()` helper in `server.py` for test isolation | no |

Commit: `feat(cycle-1): schema dedup, context_token_count, report_idle`

---

## Cycle 2 — Test suite for MCP server

**Goal:** full behavioural coverage of every MCP tool. Tests written against the spec, not the implementation.

| # | Task | TDD? |
|---|------|------|
| 1 | Add `pytest`, `pytest-asyncio` to `pyproject.toml`; create `tests/conftest.py` with per-test temp-DB fixture | — |
| 2 | `test_send_message`: valid types persist to DB; invalid type returns error; `agent_status` set to working | yes |
| 3 | `test_read_messages`: `unread_only=True` skips read rows; `limit` respected; order newest-first | yes |
| 4 | `test_mark_messages_read`: marks own messages; silently ignores other agents' messages | yes |
| 5 | `test_shared_state`: upsert behaviour; `get` for missing key returns error; `list` with prefix filter | yes |
| 6 | `test_turn_metrics`: `report_turn_start` returns `turn_id`; `report_turn_end` computes duration, rejects wrong agent | yes |
| 7 | `test_report_idle`: status becomes `idle`; `current_task` cleared; `last_active` updated | yes |
| 8 | `test_agent_status_side_effects`: status auto-set to `working` on `send_message`, `read_messages`, `set_shared_state` | yes |
| 9 | `test_tool_metrics`: latency row inserted after each tool call | yes |

Commit: `test(cycle-2): full MCP server test suite`

---

## Cycle 3 — Panel escalate age highlighting

**Goal:** implement the spec's age-based escalate colouring (new vs stale unread escalates).

| # | Task | TDD? |
|---|------|------|
| 1 | In `_messages_table`, add `Age` column showing oldest unread escalate age per route | no |
| 2 | Style: escalate <2 min → bright red; 2–10 min → red; >10 min unread → bold red + `!!` prefix | no |
| 3 | `tests/test_panel_queries.py`: unit-test pure DB-query helpers with seeded data | yes |

Commit: `feat(cycle-3): escalate age highlighting + panel query tests`

---

## Cycle 4 — Operational setup

**Goal:** make it trivial to start the full system.

| # | Task | TDD? |
|---|------|------|
| 1 | `launch.sh`: creates/attaches tmux session with 3 windows — `agent_a`, `agent_b`, `status` (runs `panel.py`) | no |
| 2 | `claude_mcp_config.json`: ready-to-paste MCP server config for Claude Code | no |
| 3 | `CLAUDE.md`: project overview, quickstart, MCP tool reference for agents (what to call and when) | no |

Commit: `ops(cycle-4): tmux launch script, MCP config, CLAUDE.md`
