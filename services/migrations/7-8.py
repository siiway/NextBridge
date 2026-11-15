# v0.8: Persist QQ qid values alongside user mappings.
from sqlalchemy.engine import Connection


def upgrade(conn: Connection, dialect_name: str = "") -> None:
    if dialect_name == "sqlite":
        columns = {
            row[1]
            for row in conn.exec_driver_sql(
                "PRAGMA table_info(user_mappings)"
            ).fetchall()
        }
        if "qid" not in columns:
            conn.exec_driver_sql("ALTER TABLE user_mappings ADD COLUMN qid VARCHAR")
    else:
        conn.exec_driver_sql(
            "ALTER TABLE user_mappings ADD COLUMN IF NOT EXISTS qid VARCHAR"
        )
