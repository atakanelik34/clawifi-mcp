from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from clawifi import AsyncClawifi, Clawifi, ClawifiAPIError, ClawifiConfig, ClawifiDryRunUnsupportedError
from clawifi.errors import parse_retry_after
from clawifi.testing import fixture_transport, load_fixture_manifest


def test_fixture_transport_drives_sync_resources():
    manifest = load_fixture_manifest()
    client = Clawifi(api_key="test-token", transport=fixture_transport())

    fetch = client.fetch("https://example.com")
    scrape = client.scrape("https://example.com", formats=["markdown"])
    schema = client.schema_assist(mode="infer", html="<title>Example</title>")
    account = client.account()
    credits = client.credits()

    assert fetch["success"] is True
    assert scrape["formats"]["markdown"] == "# Example Domain"
    assert schema["schema"]["properties"]["title"]["type"] == "string"
    assert account["monthly_credit_remaining"] == 975
    assert credits["total_units"] == 1
    assert "fetch" in manifest["operations"]


@pytest.mark.asyncio
async def test_async_client_is_contract_equivalent_to_sync_client():
    sync_client = Clawifi(api_key="test-token", transport=fixture_transport())
    async_client = AsyncClawifi(api_key="test-token", transport=fixture_transport())

    sync_payload = sync_client.search_free("agent memory")
    async_payload = await async_client.search_free("agent memory")
    await async_client.aclose()

    assert async_payload == sync_payload


def test_error_preserves_request_id_and_server_details():
    client = Clawifi(api_key="test-token", transport=fixture_transport(errors={"POST /fetch"}))

    with pytest.raises(ClawifiAPIError) as raised:
        client.fetch("https://example.com")

    assert raised.value.status_code == 422
    assert raised.value.request_id == "req_sdk_fixture"
    assert raised.value.details["suggested_action"].startswith("Fix the request")


def test_retries_only_idempotent_or_explicitly_retryable_operations():
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(f"{request.method} {request.url.path}")
        if len(attempts) == 1:
            return httpx.Response(503, json={"error": {"code": "upstream_unavailable", "message": "try later", "details": {"request_id": "req_retry", "retryable": True}}})
        return httpx.Response(200, json={"ok": True})

    client = Clawifi(api_key="test-token", transport=httpx.MockTransport(handler), max_retries=1)

    assert client.get("/history") == {"ok": True}
    assert attempts == ["GET /history", "GET /history"]

    attempts.clear()
    with pytest.raises(ClawifiAPIError):
        client.post("/jobs", json={"operation": "fetch", "payload": {}})
    assert attempts == ["POST /jobs"]


def test_pollers_and_cursor_iterators_use_stable_json_contracts():
    client = Clawifi(api_key="test-token", transport=fixture_transport())

    assert client.poll_job("job_sdk_fixture", interval_seconds=0, timeout_seconds=1)["status"] == "succeeded"
    assert list(client.iter_history(limit=1))[0]["operation_id"] == "op_sdk_fixture"
    assert list(client.iter_monitors(limit=1))[0]["monitor_id"] == "mon_sdk_fixture"


def test_environment_config_reads_key_without_printing(monkeypatch):
    monkeypatch.setenv("CLAWIFI_API_KEY", "env-token")
    monkeypatch.setenv("CLAWIFI_API_BASE", "https://api.example.test")

    config = ClawifiConfig.from_env()

    assert config.api_key == "env-token"
    assert config.api_base == "https://api.example.test"
    assert "env-token" not in repr(config)


@pytest.mark.asyncio
async def test_async_context_manager_closes_client():
    async with AsyncClawifi(api_key="test-token", transport=fixture_transport()) as client:
        payload = await client.fetch("https://example.com")

    assert payload["success"] is True
    assert client.is_closed


