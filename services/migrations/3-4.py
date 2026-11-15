from __future__ import annotations

# v0.4: Add avatar_url column to user_mappings.
from sqlalchemy.engine import Connection


def _sqlite_has_column(conn: Connection, table: str, column: str) -> bool:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return any(str(row[1]) == column for row in rows)


def upgrade(conn: Connection, dialect_name: str = "") -> None:
    if dialect_name == "sqlite":
        if _sqlite_has_column(conn, "user_mappings", "avatar_url"):
            return
        conn.exec_driver_sql(
            "ALTER TABLE user_mappings ADD COLUMN avatar_url TEXT NULL"
        )
        return

    if dialect_name == "postgresql":
        conn.exec_driver_sql(
            "ALTER TABLE user_mappings ADD COLUMN IF NOT EXISTS avatar_url TEXT NULL"
        )
        return

    from sqlalchemy import inspect

    insp = inspect(conn)
    cols = [c["name"] for c in insp.get_columns("user_mappings")]
    if "avatar_url" not in cols:
        conn.exec_driver_sql(
            "ALTER TABLE user_mappings ADD COLUMN avatar_url TEXT NULL"
        )
