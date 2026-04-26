import os
import sys
import tempfile
import pytest

# Ensure project root is on the path so `import server` and `import schema` work.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def db_path(tmp_path):
    """Return a fresh temp DB path and wire server.py to use it."""
    import server

    path = str(tmp_path / "test.db")
    server.DB_PATH = path
    server._reset_connection()
    yield path
    server._reset_connection()