def test_mcp_fetch_and_scrape_forward_the_question(monkeypatch):
    from clawifi import mcp_server

    calls = []

    class _Fake:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def fetch(self, url, **kwargs):
            calls.append(("fetch", url, kwargs))
            return {}

        def scrape(self, url, **kwargs):
            calls.append(("scrape", url, kwargs))
            return {}

    monkeypatch.setattr(mcp_server, "_client", _Fake)
    mcp_server.fetch("https://example.com", query="when", top_k=2)
    mcp_server.fetch("https://example.com")
    mcp_server.scrape("https://example.com", query="when", formats=["markdown"])
    mcp_server.scrape("https://example.com", query="  ")
    assert calls == [
        ("fetch", "https://example.com", {"timeout_seconds": 15, "query": "when", "top_k": 2}),
        ("fetch", "https://example.com", {"timeout_seconds": 15}),
        ("scrape", "https://example.com", {"formats": ["markdown"], "query": "when", "top_k": 5}),
        ("scrape", "https://example.com", {}),
    ]


def _api(manifest_version: str | None, calls: list[tuple[str, str, dict]], *, body: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else {}
        calls.append((request.method, request.url.path, payload))
        if request.url.path == "/product/manifest":
            if manifest_version is None:
                return httpx.Response(404, json={"error": {"code": "http_error", "message": "Not Found", "details": {}}})
            return httpx.Response(200, json={"success": True, "version": manifest_version})
        return httpx.Response(200, json=body if body is not None else {"success": True, "data": payload})

    return httpx.MockTransport(handler)


ESTIMATE_BODY = {"dry_run": True, "estimate": {"minimum": 1, "maximum": 3, "raises": ["browser_render"]}, "balance": 975, "would_402": False}


def test_estimate_sends_dry_run_once_the_api_supports_it(monkeypatch):
    monkeypatch.delenv("CLAWIFI_API_KEY", raising=False)
    calls: list = []
    client = Clawifi(api_key="test-token", transport=_api("1.7.0", calls, body=ESTIMATE_BODY))

    result = client.estimate("fetch", url="https://example.com", force_browser=True)
    again = client.scrape("https://example.com", dry_run=True)

    assert result == ESTIMATE_BODY and again == ESTIMATE_BODY
    assert calls == [
        ("GET", "/product/manifest", {}),
        ("POST", "/fetch", {"url": "https://example.com", "force_browser": True, "dry_run": True}),
        ("POST", "/scrape", {"url": "https://example.com", "dry_run": True}),
    ]


@pytest.mark.parametrize("version", ["1.6.3", None, ""])
def test_dry_run_never_reaches_a_billable_route_on_an_older_api(monkeypatch, version):
    monkeypatch.delenv("CLAWIFI_API_KEY", raising=False)
    calls: list = []
    client = Clawifi(api_key="test-token", transport=_api(version, calls))

    with pytest.raises(ClawifiDryRunUnsupportedError, match="1.7.0"):
        client.estimate("crawl", seed_url="https://example.com")
    with pytest.raises(ClawifiDryRunUnsupportedError):
        client.fetch("https://example.com", dry_run=True)

    assert {path for _, path, _ in calls} == {"/product/manifest"}


def test_estimate_rejects_unknown_operations():
    client = Clawifi(api_key="test-token", transport=_api("1.7.0", []))
    with pytest.raises(ValueError, match="unknown operation"):
        client.estimate("delete_everything")


@pytest.mark.asyncio
async def test_async_estimate_and_dry_run_match_sync(monkeypatch):
    monkeypatch.delenv("CLAWIFI_API_KEY", raising=False)
    calls: list = []
    async with AsyncClawifi(api_key="test-token", transport=_api("1.7.1", calls, body=ESTIMATE_BODY)) as client:
        assert await client.estimate("search_content", query="agent memory") == ESTIMATE_BODY
        assert await client.map("https://example.com", dry_run=True) == ESTIMATE_BODY
    assert [path for _, path, _ in calls] == ["/product/manifest", "/search/content", "/map"]

    old_calls: list = []
    async with AsyncClawifi(api_key="test-token", transport=_api("1.6.3", old_calls)) as client:
        with pytest.raises(ClawifiDryRunUnsupportedError):
            await client.extract("https://example.com", dry_run=True)
    assert [path for _, path, _ in old_calls] == ["/product/manifest"]


def test_search_content_passes_full_through_only_when_set():
    calls: list = []
    client = Clawifi(api_key="test-token", transport=_api("1.6.3", calls))

    client.search_content("agent memory")
    client.search_content("agent memory", full=True, max_results=3)
    client.search_content("agent memory", full=False)

    assert [body for _, _, body in calls] == [
        {"query": "agent memory"},
        {"query": "agent memory", "max_results": 3, "full": True},
        {"query": "agent memory", "full": False},
    ]


def test_freshness_fields_pass_through_untouched():
    envelope = {"success": True, "data": {"text": "x", "published_at": "2026-10-01T00:00:00Z", "modified_at": None, "fetched_at": "2026-10-21T12:00:00Z"}}
    client = Clawifi(api_key="test-token", transport=_api("1.7.0", [], body=envelope))
    assert client.fetch("https://example.com") == envelope


RATE_LIMITED = {"error": {"code": "rate_limited", "message": "Slow down", "details": {"request_id": "req_429", "limit_scope": "address", "retryable": True}}}


def test_429_exposes_retry_after_and_limit_scope():
    client = Clawifi(
        api_key="test-token",
        max_retries=2,
        transport=httpx.MockTransport(lambda request: httpx.Response(429, json=RATE_LIMITED, headers={"Retry-After": "30"})),
    )

    with pytest.raises(ClawifiAPIError) as raised:
        client.get("/history")

    assert raised.value.status_code == 429
    assert raised.value.retry_after == 30.0
    assert raised.value.limit_scope == "address"
    assert raised.value.request_id == "req_429"


def test_short_retry_after_is_honoured_before_retrying(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("clawifi.client.time.sleep", slept.append)
    responses = iter([httpx.Response(429, json=RATE_LIMITED, headers={"Retry-After": "2"}), httpx.Response(200, json={"ok": True})])
    client = Clawifi(api_key="test-token", max_retries=1, transport=httpx.MockTransport(lambda request: next(responses)))

    assert client.get("/history") == {"ok": True}
    assert slept == [2.0]


def test_long_retry_after_is_not_waited_out(monkeypatch):
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        return httpx.Response(429, json=RATE_LIMITED, headers={"Retry-After": "3600"})

    monkeypatch.setattr("clawifi.client.time.sleep", lambda seconds: pytest.fail("should not sleep"))
    client = Clawifi(api_key="test-token", max_retries=2, transport=httpx.MockTransport(handler))
    with pytest.raises(ClawifiAPIError) as raised:
        client.get("/history")
    assert attempts == ["/history"]
    assert raised.value.retry_after == 3600.0


def test_parse_retry_after_handles_seconds_dates_and_junk():
    now = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_retry_after("7", now=now) == 7.0
    assert parse_retry_after("Wed, 21 Oct 2026 12:00:45 GMT", now=now) == 45.0
    assert parse_retry_after("Wed, 21 Oct 2026 11:00:00 GMT", now=now) == 0.0
    assert parse_retry_after("soon", now=now) is None
    assert parse_retry_after(None) is None
    assert ClawifiAPIError("x").limit_scope is None


def test_billing_plans_returns_credit_costs_without_a_key(monkeypatch):
    monkeypatch.delenv("CLAWIFI_API_KEY", raising=False)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"credit_costs": [{"operation": "search", "credits": 1, "unit": "call"}]})

    client = Clawifi(transport=httpx.MockTransport(handler))
    assert client.billing_plans()["credit_costs"][0]["operation"] == "search"
    assert seen[0].url.path == "/billing/plans"
    assert "authorization" not in seen[0].headers


