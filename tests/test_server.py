import json
import sqlite3
import pytest
import server


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _rows(db_path: str, table: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
    conn.close()
    return rows


def _agent_status(db_path: str, agent_id: str) -> dict | None:
    rows = _rows(db_path, "agent_status")
    return next((r for r in rows if r["agent_id"] == agent_id), None)


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------

class TestSendMessage:
    async def test_valid_task(self, db_path):
        result = json.loads(await server.send_message("a", "b", "task", "do X", "t1"))
        assert result["ok"] is True
        assert isinstance(result["message_id"], int)

        msgs = _rows(db_path, "messages")
        assert len(msgs) == 1
        assert msgs[0]["type"] == "task"
        assert msgs[0]["content"] == "do X"
        assert msgs[0]["task_id"] == "t1"
        assert msgs[0]["read_at"] is None

    async def test_valid_result(self, db_path):
        result = json.loads(await server.send_message("b", "a", "result", "done"))
        assert result["ok"] is True

    async def test_valid_escalate(self, db_path):
        result = json.loads(await server.send_message("b", "a", "escalate", "blocked"))
        assert result["ok"] is True

    async def test_invalid_type(self, db_path):
        result = json.loads(await server.send_message("a", "b", "gossip", "hello"))
        assert "error" in result
        assert _rows(db_path, "messages") == []

    async def test_sets_agent_working(self, db_path):
        await server.send_message("alice", "bob", "task", "hi")
        status = _agent_status(db_path, "alice")
        assert status is not None
        assert status["status"] == "working"


# ---------------------------------------------------------------------------
# read_messages
# ---------------------------------------------------------------------------

class TestReadMessages:
    async def test_returns_unread_by_default(self, db_path):
        await server.send_message("a", "b", "task", "msg1")
        await server.send_message("a", "b", "task", "msg2")

        result = json.loads(await server.read_messages("b"))
        assert len(result) == 2

    async def test_unread_only_skips_read(self, db_path):
        r = json.loads(await server.send_message("a", "b", "task", "msg1"))
        msg_id = r["message_id"]
        await server.mark_messages_read("b", [msg_id])

        result = json.loads(await server.read_messages("b", unread_only=True))
        assert result == []

    async def test_unread_false_includes_read(self, db_path):
        r = json.loads(await server.send_message("a", "b", "task", "msg1"))
        await server.mark_messages_read("b", [r["message_id"]])

        result = json.loads(await server.read_messages("b", unread_only=False))
        assert len(result) == 1

    async def test_limit_respected(self, db_path):
        for i in range(5):
            await server.send_message("a", "b", "task", f"msg{i}")

        result = json.loads(await server.read_messages("b", limit=3))
        assert len(result) == 3

    async def test_only_own_messages(self, db_path):
        await server.send_message("a", "b", "task", "for b")
        await server.send_message("a", "c", "task", "for c")

        result = json.loads(await server.read_messages("b"))
        assert all(m["to_agent"] == "b" for m in result)
        assert len(result) == 1

    async def test_newest_first(self, db_path):
        await server.send_message("a", "b", "task", "first")
        await server.send_message("a", "b", "task", "second")

        result = json.loads(await server.read_messages("b"))
        assert result[0]["content"] == "second"


# ---------------------------------------------------------------------------
# mark_messages_read
# ---------------------------------------------------------------------------

class TestMarkMessagesRead:
    async def test_marks_own_messages(self, db_path):
        r = json.loads(await server.send_message("a", "b", "task", "hi"))
        msg_id = r["message_id"]

        result = json.loads(await server.mark_messages_read("b", [msg_id]))
        assert result["marked"] == 1

        msgs = _rows(db_path, "messages")
        assert msgs[0]["read_at"] is not None

    async def test_ignores_other_agents_messages(self, db_path):
        r = json.loads(await server.send_message("a", "b", "task", "for b"))
        msg_id = r["message_id"]

        # c tries to mark b's message
        result = json.loads(await server.mark_messages_read("c", [msg_id]))
        assert result["marked"] == 0

        msgs = _rows(db_path, "messages")
        assert msgs[0]["read_at"] is None

    async def test_empty_list(self, db_path):
        result = json.loads(await server.mark_messages_read("b", []))
        assert result["ok"] is True
        assert result["marked"] == 0

    async def test_nonexistent_id(self, db_path):
        result = json.loads(await server.mark_messages_read("b", [9999]))
        assert result["marked"] == 0

    async def test_partial_match(self, db_path):
        r1 = json.loads(await server.send_message("a", "b", "task", "one"))
        r2 = json.loads(await server.send_message("a", "b", "task", "two"))
        await server.mark_messages_read("b", [r1["message_id"]])

        result = json.loads(await server.mark_messages_read("b", [r1["message_id"], r2["message_id"]]))
        # r1 already read — UPDATE WHERE read_at IS NULL would skip it, but
        # our query doesn't filter on read_at, so both match; r1 gets
        # re-stamped. rowcount == 2.
        assert result["marked"] == 2


# ---------------------------------------------------------------------------
# shared state
# ---------------------------------------------------------------------------

class TestSharedState:
    async def test_set_and_get(self, db_path):
        await server.set_shared_state("doc:design:t1", '{"spec": 1}', "agent_a")
        result = json.loads(await server.get_shared_state("doc:design:t1"))
        assert result["value"] == '{"spec": 1}'
        assert result["updated_by"] == "agent_a"

    async def test_upsert(self, db_path):
        await server.set_shared_state("k", "v1", "a")
        await server.set_shared_state("k", "v2", "b")
        result = json.loads(await server.get_shared_state("k"))
        assert result["value"] == "v2"
        assert result["updated_by"] == "b"

    async def test_get_missing_key(self, db_path):
        result = json.loads(await server.get_shared_state("no-such-key"))
        assert "error" in result

    async def test_list_all(self, db_path):
        await server.set_shared_state("doc:design:t1", "d1", "a")
        await server.set_shared_state("doc:impl:t1", "i1", "b")
        result = json.loads(await server.list_shared_state())
        keys = [r["key"] for r in result]
        assert "doc:design:t1" in keys
        assert "doc:impl:t1" in keys

    async def test_list_with_prefix(self, db_path):
        await server.set_shared_state("doc:design:t1", "d", "a")
        await server.set_shared_state("doc:impl:t1", "i", "a")
        await server.set_shared_state("other:key", "o", "a")
        result = json.loads(await server.list_shared_state(prefix="doc:design"))
        keys = [r["key"] for r in result]
        assert keys == ["doc:design:t1"]


# ---------------------------------------------------------------------------
# turn metrics
# ---------------------------------------------------------------------------

class TestTurnMetrics:
    async def test_start_returns_turn_id(self, db_path):
        result = json.loads(await server.report_turn_start("a", "claude-opus-4-7", "t1"))
        assert "turn_id" in result
        assert isinstance(result["turn_id"], int)

    async def test_end_updates_row(self, db_path):
        r = json.loads(await server.report_turn_start("a", "claude-opus-4-7"))
        turn_id = r["turn_id"]

        result = json.loads(await server.report_turn_end("a", turn_id, 100, 200))
        assert result["ok"] is True

        turns = _rows(db_path, "turn_metrics")
        t = turns[0]
        assert t["input_tokens"] == 100
        assert t["output_tokens"] == 200
        assert t["turn_duration_ms"] is not None
        assert t["turn_duration_ms"] >= 0

    async def test_end_rejects_wrong_agent(self, db_path):
        r = json.loads(await server.report_turn_start("a", "claude-opus-4-7"))
        turn_id = r["turn_id"]

        result = json.loads(await server.report_turn_end("b", turn_id, 1, 1))
        assert result["ok"] is False

    async def test_end_rejects_nonexistent_turn(self, db_path):
        result = json.loads(await server.report_turn_end("a", 9999, 1, 1))
        assert result["ok"] is False

    async def test_context_tokens_stored(self, db_path):
        await server.report_turn_start("a", "claude-opus-4-7", context_tokens=4096)
        turns = _rows(db_path, "turn_metrics")
        assert turns[0]["context_tokens"] == 4096

    async def test_end_does_not_change_status(self, db_path):
        r = json.loads(await server.report_turn_start("a", "claude-opus-4-7"))
        # Manually set idle so we can verify end doesn't overwrite it
        await server.report_idle("a")
        status_before = _agent_status(db_path, "a")["status"]
        assert status_before == "idle"

        await server.report_turn_end("a", r["turn_id"], 10, 20)
        status_after = _agent_status(db_path, "a")["status"]
        assert status_after == "idle"


# ---------------------------------------------------------------------------
# report_idle
# ---------------------------------------------------------------------------

class TestReportIdle:
    async def test_sets_idle(self, db_path):
        await server.send_message("a", "b", "task", "work")  # sets a to working
        assert _agent_status(db_path, "a")["status"] == "working"

        result = json.loads(await server.report_idle("a"))
        assert result["ok"] is True
        assert _agent_status(db_path, "a")["status"] == "idle"

    async def test_clears_current_task(self, db_path):
        await server.report_turn_start("a", "claude-opus-4-7", task_id="t42")
        assert _agent_status(db_path, "a")["current_task"] == "t42"

        await server.report_idle("a")
        assert _agent_status(db_path, "a")["current_task"] is None

    async def test_updates_last_active(self, db_path):
        await server.send_message("a", "b", "task", "x")
        before = _agent_status(db_path, "a")["last_active"]

        await server.report_idle("a")
        after = _agent_status(db_path, "a")["last_active"]
        assert after >= before


# ---------------------------------------------------------------------------
# agent_status side effects
# ---------------------------------------------------------------------------

class TestAgentStatusSideEffects:
    async def test_send_message_sets_working(self, db_path):
        await server.send_message("agent_x", "agent_y", "task", "go")
        assert _agent_status(db_path, "agent_x")["status"] == "working"

    async def test_read_messages_sets_working(self, db_path):
        await server.read_messages("agent_x")
        assert _agent_status(db_path, "agent_x")["status"] == "working"

    async def test_set_shared_state_sets_working(self, db_path):
        await server.set_shared_state("k", "v", "agent_x")
        assert _agent_status(db_path, "agent_x")["status"] == "working"

    async def test_started_working_at_set_on_first_working(self, db_path):
        await server.send_message("a", "b", "task", "x")
        s = _agent_status(db_path, "a")
        assert s["started_working_at"] is not None

    async def test_started_working_at_not_reset_while_working(self, db_path):
        await server.send_message("a", "b", "task", "x")
        first = _agent_status(db_path, "a")["started_working_at"]

        await server.send_message("a", "b", "task", "y")
        second = _agent_status(db_path, "a")["started_working_at"]
        assert first == second

    async def test_started_working_at_resets_after_idle(self, db_path):
        await server.send_message("a", "b", "task", "x")
        await server.report_idle("a")
        await server.send_message("a", "b", "task", "y")
        after = _agent_status(db_path, "a")["started_working_at"]
        assert after is not None


# ---------------------------------------------------------------------------
# tool_metrics
# ---------------------------------------------------------------------------

class TestToolMetrics:
    async def test_send_message_records_metric(self, db_path):
        await server.send_message("a", "b", "task", "hi")
        metrics = _rows(db_path, "tool_metrics")
        tools = [m["tool_name"] for m in metrics]
        assert "send_message" in tools

    async def test_latency_is_non_negative(self, db_path):
        await server.send_message("a", "b", "task", "hi")
        metrics = _rows(db_path, "tool_metrics")
        assert all(m["latency_ms"] >= 0 for m in metrics)

    async def test_each_tool_call_appends_row(self, db_path):
        await server.send_message("a", "b", "task", "1")
        await server.send_message("a", "b", "task", "2")
        metrics = [m for m in _rows(db_path, "tool_metrics") if m["tool_name"] == "send_message"]
        assert len(metrics) == 2

    async def test_context_token_count_stored(self, db_path):
        server._record_tool_metric("a", "mytool", 10, context_token_count=512)
        metrics = _rows(db_path, "tool_metrics")
        assert metrics[-1]["context_token_count"] == 512
