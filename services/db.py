import time
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Column,
    Index,
    Integer,
    String,
    create_engine,
    delete,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session

import services.util as u
import services.logger as log
import services.config as config

logger = log.get_logger()


class _Base(DeclarativeBase):
    pass


class MessageMapping(_Base):
    __tablename__ = "message_mappings"
    bridge_id = Column(String, nullable=False)
    instance_id = Column(String, primary_key=True)
    channel_id = Column(String, nullable=False)
    platform_msg_id = Column(String, primary_key=True)


Index("idx_bridge_id", MessageMapping.bridge_id)


class UserMapping(_Base):
    __tablename__ = "user_mappings"
    instance_id = Column(String, primary_key=True)
    platform_user_id = Column(String, primary_key=True)
    display_name = Column(String, nullable=False)


class BindingCode(_Base):
    __tablename__ = "binding_codes"
    code = Column(String, primary_key=True)
    instance_id = Column(String, nullable=False)
    platform_user_id = Column(String, nullable=False)
    expires_at = Column(Integer, nullable=False)


class UserBinding(_Base):
    __tablename__ = "user_bindings"
    global_user_id = Column(String, nullable=False)
    instance_id = Column(String, primary_key=True)
    platform_user_id = Column(String, primary_key=True)


Index("idx_global_user", UserBinding.global_user_id)