BILLABLE_CALLS = [
    ("fetch", "https://example.com", "/fetch"),
    ("scrape", "https://example.com", "/scrape"),
    ("extract", "https://example.com", "/extract"),
    ("map", "https://example.com", "/map"),
    ("crawl", "https://example.com", "/crawl"),
    ("search_free", "agent memory", "/search/free"),
    ("search_content", "agent memory", "/search/content"),
]


@pytest.mark.parametrize("method,first,path", BILLABLE_CALLS)
def test_a_normal_call_sends_no_dry_run_key(method, first, path):
    calls: list = []
    client = Clawifi(api_key="test-token", transport=_api("1.7.0", calls))

    getattr(client, method)(first)
    getattr(client, method)(first, dry_run=False)

    assert [p for _, p, _ in calls] == [path, path]
    assert all("dry_run" not in body for _, _, body in calls)


def test_a_normal_fetch_body_has_no_dry_run_key_and_dry_run_false_sends_nothing():
    calls: list = []
    client = Clawifi(api_key="test-token", transport=_api("1.7.0", calls))

    client.fetch("https://example.com", timeout_seconds=15)
    client.fetch("https://example.com", dry_run=False)

    assert calls == [
        ("POST", "/fetch", {"url": "https://example.com", "timeout_seconds": 15}),
        ("POST", "/fetch", {"url": "https://example.com"}),
    ]


