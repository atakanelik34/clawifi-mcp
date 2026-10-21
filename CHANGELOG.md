# Changelog

## 0.3.1 (2026-10-22)

For hosted API 1.7.1. Metadata only, no code change.

- LICENSE names the copyright holder as ReARC Labs Inc. (0.3.0 shipped the older "ReARC Labs" text).

## 0.3.0 (2026-10-22)

For hosted API 1.7.0.

- MCP: every tool has a title and the `readOnlyHint`, `destructiveHint`, `idempotentHint` and `openWorldHint` annotations.
- MCP: `scrape`, `extract`, `map_site`, `crawl`, `list_history` and `list_monitors` take explicit, typed parameters instead of `**kwargs` (which FastMCP exposed as one required argument named `kwargs`, sent nested in the body). The billable tools take the common options as parameters plus `options`, a dict merged into the body at the top level; `extract`, `map_site` and `crawl` need only their URL. An option that repeats a parameter is refused.
- MCP: `dry_run` is refused on every billable tool, at the top level, in `options` or in a `create_job` payload, with "use the estimate tool to price a call"; nothing is sent. Arguments a tool does not declare are refused too, instead of being dropped by FastMCP and the call run without them.
- MCP: new `estimate` tool ("Estimate credits", read-only, idempotent, open-world): `estimate(operation, args)` wraps `client.estimate`. An unknown operation, `operation` or `dry_run` inside `args`, an API older than 1.7.0 and API or transport errors come back as tool errors; configuration errors (a malformed key) are not dressed up as operation errors.
- Requires `mcp>=1.21.1,<2`. With pydantic 2.14 (the newest, and what pip installs today), `mcp` 1.10.0 through 1.21.0 fails to import `mcp.server.fastmcp` (`ImportError: cannot import name 'eval_type_backport' from 'pydantic._internal._typing_extra'`); 1.21.1 is the first release that imports, lists all 14 tools with their titles and hints, and passes this test suite. Checked by installing every minor release from 1.10.0 to 1.30.0 (plus 1.10.1, 1.12.4, 1.13.1, 1.14.1, 1.21.1 and 1.21.2) into a fresh venv with the newest pydantic. (mcp 1.21.0 still works with pydantic 2.13 or older, but nothing stops pip pairing it with 2.14.)
- CLI: `clawifi init` finds Claude Code, Codex, Cursor, Claude Desktop and VS Code and prints local (stdio) and remote install lines for each, plus a first call. `--write cursor|claude-desktop` edits the config after confirmation and a backup. The key is never printed.
- CLI: `clawifi credits` prints the per-operation credit costs from `/billing/plans`.
- SDK: `estimate(operation, **args)` and `dry_run=` on `fetch`, `scrape`, `extract`, `map`, `crawl`, `search_free` and `search_content`. The client checks `/product/manifest` first and refuses to send `dry_run` to an API older than 1.7.0, which would run and bill the call; pre-releases (`1.7.0rc1`, `1.7.0a1`, `1.7.0b2`, `1.7.0.dev3`) count as older, `1.7.0.post1` does not.
- SDK: `dry_run` is sent only when it is `True`, as the JSON boolean `true`, and only to the routes that accept it. A normal call or `dry_run=False` sends no `dry_run` key (the API answers any `dry_run`, even `false`, on a route that cannot dry-run with 422); a non-bool `dry_run` raises `TypeError` before anything is sent; `schema_assist` drops `dry_run=False` and refuses `dry_run=True`.
- SDK: `search_content(query, full=...)`.
- SDK: after a dry run the client checks that the answer says `dry_run: true` and `charged: 0`; otherwise it raises `ClawifiDryRunIgnoredError` (the API ran the call, for example an older node during a rolling deploy, and may have billed it).
- SDK: the API key is stripped of surrounding whitespace (a pasted newline), and a key with inner whitespace, control or non-ASCII characters raises `ValueError` without echoing it. Every SDK and MCP error message has bearer tokens and `clawifi_live_`/`clawifi_test_` keys replaced by `***`.
- CLI: `clawifi init --write` writes the config through a 0600 temp file in the same directory and `os.replace`, so it ends 0600 whether it was new or not; backups are created 0600 with microsecond names (and a counter), so they never overwrite each other.
- SDK: `ClawifiAPIError.retry_after` (from `Retry-After`) and `ClawifiAPIError.limit_scope` (from `details.limit_scope`); retryable calls honour a `Retry-After` of up to 10 seconds.
- `server.json`: lists the remote MCP server `https://api.clawifi.qzz.io/mcp` (streamable HTTP); its Authorization header and key variable are both optional, since the remote server has a keyless tier.
- README: remote MCP, keyless tier, `init`, credits, estimates and the `estimate` tool.
- sdist: ships `CHANGELOG.md`, `server.json`, `tests/conftest.py` and the test fixtures (`MANIFEST.in`), so its test suite runs.

### Known limitations

- The API version check behind `estimate()` and `dry_run=True` is cached: once `/product/manifest` reports 1.7.0 or later, a `Clawifi` or `AsyncClawifi` client does not check again for the rest of its life (in practice, the process that holds it), so an API rolled back under a long-lived client is not noticed until a new client is made. The local MCP server makes a new client for each tool call, so its `estimate` tool checks on every call.
- `create_job` does not expose `dry_run`, although the API (1.7.0) accepts it on `POST /jobs`.

## 0.2.0

- `fetch` and `scrape` take `query` and `top_k` and return only the passages that answer it.
