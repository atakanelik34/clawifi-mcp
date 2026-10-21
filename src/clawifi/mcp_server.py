from __future__ import annotations

import os
from typing import Annotated, Any, Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from clawifi.client import ESTIMATE_ROUTES, Clawifi
from clawifi.errors import ClawifiAPIError, ClawifiError, ClawifiTransportError, redact

class _StrictFastMCP(FastMCP):
    """FastMCP that refuses arguments a tool does not declare. FastMCP drops them, so {"kwargs": {"dry_run": true}}
    (the 0.3.0 pre-release schema) or a misspelt option would run the call as if it had not been given."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        declared = {tool.name: set(tool.inputSchema.get("properties", {})) for tool in await self.list_tools()}
        if name in declared:
            unknown = sorted(set(arguments or {}) - declared[name])
            if unknown:
                hint = " (put other API fields in options)" if "options" in declared[name] else ""
                raise ToolError(f"{name} does not take {', '.join(unknown)}{hint}; nothing was sent")
        return await super().call_tool(name, arguments)


mcp = _StrictFastMCP("clawifi")

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


NO_DRY_RUN = "dry_run is not supported on this tool; use the estimate tool to price a call"
# Shown in every billable tool's schema so an agent sees it is refused rather than silently ignored (FastMCP drops
# unknown arguments, which would turn an intended dry run into a real, billed call).
DryRun = Annotated[Any, Field(description="Not supported here: leave it out and use the estimate tool to price a call.")]
Options = Annotated[
    dict[str, Any] | None,
    Field(description="Other API fields for this operation, merged into the request body as they are (see the Clawifi API docs)."),
]


def _call(fn: Callable[[Clawifi], dict[str, Any]]) -> dict[str, Any]:
    """Run fn with a fresh client; Clawifi errors become tool errors whose text never carries a key."""
    try:
        with _client() as client:
            return fn(client)
    except ClawifiAPIError as exc:
        raise ToolError(_api_error_text(exc)) from exc
    except ClawifiTransportError as exc:
        raise ToolError(redact(f"Clawifi API unreachable: {exc}")) from exc
    except ClawifiError as exc:
        raise ToolError(redact(exc)) from exc


def _body(first: tuple[str, Any], dry_run: Any, options: dict[str, Any] | None, **fields: Any) -> dict[str, Any]:
    """The request fields: the explicit ones that are set, then options. dry_run is refused wherever it appears,
    and an option may not repeat a field already given."""
    if dry_run is not None or (options and "dry_run" in options):
        raise ToolError(NO_DRY_RUN)
    body = {key: value for key, value in fields.items() if value is not None}
    for key, value in (options or {}).items():
        if key == first[0] or key in body:
            raise ToolError(f"options.{key} repeats a parameter of this tool; pass it once, as the parameter")
        body[key] = value
    return body


def _question(query: str | None, top_k: int) -> dict[str, Any]:
    return {"query": query, "top_k": top_k} if query and query.strip() else {}


@mcp.tool(title="Fetch a URL", annotations=WEB_READ)
def fetch(url: str, query: str | None = None, top_k: int = 5, timeout_seconds: int = 15, options: Options = None, dry_run: DryRun = None) -> dict[str, Any]:
    """Fetch a single URL and return its extracted content. With query, the text is only the top_k passages
    that answer it, and data.query_selection gives their place in the page."""
    body = _body(("url", url), dry_run, options, timeout_seconds=timeout_seconds, **_question(query, top_k))
    return _call(lambda client: client.fetch(url, **body))


@mcp.tool(title="Scrape a URL", annotations=WEB_READ)
def scrape(
    url: str,
    query: str | None = None,
    top_k: int = 5,
    formats: list[str] | None = None,
    mode: str | None = None,
    timeout_seconds: int | None = None,
    wait_for_selector: str | None = None,
    target_selector: str | None = None,
    options: Options = None,
    dry_run: DryRun = None,
) -> dict[str, Any]:
    """Scrape a URL with source-aware routing and return structured content. formats defaults to ["markdown"].
    With query, markdown and text are only the top_k passages that answer it."""
    body = _body(
        ("url", url), dry_run, options, formats=formats, mode=mode, timeout_seconds=timeout_seconds,
        wait_for_selector=wait_for_selector, target_selector=target_selector, **_question(query, top_k),
    )
    return _call(lambda client: client.scrape(url, **body))


@mcp.tool(title="Free web search", annotations=WEB_READ)
def search_free(query: str, options: Options = None, dry_run: DryRun = None) -> dict[str, Any]:
    """Run a free-tier web search and return results."""
    body = _body(("query", query), dry_run, options)
    return _call(lambda client: client.search_free(query, **body))


@mcp.tool(title="Extract structured data", annotations=WEB_READ)
def extract(
    url: str,
    extraction_schema: Annotated[dict[str, Any] | None, Field(description="Fields to extract: {name: {type, selector, ...}}; sent as the API's schema.")] = None,
    preset: str | None = None,
    timeout_seconds: int | None = None,
    options: Options = None,
    dry_run: DryRun = None,
) -> dict[str, Any]:
    """Extract structured data from a URL, with an extraction schema or a preset (or neither, for the defaults)."""
    body = _body(("url", url), dry_run, options, schema=extraction_schema, preset=preset, timeout_seconds=timeout_seconds)
    return _call(lambda client: client.extract(url, **body))


@mcp.tool(title="Map a site's URLs", annotations=WEB_READ)
def map_site(
    url: str,
    search: str | None = None,
    max_urls: int | None = None,
    same_domain_only: bool | None = None,
    timeout_seconds: int | None = None,
    options: Options = None,
    dry_run: DryRun = None,
) -> dict[str, Any]:
    """Map a site's discoverable URLs starting from a seed URL. search ranks them by relevance to a phrase."""
    body = _body(("url", url), dry_run, options, search=search, max_urls=max_urls, same_domain_only=same_domain_only, timeout_seconds=timeout_seconds)
    return _call(lambda client: client.map(url, **body))


