"""`clawifi init`: find the MCP clients on this machine and show how to add Clawifi to each.

Every install line below follows the client's own public docs (checked for the 0.3.0 release):

- Claude Code: https://code.claude.com/docs/en/mcp
- Codex: https://learn.chatgpt.com/docs/extend/mcp?surface=cli and `codex mcp add --help`
- Cursor: https://cursor.com/docs/context/mcp
- VS Code: https://code.visualstudio.com/docs/agents/reference/mcp-configuration
- Claude Desktop: https://modelcontextprotocol.io/docs/develop/connect-local-servers (local servers only)

The API key is never printed: lines show `$CLAWIFI_API_KEY` (or the client's own variable syntax) and the
key itself appears only masked.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, TextIO

REMOTE_MCP_URL = "https://api.clawifi.qzz.io/mcp"
SERVER_NAME = "clawifi"
KEY_VAR = "CLAWIFI_API_KEY"
WRITABLE_CLIENTS = ("cursor", "claude-desktop")


@dataclass
class ClientSetup:
    key: str
    name: str
    detected: bool
    where: str
    lines: list[tuple[str, str]] = field(default_factory=list)
    config_path: Path | None = None


def mask_key(api_key: str | None) -> str:
    if not api_key:
        return "not set"
    prefix = "clawifi_live_" if api_key.startswith("clawifi_live_") else ""
    return f"{prefix}****"


def claude_desktop_config_path(home: Path, platform: str, environ: dict[str, str]) -> Path | None:
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if platform.startswith("win"):
        appdata = environ.get("APPDATA")
        return Path(appdata) / "Claude" / "claude_desktop_config.json" if appdata else None
    return None  # Claude Desktop documents config paths for macOS and Windows only.


def _json(value: dict) -> str:
    return json.dumps(value, indent=2)


def _mcp_command(which: Callable[[str], str | None]) -> str:
    # GUI apps often start without the shell's PATH, so prefer the absolute path when we can find it.
    return which("clawifi-mcp") or "clawifi-mcp"


def stdio_entry(command: str, key_value: str) -> dict:
    return {"command": command, "env": {KEY_VAR: key_value}}


def detect_clients(
    *,
    home: Path,
    environ: dict[str, str],
    platform: str,
    which: Callable[[str], str | None] = shutil.which,
) -> list[ClientSetup]:
    command = _mcp_command(which)
    clients: list[ClientSetup] = []

    claude = which("claude")
    clients.append(
        ClientSetup(
            key="claude-code",
            name="Claude Code",
            detected=bool(claude),
            where=claude or "`claude` not on PATH",
            lines=[
                ("local (stdio)", f"claude mcp add --env {KEY_VAR}=${KEY_VAR} --transport stdio {SERVER_NAME} -- clawifi-mcp"),
                ("remote", f'claude mcp add --transport http {SERVER_NAME} {REMOTE_MCP_URL} --header "Authorization: Bearer ${KEY_VAR}"'),
                ("remote, keyless tier", f"claude mcp add --transport http {SERVER_NAME} {REMOTE_MCP_URL}"),
            ],
        )
    )

    codex = which("codex")
    clients.append(
        ClientSetup(
            key="codex",
            name="Codex",
            detected=bool(codex),
            where=codex or "`codex` not on PATH",
            lines=[
                ("local (stdio)", f"codex mcp add {SERVER_NAME} --env {KEY_VAR}=${KEY_VAR} -- clawifi-mcp"),
                ("remote", f"codex mcp add {SERVER_NAME} --url {REMOTE_MCP_URL} --bearer-token-env-var {KEY_VAR}"),
                ("remote, keyless tier", f"codex mcp add {SERVER_NAME} --url {REMOTE_MCP_URL}"),
            ],
        )
    )

    cursor_dir = home / ".cursor"
    cursor_config = cursor_dir / "mcp.json"
    clients.append(
        ClientSetup(
            key="cursor",
            name="Cursor",
            detected=cursor_dir.is_dir(),
            where=str(cursor_config),
            config_path=cursor_config,
            lines=[
                ("local (stdio), in mcp.json", _json({"mcpServers": {SERVER_NAME: stdio_entry(command, "${env:" + KEY_VAR + "}")}})),
                (
                    "remote, in mcp.json",
                    _json({"mcpServers": {SERVER_NAME: {"url": REMOTE_MCP_URL, "headers": {"Authorization": "Bearer ${env:" + KEY_VAR + "}"}}}}),
                ),
            ],
        )
    )

    desktop_config = claude_desktop_config_path(home, platform, environ)
    clients.append(
        ClientSetup(
            key="claude-desktop",
            name="Claude Desktop",
            detected=bool(desktop_config and desktop_config.parent.is_dir()),
            where=str(desktop_config) if desktop_config else "no documented config path on this OS",
            config_path=desktop_config,
            lines=[
                (
                    "local (stdio), in claude_desktop_config.json (replace $CLAWIFI_API_KEY with your key, or use --write)",
                    _json({"mcpServers": {SERVER_NAME: stdio_entry(command, "$" + KEY_VAR)}}),
                ),
            ],
        )
    )

    code = which("code")
    vscode_dir = home / ".vscode"
    vscode_inputs = [{"type": "promptString", "id": "clawifi-api-key", "description": "Clawifi API key", "password": True}]
    clients.append(
        ClientSetup(
            key="vscode",
            name="VS Code",
            detected=bool(code) or vscode_dir.is_dir(),
            where=code or str(vscode_dir),
            lines=[
                (
                    "local (stdio), in mcp.json (MCP: Open User Configuration)",
                    _json({"inputs": vscode_inputs, "servers": {SERVER_NAME: {"type": "stdio", **stdio_entry("clawifi-mcp", "${input:clawifi-api-key}")}}}),
                ),
                (
                    "remote, in mcp.json",
                    _json({"inputs": vscode_inputs, "servers": {SERVER_NAME: {"type": "http", "url": REMOTE_MCP_URL, "headers": {"Authorization": "Bearer ${input:clawifi-api-key}"}}}}),
                ),
            ],
        )
    )
    return clients


def print_setup(clients: list[ClientSetup], *, api_key: str | None, show_all: bool, out: TextIO) -> None:
    print(f"Clawifi MCP setup. API key ({KEY_VAR}): {mask_key(api_key)}", file=out)
    print(f"Remote MCP: {REMOTE_MCP_URL} (streamable HTTP, Authorization: Bearer <key>).", file=out)
    print("Without a key the remote server offers search_free, fetch_url, scrape_url and map_site at 12/min and 50/day.", file=out)
    shown = [client for client in clients if client.detected or show_all]
    if not shown:
        print("\nNo MCP clients found. Run `clawifi init --all` to see every client's install lines.", file=out)
    for client in shown:
        state = "found" if client.detected else "not found"
        print(f"\n== {client.name} ({state}: {client.where})", file=out)
        for label, text in client.lines:
            print(f"-- {label}:", file=out)
            print(text, file=out)
    hidden = [client.name for client in clients if not client.detected and not show_all]
    if hidden:
        print(f"\nNot found: {', '.join(hidden)} (use --all to show them).", file=out)
    print("\nFirst call to try:", file=out)
    print("  clawifi quicktest --url https://example.com", file=out)
    print('  then ask your agent: "Use clawifi to fetch https://example.com and tell me what the page says."', file=out)


def write_config(
    client: ClientSetup,
    *,
    remote: bool,
    api_key: str | None,
    which: Callable[[str], str | None],
    input_fn: Callable[[str], str],
    is_tty: bool,
    out: TextIO,
    now: Callable[[], datetime] = datetime.now,
) -> int:
    path = client.config_path
    if client.key not in WRITABLE_CLIENTS or path is None:
        print(f"--write is not available for {client.name}; run the install line shown above instead.", file=out)
        return 2
    if client.key == "claude-desktop" and remote:
        print("Claude Desktop's config file takes local servers only; --remote is not supported there.", file=out)
        return 2
    if not is_tty:
        print("--write asks for confirmation and needs an interactive terminal; nothing was written.", file=out)
        return 2

    if client.key == "cursor":
        entry = (
            {"url": REMOTE_MCP_URL, "headers": {"Authorization": "Bearer ${env:" + KEY_VAR + "}"}}
            if remote
            else stdio_entry(_mcp_command(which), "${env:" + KEY_VAR + "}")
        )
        shown_entry = entry
    else:
        if not api_key:
            print(f"Claude Desktop reads the key from its config file; export {KEY_VAR} first. Nothing was written.", file=out)
            return 2
        entry = stdio_entry(_mcp_command(which), api_key)
        shown_entry = stdio_entry(entry["command"], mask_key(api_key))

    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8") or "{}")
        except ValueError:
            print(f"{path} is not valid JSON; fix or move it first. Nothing was written.", file=out)
            return 2
        if not isinstance(existing, dict):
            print(f"{path} does not hold a JSON object; nothing was written.", file=out)
            return 2
    servers = existing.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        print(f"{path} has an mcpServers value that is not an object; nothing was written.", file=out)
        return 2

    action = "replace the existing" if isinstance(servers, dict) and SERVER_NAME in servers else "add a"
    print(f"This will {action} '{SERVER_NAME}' entry in {path}:", file=out)
    print(_json({SERVER_NAME: shown_entry}), file=out)
    if path.exists():
        print("The current file is backed up first.", file=out)
    answer = input_fn("Write it? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        print("Nothing was written.", file=out)
        return 1

    if path.exists():
        backup = path.with_name(f"{path.name}.bak-{now().strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup)
        print(f"Backed up {path} to {backup}", file=out)
    merged = dict(existing)
    merged["mcpServers"] = {**(servers or {}), SERVER_NAME: entry}
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    if new_file and client.key == "claude-desktop":
        os.chmod(path, 0o600)
    print(f"Wrote {path}. Restart {client.name} to load Clawifi.", file=out)
    return 0


def run_init(
    *,
    write: str | None,
    remote: bool,
    show_all: bool,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
    platform: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    input_fn: Callable[[str], str] = input,
    is_tty: bool | None = None,
    out: TextIO | None = None,
) -> int:
    environ = dict(os.environ) if environ is None else environ
    out = out or sys.stdout
    clients = detect_clients(home=home or Path.home(), environ=environ, platform=platform or sys.platform, which=which)
    api_key = environ.get(KEY_VAR, "").strip() or None
    if write is None:
        print_setup(clients, api_key=api_key, show_all=show_all, out=out)
        return 0
    client = next(client for client in clients if client.key == write)
    return write_config(
        client,
        remote=remote,
        api_key=api_key,
        which=which,
        input_fn=input_fn,
        is_tty=sys.stdin.isatty() if is_tty is None else is_tty,
        out=out,
    )
