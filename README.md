# clawifi

<!-- mcp-name: io.github.atakanelik34/clawifi-mcp -->

[![PyPI](https://img.shields.io/pypi/v/clawifi.svg)](https://pypi.org/project/clawifi/)
[![Python](https://img.shields.io/pypi/pyversions/clawifi.svg)](https://pypi.org/project/clawifi/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-server-purple.svg)](https://clawifi.dev/docs)
[![GitHub stars](https://img.shields.io/github/stars/atakanelik34/clawifi-mcp?style=flat)](https://github.com/atakanelik34/clawifi-mcp/stargazers)

Official Python SDK, CLI, and MCP server for [Clawifi](https://clawifi.dev), the agent-native internet gateway: one typed API and MCP surface for fetching, scraping, searching, and crawling the web on behalf of an agent, with Cloudflare-challenge handling and realistic browser fingerprinting behind it.

This package is a thin client over the hosted Clawifi API (hosted API version 1.7.2 at time of release). It does not include the Clawifi server, browser runtime, or Playwright — those run on Clawifi's infrastructure. Live capability evidence and uptime: [clawifi.dev/benchmarks](https://clawifi.dev/benchmarks) · [clawifi.dev/trust](https://clawifi.dev/trust) · [clawifi.dev/status](https://clawifi.dev/status).

## Install

```bash
pip install clawifi
```

## Get an API key

```bash
clawifi signup --email you@example.com --password "a strong password"
```

This creates an account, grants 1,000 free credits, and prints an API key. Export it:

```bash
export CLAWIFI_API_KEY="clawifi_live_..."
```

## Quicktest

```bash
clawifi quicktest --url https://example.com
```

## Set up your MCP client

```bash
clawifi init
```

finds the MCP clients installed on this machine (Claude Code, Codex, Cursor, Claude Desktop, VS Code) and prints, for each one, the install line for the local server (`clawifi-mcp`, stdio) and for the remote server, followed by a first call to try. It only prints; it never shows your key, only `$CLAWIFI_API_KEY` or a masked `clawifi_live_****`. `clawifi init --all` shows every client, found or not.

To have it edit a config file for you:

```bash
clawifi init --write cursor            # ~/.cursor/mcp.json, stdio entry
clawifi init --write cursor --remote   # ~/.cursor/mcp.json, remote entry
clawifi init --write claude-desktop    # claude_desktop_config.json, stdio entry
```

`--write` asks before it changes anything and copies the existing file to `<file>.bak-<timestamp>` first. Claude Code, Codex and VS Code have their own install commands, which `init` prints.

For Claude Code, for example:

```bash
# local (stdio)
claude mcp add --env CLAWIFI_API_KEY=$CLAWIFI_API_KEY --transport stdio clawifi -- clawifi-mcp
# remote
claude mcp add --transport http clawifi https://api.clawifi.dev/mcp --header "Authorization: Bearer $CLAWIFI_API_KEY"
```

## Use as an MCP server

The local MCP server runs as:

```bash
clawifi-mcp
```

reading `CLAWIFI_API_KEY` from the environment. `clawifi mcp config` prints a minimal config for it. Every tool carries a title and the MCP hints `readOnlyHint`, `destructiveHint`, `idempotentHint` and `openWorldHint`; none is destructive.

The billable tools (`fetch`, `scrape`, `extract`, `map_site`, `crawl`, `search_free`) take their common options as parameters and any other API field in `options`, which is merged into the request body. They refuse `dry_run`: use the `estimate` tool to price a call. Arguments a tool does not declare are refused rather than ignored.

## Remote MCP

Clawifi also runs a hosted MCP server, so nothing needs installing:

- URL: `https://api.clawifi.dev/mcp` (streamable HTTP)
- Auth: `Authorization: Bearer <your key>`, or the `X-Clawifi-Api-Key: <your key>` header

The old host `api.clawifi.qzz.io` (API and `/mcp`) keeps working, so `CLAWIFI_API_BASE=https://api.clawifi.qzz.io` and existing remote configs need no change.

Without a key the remote server offers a keyless tier of four tools, `search_free`, `fetch_url`, `scrape_url` and `map_site`, at 12 calls a minute and 50 a day per address. With a key you get the full tool list.

## Credits

Calls are charged per operation (a plain fetch is 1 credit, a browser render 3, a crawl 1 per page, and so on). See [clawifi.dev/pricing](https://clawifi.dev/pricing), or print the current table, which needs no key:

```bash
clawifi credits
```

The `credits` MCP tool and `client.credits()` show your own usage and balance instead.

## Use as a Python SDK

```python
from clawifi import Clawifi

client = Clawifi()  # reads CLAWIFI_API_KEY from the environment
page = client.fetch("https://example.com")
print(page["success"])
```

An async client is also available as `clawifi.AsyncClawifi`.

`search_content` searches and reads the top results; it is compact by default and `full=True` returns the full output:

```python
results = client.search_content("agent memory benchmarks", full=True)
```

Responses are returned as the API sends them, so fields such as `published_at`, `modified_at` and `fetched_at` come through untouched.

### Estimates (hosted API 1.7.0 and later)

```python
quote = client.estimate("fetch", url="https://example.com")
# {"dry_run": true, "route": "POST /fetch", "estimate": {"minimum": ..., "maximum": ..., "raises": [...]},
#  "balance": ..., "would_402": ..., "would_429": ..., "binding_limit": ..., "charged": 0}
client.crawl("https://example.com", max_pages=50, dry_run=True)
```

`estimate()` and `dry_run=True` work for `fetch`, `scrape`, `extract`, `map`, `crawl`, `search_free` and `search_content`. Before the first dry run the client checks the API version at `/product/manifest`; an API older than 1.7.0 would ignore `dry_run` and run (and bill) the call, so the client raises `ClawifiDryRunUnsupportedError` and sends nothing. Pre-releases such as `1.7.0rc1` count as older than 1.7.0.

`dry_run` is sent only when it is `True`, and only as the JSON boolean `true`: a normal call, or `dry_run=False`, has no `dry_run` key in its body, and a value that is not a bool raises `TypeError` before anything is sent. The API answers any `dry_run` key (even `false`) on a route that cannot dry-run with a 422, so `schema_assist` drops `dry_run=False` and refuses `dry_run=True`.

The `estimate` MCP tool does the same from an agent: `estimate(operation="fetch", args={"url": "https://example.com"})`.

### Rate limits

A `429` raises `ClawifiAPIError` with `retry_after` (seconds, from the `Retry-After` header) and `limit_scope` (which limit was hit, from `details.limit_scope`). Retryable calls wait out a `Retry-After` of up to 10 seconds before retrying; a longer one is raised straight away.

## MCP tools

| Tool | What it does |
| --- | --- |
| `fetch` | Fetch a single URL and return its extracted content. With `query`, only the passages that answer it. |
| `scrape` | Scrape a URL with source-aware routing and return structured content. With `query`, only the passages that answer it. |
| `search_free` | Run a free-tier web search and return results. |
| `extract` | Extract structured data from a URL. |
| `map_site` | Map a site's discoverable URLs starting from a seed URL. |
| `crawl` | Start an asynchronous crawl from a seed URL; returns a `crawl_id` to poll. |
| `estimate` | Price a `fetch`, `scrape`, `extract`, `map`, `crawl`, `search_free` or `search_content` call without running it or charging for it (hosted API 1.7.0+). |
| `get_crawl` | Get the current status and results of a crawl. |
| `create_job` | Create an asynchronous job for a billable operation; returns a `job_id` to poll. |
| `get_job` | Get the current status and results of a job. |
| `account` | Get the authenticated account's profile and plan. |
| `credits` | Get the authenticated account's credit usage and remaining balance. |
| `list_history` | List past requests for the authenticated account. |
| `list_monitors` | List configured Evidence Monitor checks for the authenticated account. |

## Documentation

See [clawifi.dev/docs](https://clawifi.dev/docs) for the full API reference, MCP tool list, and CLI command reference.

## License

MIT
