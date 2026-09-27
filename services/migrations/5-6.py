# v0.6: Add metrics_counters table for persisted metric snapshots.
from sqlalchemy.engine import Connection


def upgrade(conn: Connection, dialect_name: str = "") -> None:
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS metrics_counters (
            name TEXT NOT NULL,
            labels TEXT NOT NULL,
            value REAL NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (name, labels)
        )
        """
    )
