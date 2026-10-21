from __future__ import annotations

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from clawifi import mcp_server
from clawifi.errors import ClawifiAPIError, ClawifiDryRunUnsupportedError, ClawifiTransportError

HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
EXPECTED = {
    "fetch": (True, False, True, True),
    "scrape": (True, False, True, True),
    "search_free": (True, False, True, True),
    "extract": (True, False, True, True),
    "map_site": (True, False, True, True),
    "crawl": (False, False, False, True),
    "estimate": (True, False, True, True),
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


class _FakeEstimator:
    calls: list = []
    error: Exception | None = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def estimate(self, operation, **args):
        type(self).calls.append((operation, args))
        if type(self).error is not None:
            raise type(self).error
        return {"dry_run": True, "route": "POST /fetch", "estimate": {"minimum": 1, "maximum": 3, "raises": []}, "charged": 0}


@pytest.fixture
def estimator(monkeypatch):
    _FakeEstimator.calls = []
    _FakeEstimator.error = None
    monkeypatch.setattr(mcp_server, "_client", _FakeEstimator)
    return _FakeEstimator


@pytest.mark.asyncio
async def test_estimate_tool_has_its_title_and_hints():
    tool = next(tool for tool in await mcp_server.mcp.list_tools() if tool.name == "estimate")
    assert tool.title == "Estimate credits"
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.idempotentHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is True
    assert tool.inputSchema["required"] == ["operation"]


def test_estimate_tool_forwards_operation_and_args(estimator):
    result = mcp_server.estimate("fetch", {"url": "https://example.com", "force_browser": True})
    mcp_server.estimate("search_free", None)
    assert result["charged"] == 0
    assert estimator.calls == [("fetch", {"url": "https://example.com", "force_browser": True}), ("search_free", {})]


@pytest.mark.parametrize(
    "error,expected",
    [
        (ClawifiDryRunUnsupportedError("dry_run needs Clawifi API 1.7.0 or later"), "dry_run needs Clawifi API 1.7.0"),
        (ClawifiAPIError("Insufficient credits", status_code=402, code="insufficient_credits", request_id="req_1"), "status 402; code insufficient_credits; request_id req_1"),
        (ClawifiTransportError("connection refused"), "unreachable: connection refused"),
        (ValueError("unknown operation 'nope'"), "operation must be one of crawl, extract"),
    ],
)
def test_estimate_tool_turns_errors_into_tool_errors(estimator, error, expected):
    estimator.error = error
    with pytest.raises(ToolError, match=expected):
        mcp_server.estimate("fetch", {"url": "https://example.com"})


@pytest.mark.asyncio
async def test_estimate_tool_error_reaches_the_client_as_an_error_result(estimator):
    estimator.error = ClawifiDryRunUnsupportedError("dry_run needs Clawifi API 1.7.0 or later; reports 1.6.3")
    with pytest.raises(ToolError, match="1.6.3"):
        await mcp_server.mcp.call_tool("estimate", {"operation": "fetch", "args": {"url": "https://example.com"}})
