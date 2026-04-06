from __future__ import annotations

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, Text


metadata = MetaData()

forward_pages = Table(
    "forward_pages",
    metadata,
    Column("page_id", String, primary_key=True),
    Column("instance_id", String, nullable=False),
    Column("token", String, nullable=False),
    Column("html_content", Text, nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("expires_at", Integer, nullable=False),
    Column("destroyed_at", Integer, nullable=True),
)


def upgrade(conn, dialect_name: str = "") -> None:
    """Create the forward page storage used by merged-forward rendering."""
    forward_pages.create(bind=conn, checkfirst=True)
    Index(
        "idx_forward_pages_instance_id",
        forward_pages.c.instance_id,
    ).create(bind=conn, checkfirst=True)
    Index(
        "idx_forward_pages_expires_at",
        forward_pages.c.expires_at,
    ).create(bind=conn, checkfirst=True)