class MessageDB:
    """Handles mapping of message IDs between different platforms."""

    def __init__(self, engine: Optional[Engine] = None):
        """Initialize the database handler.

        Args:
            engine: Optional SQLAlchemy engine. If not provided, will be created from config.
        """
        self._engine = engine or self._create_engine_from_config()
        _Base.metadata.create_all(self._engine)

    @staticmethod
    def _create_engine_from_config() -> Engine:
        """Create a SQLAlchemy engine from the global configuration.

        Returns:
            SQLAlchemy Engine instance configured according to database settings.
        """
        db_config: dict = config.get("database", {})
        url = db_config.get("url", "sqlite:///data/messages.db")

        # Handle SQLite relative paths
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            # Convert relative path to absolute path
            db_path = url.replace("sqlite:///", "")
            if not Path(db_path).is_absolute():
                data_path = Path(u.get_data_path())
                db_path = data_path / db_path
                db_path.parent.mkdir(parents=True, exist_ok=True)
                url = f"sqlite:///{db_path}"

        # Build engine kwargs from config
        engine_kwargs = {"echo": db_config.get("echo", False)}

        # SQLite-specific settings
        if url.startswith("sqlite:///"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}

        # Pool settings for non-SQLite databases
        else:
            if "pool_size" in db_config:
                engine_kwargs["pool_size"] = db_config["pool_size"]
            if "max_overflow" in db_config:
                engine_kwargs["max_overflow"] = db_config["max_overflow"]
            if "pool_recycle" in db_config:
                engine_kwargs["pool_recycle"] = db_config["pool_recycle"]

        logger.info(f"Initializing database engine: {url.split('://')[0]}")
        return create_engine(url, **engine_kwargs)

    def _session(self) -> Session:
        return Session(self._engine)

    # ------------------------------------------------------------------
    # Binding codes
    # ------------------------------------------------------------------

    def create_binding_code(
        self, code: str, instance_id: str, platform_user_id: str, ttl: int = 300
    ):
        """Create a temporary binding code."""
        expires_at = int(time.time()) + ttl
        with self._session() as s:
            s.merge(
                BindingCode(
                    code=code,
                    instance_id=instance_id,
                    platform_user_id=platform_user_id,
                    expires_at=expires_at,
                )
            )
            s.commit()

    def consume_binding_code(
        self, code: str, target_instance: str, target_user_id: str
    ) -> bool:
        """Verify and consume a binding code, creating a permanent link."""
        now = int(time.time())
        with self._session() as s:
            row = s.execute(
                select(BindingCode).where(
                    BindingCode.code == code,
                    BindingCode.expires_at > now,
                )
            ).scalar_one_or_none()
            if row is None:
                return False

            src_inst = row.instance_id
            src_uid = row.platform_user_id

            s.execute(delete(BindingCode).where(BindingCode.code == code))

            existing = (
                s.execute(
                    select(UserBinding).where(
                        (
                            (UserBinding.instance_id == src_inst)
                            & (UserBinding.platform_user_id == src_uid)
                        )
                        | (
                            (UserBinding.instance_id == target_instance)
                            & (UserBinding.platform_user_id == target_user_id)
                        )
                    )
                )
                .scalars()
                .first()
            )

            global_id = existing.global_user_id if existing else str(uuid.uuid4())

            s.merge(
                UserBinding(
                    global_user_id=global_id,
                    instance_id=src_inst,
                    platform_user_id=src_uid,
                )
            )
            s.merge(
                UserBinding(
                    global_user_id=global_id,
                    instance_id=target_instance,
                    platform_user_id=target_user_id,
                )
            )
            s.commit()
        return True

    # ------------------------------------------------------------------
    # User bindings
    # ------------------------------------------------------------------

    def get_bound_user_id(
        self, source_instance: str, source_user_id: str, target_instance: str
    ) -> str | None:
        """Find the target user ID explicitly bound to a source user ID."""
        with self._session() as s:
            b1 = UserBinding.__table__.alias("b1")
            b2 = UserBinding.__table__.alias("b2")
            stmt = (
                select(b2.c.platform_user_id)
                .select_from(b1.join(b2, b1.c.global_user_id == b2.c.global_user_id))
                .where(
                    b1.c.instance_id == source_instance,
                    b1.c.platform_user_id == source_user_id,
                    b2.c.instance_id == target_instance,
                )
            )
            return s.execute(stmt).scalar_one_or_none()

    def remove_user_binding(
        self,
        instance_id: str,
        platform_user_id: str,
        target_instance_id: str | None = None,
    ) -> bool:
        """Remove bindings. If target_instance_id is set, only remove that one. Otherwise remove all."""
        with self._session() as s:
            row = s.execute(
                select(UserBinding.global_user_id).where(
                    UserBinding.instance_id == instance_id,
                    UserBinding.platform_user_id == platform_user_id,
                )
            ).scalar_one_or_none()
            if row is None:
                return False

            global_id: str = row
            if target_instance_id:
                s.execute(
                    delete(UserBinding).where(
                        UserBinding.global_user_id == global_id,
                        UserBinding.instance_id == target_instance_id,
                    )
                )
            else:
                s.execute(
                    delete(UserBinding).where(UserBinding.global_user_id == global_id)
                )
            s.commit()
        return True

    def get_all_bindings(
        self, instance_id: str, platform_user_id: str
    ) -> list[tuple[str, str]]:
        """Return all (instance_id, platform_user_id) linked to this account."""
        with self._session() as s:
            global_id = s.execute(
                select(UserBinding.global_user_id).where(
                    UserBinding.instance_id == instance_id,
                    UserBinding.platform_user_id == platform_user_id,
                )
            ).scalar_one_or_none()
            if global_id is None:
                return []

            rows = s.execute(
                select(UserBinding.instance_id, UserBinding.platform_user_id).where(
                    UserBinding.global_user_id == global_id
                )
            ).all()
            return [(r[0], r[1]) for r in rows]

    # ------------------------------------------------------------------
    # User mappings
    # ------------------------------------------------------------------

    def save_user(self, instance_id: str, platform_user_id: str, display_name: str):
        """Store or update a user's display name for an instance."""
        try:
            with self._session() as s:
                s.merge(
                    UserMapping(
                        instance_id=instance_id,
                        platform_user_id=platform_user_id,
                        display_name=display_name,
                    )
                )
                s.commit()
        except Exception as e:
            logger.error(f"Failed to save user mapping: {e}")

    def get_user_name(self, instance_id: str, platform_user_id: str) -> str | None:
        """Find a platform-specific display name by their user ID."""
        with self._session() as s:
            return s.execute(
                select(UserMapping.display_name).where(
                    UserMapping.instance_id == instance_id,
                    UserMapping.platform_user_id == platform_user_id,
                )
            ).scalar_one_or_none()

    def get_user_id_by_name(self, instance_id: str, display_name: str) -> str | None:
        """Find a platform-specific user ID by their display name on that instance."""
        with self._session() as s:
            return s.execute(
                select(UserMapping.platform_user_id).where(
                    UserMapping.instance_id == instance_id,
                    UserMapping.display_name == display_name,
                )
            ).scalar_one_or_none()

    def get_mapped_user_id(
        self, source_instance: str, source_user_id: str, target_instance: str
    ) -> str | None:
        """Find the target user ID mapped from a source user ID via display name."""
        name = self.get_user_name(source_instance, source_user_id)
        if not name:
            return None
        return self.get_user_id_by_name(target_instance, name)

    # ------------------------------------------------------------------
    # Message mappings
    # ------------------------------------------------------------------

    def save_mapping(
        self, bridge_id: str, instance_id: str, channel_id: str, platform_msg_id: str
    ):
        """Store a mapping between a bridge ID and a platform-specific message ID."""
        try:
            with self._session() as s:
                s.merge(
                    MessageMapping(
                        bridge_id=bridge_id,
                        instance_id=instance_id,
                        channel_id=channel_id,
                        platform_msg_id=platform_msg_id,
                    )
                )
                s.commit()
        except Exception as e:
            logger.error(f"Failed to save message mapping: {e}")

    def get_bridge_id(self, instance_id: str, platform_msg_id: str) -> str | None:
        """Find the bridge ID for a given platform-specific message ID."""
        with self._session() as s:
            return s.execute(
                select(MessageMapping.bridge_id).where(
                    MessageMapping.instance_id == instance_id,
                    MessageMapping.platform_msg_id == platform_msg_id,
                )
            ).scalar_one_or_none()

    def get_platform_msg_id(
        self, bridge_id: str, instance_id: str, channel_id: str | None = None
    ) -> str | None:
        """Find the platform-specific message ID for a given bridge ID and target instance."""
        with self._session() as s:
            stmt = select(MessageMapping.platform_msg_id).where(
                MessageMapping.bridge_id == bridge_id,
                MessageMapping.instance_id == instance_id,
            )
            if channel_id:
                stmt = stmt.where(MessageMapping.channel_id == channel_id)
            return s.execute(stmt).scalar_one_or_none()


# Shared singleton

_msg_db_instance: Optional[MessageDB] = None


def msg_db() -> MessageDB:
    """Get the shared MessageDB instance.

    This function implements lazy initialization to ensure the database
    is only initialized after the configuration has been loaded.

    Returns:
        The shared MessageDB instance.
    """
    global _msg_db_instance
    if _msg_db_instance is None:
        _msg_db_instance = MessageDB()
    return _msg_db_instance


def init_db(engine: Optional[Engine] = None) -> None:
    """Initialize the database with an optional custom engine.

    This function allows explicit initialization of the database,
    useful for testing or when using a custom engine.

    Args:
        engine: Optional SQLAlchemy engine to use.
    """
    global _msg_db_instance
    _msg_db_instance = MessageDB(engine)
