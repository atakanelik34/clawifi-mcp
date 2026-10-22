from __future__ import annotations

import io
import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from clawifi import cli
from clawifi.mcp_setup import REMOTE_MCP_URL, detect_clients, mask_key, run_init, write_config

SECRET = "clawifi_live_supersecretvalue123"


@pytest.fixture
def home(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("PATH", str(empty_bin))
    monkeypatch.setenv("CLAWIFI_API_KEY", SECRET)
    monkeypatch.delenv("APPDATA", raising=False)
    return fake_home


def _which(found: dict[str, str]):
    return lambda name: found.get(name)


def _init(home: Path, **kwargs) -> tuple[int, str]:
    out = io.StringIO()
    kwargs.setdefault("environ", {"CLAWIFI_API_KEY": SECRET})
    kwargs.setdefault("platform", "darwin")
    kwargs.setdefault("which", _which({}))
    code = run_init(home=home, out=out, **{"write": None, "remote": False, "show_all": False, **kwargs})
    return code, out.getvalue()


def test_init_detects_each_client_from_path_and_home(home, tmp_path):
    (home / ".cursor").mkdir()
    (home / "Library" / "Application Support" / "Claude").mkdir(parents=True)
    which = _which({"claude": "/x/claude", "codex": "/x/codex", "code": "/x/code"})

    clients = {c.key: c for c in detect_clients(home=home, environ={}, platform="darwin", which=which)}
    assert all(c.detected for c in clients.values())

    bare = {c.key: c.detected for c in detect_clients(home=tmp_path / "nobody", environ={}, platform="linux", which=_which({}))}
    assert bare == {"claude-code": False, "codex": False, "cursor": False, "claude-desktop": False, "vscode": False}


def test_claude_desktop_config_path_per_os(home):
    win = {c.key: c for c in detect_clients(home=home, environ={"APPDATA": str(home / "AppData")}, platform="win32", which=_which({}))}
    assert win["claude-desktop"].config_path == home / "AppData" / "Claude" / "claude_desktop_config.json"
    mac = {c.key: c for c in detect_clients(home=home, environ={}, platform="darwin", which=_which({}))}
    assert mac["claude-desktop"].config_path == home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def test_init_prints_verified_lines_and_never_the_key(home):
    code, output = _init(home, which=_which({"claude": "/x/claude", "codex": "/x/codex"}), show_all=True)

    assert code == 0
    assert SECRET not in output and "supersecret" not in output
    assert "clawifi_live_****" in output
    assert f'claude mcp add --transport http clawifi {REMOTE_MCP_URL} --header "Authorization: Bearer $CLAWIFI_API_KEY"' in output
    assert "claude mcp add --env CLAWIFI_API_KEY=$CLAWIFI_API_KEY --transport stdio clawifi -- clawifi-mcp" in output
    assert f"codex mcp add clawifi --url {REMOTE_MCP_URL} --bearer-token-env-var CLAWIFI_API_KEY" in output
    assert "codex mcp add clawifi --env CLAWIFI_API_KEY=$CLAWIFI_API_KEY -- clawifi-mcp" in output
    assert "Bearer ${env:CLAWIFI_API_KEY}" in output
    assert "${input:clawifi-api-key}" in output
    assert "clawifi quicktest --url https://example.com" in output


def test_init_shows_only_found_clients_by_default(home):
    code, output = _init(home, which=_which({"codex": "/x/codex"}))
    assert code == 0
    assert "== Codex (found" in output
    assert "== Claude Code" not in output
    assert "Not found: Claude Code, Cursor, Claude Desktop, VS Code" in output


def test_init_writes_nothing_by_default(home):
    (home / ".cursor").mkdir()
    _init(home)
    assert list((home / ".cursor").iterdir()) == []


def _desktop_config(home: Path) -> Path:
    path = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "other-mcp"}}, "theme": "dark"}), encoding="utf-8")
    return path


def test_write_refuses_without_confirmation_and_leaves_the_file_alone(home):
    path = _desktop_config(home)
    before = path.read_text()

    code, output = _init(home, write="claude-desktop", is_tty=True, input_fn=lambda prompt: "n")

    assert code == 1
    assert path.read_text() == before
    assert not list(path.parent.glob("*.bak-*"))
    assert SECRET not in output


def test_write_backs_up_then_merges_after_yes(home):
    path = _desktop_config(home)
    before = path.read_text()

    code, output = _init(home, write="claude-desktop", is_tty=True, input_fn=lambda prompt: "y", which=_which({"clawifi-mcp": "/venv/bin/clawifi-mcp"}))

    assert code == 0
    backups = list(path.parent.glob("claude_desktop_config.json.bak-*"))
    assert len(backups) == 1 and backups[0].read_text() == before
    merged = json.loads(path.read_text())
    assert merged["theme"] == "dark"
    assert merged["mcpServers"]["other"] == {"command": "other-mcp"}
    assert merged["mcpServers"]["clawifi"] == {"command": "/venv/bin/clawifi-mcp", "env": {"CLAWIFI_API_KEY": SECRET}}
    assert SECRET not in output


def test_write_cursor_remote_uses_env_reference_not_the_key(home):
    (home / ".cursor").mkdir()
    code, _ = _init(home, write="cursor", remote=True, is_tty=True, input_fn=lambda prompt: "yes")

    assert code == 0
    written = (home / ".cursor" / "mcp.json").read_text()
    assert SECRET not in written
    assert json.loads(written)["mcpServers"]["clawifi"] == {"url": REMOTE_MCP_URL, "headers": {"Authorization": "Bearer ${env:CLAWIFI_API_KEY}"}}


