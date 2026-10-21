from __future__ import annotations

import pytest

from clawifi import mcp_server

HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
EXPECTED = {
    "fetch": (True, False, True, True),
    "scrape": (True, False, True, True),
    "search_free": (True, False, True, True),
    "extract": (True, False, True, True),
    "map_site": (True, False, True, True),
    "crawl": (False, False, False, True),
    "create_job": (False, False, False, True),
    "get_crawl": (True, False, True, False),
    "get_job": (True, False, True, False),
    "account": (True, False, True, False),
    "credits": (True, False, True, False),
    "list_history": (True, False, True, False),
    "list_monitors": (True, False, True, False),
}


@pytest.mark.asyncio
async def test_every_tool_has_a_title_and_all_four_hints():
    tools = await mcp_server.mcp.list_tools()

    assert {tool.name for tool in tools} == set(EXPECTED)
    for tool in tools:
        assert tool.title and tool.title.strip(), tool.name
        assert tool.annotations is not None, tool.name
        hints = tuple(getattr(tool.annotations, hint) for hint in HINTS)
        assert None not in hints, tool.name
        assert hints == EXPECTED[tool.name], tool.name


@pytest.mark.asyncio
async def test_no_tool_is_destructive_and_titles_are_unique():
    tools = await mcp_server.mcp.list_tools()
    assert not any(tool.annotations.destructiveHint for tool in tools)
    assert len({tool.title for tool in tools}) == len(tools)


def test_version_is_the_same_everywhere():
    import json
    import re
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    server = json.loads((root / "server.json").read_text())
    assert server["version"] == version
    assert [package["version"] for package in server["packages"]] == [version]
    assert f'"clawifi/{version}"' in (root / "src/clawifi/client.py").read_text()
    assert f"clawifi-cli/{version} " in (root / "src/clawifi/cli.py").read_text()
    assert re.search(rf"^## {re.escape(version)} ", (root / "CHANGELOG.md").read_text(), re.M)
