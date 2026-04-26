#!/usr/bin/env python3
import json
import os
import pathlib
import sqlite3
import threading
import time
from typing import Optional

from mcp.server.fastmcp import FastMCP

from schema import SCHEMA_DDL

DB_PATH = os.environ.get("AGENT_DB_PATH", "/home/chuan/mcp/data/agent_comms.db")

_conn: Optional[sqlite3.Connection] = None
_write_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        pathlib.Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA_DDL)
    return _conn


def _reset_connection() -> None:
    """Close and discard the current DB connection. Used for test isolation."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def _update_agent_status(
    agent_id: str,
    status: str = "working",
    task_id: Optional[str] = None,
    clear_task: bool = False,
) -> None:
    db = get_db()
    with _write_lock:
        db.execute(
            """
            INSERT INTO agent_status
                (agent_id, status, current_task, last_active, started_working_at)
            VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                    CASE WHEN ? = 'working' THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NULL END)
            ON CONFLICT(agent_id) DO UPDATE SET
                status       = excluded.status,
                current_task = CASE
                    WHEN ? THEN NULL
                    WHEN excluded.current_task IS NOT NULL THEN excluded.current_task
                    ELSE agent_status.current_task
                END,
                last_active  = excluded.last_active,
                started_working_at = CASE
                    WHEN excluded.status = 'working' AND agent_status.status != 'working'
                    THEN excluded.started_working_at
                    WHEN excluded.status != 'working'
                    THEN NULL
                    ELSE agent_status.started_working_at
                END
            """,
            (agent_id, status, task_id, status, clear_task),
        )
        db.commit()


def _record_tool_metric(
    agent_id: str,
    tool_name: str,
    latency_ms: int,
    model_name: Optional[str] = None,
    task_id: Optional[str] = None,
    context_token_count: Optional[int] = None,
) -> None:
    db = get_db()
    with _write_lock:
        db.execute(
            """
            INSERT INTO tool_metrics
                (timestamp, agent_id, tool_name, latency_ms, context_token_count, model_name, task_id)
            VALUES (strftime('%Y-%m-%dT%H:%M:%fZ','now'), ?, ?, ?, ?, ?, ?)
            """,
            (agent_id, tool_name, latency_ms, context_token_count, model_name, task_id),
        )
        db.commit()


mcp = FastMCP("agent-comms")


@mcp.tool()
async def send_message(
    from_agent: str,
    to_agent: str,
    type: str,
    content: str,
    task_id: Optional[str] = None,
) -> str:
    """Send a message between agents. type must be one of: task, result, escalate."""
    t0 = time.monotonic()
    _update_agent_status(from_agent, task_id=task_id)

    if type not in ("task", "result", "escalate"):
        return json.dumps({"error": f"Invalid type '{type}'. Must be task/result/escalate"})

    db = get_db()
    with _write_lock:
        cur = db.execute(
            """
            INSERT INTO messages (from_agent, to_agent, type, content, task_id, created_at)
            VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            """,
            (from_agent, to_agent, type, content, task_id),
        )
        db.commit()
        msg_id = cur.lastrowid

    _record_tool_metric(from_agent, "send_message", int((time.monotonic() - t0) * 1000), task_id=task_id)
    return json.dumps({"ok": True, "message_id": msg_id})


@mcp.tool()
async def read_messages(
    agent_id: str,
    unread_only: bool = True,
    limit: int = 20,
) -> str:
    """Read messages addressed to agent_id. Returns a JSON list of message objects."""
    t0 = time.monotonic()
    _update_agent_status(agent_id)

    db = get_db()
    query = "SELECT * FROM messages WHERE to_agent=?"
    params: list = [agent_id]
    if unread_only:
        query += " AND read_at IS NULL"
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)

    rows = db.execute(query, params).fetchall()
    result = [dict(row) for row in rows]

    _record_tool_metric(agent_id, "read_messages", int((time.monotonic() - t0) * 1000))
    return json.dumps(result)


@mcp.tool()
async def mark_messages_read(agent_id: str, message_ids: list[int]) -> str:
    """Mark specific messages as read. Only marks messages addressed to agent_id."""
    t0 = time.monotonic()
    _update_agent_status(agent_id)

    if not message_ids:
        return json.dumps({"ok": True, "marked": 0})

    db = get_db()
    placeholders = ",".join("?" * len(message_ids))
    with _write_lock:
        cur = db.execute(
            f"UPDATE messages SET read_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            f"WHERE id IN ({placeholders}) AND to_agent=? AND read_at IS NULL",
            (*message_ids, agent_id),
        )
        db.commit()

    _record_tool_metric(agent_id, "mark_messages_read", int((time.monotonic() - t0) * 1000))
    return json.dumps({"ok": True, "marked": cur.rowcount})


@mcp.tool()
async def set_shared_state(key: str, value: str, agent_id: str) -> str:
    """Store a key-value pair in shared state. Use keys like doc:design:<id> and doc:impl:<id>."""
    t0 = time.monotonic()
    _update_agent_status(agent_id)

    db = get_db()
    with _write_lock:
        db.execute(
            """
            INSERT INTO shared_state (key, value, updated_by, updated_at)
            VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            ON CONFLICT(key) DO UPDATE SET
                value      = excluded.value,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (key, value, agent_id),
        )
        db.commit()

    _record_tool_metric(agent_id, "set_shared_state", int((time.monotonic() - t0) * 1000))
    return json.dumps({"ok": True, "key": key})