def test_write_needs_a_terminal_and_a_valid_file(home):
    path = _desktop_config(home)
    code, output = _init(home, write="claude-desktop", is_tty=False, input_fn=lambda prompt: pytest.fail("must not prompt"))
    assert code == 2 and "interactive terminal" in output

    path.write_text("{not json")
    code, output = _init(home, write="claude-desktop", is_tty=True, input_fn=lambda prompt: pytest.fail("must not prompt"))
    assert code == 2 and "not valid JSON" in output
    assert path.read_text() == "{not json"


def test_write_rejects_remote_for_claude_desktop(home):
    _desktop_config(home)
    code, output = _init(home, write="claude-desktop", remote=True, is_tty=True, input_fn=lambda prompt: pytest.fail("must not prompt"))
    assert code == 2 and "local servers only" in output


def test_backup_name_is_timestamped(home):
    path = _desktop_config(home)
    client = next(c for c in detect_clients(home=home, environ={}, platform="darwin", which=_which({})) if c.key == "claude-desktop")
    write_config(client, remote=False, api_key=SECRET, which=_which({}), input_fn=lambda p: "y", is_tty=True, out=io.StringIO(), now=lambda: datetime(2026, 10, 21, 9, 5, 7))
    assert (path.parent / "claude_desktop_config.json.bak-20261021-090507-000000").exists()


def test_written_config_and_backups_are_private_and_never_overwrite_each_other(home):
    import stat

    path = _desktop_config(home)
    os.chmod(path, 0o644)
    client = next(c for c in detect_clients(home=home, environ={}, platform="darwin", which=_which({})) if c.key == "claude-desktop")
    same_instant = lambda: datetime(2026, 10, 22, 9, 5, 7, 123456)  # noqa: E731
    for _ in range(3):
        assert write_config(client, remote=False, api_key=SECRET, which=_which({}), input_fn=lambda p: "y", is_tty=True, out=io.StringIO(), now=same_instant) == 0
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    backups = sorted(p.name for p in path.parent.glob("claude_desktop_config.json.bak-*"))
    assert backups == [
        "claude_desktop_config.json.bak-20261022-090507-123456",
        "claude_desktop_config.json.bak-20261022-090507-123456-1",
        "claude_desktop_config.json.bak-20261022-090507-123456-2",
    ]
    for name in backups:
        assert stat.S_IMODE((path.parent / name).stat().st_mode) == 0o600
    assert not list(path.parent.glob(".*.tmp"))


def test_a_new_cursor_config_is_private_too(home):
    import stat

    (home / ".cursor").mkdir()
    code, _ = _init(home, write="cursor", is_tty=True, input_fn=lambda prompt: "y")
    assert code == 0
    assert stat.S_IMODE((home / ".cursor" / "mcp.json").stat().st_mode) == 0o600


def test_mask_key():
    assert mask_key(SECRET) == "clawifi_live_****"
    assert mask_key("other-format-key") == "****"
    assert mask_key(None) == "not set"


def test_cli_init_entrypoint_uses_the_temp_home(home, capsys):
    (home / ".cursor").mkdir()
    with pytest.raises(SystemExit) as raised:
        cli.run(["init"])
    output = capsys.readouterr().out
    assert raised.value.code == 0
    assert f"== Cursor (found: {home / '.cursor' / 'mcp.json'})" in output
    assert SECRET not in output


def test_cli_credits_prints_credit_costs_without_a_key(monkeypatch, capsys):
    monkeypatch.delenv("CLAWIFI_API_KEY", raising=False)
    seen = []

    def fake_request(method, url, *, json_body=None, token=None):
        seen.append((method, url, token))
        return {"credit_costs": [{"operation": "search", "credits": 1, "unit": "call", "notes": "plain fetch"}, {"operation": "crawl", "credits": 1, "unit": "page", "notes": ""}]}

    monkeypatch.setattr(cli, "_request", fake_request)
    with pytest.raises(SystemExit):
        cli.run(["--api-base", "https://api.example.test", "credits"])
    output = capsys.readouterr().out
    assert seen == [("GET", "https://api.example.test/billing/plans", None)]
    assert "search" in output and "1 per call  (plain fetch)" in output
    assert "1 per page" in output

    with pytest.raises(SystemExit):
        cli.run(["credits", "--json"])
    assert json.loads(capsys.readouterr().out)[1]["operation"] == "crawl"


def test_init_output_uses_the_clawifi_dev_hosts(home):
    (home / ".cursor").mkdir()
    code, output = _init(home, show_all=True)
    assert code == 0
    assert REMOTE_MCP_URL == "https://api.clawifi.dev/mcp"
    assert "https://api.clawifi.dev/mcp" in output
    assert "qzz" not in output


def test_cli_default_api_base_is_clawifi_dev_and_the_old_host_still_works(monkeypatch, capsys):
    seen = []

    def fake_request(method, url, *, json_body=None, token=None):
        seen.append(url)
        return {"credit_costs": []}

    monkeypatch.setattr(cli, "_request", fake_request)
    monkeypatch.delenv("CLAWIFI_API_BASE", raising=False)
    with pytest.raises(SystemExit):
        cli.run(["credits"])
    monkeypatch.setenv("CLAWIFI_API_BASE", "https://api.clawifi.qzz.io")
    with pytest.raises(SystemExit):
        cli.run(["credits"])
    assert seen == ["https://api.clawifi.dev/billing/plans", "https://api.clawifi.qzz.io/billing/plans"]
