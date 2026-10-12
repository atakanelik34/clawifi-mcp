# clawifi

<!-- mcp-name: io.github.atakanelik34/clawifi-mcp -->

[![PyPI](https://img.shields.io/pypi/v/clawifi.svg)](https://pypi.org/project/clawifi/)
[![Python](https://img.shields.io/pypi/pyversions/clawifi.svg)](https://pypi.org/project/clawifi/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-server-purple.svg)](https://clawifi.qzz.io/docs)
[![GitHub stars](https://img.shields.io/github/stars/atakanelik34/clawifi-mcp?style=flat)](https://github.com/atakanelik34/clawifi-mcp/stargazers)

Official Python SDK, CLI, and MCP server for [Clawifi](https://clawifi.qzz.io), the agent-native internet gateway: one typed API and MCP surface for fetching, scraping, searching, and crawling the web on behalf of an agent, with Cloudflare-challenge handling and realistic browser fingerprinting behind it.

This package is a thin client over the hosted Clawifi API (hosted API version 1.2.0 at time of release). It does not include the Clawifi server, browser runtime, or Playwright — those run on Clawifi's infrastructure. Live capability evidence and uptime: [clawifi.qzz.io/benchmarks](https://clawifi.qzz.io/benchmarks) · [clawifi.qzz.io/trust](https://clawifi.qzz.io/trust) · [clawifi.qzz.io/status](https://clawifi.qzz.io/status).

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

## Use as an MCP server

```bash
clawifi mcp config
```

prints a ready-to-paste MCP client config. The MCP server itself runs as:

```bash
clawifi-mcp
```

reading `CLAWIFI_API_KEY` from the environment.

## Use as a Python SDK

```python
from clawifi import Clawifi

client = Clawifi()  # reads CLAWIFI_API_KEY from the environment
page = client.fetch("https://example.com")
print(page["success"])
```

An async client is also available as `clawifi.AsyncClawifi`.

## MCP tools

| Tool | What it does |
| --- | --- |
| `fetch` | Fetch a single URL and return its extracted content. |
| `scrape` | Scrape a URL with source-aware routing and return structured content. |
| `search_free` | Run a free-tier web search and return results. |
| `extract` | Extract structured data from a URL. |
| `map_site` | Map a site's discoverable URLs starting from a seed URL. |
| `crawl` | Start an asynchronous crawl from a seed URL; returns a `crawl_id` to poll. |
| `get_crawl` | Get the current status and results of a crawl. |
| `create_job` | Create an asynchronous job for a billable operation; returns a `job_id` to poll. |
| `get_job` | Get the current status and results of a job. |
| `account` | Get the authenticated account's profile and plan. |
| `credits` | Get the authenticated account's credit usage and remaining balance. |
| `list_history` | List past requests for the authenticated account. |
| `list_monitors` | List configured Evidence Monitor checks for the authenticated account. |

## Documentation

See [clawifi.qzz.io/docs](https://clawifi.qzz.io/docs) for the full API reference, MCP tool list, and CLI command reference.

## License

MIT
