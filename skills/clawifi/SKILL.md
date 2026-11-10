---
name: clawifi
description: Search the web, read pages and PDFs, map and crawl sites, and watch pages for changes through Clawifi's hosted MCP server or HTTP API. Use when an agent needs current information from the public web with sources, only the passages that answer a question, or a page's text as Markdown.
---

# Clawifi: web access for AI agents

Clawifi searches many engines as one, reads pages and PDFs, and returns the passages that answer a question, each with its source. Site: https://clawifi.dev. Every page there has a Markdown twin (add `.md`), and https://clawifi.dev/llms-full.txt has all of them.

## Connect

- Hosted MCP server: `https://api.clawifi.dev/mcp` (streamable HTTP).
- Sign-in: MCP sign-in (OAuth 2.1). The free tools answer without an account; the first call that needs one asks the person to sign in or create a free account (1,000 credits a month, no card).
- Clients without MCP sign-in send `Authorization: Bearer <key>` with a key from https://clawifi.dev/account.
- One line per client: https://clawifi.dev/install.md
  - Claude Code: `claude mcp add --transport http clawifi https://api.clawifi.dev/mcp`, then `/mcp` to sign in.
  - Codex: `codex mcp add clawifi --url https://api.clawifi.dev/mcp`, then `codex mcp login clawifi`.
- HTTP API: JSON over HTTPS at `https://api.clawifi.dev` with the key as a bearer token. Reference: https://clawifi.dev/api-reference.md

## Which tool

| Need | Tool (HTTP route) |
|---|---|
| Find pages on a topic | `search_free` (`POST /search/free`): free engines first, merged by rank; optional `include_domains`, `exclude_domains`, `time_range` |
| Read one page or PDF as Markdown | `fetch_url` (`POST /fetch`) |
| Only the passages that answer a question | `fetch_url` or `scrape_url` with `query` and `top_k` |
| The whole page, not just the main content | `fetch_url` with `content_scope: "full"` (scripts and styles removed) |
| A page that only appears once JavaScript runs | `fetch_url` with `render: "auto"` (browser only for a JavaScript shell; `"always"` always renders; needs a key) |
| Structured fields from a page | `extract_url` (`POST /extract`) |
| All URLs of a site | `map_site` (`POST /map`) |
| Many pages of a site | `start_crawl` then `get_crawl` (`POST /crawl`) |
| Long work in the background | `create_job` then `get_job` |
| Earlier calls and their results | `list_history`, `read_artifact` |
| Balance and plan | `credits`, `account` |
| Price of a call before running it | `estimate`, or `"dry_run": true` on any paid HTTP call |

## What comes back

Every endpoint page lists the fields it returns and the ones it does not: [search](https://clawifi.dev/docs/api/post-search-free.md), [fetch](https://clawifi.dev/docs/api/post-fetch.md), [scrape](https://clawifi.dev/docs/api/post-scrape.md), [extract](https://clawifi.dev/docs/api/post-extract.md).

- Search results carry `url`, `title`, `snippet`, `rank`, `provider` and, when the engine gives a date, `published_at` / `modified_at`. No page text: read a result with `fetch_url`. An identical search within 60 seconds answers from the cache with `cache_hit: true` for 0 credits.
- A page read carries `data.title`, `data.content_markdown`, `data.content_text`, `data.published_at` / `modified_at` when the page gives them, `data.fetched_at`, and `content_status` (`ok`, `thin`, `blocked`, `needs_javascript`, `not_found`). `data.page_text_chars` and `data.content_chars` say how much text the page had and how much was returned, `data.scope_used` says what the content covers (`main`, `whole`, `selector` or `full`) and `data.language` is the page's `<html lang>`. Not returned: `author`, a summary, favicon or `og:image`, a links list (use `scrape_url` with the `links` format).

Monitoring is on the HTTP API. A page monitor checks a page on a schedule, from every 5 minutes to once a month (`include_selectors` limits it to part of the page). A search monitor (`kind: "search"` with `query`) runs a search at most hourly and reports only results it has not seen before. Either can email its creator (`notify_email: true`) or call a signed webhook on change. Price it with `POST /monitors/estimate` (free), create it with `POST /monitors`, then read `GET /monitors/{id}/diffs`. `list_monitors` lists them over MCP. Details: https://clawifi.dev/docs/monitors.md

## Costs

Most calls cost 1 credit. Asking a question about a page (`query`) adds nothing. A page or search with nothing to read costs 0, and failures on Clawifi's side are free. A page that needs the browser costs 3 (`render: "auto"` charges 3 only when it actually renders; `"always"` always does), and a PDF costs 2 for 1 to 50 pages. A crawl costs 1 per page, and a monitor check costs 1 (3 with the browser). `research` costs 30 to 300. A repeated identical search within 60 seconds is a cache hit and costs 0. Every response says what it charged in `X-Clawifi-Credits-Charged`. `"dry_run": true` (or `estimate`) quotes a call before it runs, a `render: "auto"` fetch included. Full table: https://clawifi.dev/pricing.md

## Rules for agents

- Prefer `query` + `top_k` over reading whole pages: fewer tokens, same cost. Ask for `content_scope: "full"` only when the main content misses what you need (compare `content_chars` with `page_text_chars`).
- Leave `render` at `"never"` unless `content_status` came back `needs_javascript`; then retry with `render: "auto"`.
- Price expensive calls (`research`, large crawls) with `estimate` or `dry_run` first, and ask the person before running them.
- Cite the URL of every passage you use.
- Clawifi reads public pages. It does not bypass logins, paywalls, bot protection or CAPTCHAs; a blocked page answers with the reason (`content_status`, `block_type`) and costs nothing.