@mcp.tool()
async def get_shared_state(key: str) -> str:
    """Retrieve a value from shared state by exact key."""
    db = get_db()
    row = db.execute("SELECT * FROM shared_state WHERE key=?", (key,)).fetchone()
    if row is None:
        return json.dumps({"error": f"Key '{key}' not found"})
    return json.dumps(dict(row))


@mcp.tool()
async def list_shared_state(prefix: Optional[str] = None) -> str:
    """List shared state keys with metadata. Optionally filter by key prefix."""
    db = get_db()
    if prefix:
        rows = db.execute(
            "SELECT key, updated_by, updated_at FROM shared_state WHERE key LIKE ? ORDER BY key",
            (prefix + "%",),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT key, updated_by, updated_at FROM shared_state ORDER BY key"
        ).fetchall()
    return json.dumps([dict(r) for r in rows])


@mcp.tool()
async def report_turn_start(
    agent_id: str,
    model_name: str,
    task_id: Optional[str] = None,
    context_tokens: Optional[int] = None,
) -> str:
    """Call at the start of each agent turn. Returns turn_id to pass to report_turn_end."""
    t0 = time.monotonic()
    _update_agent_status(agent_id, task_id=task_id)

    db = get_db()
    with _write_lock:
        cur = db.execute(
            """
            INSERT INTO turn_metrics (timestamp, agent_id, model_name, task_id, context_tokens)
            VALUES (strftime('%Y-%m-%dT%H:%M:%fZ','now'), ?, ?, ?, ?)
            """,
            (agent_id, model_name, task_id, context_tokens),
        )
        db.commit()
        turn_id = cur.lastrowid

    _record_tool_metric(agent_id, "report_turn_start", int((time.monotonic() - t0) * 1000), model_name, task_id)
    return json.dumps({"turn_id": turn_id})


@mcp.tool()
async def report_turn_end(
    agent_id: str,
    turn_id: int,
    input_tokens: int,
    output_tokens: int,
) -> str:
    """Call at the end of a turn with token counts. Completes the turn_metrics record."""
    t0 = time.monotonic()

    db = get_db()
    with _write_lock:
        cur = db.execute(
            """
            UPDATE turn_metrics
            SET turn_duration_ms = CAST(
                    (julianday(strftime('%Y-%m-%dT%H:%M:%fZ','now')) -
                     julianday(timestamp)) * 86400000 AS INTEGER
                ),
                input_tokens  = ?,
                output_tokens = ?
            WHERE id=? AND agent_id=?
            """,
            (input_tokens, output_tokens, turn_id, agent_id),
        )
        db.commit()
        changed = cur.rowcount

    _record_tool_metric(agent_id, "report_turn_end", int((time.monotonic() - t0) * 1000))

    if changed == 0:
        return json.dumps({"ok": False, "error": "turn_id not found or belongs to a different agent"})
    return json.dumps({"ok": True, "turn_id": turn_id})


@mcp.tool()
async def report_idle(agent_id: str) -> str:
    """Mark agent as idle. Call when a turn ends with no pending work."""
    t0 = time.monotonic()
    _update_agent_status(agent_id, status="idle", clear_task=True)
    _record_tool_metric(agent_id, "report_idle", int((time.monotonic() - t0) * 1000))
    return json.dumps({"ok": True, "agent_id": agent_id, "status": "idle"})


if __name__ == "__main__":
    mcp.run(transport="stdio")
