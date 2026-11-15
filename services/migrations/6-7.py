# v0.7: Retain a creation timestamp for bounded message mapping cleanup.
import time

from sqlalchemy.engine import Connection


def upgrade(conn: Connection, dialect_name: str = "") -> None:
    if dialect_name == "sqlite":
        columns = {
            row[1]
            for row in conn.exec_driver_sql(
                "PRAGMA table_info(message_mappings)"
            ).fetchall()
        }
        if "created_at" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE message_mappings ADD COLUMN created_at INTEGER NOT NULL DEFAULT 0"
            )
    else:
        conn.exec_driver_sql(
            "ALTER TABLE message_mappings ADD COLUMN IF NOT EXISTS created_at INTEGER NOT NULL DEFAULT 0"
        )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_message_mappings_created_at ON message_mappings (created_at)"
    )
    conn.exec_driver_sql(
        f"UPDATE message_mappings SET created_at = {int(time.time())} WHERE created_at = 0"
    )
