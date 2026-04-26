"""Tests for pure panel query/style helpers — no rich rendering required."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from panel import fetch_unread_counts, _escalate_style
from schema import SCHEMA_DDL


# ---------------------------------------------------------------------------
# fixture: in-memory DB seeded with messages
# ---------------------------------------------------------------------------

@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA_DDL)
    yield c
    c.close()


def _insert_message(conn, from_agent, to_agent, msg_type, content, read=False, created_at=None):
    ts = created_at or "2026-01-01T00:00:00.000Z"
    read_at = "2026-01-01T01:00:00.000Z" if read else None
    conn.execute(
        "INSERT INTO messages (from_agent, to_agent, type, content, created_at, read_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (from_agent, to_agent, msg_type, content, ts, read_at),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# fetch_unread_counts
# ---------------------------------------------------------------------------

class TestFetchUnreadCounts:
    def test_empty_db(self, conn):
        assert fetch_unread_counts(conn) == []

    def test_single_unread(self, conn):
        _insert_message(conn, "a", "b", "task", "do X")
        rows = fetch_unread_counts(conn)
        assert len(rows) == 1
        assert rows[0]["cnt"] == 1
        assert rows[0]["type"] == "task"

    def test_excludes_read_messages(self, conn):
        _insert_message(conn, "a", "b", "task", "done", read=True)
        assert fetch_unread_counts(conn) == []

    def test_groups_by_route_and_type(self, conn):
        _insert_message(conn, "a", "b", "task", "t1")
        _insert_message(conn, "a", "b", "task", "t2")
        _insert_message(conn, "a", "b", "result", "r1")
        rows = fetch_unread_counts(conn)
        task_row = next(r for r in rows if r["type"] == "task")
        result_row = next(r for r in rows if r["type"] == "result")
        assert task_row["cnt"] == 2
        assert result_row["cnt"] == 1

    def test_escalate_sorted_first(self, conn):
        _insert_message(conn, "a", "b", "task", "t")
        _insert_message(conn, "b", "a", "escalate", "blocked")
        rows = fetch_unread_counts(conn)
        assert rows[0]["type"] == "escalate"

    def test_oldest_created_at_is_minimum(self, conn):
        _insert_message(conn, "a", "b", "task", "old", created_at="2026-01-01T00:00:00.000Z")
        _insert_message(conn, "a", "b", "task", "new", created_at="2026-01-01T01:00:00.000Z")
        rows = fetch_unread_counts(conn)
        assert rows[0]["oldest_created_at"] == "2026-01-01T00:00:00.000Z"

    def test_separate_routes_not_grouped(self, conn):
        _insert_message(conn, "a", "b", "task", "for b")
        _insert_message(conn, "a", "c", "task", "for c")
        rows = fetch_unread_counts(conn)
        assert len(rows) == 2

    def test_mixed_read_and_unread(self, conn):
        _insert_message(conn, "a", "b", "task", "read one", read=True)
        _insert_message(conn, "a", "b", "task", "unread one")
        rows = fetch_unread_counts(conn)
        assert rows[0]["cnt"] == 1


# ---------------------------------------------------------------------------
# _escalate_style
# ---------------------------------------------------------------------------

class TestEscalateStyle:
    def _now(self):
        return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def _ts(self, seconds_ago: int) -> str:
        dt = self._now() - timedelta(seconds=seconds_ago)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def test_new_escalate_under_2min(self):
        style, prefix = _escalate_style(self._ts(60), self._now())
        assert style == "bright_red"
        assert prefix == ""

    def test_medium_escalate_2_to_10_min(self):
        style, prefix = _escalate_style(self._ts(300), self._now())
        assert style == "red"
        assert prefix == ""

    def test_stale_escalate_over_10_min(self):
        style, prefix = _escalate_style(self._ts(700), self._now())
        assert style == "bold red"
        assert prefix == "!! "

    def test_boundary_exactly_2_min(self):
        # 120s = exactly 2 min, not yet "medium" (> 120)
        style, prefix = _escalate_style(self._ts(120), self._now())
        assert style == "bright_red"

    def test_boundary_just_over_2_min(self):
        style, prefix = _escalate_style(self._ts(121), self._now())
        assert style == "red"

    def test_boundary_exactly_10_min(self):
        style, prefix = _escalate_style(self._ts(600), self._now())
        assert style == "red"

    def test_boundary_just_over_10_min(self):
        style, prefix = _escalate_style(self._ts(601), self._now())
        assert style == "bold red"

    def test_none_timestamp(self):
        style, prefix = _escalate_style(None, self._now())
        assert style == "red"
        assert prefix == ""

    def test_malformed_timestamp(self):
        style, prefix = _escalate_style("not-a-date", self._now())
        assert style == "red"
