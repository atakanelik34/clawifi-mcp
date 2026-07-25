# clawifi

<!-- mcp-name: io.github.atakanelik34/clawifi-mcp -->

Official Python SDK, CLI, and MCP server for [Clawifi](https://clawifi.qzz.io), the agent-native internet gateway.

This package is a thin client over the hosted Clawifi API. It does not include the Clawifi server, browser runtime, or Playwright — those run on Clawifi's infrastructure.

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

## Documentation

See [clawifi.qzz.io/docs](https://clawifi.qzz.io/docs) for the full API reference, MCP tool list, and CLI command reference.

## License

MIT
