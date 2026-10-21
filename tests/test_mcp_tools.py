from __future__ import annotations

import json

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from clawifi import mcp_server
from clawifi.client import Clawifi
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


def test_estimate_tool_checks_operation_and_args_before_any_client_is_made(estimator):
    with pytest.raises(ToolError) as raised:
        mcp_server.estimate("nope")
    assert str(raised.value) == "unknown operation 'nope'; expected one of crawl, extract, fetch, map, scrape, search_content, search_free"
    with pytest.raises(ToolError, match="args.operation is not allowed"):
        mcp_server.estimate("fetch", {"url": "u", "operation": "crawl"})
    with pytest.raises(ToolError, match="args.dry_run is not allowed"):
        mcp_server.estimate("fetch", {"url": "u", "dry_run": "yes"})
    assert estimator.calls == []


def test_estimate_tool_does_not_dress_config_errors_up_as_operation_errors(monkeypatch):
    monkeypatch.setenv("CLAWIFI_API_KEY", "clawifi_live_SECRET\r\nX: y")
    monkeypatch.setattr(mcp_server, "_client", mcp_server.Clawifi)
    with pytest.raises(ValueError) as raised:
        mcp_server.estimate("fetch", {"url": "https://example.com"})
    assert "operation" not in str(raised.value) and "SECRET" not in str(raised.value)


# --- the tools through the MCP protocol layer, against a mock API ---------------------------------------------


@pytest.fixture
def api(monkeypatch):
    sent: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        sent.append((request.method, request.url.path, body if request.method == "POST" else dict(request.url.params) or None))
        if request.url.path == "/product/manifest":
            return httpx.Response(200, json={"version": "1.7.0"})
        if body and body.get("dry_run") is True:
            return httpx.Response(200, json={"dry_run": True, "route": f"POST {request.url.path}", "estimate": {"minimum": 1, "maximum": 1, "raises": []}, "charged": 0})
        return httpx.Response(200, json={"ok": True, "params": dict(request.url.params)})

    monkeypatch.setattr(mcp_server, "_client", lambda: Clawifi(api_key="test-token", api_base="http://api.test", transport=httpx.MockTransport(handler)))
    return sent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,arguments",
    [
        ("scrape", {"url": "u", "dry_run": True}),
        ("scrape", {"url": "u", "dry_run": False}),
        ("scrape", {"url": "u", "options": {"dry_run": True}}),
        ("crawl", {"seed_url": "u", "dry_run": True}),
        ("crawl", {"seed_url": "u", "options": {"dry_run": "yes"}}),
        ("fetch", {"url": "u", "dry_run": "true"}),
        ("extract", {"url": "u", "options": {"dry_run": True}}),
        ("map_site", {"url": "u", "dry_run": 1}),
        ("search_free", {"query": "q", "dry_run": True}),
        ("create_job", {"operation": "fetch", "payload": {"url": "u", "dry_run": True}}),
        ("create_job", {"operation": "fetch", "payload": {"url": "u"}, "dry_run": True}),
    ],
)
async def test_dry_run_is_refused_on_every_billable_tool_and_nothing_is_sent(api, name, arguments):
    with pytest.raises(ToolError, match="use the estimate tool"):
        await mcp_server.mcp.call_tool(name, arguments)
    assert api == []


@pytest.mark.asyncio
async def test_extract_map_and_crawl_need_no_options_and_options_merge_at_the_top_level(api):
    await mcp_server.mcp.call_tool("extract", {"url": "https://example.com"})
    await mcp_server.mcp.call_tool("map_site", {"url": "https://example.com"})
    await mcp_server.mcp.call_tool("crawl", {"seed_url": "https://example.com"})
    await mcp_server.mcp.call_tool("crawl", {"seed_url": "https://example.com", "max_pages": 5, "options": {"robots_policy": "respect"}})
    await mcp_server.mcp.call_tool("extract", {"url": "https://example.com", "extraction_schema": {"title": {"type": "string"}}})
    await mcp_server.mcp.call_tool("scrape", {"url": "https://example.com", "formats": ["html"], "options": {"artifact_policy": "metadata_only"}})
    assert api == [
        ("POST", "/extract", {"url": "https://example.com"}),
        ("POST", "/map", {"url": "https://example.com"}),
        ("POST", "/crawl", {"seed_url": "https://example.com"}),
        ("POST", "/crawl", {"seed_url": "https://example.com", "max_pages": 5, "robots_policy": "respect"}),
        ("POST", "/extract", {"url": "https://example.com", "schema": {"title": {"type": "string"}}}),
        ("POST", "/scrape", {"url": "https://example.com", "formats": ["html"], "artifact_policy": "metadata_only"}),
    ]
    assert not any("kwargs" in (body or {}) or "options" in (body or {}) for _, _, body in api)


@pytest.mark.asyncio
async def test_no_tool_schema_has_a_kwargs_or_params_argument():
    for tool in await mcp_server.mcp.list_tools():
        properties = tool.inputSchema.get("properties", {})
        assert "kwargs" not in properties and "params" not in properties, tool.name
        assert not set(tool.inputSchema.get("required", [])) & {"kwargs", "params", "options"}, tool.name


@pytest.mark.asyncio
async def test_an_option_may_not_repeat_a_parameter(api):
    with pytest.raises(ToolError, match="options.url repeats"):
        await mcp_server.mcp.call_tool("fetch", {"url": "u", "options": {"url": "other"}})
    with pytest.raises(ToolError, match="options.max_pages repeats"):
        await mcp_server.mcp.call_tool("crawl", {"seed_url": "u", "max_pages": 2, "options": {"max_pages": 500}})
    assert api == []


@pytest.mark.asyncio
async def test_estimate_and_list_tools_through_call_tool(api):
    await mcp_server.mcp.call_tool("estimate", {"operation": "crawl", "args": {"seed_url": "https://example.com", "max_pages": 3}})
    await mcp_server.mcp.call_tool("list_history", {"limit": 5, "operation": "search_free"})
    await mcp_server.mcp.call_tool("list_monitors", {})
    assert api == [
        ("GET", "/product/manifest", None),
        ("POST", "/crawl", {"seed_url": "https://example.com", "max_pages": 3, "dry_run": True}),
        ("GET", "/history", {"limit": "5", "operation": "search_free"}),
        ("GET", "/monitors", None),
    ]


@pytest.mark.asyncio
async def test_api_error_text_in_a_tool_error_never_carries_a_key(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"code": "unauthorized", "message": "bad key clawifi_live_ABC123 (Bearer clawifi_live_ABC123)", "details": {}}})

    monkeypatch.setattr(mcp_server, "_client", lambda: Clawifi(api_key="clawifi_live_ABC123", api_base="http://api.test", transport=httpx.MockTransport(handler)))
    with pytest.raises(ToolError) as raised:
        await mcp_server.mcp.call_tool("account", {})
    assert "ABC123" not in str(raised.value)
    assert "clawifi_live_***" in str(raised.value) and "status 401" in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,arguments",
    [
        ("crawl", {"seed_url": "u", "kwargs": {"dry_run": True}}),
        ("scrape", {"url": "u", "kwargs": {"dry_run": "yes"}}),
        ("fetch", {"url": "u", "force_browsr": True}),
        ("list_history", {"params": {"limit": 1}}),
    ],
)
async def test_undeclared_arguments_are_refused_not_dropped(api, name, arguments):
    with pytest.raises(ToolError, match="does not take"):
        await mcp_server.mcp.call_tool(name, arguments)
    assert api == []
