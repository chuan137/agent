#!/usr/bin/env bash
# Start or attach to the dual-agent tmux session.
# Windows: agent_a | agent_b | status (read-only dashboard)
set -euo pipefail

SESSION="agent-comms"
DIR="$(cd "$(dirname "$0")" && pwd)"
DB_PATH="${AGENT_DB_PATH:-$DIR/data/agent_comms.db}"

export AGENT_DB_PATH="$DB_PATH"

# Initialize the database if it doesn't exist yet.
if [ ! -f "$DB_PATH" ]; then
  uv run --project "$DIR" agent-comms-init-db
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Session '$SESSION' already exists — attaching."
  tmux attach-session -t "$SESSION"
  exit 0
fi

# Create session with first window: agent_a
tmux new-session -d -s "$SESSION" -n "agent_a" -x 220 -y 50

# agent_a: launch Claude Code (user starts it manually after attach)
tmux send-keys -t "$SESSION:agent_a" \
  "export AGENT_DB_PATH='$DB_PATH'" Enter
tmux send-keys -t "$SESSION:agent_a" \
  "# Run: claude  (then configure MCP via /mcp or settings)" ""

# Window 2: agent_b
tmux new-window -t "$SESSION" -n "agent_b"
tmux send-keys -t "$SESSION:agent_b" \
  "export AGENT_DB_PATH='$DB_PATH'" Enter
tmux send-keys -t "$SESSION:agent_b" \
  "# Run: claude  (then configure MCP via /mcp or settings)" ""

# Window 3: status dashboard (starts immediately)
tmux new-window -t "$SESSION" -n "status"
tmux send-keys -t "$SESSION:status" \
  "export AGENT_DB_PATH='$DB_PATH' && uv run --project '$DIR' agent-comms-panel" Enter

# Focus agent_a on attach
tmux select-window -t "$SESSION:agent_a"

echo "Attaching to session '$SESSION'  (Ctrl-b d to detach)"
tmux attach-session -t "$SESSION"