@pytest.mark.parametrize("value", [1, 0, "true", "false", "yes", [], {}])
def test_a_non_boolean_dry_run_is_refused_before_anything_is_sent(value):
    calls: list = []
    client = Clawifi(api_key="test-token", transport=_api("1.7.0", calls))
    with pytest.raises(TypeError, match="dry_run must be True or False"):
        client.fetch("https://example.com", dry_run=value)
    assert calls == []


def test_dry_run_is_sent_as_the_json_boolean_true():
    calls: list = []
    client = Clawifi(api_key="test-token", transport=_api("1.7.0", calls, body=ESTIMATE_BODY))
    client.fetch("https://example.com", dry_run=True)
    client.estimate("search_free", query="q", dry_run=False)
    raw = [body for _, path, body in calls if path != "/product/manifest"]
    assert raw == [{"url": "https://example.com", "dry_run": True}, {"query": "q", "dry_run": True}]
    assert all(body["dry_run"] is True for body in raw)


def test_schema_assist_never_sends_dry_run():
    calls: list = []
    client = Clawifi(api_key="test-token", transport=_api("1.7.0", calls))
    client.schema_assist(mode="infer", html="<p>x</p>", dry_run=False)
    assert calls == [("POST", "/schema/assist", {"mode": "infer", "html": "<p>x</p>"})]
    with pytest.raises(ClawifiDryRunUnsupportedError):
        client.schema_assist(mode="infer", html="<p>x</p>", dry_run=True)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_async_normal_calls_send_no_dry_run_key():
    calls: list = []
    async with AsyncClawifi(api_key="test-token", transport=_api("1.7.0", calls)) as client:
        await client.fetch("https://example.com")
        await client.crawl("https://example.com", dry_run=False)
        await client.schema_assist(mode="infer", dry_run=False)
        with pytest.raises(TypeError):
            await client.scrape("https://example.com", dry_run="true")
    assert [path for _, path, _ in calls] == ["/fetch", "/crawl", "/schema/assist"]
    assert all("dry_run" not in body for _, _, body in calls)


@pytest.mark.parametrize("version", ["1.7.0rc1", "1.7.0a1", "1.7.0b2", "1.7.0.dev3", "1.7.0-rc.1", "1.6.9", "1.6.99", "0.9.0", "1.7.0weird"])
def test_pre_releases_and_older_versions_sort_below_1_7_0(version):
    from clawifi.client import DRY_RUN_MIN_API_VERSION, _version_tuple

    assert _version_tuple(version) < (*DRY_RUN_MIN_API_VERSION, 0)
    calls: list = []
    client = Clawifi(api_key="test-token", transport=_api(version, calls))
    with pytest.raises(ClawifiDryRunUnsupportedError):
        client.estimate("fetch", url="https://example.com")
    assert [path for _, path, _ in calls] == ["/product/manifest"]


@pytest.mark.parametrize("version", ["1.7.0", "v1.7.0", "1.7.0.post1", "1.7.0-post2", "1.7.0+build.5", "1.7.1", "1.10.0", "2.0.0", "1.8"])
def test_final_and_post_releases_from_1_7_0_pass(version):
    from clawifi.client import DRY_RUN_MIN_API_VERSION, _version_tuple

    assert _version_tuple(version) >= (*DRY_RUN_MIN_API_VERSION, 0)
    calls: list = []
    client = Clawifi(api_key="test-token", transport=_api(version, calls, body=ESTIMATE_BODY))
    assert client.estimate("fetch", url="https://example.com") == ESTIMATE_BODY


def test_version_ordering_is_numeric_not_lexical():
    from clawifi.client import _version_tuple

    assert _version_tuple("1.10.0") > _version_tuple("1.9.0")
    assert _version_tuple("1.7.0rc1") < _version_tuple("1.7.0") == _version_tuple("1.7.0.post1")
    assert _version_tuple("") == (0, 0, 0, 0)
