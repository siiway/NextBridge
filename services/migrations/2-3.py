from __future__ import annotations

# v0.3: Remove obsolete token columns from forward page/asset tables.

from sqlalchemy.engine import Connection


def _sqlite_has_column(conn: Connection, table: str, column: str) -> bool:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return any(str(row[1]) == column for row in rows)


def _sqlite_drop_token_forward_pages(conn: Connection) -> None:
    if not _sqlite_has_column(conn, "forward_pages", "token"):
        return

    conn.exec_driver_sql(
        """
        CREATE TABLE forward_pages__new (
            page_id TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL,
            html_content TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            destroyed_at INTEGER NULL
        )
        """
    )
    conn.exec_driver_sql(
        """
        INSERT INTO forward_pages__new
            (page_id, instance_id, html_content, created_at, expires_at, destroyed_at)
        SELECT
            page_id, instance_id, html_content, created_at, expires_at, destroyed_at
        FROM forward_pages
        """
    )
    conn.exec_driver_sql("DROP TABLE forward_pages")
    conn.exec_driver_sql("ALTER TABLE forward_pages__new RENAME TO forward_pages")
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_forward_pages_instance_id ON forward_pages (instance_id)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_forward_pages_expires_at ON forward_pages (expires_at)"
    )


def _sqlite_drop_token_forward_assets(conn: Connection) -> None:
    if not _sqlite_has_column(conn, "forward_assets", "token"):
        return

    conn.exec_driver_sql(
        """
        CREATE TABLE forward_assets__new (
            asset_id TEXT PRIMARY KEY,
            page_id TEXT NOT NULL,
            instance_id TEXT NOT NULL,
            mime TEXT NOT NULL,
            data BLOB NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NULL
        )
        """
    )
    conn.exec_driver_sql(
        """
        INSERT INTO forward_assets__new
            (asset_id, page_id, instance_id, mime, data, created_at, expires_at)
        SELECT
            asset_id, page_id, instance_id, mime, data, created_at, expires_at
        FROM forward_assets
        """
    )
    conn.exec_driver_sql("DROP TABLE forward_assets")
    conn.exec_driver_sql("ALTER TABLE forward_assets__new RENAME TO forward_assets")
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_forward_assets_page_id ON forward_assets (page_id)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_forward_assets_expires_at ON forward_assets (expires_at)"
    )


def upgrade(conn: Connection, dialect_name: str = "") -> None:
    if dialect_name == "sqlite":
        _sqlite_drop_token_forward_pages(conn)
        _sqlite_drop_token_forward_assets(conn)
        return

    # Standard SQL path for PostgreSQL/MySQL-like dialects.
    conn.exec_driver_sql("ALTER TABLE forward_pages DROP COLUMN token")
    conn.exec_driver_sql("ALTER TABLE forward_assets DROP COLUMN token")
