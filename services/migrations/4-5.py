# v0.5: Add mention_notify_prefs table for per-user notification preferences.
from sqlalchemy.engine import Connection


def upgrade(conn: Connection, dialect_name: str = "") -> None:
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS mention_notify_prefs (
            global_user_id TEXT PRIMARY KEY NOT NULL,
            mode TEXT NOT NULL DEFAULT 'all',
            platforms TEXT
        )
        """
    )
