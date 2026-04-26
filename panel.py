#!/usr/bin/env python3
"""Read-only status dashboard for the dual-agent system.

Keys: r=force refresh, s=toggle stats view, q/Ctrl-C=quit
"""
import os
import select
import sqlite3
import sys
import termios
import threading
import time
import tty
from datetime import datetime, timezone
from typing import Optional

from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

DB_PATH = os.environ.get("AGENT_DB_PATH", "/home/chuan/mcp/data/agent_comms.db")

_quit_flag = threading.Event()
_force_refresh = threading.Event()
_show_stats = threading.Event()


def get_panel_db() -> Optional[sqlite3.Connection]:
    if not os.path.exists(DB_PATH):
        return None
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError:
        return None


def _keyboard_listener() -> None:
    fd = sys.stdin.fileno()
    if not os.isatty(fd):
        return
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while not _quit_flag.is_set():
            ready, _, _ = select.select([sys.stdin], [], [], 0.1)
            if ready:
                ch = sys.stdin.read(1)
                if not ch:
                    _quit_flag.set()
                    break
                if ch in ("q", "\x03"):
                    _quit_flag.set()
                elif ch == "r":
                    _force_refresh.set()
                elif ch == "s":
                    if _show_stats.is_set():
                        _show_stats.clear()
                    else:
                        _show_stats.set()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _format_elapsed(ts_str: Optional[str]) -> str:
    if not ts_str:
        return "-"
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        elapsed = int((datetime.now(timezone.utc) - dt).total_seconds())
        if elapsed < 60:
            return f"{elapsed}s"
        return f"{elapsed // 60}m{elapsed % 60:02d}s"
    except (ValueError, OSError):
        return "-"


