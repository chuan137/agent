#!/usr/bin/env python3
import os
import pathlib
import sqlite3

from schema import SCHEMA_DDL

DB_PATH = os.environ.get("AGENT_DB_PATH", "/home/chuan/mcp/data/agent_comms.db")


def init_db(db_path: str = DB_PATH) -> None:
    pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_DDL)
    conn.close()
    print(f"Database initialized at {db_path}")


if __name__ == "__main__":
    init_db()