@mcp.tool(title="Start a crawl", annotations=WEB_START)
def crawl(
    seed_url: str,
    max_pages: int | None = None,
    max_depth: int | None = None,
    same_domain_only: bool | None = None,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    options: Options = None,
    dry_run: DryRun = None,
) -> dict[str, Any]:
    """Start an asynchronous crawl from a seed URL. Returns a crawl_id to poll. Each page is billed; use the
    estimate tool first to price it."""
    body = _body(
        ("seed_url", seed_url), dry_run, options, max_pages=max_pages, max_depth=max_depth, same_domain_only=same_domain_only,
        include_patterns=include_patterns, exclude_patterns=exclude_patterns,
    )
    return _call(lambda client: client.crawl(seed_url, **body))


@mcp.tool(title="Estimate credits", annotations=ESTIMATE)
def estimate(operation: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Price a billable call without running it or charging for it (Clawifi API 1.7.0+). operation is one of
    fetch, scrape, extract, map, crawl, search_free or search_content; args are that operation's fields, for
    example {"url": "https://example.com"}, {"seed_url": ...} for crawl or {"query": ...} for the searches. Returns
    estimate {minimum, maximum, raises}, balance, would_402, would_429 and binding_limit; charged is 0."""
    if operation not in ESTIMATE_ROUTES:
        raise ToolError(f"unknown operation {operation!r}; expected one of {', '.join(sorted(ESTIMATE_ROUTES))}")
    fields = dict(args or {})
    if "operation" in fields:
        raise ToolError("args.operation is not allowed; name the operation once, in operation")
    if "dry_run" in fields:
        raise ToolError("args.dry_run is not allowed; estimate always prices the call without running it")
    return _call(lambda client: client.estimate(operation, **fields))


def _api_error_text(exc: ClawifiAPIError) -> str:
    parts = [str(exc)]
    if exc.status_code is not None:
        parts.append(f"status {exc.status_code}")
    if exc.code:
        parts.append(f"code {exc.code}")
    if exc.request_id:
        parts.append(f"request_id {exc.request_id}")
    return redact("; ".join(parts))


@mcp.tool(title="Get crawl status", annotations=ACCOUNT_READ)
def get_crawl(crawl_id: str) -> dict[str, Any]:
    """Get the current status and results of a crawl."""
    return _call(lambda client: client.get_crawl(crawl_id))


@mcp.tool(title="Create a job", annotations=WEB_START)
def create_job(operation: str, payload: dict[str, Any], dry_run: DryRun = None) -> dict[str, Any]:
    """Create an asynchronous job for a billable operation. Returns a job_id to poll."""
    if dry_run is not None or "dry_run" in payload:
        raise ToolError(NO_DRY_RUN)
    return _call(lambda client: client.create_job(operation, payload))


@mcp.tool(title="Get job status", annotations=ACCOUNT_READ)
def get_job(job_id: str) -> dict[str, Any]:
    """Get the current status and results of a job."""
    return _call(lambda client: client.get_job(job_id))


@mcp.tool(title="Account profile", annotations=ACCOUNT_READ)
def account() -> dict[str, Any]:
    """Get the authenticated account's profile and plan."""
    return _call(lambda client: client.account())


@mcp.tool(title="Credit usage", annotations=ACCOUNT_READ)
def credits() -> dict[str, Any]:
    """Get the authenticated account's credit usage and remaining balance."""
    return _call(lambda client: client.credits())


@mcp.tool(title="List request history", annotations=ACCOUNT_READ)
def list_history(
    limit: int | None = None,
    cursor: str | None = None,
    operation: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> dict[str, Any]:
    """List past requests for the authenticated account, newest first. Filters: operation (e.g. search_free),
    status, kind and a created_after/created_before window (ISO 8601); pass next_cursor back as cursor."""
    params = {key: value for key, value in dict(limit=limit, cursor=cursor, operation=operation, status=status, kind=kind, created_after=created_after, created_before=created_before).items() if value is not None}
    return _call(lambda client: client.list_history(**params))


@mcp.tool(title="List monitors", annotations=ACCOUNT_READ)
def list_monitors(limit: int | None = None, include_deleted: bool | None = None) -> dict[str, Any]:
    """List configured Evidence Monitor checks for the authenticated account."""
    params = {key: value for key, value in dict(limit=limit, include_deleted=include_deleted).items() if value is not None}
    return _call(lambda client: client.list_monitors(**params))


def run() -> None:
    if not os.getenv("CLAWIFI_API_KEY"):
        raise SystemExit(
            "CLAWIFI_API_KEY is required. Get one at https://clawifi.qzz.io/signup, "
            "then export CLAWIFI_API_KEY=... before starting this MCP server."
        )
    mcp.run()


if __name__ == "__main__":
    run()
