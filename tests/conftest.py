import pytest
import agent_comms_mcp.server as server


@pytest.fixture()
def db_path(tmp_path):
    """Return a fresh temp DB path and wire server.py to use it."""
    original_path = server.DB_PATH
    path = str(tmp_path / "test.db")
    server.DB_PATH = path
    server._reset_connection()
    yield path
    server._reset_connection()
    server.DB_PATH = original_path
