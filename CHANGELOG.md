# Changelog

## 0.3.0 (2026-10-21)

For hosted API 1.6.3; estimates need 1.7.0.

- MCP: every tool has a title and the `readOnlyHint`, `destructiveHint`, `idempotentHint` and `openWorldHint` annotations. Requires `mcp>=1.10.0,<2`.
- CLI: `clawifi init` finds Claude Code, Codex, Cursor, Claude Desktop and VS Code and prints local (stdio) and remote install lines for each, plus a first call. `--write cursor|claude-desktop` edits the config after confirmation and a backup. The key is never printed.
- CLI: `clawifi credits` prints the per-operation credit costs from `/billing/plans`.
- SDK: `estimate(operation, **args)` and `dry_run=` on `fetch`, `scrape`, `extract`, `map`, `crawl`, `search_free` and `search_content`. The client checks `/product/manifest` first and refuses to send `dry_run` to an API older than 1.7.0, which would run and bill the call.
- SDK: `search_content(query, full=...)`.
- SDK: `ClawifiAPIError.retry_after` (from `Retry-After`) and `ClawifiAPIError.limit_scope` (from `details.limit_scope`); retryable calls honour a `Retry-After` of up to 10 seconds.
- `server.json`: lists the remote MCP server `https://api.clawifi.qzz.io/mcp` (streamable HTTP).
- README: remote MCP, keyless tier, `init`, credits.

## 0.2.0

- `fetch` and `scrape` take `query` and `top_k` and return only the passages that answer it.