def _agent_status_table(conn: sqlite3.Connection) -> Table:
    table = Table(title="Agent Status", show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("Agent", style="bold")
    table.add_column("Status")
    table.add_column("Current Task")
    table.add_column("Last Active")
    table.add_column("Working For")

    rows = conn.execute("SELECT * FROM agent_status ORDER BY agent_id").fetchall()
    now = datetime.now(timezone.utc)

    for row in rows:
        status = row["status"]
        if status == "working":
            status_text = Text("● working", style="bold green")
            if row["started_working_at"]:
                try:
                    start = datetime.fromisoformat(row["started_working_at"].replace("Z", "+00:00"))
                    secs = int((now - start).total_seconds())
                    working_for = f"{secs // 60}m{secs % 60:02d}s"
                    if secs > 1200:
                        working_for = f"[bold red]{working_for}[/bold red]"
                except (ValueError, OSError):
                    working_for = "-"
            else:
                working_for = "-"
        else:
            status_text = Text("○ idle", style="dim")
            working_for = "-"

        last_active = _format_elapsed(row["last_active"])
        table.add_row(
            row["agent_id"],
            status_text,
            row["current_task"] or "-",
            last_active,
            working_for,
        )

    if not rows:
        table.add_row("[dim]no agents seen yet[/dim]", "", "", "", "")

    return table


def _messages_table(conn: sqlite3.Connection) -> Table:
    table = Table(title="Unread Messages", show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("Route")
    table.add_column("Type")
    table.add_column("Count", justify="right")

    rows = conn.execute(
        """
        SELECT from_agent, to_agent, type, COUNT(*) as cnt
        FROM messages WHERE read_at IS NULL
        GROUP BY from_agent, to_agent, type
        ORDER BY type DESC, cnt DESC
        """
    ).fetchall()

    for row in rows:
        route = f"{row['from_agent']} → {row['to_agent']}"
        msg_type = row["type"]
        count = str(row["cnt"])
        style = "bold red" if msg_type == "escalate" else ""
        table.add_row(route, msg_type, count, style=style)

    if not rows:
        table.add_row("[dim]no unread messages[/dim]", "", "")

    return table


def _tasks_table(conn: sqlite3.Connection) -> Table:
    table = Table(title="Tasks", show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("Task ID")
    table.add_column("Design")
    table.add_column("Impl")
    table.add_column("Status")

    keys = conn.execute(
        "SELECT key FROM shared_state WHERE key LIKE 'doc:%' ORDER BY key"
    ).fetchall()

    task_ids: set[str] = set()
    for (key,) in keys:
        parts = key.split(":")
        if len(parts) == 3:
            task_ids.add(parts[2])

    for task_id in sorted(task_ids):
        has_design = conn.execute(
            "SELECT 1 FROM shared_state WHERE key=?", (f"doc:design:{task_id}",)
        ).fetchone() is not None
        has_impl = conn.execute(
            "SELECT 1 FROM shared_state WHERE key=?", (f"doc:impl:{task_id}",)
        ).fetchone() is not None

        design_cell = "[green]✓[/green]" if has_design else "[dim]—[/dim]"
        impl_cell = "[green]✓[/green]" if has_impl else "[dim]—[/dim]"

        if has_design and has_impl:
            status = "[green]closed[/green]"
        elif has_design:
            status = "[yellow]in progress[/yellow]"
        else:
            status = "[dim]pending[/dim]"

        table.add_row(task_id, design_cell, impl_cell, status)

    if not task_ids:
        table.add_row("[dim]no tasks yet[/dim]", "", "", "")

    return table


def _preview_table(conn: sqlite3.Connection) -> Table:
    table = Table(title="Recent Messages", show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("From")
    table.add_column("To")
    table.add_column("Type")
    table.add_column("Preview")
    table.add_column("Age")

    rows = conn.execute(
        """
        SELECT from_agent, to_agent, type, content, created_at
        FROM messages
        ORDER BY created_at DESC
        LIMIT 5
        """
    ).fetchall()

    for row in rows:
        preview = row["content"][:60].replace("\n", " ")
        if len(row["content"]) > 60:
            preview += "…"
        style = "dim red" if row["type"] == "escalate" else "dim"
        table.add_row(
            row["from_agent"],
            row["to_agent"],
            row["type"],
            preview,
            _format_elapsed(row["created_at"]),
            style=style,
        )

    if not rows:
        table.add_row("[dim]no messages yet[/dim]", "", "", "", "")

    return table


def _stats_view(conn: sqlite3.Connection) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="per_agent"),
        Layout(name="top_tools"),
    )

    agent_table = Table(
        title="Today's Stats (per Agent)",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
    )
    agent_table.add_column("Metric")

    agents = [r[0] for r in conn.execute("SELECT DISTINCT agent_id FROM turn_metrics ORDER BY agent_id").fetchall()]
    if not agents:
        agents = ["agent_a", "agent_b"]

    metrics: dict[str, dict] = {}
    for agent in agents:
        agent_table.add_column(agent, justify="right")
        row = conn.execute(
            """
            SELECT
                COUNT(*) as turns,
                COALESCE(AVG(turn_duration_ms), 0) as avg_dur,
                COALESCE(SUM(input_tokens), 0) as total_in,
                COALESCE(SUM(output_tokens), 0) as total_out
            FROM turn_metrics
            WHERE agent_id=? AND date(timestamp)=date('now')
            """,
            (agent,),
        ).fetchone()
        metrics[agent] = dict(row) if row else {}

    escalations: dict[str, int] = {}
    for agent in agents:
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE to_agent=? AND type='escalate' AND date(created_at)=date('now')",
            (agent,),
        ).fetchone()[0]
        escalations[agent] = count

    def vals(key: str) -> list[str]:
        return [str(metrics.get(a, {}).get(key, 0)) for a in agents]

    def dur_vals() -> list[str]:
        result = []
        for a in agents:
            ms = int(metrics.get(a, {}).get("avg_dur", 0))
            result.append(f"{ms // 1000}s" if ms else "0s")
        return result

    def tok_vals(key: str) -> list[str]:
        return [f"{int(metrics.get(a, {}).get(key, 0)):,}" for a in agents]

    agent_table.add_row("Turns today", *vals("turns"))
    agent_table.add_row("Avg turn duration", *dur_vals())
    agent_table.add_row("Input tokens", *tok_vals("total_in"))
    agent_table.add_row("Output tokens", *tok_vals("total_out"))
    agent_table.add_row("Escalations received", *[str(escalations.get(a, 0)) for a in agents])

    tools_table = Table(
        title="Top 5 Tools Today",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
    )
    tools_table.add_column("Tool")
    tools_table.add_column("Calls", justify="right")
    tools_table.add_column("Avg Latency", justify="right")

    top_tools = conn.execute(
        """
        SELECT tool_name, COUNT(*) as calls, AVG(latency_ms) as avg_ms
        FROM tool_metrics WHERE date(timestamp)=date('now')
        GROUP BY tool_name ORDER BY calls DESC LIMIT 5
        """
    ).fetchall()

    for row in top_tools:
        tools_table.add_row(row["tool_name"], str(row["calls"]), f"{int(row['avg_ms'])}ms")

    if not top_tools:
        tools_table.add_row("[dim]no tool calls yet[/dim]", "", "")

    layout["per_agent"].update(agent_table)
    layout["top_tools"].update(tools_table)
    return layout


def _build_normal_view(conn: sqlite3.Connection) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="top", ratio=2),
        Layout(name="bottom", ratio=3),
    )
    layout["top"].split_row(
        Layout(_agent_status_table(conn), name="status"),
        Layout(_messages_table(conn), name="messages"),
    )
    layout["bottom"].split_row(
        Layout(_tasks_table(conn), name="tasks"),
        Layout(_preview_table(conn), name="preview"),
    )
    return layout


def _build_display() -> Panel:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    keys_hint = "[dim]r[/dim]=refresh  [dim]s[/dim]=stats  [dim]q[/dim]=quit"
    view_label = "[yellow]STATS[/yellow]" if _show_stats.is_set() else "STATUS"
    title = f"[bold]Agent Comms — {view_label}[/bold]  {keys_hint}  [dim]{now_str}[/dim]"

    conn = get_panel_db()
    if conn is None:
        body = Align.center(
            f"[yellow]Waiting for database…[/yellow]\n[dim]{DB_PATH}[/dim]\n\n"
            "Run [bold]python3 init_db.py[/bold] to initialize",
            vertical="middle",
        )
        return Panel(body, title=title, height=20)

    try:
        if _show_stats.is_set():
            content = _stats_view(conn)
        else:
            content = _build_normal_view(conn)
        return Panel(content, title=title)
    except sqlite3.OperationalError as e:
        return Panel(f"[red]DB error: {e}[/red]", title=title)
    finally:
        conn.close()


def main() -> None:
    kb_thread = threading.Thread(target=_keyboard_listener, daemon=True)
    kb_thread.start()

    console = Console()

    with Live(_build_display(), console=console, refresh_per_second=0, screen=False) as live:
        while not _quit_flag.is_set():
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and not _quit_flag.is_set():
                if _force_refresh.is_set():
                    _force_refresh.clear()
                    break
                time.sleep(0.1)
            live.update(_build_display())
            live.refresh()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
