from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from clawifi.client import Clawifi

mcp = FastMCP("clawifi")


def _client() -> Clawifi:
    return Clawifi()


def _question(query: str | None, top_k: int) -> dict[str, Any]:
    return {"query": query, "top_k": top_k} if query and query.strip() else {}


@mcp.tool()
def fetch(url: str, query: str | None = None, top_k: int = 5, timeout_seconds: int = 15) -> dict[str, Any]:
    """Fetch a single URL and return its extracted content. With query, the text is only the top_k passages
    that answer it, and data.query_selection gives their place in the page."""
    with _client() as client:
        return client.fetch(url, timeout_seconds=timeout_seconds, **_question(query, top_k))


@mcp.tool()
def scrape(url: str, query: str | None = None, top_k: int = 5, **kwargs: Any) -> dict[str, Any]:
    """Scrape a URL with source-aware routing and return structured content. With query, markdown and text are
    only the top_k passages that answer it."""
    with _client() as client:
        return client.scrape(url, **kwargs, **_question(query, top_k))


@mcp.tool()
def search_free(query: str) -> dict[str, Any]:
    """Run a free-tier web search and return results."""
    with _client() as client:
        return client.search_free(query)


@mcp.tool()
def extract(url: str, **kwargs: Any) -> dict[str, Any]:
    """Extract structured data from a URL."""
    with _client() as client:
        return client.extract(url, **kwargs)


@mcp.tool()
def map_site(url: str, **kwargs: Any) -> dict[str, Any]:
    """Map a site's discoverable URLs starting from a seed URL."""
    with _client() as client:
        return client.map(url, **kwargs)


@mcp.tool()
def crawl(seed_url: str, **kwargs: Any) -> dict[str, Any]:
    """Start an asynchronous crawl from a seed URL. Returns a crawl_id to poll."""
    with _client() as client:
        return client.crawl(seed_url, **kwargs)


@mcp.tool()
def get_crawl(crawl_id: str) -> dict[str, Any]:
    """Get the current status and results of a crawl."""
    with _client() as client:
        return client.get_crawl(crawl_id)


@mcp.tool()
def create_job(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create an asynchronous job for a billable operation. Returns a job_id to poll."""
    with _client() as client:
        return client.create_job(operation, payload)


@mcp.tool()
def get_job(job_id: str) -> dict[str, Any]:
    """Get the current status and results of a job."""
    with _client() as client:
        return client.get_job(job_id)


@mcp.tool()
def account() -> dict[str, Any]:
    """Get the authenticated account's profile and plan."""
    with _client() as client:
        return client.account()


@mcp.tool()
def credits() -> dict[str, Any]:
    """Get the authenticated account's credit usage and remaining balance."""
    with _client() as client:
        return client.credits()


@mcp.tool()
def list_history(**params: Any) -> dict[str, Any]:
    """List past requests for the authenticated account."""
    with _client() as client:
        return client.list_history(**params)


@mcp.tool()
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
