from __future__ import annotations

# v0.3: create `forward_assets` table and related indices.

from sqlalchemy import Column, Index, Integer, LargeBinary, MetaData, String, Table


metadata = MetaData()

forward_assets = Table(
    "forward_assets",
    metadata,
    Column("asset_id", String, primary_key=True),
    Column("page_id", String, nullable=False),
    Column("instance_id", String, nullable=False),
    Column("token", String, nullable=False),
    Column("mime", String, nullable=False),
    Column("data", LargeBinary, nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("expires_at", Integer, nullable=True),
)


def upgrade(conn, dialect_name: str = "") -> None:
    """Create DB-backed forward asset cache table and indices."""
    forward_assets.create(bind=conn, checkfirst=True)
    Index(
        "idx_forward_assets_page_id",
        forward_assets.c.page_id,
    ).create(bind=conn, checkfirst=True)
    Index(
        "idx_forward_assets_expires_at",
        forward_assets.c.expires_at,
    ).create(bind=conn, checkfirst=True)
