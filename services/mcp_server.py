from __future__ import annotations

from importlib import import_module
from typing import Any

import services.logger as log
from services.db import msg_db

logger = log.get_logger("mcp")

try:
    FastMCP = import_module("mcp.server.fastmcp").FastMCP
except ModuleNotFoundError:

    class FastMCP:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def tool(self, *_args: Any, **_kwargs: Any) -> Any:
            def decorator(func: Any) -> Any:
                return func

            return decorator

        def run(self) -> None:
            raise RuntimeError(
                "MCP server support requires the 'mcp' package to be installed."
            )


mcp = FastMCP("NextBridge")


@mcp.tool()
def get_bind_relations(
    instance_id: str | None = None,
    platform_user_id: str | None = None,
) -> dict[str, Any]:
    """Return current binding groups from the database."""
    groups: list[dict[str, Any]] = msg_db().list_binding_groups(
        instance_id, platform_user_id
    )
    total_members = 0
    for group in groups:
        members = group.get("members", [])
        if isinstance(members, list):
            total_members += len(members)
    return {
        "total_groups": len(groups),
        "total_members": total_members,
        "bindings": groups,
    }


def run_mcp_server() -> None:
    logger.info("NextBridge MCP server starting...")
    mcp.run()
