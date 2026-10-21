from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from clawifi.client import ESTIMATE_ROUTES, Clawifi
from clawifi.errors import ClawifiAPIError, ClawifiDryRunUnsupportedError, ClawifiTransportError

mcp = FastMCP("clawifi")

# Reads of the open web: they change nothing, and repeating one gives the same answer (they are still billed,
# like the hosted server's fetch_url, scrape_url, search_free and map_site, which carry the same hints).
WEB_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
# Starts server-side work on the open web: each call creates a new crawl or job, nothing is overwritten.
WEB_START = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
# Prices a call on the open web without running it: no fetch, no charge, the same answer for the same input.
ESTIMATE = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
# Reads of the caller's own Clawifi account state; they touch only Clawifi's API.
ACCOUNT_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def _client() -> Clawifi:
    return Clawifi()


def _question(query: str | None, top_k: int) -> dict[str, Any]:
    return {"query": query, "top_k": top_k} if query and query.strip() else {}


@mcp.tool(title="Fetch a URL", annotations=WEB_READ)
def fetch(url: str, query: str | None = None, top_k: int = 5, timeout_seconds: int = 15) -> dict[str, Any]:
    """Fetch a single URL and return its extracted content. With query, the text is only the top_k passages
    that answer it, and data.query_selection gives their place in the page."""
    with _client() as client:
        return client.fetch(url, timeout_seconds=timeout_seconds, **_question(query, top_k))


@mcp.tool(title="Scrape a URL", annotations=WEB_READ)
def scrape(url: str, query: str | None = None, top_k: int = 5, **kwargs: Any) -> dict[str, Any]:
    """Scrape a URL with source-aware routing and return structured content. With query, markdown and text are
    only the top_k passages that answer it."""
    with _client() as client:
        return client.scrape(url, **kwargs, **_question(query, top_k))


@mcp.tool(title="Free web search", annotations=WEB_READ)
def search_free(query: str) -> dict[str, Any]:
    """Run a free-tier web search and return results."""
    with _client() as client:
        return client.search_free(query)


@mcp.tool(title="Extract structured data", annotations=WEB_READ)
def extract(url: str, **kwargs: Any) -> dict[str, Any]:
    """Extract structured data from a URL."""
    with _client() as client:
        return client.extract(url, **kwargs)


@mcp.tool(title="Map a site's URLs", annotations=WEB_READ)
def map_site(url: str, **kwargs: Any) -> dict[str, Any]:
    """Map a site's discoverable URLs starting from a seed URL."""
    with _client() as client:
        return client.map(url, **kwargs)


@mcp.tool(title="Start a crawl", annotations=WEB_START)
def crawl(seed_url: str, **kwargs: Any) -> dict[str, Any]:
    """Start an asynchronous crawl from a seed URL. Returns a crawl_id to poll."""
    with _client() as client:
        return client.crawl(seed_url, **kwargs)


@mcp.tool(title="Estimate credits", annotations=ESTIMATE)
def estimate(operation: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Price a billable call without running it or charging for it (Clawifi API 1.7.0+). operation is one of
    fetch, scrape, extract, map, crawl, search_free or search_content; args are that operation's fields, for
    example {"url": "https://example.com"}, {"seed_url": ...} for crawl or {"query": ...} for the searches. Returns
    estimate {minimum, maximum, raises}, balance, would_402, would_429 and binding_limit; charged is 0."""
    try:
        with _client() as client:
            return client.estimate(operation, **(args or {}))
    except ClawifiDryRunUnsupportedError as exc:
        raise ToolError(str(exc)) from exc
    except ClawifiAPIError as exc:
        raise ToolError(_api_error_text(exc)) from exc
    except ClawifiTransportError as exc:
        raise ToolError(f"Clawifi API unreachable: {exc}") from exc
    except ValueError as exc:
        raise ToolError(f"{exc}. operation must be one of {', '.join(sorted(ESTIMATE_ROUTES))}") from exc


def _api_error_text(exc: ClawifiAPIError) -> str:
    parts = [str(exc)]
    if exc.status_code is not None:
        parts.append(f"status {exc.status_code}")
    if exc.code:
        parts.append(f"code {exc.code}")
    if exc.request_id:
        parts.append(f"request_id {exc.request_id}")
    return "; ".join(parts)


@mcp.tool(title="Get crawl status", annotations=ACCOUNT_READ)
def get_crawl(crawl_id: str) -> dict[str, Any]:
    """Get the current status and results of a crawl."""
    with _client() as client:
        return client.get_crawl(crawl_id)


@mcp.tool(title="Create a job", annotations=WEB_START)
def create_job(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create an asynchronous job for a billable operation. Returns a job_id to poll."""
    with _client() as client:
        return client.create_job(operation, payload)


@mcp.tool(title="Get job status", annotations=ACCOUNT_READ)
def get_job(job_id: str) -> dict[str, Any]:
    """Get the current status and results of a job."""
    with _client() as client:
        return client.get_job(job_id)


@mcp.tool(title="Account profile", annotations=ACCOUNT_READ)
def account() -> dict[str, Any]:
    """Get the authenticated account's profile and plan."""
    with _client() as client:
        return client.account()


@mcp.tool(title="Credit usage", annotations=ACCOUNT_READ)
def credits() -> dict[str, Any]:
    """Get the authenticated account's credit usage and remaining balance."""
    with _client() as client:
        return client.credits()


@mcp.tool(title="List request history", annotations=ACCOUNT_READ)
def list_history(**params: Any) -> dict[str, Any]:
    """List past requests for the authenticated account."""
    with _client() as client:
        return client.list_history(**params)


@mcp.tool(title="List monitors", annotations=ACCOUNT_READ)
def list_monitors(**params: Any) -> dict[str, Any]:
    """List configured Evidence Monitor checks for the authenticated account."""
    with _client() as client:
        return client.list_monitors(**params)


def run() -> None:
    if not os.getenv("CLAWIFI_API_KEY"):
        raise SystemExit(
            "CLAWIFI_API_KEY is required. Get one at https://clawifi.qzz.io/signup, "
            "then export CLAWIFI_API_KEY=... before starting this MCP server."
        )
    mcp.run()


if __name__ == "__main__":
    run()
