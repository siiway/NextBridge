import sqlite3
import threading
import uuid
from pathlib import Path
import services.util as u
import services.logger as log

logger = log.get_logger()


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
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_bridge_id ON message_mappings (bridge_id)"
        )

        # Map display names/IDs across instances
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_mappings (
                instance_id TEXT,
                platform_user_id TEXT,
                display_name TEXT,
                PRIMARY KEY (instance_id, platform_user_id)
            )
        """)

        # Binding codes (temporary TOTP-like codes)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS binding_codes (
                code TEXT PRIMARY KEY,
                instance_id TEXT,
                platform_user_id TEXT,
                expires_at INTEGER
            )
        """)

        # Permanent user bindings (linked accounts)
        # global_user_id links multiple (instance_id, platform_user_id)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_bindings (
                global_user_id TEXT,
                instance_id TEXT,
                platform_user_id TEXT,
                PRIMARY KEY (instance_id, platform_user_id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_global_user ON user_bindings (global_user_id)"
        )
        conn.commit()

    def create_binding_code(
        self, code: str, instance_id: str, platform_user_id: str, ttl: int = 300
    ):
        """Create a temporary binding code."""
        conn = self._get_conn()
        cursor = conn.cursor()
        import time

        expires_at = int(time.time()) + ttl
        cursor.execute(
            "INSERT OR REPLACE INTO binding_codes (code, instance_id, platform_user_id, expires_at) VALUES (?, ?, ?, ?)",
            (code, instance_id, platform_user_id, expires_at),
        )
        conn.commit()

    def consume_binding_code(
        self, code: str, target_instance: str, target_user_id: str
    ) -> bool:
        """Verify and consume a binding code, creating a permanent link."""
        conn = self._get_conn()
        cursor = conn.cursor()
        import time

        now = int(time.time())

        # Find valid code
        cursor.execute(
            "SELECT instance_id, platform_user_id FROM binding_codes WHERE code = ? AND expires_at > ?",
            (code, now),
        )
        row = cursor.fetchone()
        if not row:
            return False

        src_inst, src_uid = row

        # Delete code
        cursor.execute("DELETE FROM binding_codes WHERE code = ?", (code,))

        # Find or create global_user_id
        cursor.execute(
            "SELECT global_user_id FROM user_bindings WHERE (instance_id = ? AND platform_user_id = ?) OR (instance_id = ? AND platform_user_id = ?)",
            (src_inst, src_uid, target_instance, target_user_id),
        )
        rows = cursor.fetchall()

        global_id = rows[0][0] if rows else str(uuid.uuid4())

        # Save bindings
        cursor.execute(
            "INSERT OR REPLACE INTO user_bindings (global_user_id, instance_id, platform_user_id) VALUES (?, ?, ?)",
            (global_id, src_inst, src_uid),
        )
        cursor.execute(
            "INSERT OR REPLACE INTO user_bindings (global_user_id, instance_id, platform_user_id) VALUES (?, ?, ?)",
            (global_id, target_instance, target_user_id),
        )
        conn.commit()
        return True

    def get_bound_user_id(
        self, source_instance: str, source_user_id: str, target_instance: str
    ) -> str | None:
        """Find the target user ID explicitly bound to a source user ID."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT b2.platform_user_id FROM user_bindings b1
            JOIN user_bindings b2 ON b1.global_user_id = b2.global_user_id
            WHERE b1.instance_id = ? AND b1.platform_user_id = ? AND b2.instance_id = ?
        """,
            (source_instance, source_user_id, target_instance),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def remove_user_binding(
        self,
        instance_id: str,
        platform_user_id: str,
        target_instance_id: str | None = None,
    ) -> bool:
        """Remove bindings. If target_instance_id is set, only remove that one. Otherwise remove all."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT global_user_id FROM user_bindings WHERE instance_id = ? AND platform_user_id = ?",
            (instance_id, platform_user_id),
        )
        row = cursor.fetchone()
        if not row:
            return False

        global_id = row[0]
        if target_instance_id:
            cursor.execute(
                "DELETE FROM user_bindings WHERE global_user_id = ? AND instance_id = ?",
                (global_id, target_instance_id),
            )
        else:
            cursor.execute(
                "DELETE FROM user_bindings WHERE global_user_id = ?", (global_id,)
            )
        conn.commit()
        return True

    def get_all_bindings(
        self, instance_id: str, platform_user_id: str
    ) -> list[tuple[str, str]]:
        """Return all (instance_id, platform_user_id) linked to this account."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT global_user_id FROM user_bindings WHERE instance_id = ? AND platform_user_id = ?",
            (instance_id, platform_user_id),
        )
        row = cursor.fetchone()
        if not row:
            return []

        global_id = row[0]
        cursor.execute(
            "SELECT instance_id, platform_user_id FROM user_bindings WHERE global_user_id = ?",
            (global_id,),
        )
        return cursor.fetchall()

    def save_user(self, instance_id: str, platform_user_id: str, display_name: str):
        """Store or update a user's display name for an instance."""
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO user_mappings (instance_id, platform_user_id, display_name)
                VALUES (?, ?, ?)
            """,
                (instance_id, platform_user_id, display_name),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to save user mapping: {e}")

    def get_user_name(self, instance_id: str, platform_user_id: str) -> str | None:
        """Find a platform-specific display name by their user ID."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT display_name FROM user_mappings
            WHERE instance_id = ? AND platform_user_id = ?
        """,
            (instance_id, platform_user_id),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_user_id_by_name(self, instance_id: str, display_name: str) -> str | None:
        """Find a platform-specific user ID by their display name on that instance."""
        conn = self._get_conn()
        cursor = conn.cursor()
        # Try exact match first
        cursor.execute(
            """
            SELECT platform_user_id FROM user_mappings
            WHERE instance_id = ? AND display_name = ?
        """,
            (instance_id, display_name),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_mapped_user_id(
        self, source_instance: str, source_user_id: str, target_instance: str
    ) -> str | None:
        """Find the target user ID mapped from a source user ID via display name."""
        conn = self._get_conn()
        cursor = conn.cursor()
        # 1. Get source display name
        cursor.execute(
            "SELECT display_name FROM user_mappings WHERE instance_id = ? AND platform_user_id = ?",
            (source_instance, source_user_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        name = row[0]
        # 2. Find target ID with same name
        return self.get_user_id_by_name(target_instance, name)

    def save_mapping(
        self, bridge_id: str, instance_id: str, channel_id: str, platform_msg_id: str
    ):
        """Store a mapping between a bridge ID and a platform-specific message ID."""
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO message_mappings (bridge_id, instance_id, channel_id, platform_msg_id)
                VALUES (?, ?, ?, ?)
            """,
                (bridge_id, instance_id, channel_id, platform_msg_id),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to save message mapping: {e}")

    def get_bridge_id(self, instance_id: str, platform_msg_id: str) -> str | None:
        """Find the bridge ID for a given platform-specific message ID."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT bridge_id FROM message_mappings
            WHERE instance_id = ? AND platform_msg_id = ?
        """,
            (instance_id, platform_msg_id),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_platform_msg_id(
        self, bridge_id: str, instance_id: str, channel_id: str | None = None
    ) -> str | None:
        """Find the platform-specific message ID for a given bridge ID and target instance."""
        conn = self._get_conn()
        cursor = conn.cursor()
        if channel_id:
            cursor.execute(
                """
                SELECT platform_msg_id FROM message_mappings
                WHERE bridge_id = ? AND instance_id = ? AND channel_id = ?
            """,
                (bridge_id, instance_id, channel_id),
            )
        else:
            cursor.execute(
                """
                SELECT platform_msg_id FROM message_mappings
                WHERE bridge_id = ? AND instance_id = ?
            """,
                (bridge_id, instance_id),
            )
        row = cursor.fetchone()
        return row[0] if row else None


# Shared singleton
msg_db = MessageDB()
