import json
import importlib
import importlib.util
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    create_engine,
    delete,
    select,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session

import services.logger as log
import services.util as u
from services import config
from services import db_migrations
from services.db_migrations import MigrationStep

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


class ForwardPage(_Base):
    __tablename__ = "forward_pages"

    page_id = Column(String, primary_key=True)
    instance_id = Column(String, nullable=False)
    html_content = Column(Text, nullable=False)
    created_at = Column(Integer, nullable=False)
    expires_at = Column(Integer, nullable=False)
    destroyed_at = Column(Integer, nullable=True)


Index("idx_forward_pages_instance_id", ForwardPage.instance_id)
Index("idx_forward_pages_expires_at", ForwardPage.expires_at)


class ForwardAsset(_Base):
    __tablename__ = "forward_assets"

    asset_id = Column(String, primary_key=True)
    page_id = Column(String, nullable=False)
    instance_id = Column(String, nullable=False)
    mime = Column(String, nullable=False)
    data = Column(LargeBinary, nullable=False)
    created_at = Column(Integer, nullable=False)
    expires_at = Column(Integer, nullable=True)


Index("idx_forward_assets_page_id", ForwardAsset.page_id)
Index("idx_forward_assets_expires_at", ForwardAsset.expires_at)


class MessageDB:
    """Handles mapping of message IDs between different platforms."""

    _SCHEMA_VERSION = max(
        (step.to_version for step in db_migrations.MIGRATIONS), default=0
    )

    @classmethod
    def target_db_version(cls) -> int:
        return int(cls._SCHEMA_VERSION)

    def __init__(self, engine: Engine | None = None):
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
        # Relative SQLite paths are resolved under data/ by the logic below.
        # Use sqlite:///data.db as default to avoid data/data.db.
        url = db_config.get("url", "sqlite:///data.db")

        sqlite_db_path: Path | None = None
        # Handle SQLite relative paths
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            # Convert relative path to absolute path under the data directory
            db_path = url.replace("sqlite:///", "")
            if not Path(db_path).is_absolute():
                data_path = Path(u.get_data_path())
                db_path = data_path / db_path
                db_path.parent.mkdir(parents=True, exist_ok=True)
                url = f"sqlite:///{db_path}"
            sqlite_db_path = Path(db_path)

            legacy_path = Path(u.get_data_path()) / "messages.db"
            if (
                sqlite_db_path.name == "data.db"
                and legacy_path.is_file()
                and not sqlite_db_path.exists()
            ):
                try:
                    legacy_path.replace(sqlite_db_path)
                    logger.info(
                        f"Migrated legacy database file {legacy_path.name} -> {sqlite_db_path.name}"
                    )
                except OSError as exc:
                    logger.warning(
                        f"Failed to rename legacy database file {legacy_path} to {sqlite_db_path}: {exc}"
                    )

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
        engine = create_engine(url, **engine_kwargs)

        MessageDB._run_migrations(engine)

        return engine

    @staticmethod
    def _schema_version_path() -> Path:
        return Path(u.get_data_path()) / "meta.yaml"

    @staticmethod
    def _coerce_db_version(raw: Any) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return 0
        return value if value >= 0 else 0

    @classmethod
    def _read_schema_version(cls) -> int:
        path = cls._schema_version_path()
        if not path.is_file():
            return 0

        try:
            import yaml

            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as exc:
            logger.warning(f"Failed to read schema meta {path}: {exc}")
            return 0

        return cls._coerce_db_version(data.get("db_version", 0))

    @classmethod
    def _write_schema_version(cls, version: int) -> None:
        path = cls._schema_version_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import yaml

            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump({"db_version": int(version)}, f, sort_keys=False)
        except Exception as exc:
            logger.error(f"Failed to write schema meta {path}: {exc}")

    @staticmethod
    @lru_cache(maxsize=1)
    def _load_migration_steps() -> tuple[MigrationStep, ...]:
        steps = db_migrations.MIGRATIONS
        logger.debug(f"Loaded {len(steps)} migration step(s) from registry")
        return steps

    @classmethod
    def _run_migrations(cls, engine: Engine) -> None:
        current_version = cls._read_schema_version()
        target_version = int(cls._SCHEMA_VERSION)
        migration_flag = False
        logger.info(
            f"Database schema migration check: current={current_version}, target={target_version}"
        )

        if current_version > target_version:
            logger.warning(
                "Current database schema is newer than target; skipping downgrade "
                f"(current={current_version}, target={target_version})"
            )

        for step in cls._load_migration_steps():
            to_version = getattr(step, "to_version", None)
            if to_version is None:
                logger.debug(f"Skipping malformed migration step: {step!r}")
                continue

            if int(to_version) > target_version:
                logger.debug(
                    f"Skipping migration {step.name}: target capped at {target_version}"
                )
                continue

            if current_version >= int(to_version):
                logger.debug(
                    f"Skipping migration {step.name}: already at {current_version}"
                )
                continue

            from_version = getattr(step, "from_version", None)
            if from_version is None or current_version < int(from_version):
                logger.debug(
                    f"Skipping migration {step.name}: current={current_version} < from={from_version}"
                )
                continue

            file_path = getattr(step, "file_path", None)
            if not file_path:
                raise FileNotFoundError(
                    f"Missing migration module for {getattr(step, 'name', 'unknown')}"
                )

            logger.info(
                f"Applying migration {int(step.from_version)} -> {int(step.to_version)} ({step.name})"
            )
            logger.debug(f"Migration file={file_path}, dialect={engine.dialect.name}")

            migration_name = (
                f"nextbridge_migration_{step.from_version}_{step.to_version}"
            )
            spec = importlib.util.spec_from_file_location(migration_name, file_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Failed to load migration spec from {file_path}")
            migration_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration_module)
            upgrade = getattr(migration_module, "upgrade", None)
            if not callable(upgrade):
                raise AttributeError(f"Migration module {file_path} has no upgrade()")

            with engine.begin() as conn:
                upgrade(conn, dialect_name=engine.dialect.name)

            cls._write_schema_version(int(step.to_version))
            logger.info(
                f"Migration {step.name} applied successfully, db_version={int(step.to_version)}"
            )

            migration_flag = True
            current_version = int(to_version)

        if migration_flag:
            logger.info(
                f"Database schema migration completed: db_version={current_version}"
            )

    def _session(self) -> Session:
        return Session(self._engine)

    def _normalize_channel_id(self, channel_id) -> str:
        """Serialize channel identifiers into a stable canonical string.

        Notes:
        - Dict/list values are recursively normalized with scalar values cast to str,
          so int/str mismatches do not break lookups.
        - Known transport-only keys such as webhook_url are dropped because they are
          not part of a channel address and are absent in inbound events.
        """

        def _normalize_value(value):
            if isinstance(value, dict):
                normalized_obj = {}
                for k in sorted(value.keys()):
                    if k in ("webhook_url", "msg"):
                        continue
                    normalized_obj[str(k)] = _normalize_value(value[k])
                return normalized_obj
            if isinstance(value, list):
                return [_normalize_value(v) for v in value]
            return str(value)

        if channel_id is None:
            return ""

        if isinstance(channel_id, (dict, list)):
            return json.dumps(
                _normalize_value(channel_id),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )

        return str(channel_id)

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
            return (
                s.execute(
                    select(UserMapping.platform_user_id).where(
                        UserMapping.instance_id == instance_id,
                        UserMapping.display_name == display_name,
                    )
                )
                .scalars()
                .first()
            )

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
        self, bridge_id: str, instance_id: str, channel_id, platform_msg_id: str
    ):
        """Store a mapping between a bridge ID and a platform-specific message ID."""
        try:
            normalized_channel = self._normalize_channel_id(channel_id)
            with self._session() as s:
                s.merge(
                    MessageMapping(
                        bridge_id=bridge_id,
                        instance_id=instance_id,
                        channel_id=normalized_channel,
                        platform_msg_id=platform_msg_id,
                    )
                )
                s.commit()
        except Exception as e:
            logger.error(f"Failed to save message mapping: {e}")

    def save_forward_page(
        self,
        page_id: str,
        instance_id: str,
        html_content: str,
        created_at: int,
        expires_at: int,
        destroyed_at: int | None = None,
    ) -> None:
        try:
            with self._session() as s:
                s.merge(
                    ForwardPage(
                        page_id=page_id,
                        instance_id=instance_id,
                        html_content=html_content,
                        created_at=created_at,
                        expires_at=expires_at,
                        destroyed_at=destroyed_at,
                    )
                )
                s.commit()
        except Exception as e:
            logger.error(f"Failed to save forward page: {e}")

    def save_forward_asset(
        self,
        asset_id: str,
        page_id: str,
        instance_id: str,
        mime: str,
        data: bytes,
        created_at: int,
        expires_at: int | None,
    ) -> None:
        try:
            with self._session() as s:
                s.merge(
                    ForwardAsset(
                        asset_id=asset_id,
                        page_id=page_id,
                        instance_id=instance_id,
                        mime=mime,
                        data=data,
                        created_at=created_at,
                        expires_at=expires_at,
                    )
                )
                s.commit()
        except Exception as e:
            logger.error(f"Failed to save forward asset: {e}")

    def get_forward_page(self, page_id: str) -> dict | None:
        with self._session() as s:
            row = s.get(ForwardPage, page_id)
            if row is None:
                return None
            return {
                "page_id": row.page_id,
                "instance_id": row.instance_id,
                "html_content": row.html_content,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "destroyed_at": row.destroyed_at,
            }

    def get_forward_asset(self, asset_id: str) -> dict | None:
        with self._session() as s:
            row = s.get(ForwardAsset, asset_id)
            if row is None:
                return None
            return {
                "asset_id": row.asset_id,
                "page_id": row.page_id,
                "instance_id": row.instance_id,
                "mime": row.mime,
                "data": row.data,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
            }

    def mark_forward_page_destroyed(
        self, page_id: str, destroyed_at: int | None = None
    ) -> bool:
        with self._session() as s:
            row = s.get(ForwardPage, page_id)
            if row is None:
                return False
            if row.destroyed_at is None:
                s.execute(
                    update(ForwardPage)
                    .where(ForwardPage.page_id == page_id)
                    .values(destroyed_at=destroyed_at or int(time.time()))
                )
                s.commit()
        return True

    def purge_expired_forward_assets(self, now: int | None = None) -> int:
        cutoff = int(now or time.time())
        with self._session() as s:
            result = s.execute(
                delete(ForwardAsset).where(
                    ForwardAsset.expires_at.is_not(None),
                    ForwardAsset.expires_at <= cutoff,
                )
            )
            s.commit()
            return int(getattr(result, "rowcount", 0) or 0)

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
        self, bridge_id: str, instance_id: str, channel_id=None
    ) -> str | None:
        """Find the platform-specific message ID for a given bridge ID and target instance."""
        with self._session() as s:
            base_stmt = select(MessageMapping.platform_msg_id).where(
                MessageMapping.bridge_id == bridge_id,
                MessageMapping.instance_id == instance_id,
            )

            if channel_id:
                # Try canonical form first.
                normalized = self._normalize_channel_id(channel_id)
                strict_stmt = base_stmt.where(MessageMapping.channel_id == normalized)
                strict_hit = s.execute(strict_stmt).scalars().first()
                if strict_hit:
                    return strict_hit

                # Compatibility for legacy rows written as plain str(dict(...)).
                legacy = str(channel_id)
                if legacy != normalized:
                    legacy_stmt = base_stmt.where(MessageMapping.channel_id == legacy)
                    legacy_hit = s.execute(legacy_stmt).scalars().first()
                    if legacy_hit:
                        return legacy_hit

            # Final fallback: if there are multiple rows, pick the first deterministically
            # instead of raising MultipleResultsFound.
            return s.execute(base_stmt).scalars().first()


# Shared singleton

_msg_db_instance: MessageDB | None = None


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


def init_db(engine: Engine | None = None) -> None:
    """Initialize the database with an optional custom engine.

    This function allows explicit initialization of the database,
    useful for testing or when using a custom engine.

    Args:
        engine: Optional SQLAlchemy engine to use.
    """
    global _msg_db_instance
    _msg_db_instance = MessageDB(engine)


def db_target_version() -> int:
    """Return the target integer database version resolved from migration registry."""
    return MessageDB.target_db_version()
