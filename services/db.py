import sqlite3
import threading
from pathlib import Path
import services.util as u
import services.logger as log

l = log.get_logger()

class MessageDB:
    """Handles mapping of message IDs between different platforms."""

    def __init__(self):
        self._local = threading.local()
        self._db_path = Path(u.get_data_path()) / "messages.db"
        self._init_db()

    def _get_conn(self):
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self._db_path)
        return self._local.conn

    def _init_db(self):
        """Create tables for message mapping."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()
        cursor = conn.cursor()
        # bridge_id is a unique identifier for a single cross-platform message group
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_mappings (
                bridge_id TEXT,
                instance_id TEXT,
                channel_id TEXT,
                platform_msg_id TEXT,
                PRIMARY KEY (instance_id, platform_msg_id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bridge_id ON message_mappings (bridge_id)")
        conn.commit()

    def save_mapping(self, bridge_id: str, instance_id: str, channel_id: str, platform_msg_id: str):
        """Store a mapping between a bridge ID and a platform-specific message ID."""
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO message_mappings (bridge_id, instance_id, channel_id, platform_msg_id)
                VALUES (?, ?, ?, ?)
            """, (bridge_id, instance_id, channel_id, platform_msg_id))
            conn.commit()
        except Exception as e:
            l.error(f"Failed to save message mapping: {e}")

    def get_bridge_id(self, instance_id: str, platform_msg_id: str) -> str | None:
        """Find the bridge ID for a given platform-specific message ID."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT bridge_id FROM message_mappings
            WHERE instance_id = ? AND platform_msg_id = ?
        """, (instance_id, platform_msg_id))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_platform_msg_id(self, bridge_id: str, instance_id: str, channel_id: str | None = None) -> str | None:
        """Find the platform-specific message ID for a given bridge ID and target instance."""
        conn = self._get_conn()
        cursor = conn.cursor()
        if channel_id:
            cursor.execute("""
                SELECT platform_msg_id FROM message_mappings
                WHERE bridge_id = ? AND instance_id = ? AND channel_id = ?
            """, (bridge_id, instance_id, channel_id))
        else:
            cursor.execute("""
                SELECT platform_msg_id FROM message_mappings
                WHERE bridge_id = ? AND instance_id = ?
            """, (bridge_id, instance_id))
        row = cursor.fetchone()
        return row[0] if row else None

# Shared singleton
msg_db = MessageDB()
