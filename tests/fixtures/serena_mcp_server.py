"""Small real MCP server used only by the F3.8 transport tests."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

parser = argparse.ArgumentParser()
parser.add_argument("root", type=Path)
parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
parser.add_argument("--port", type=int, default=8000)
parser.add_argument("--omit-root", action="store_true")
parser.add_argument("--wrong-root", action="store_true")
parser.add_argument("--omit-edit", action="store_true")
arguments = parser.parse_args()

authorized_root = arguments.root.resolve(strict=True)
active_root = authorized_root
server = FastMCP(
    "serena-f3.8-test",
    host="127.0.0.1",
    port=arguments.port,
    json_response=True,
    log_level="ERROR",
)


@server.tool()
def activate_project(project: str) -> dict[str, str]:
    global active_root
    active_root = Path(project).resolve(strict=True)
    return {"path": str(active_root)}


if not arguments.omit_root:

    @server.tool()
    def get_active_project() -> dict[str, str]:
        reported = active_root.parent if arguments.wrong_root else active_root
        return {"path": str(reported)}


if not arguments.omit_edit:

    @server.tool()
    def replace_content(
        relative_path: str,
        needle: str,
        replacement: str,
        fail: bool = False,
        delay_seconds: float = 0.0,
    ) -> dict[str, object]:
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        target = (active_root / relative_path).resolve(strict=True)
        if not target.is_relative_to(active_root):
            raise ValueError("target escaped active project")
        content = target.read_text(encoding="utf-8", errors="strict")
        if fail:
            raise RuntimeError("controlled test failure")
        updated = content.replace(needle, replacement)
        target.write_text(updated, encoding="utf-8", errors="strict", newline="")
        return {"path": relative_path, "changed": updated != content}


if __name__ == "__main__":
    server.run(transport=arguments.transport)
