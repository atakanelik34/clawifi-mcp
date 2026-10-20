from __future__ import annotations

import httpx
import pytest

from clawifi import AsyncClawifi, Clawifi, ClawifiAPIError, ClawifiConfig
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
