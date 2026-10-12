from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request


DEFAULT_API_BASE = "https://api.clawifi.qzz.io"


def run(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="clawifi", description="Clawifi cloud CLI for agent internet reach.")
    parser.add_argument("--api-base", default=os.getenv("CLAWIFI_API_BASE", DEFAULT_API_BASE))
    subcommands = parser.add_subparsers(dest="command", required=True)

    signup = subcommands.add_parser("signup", help="Create a Clawifi account and first API key.")
    signup.add_argument("--email", required=True)
    signup.add_argument("--password", required=True)
    signup.add_argument("--display-name")

    login = subcommands.add_parser("login", help="Create an account session token.")
    login.add_argument("--email", required=True)
    login.add_argument("--password", required=True)

    verify = subcommands.add_parser("verify-email", help="Verify your Clawifi email token and create an API key.")
    verify.add_argument("--token", required=True)

    quicktest = subcommands.add_parser("quicktest", help="Verify your API key against the Clawifi API.")
    quicktest.add_argument("--url", default="https://example.com")

    mcp = subcommands.add_parser("mcp", help="Print MCP setup helpers.")
    mcp_subcommands = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_subcommands.add_parser("config", help="Print a minimal MCP server config.")

    browser = subcommands.add_parser("browser", help="Manage Clawifi browser runtime sessions.")
    browser_subcommands = browser.add_subparsers(dest="browser_command", required=True)
    browser_pair = browser_subcommands.add_parser("pair", help="Create a short-lived WebBridge pairing code.")
    browser_pair.add_argument(
        "--local-api-base",
        default=os.getenv("CLAWIFI_LOCAL_API_BASE", "http://127.0.0.1:8000"),
    )
    browser_doctor = browser_subcommands.add_parser(
        "doctor", help="Run browser runtime and agent configuration diagnostics."
    )
    browser_doctor.add_argument(
        "--verbose",
        action="store_true",
        help="Include the complete check report (currently the default output).",
    )
    browser_doctor.add_argument(
        "--local-api-base",
        default=os.getenv("CLAWIFI_LOCAL_API_BASE", "http://127.0.0.1:8000"),
    )
    browser_start = browser_subcommands.add_parser("start", help="Start a managed headed or headless browser session.")
    browser_start.add_argument("--url", required=True)
    browser_start.add_argument("--mode", choices=("headless", "headed"), default="headless")
    browser_start.add_argument("--profile-id")
    browser_start.add_argument("--ttl-seconds", type=int, default=300)
    browser_start.add_argument(
        "--local-api-base",
        default=os.getenv("CLAWIFI_LOCAL_API_BASE", "http://127.0.0.1:8000"),
    )
    browser_status = browser_subcommands.add_parser("status", help="List browser sessions or inspect one session.")
    browser_status.add_argument("session_id", nargs="?")
    browser_status.add_argument(
        "--local-api-base",
        default=os.getenv("CLAWIFI_LOCAL_API_BASE", "http://127.0.0.1:8000"),
    )
    browser_stop = browser_subcommands.add_parser("stop", help="Close one or all browser sessions.")
    browser_stop_target = browser_stop.add_mutually_exclusive_group(required=True)
    browser_stop_target.add_argument("session_id", nargs="?")
    browser_stop_target.add_argument("--all", action="store_true")
    browser_stop.add_argument(
        "--local-api-base",
        default=os.getenv("CLAWIFI_LOCAL_API_BASE", "http://127.0.0.1:8000"),
    )
    browser_smoke = browser_subcommands.add_parser("smoke", help="Create, verify, and always close a browser session.")
    browser_smoke.add_argument("--url", default="https://example.com")
    browser_smoke.add_argument("--mode", choices=("headless", "headed"), default="headless")
    browser_smoke.add_argument("--profile-id")
    browser_smoke.add_argument("--ttl-seconds", type=int, default=300)
    browser_smoke.add_argument(
        "--local-api-base",
        default=os.getenv("CLAWIFI_LOCAL_API_BASE", "http://127.0.0.1:8000"),
    )

    monitors = subcommands.add_parser("monitors", help="Manage Evidence Monitor checks.")
    monitor_subcommands = monitors.add_subparsers(dest="monitor_command", required=True)
    monitor_create = monitor_subcommands.add_parser("create", help="Create a monitor.")
    monitor_create.add_argument("--name", required=True)
    monitor_create.add_argument("--url", required=True)
    monitor_create.add_argument("--interval-seconds", type=int, default=900)
    monitor_create.add_argument("--format", dest="formats", action="append", default=None)
    monitor_create.add_argument("--diff-mode", dest="diff_modes", action="append", default=None)
    monitor_create.add_argument("--json", action="store_true")
    monitor_list = monitor_subcommands.add_parser("list", help="List monitors.")
    monitor_list.add_argument("--include-deleted", action="store_true")
    monitor_list.add_argument("--json", action="store_true")
    monitor_get = monitor_subcommands.add_parser("get", help="Get one monitor.")
    monitor_get.add_argument("monitor_id")
    monitor_get.add_argument("--json", action="store_true")
    monitor_pause = monitor_subcommands.add_parser("pause", help="Pause a monitor.")
    monitor_pause.add_argument("monitor_id")
    monitor_pause.add_argument("--json", action="store_true")
    monitor_resume = monitor_subcommands.add_parser("resume", help="Resume a monitor.")
    monitor_resume.add_argument("monitor_id")
    monitor_resume.add_argument("--run-immediately", action="store_true")
    monitor_resume.add_argument("--json", action="store_true")
    monitor_delete = monitor_subcommands.add_parser("delete", help="Delete a monitor.")
    monitor_delete.add_argument("monitor_id")
    monitor_delete.add_argument("--json", action="store_true")
    monitor_run = monitor_subcommands.add_parser("run", help="Run a monitor now.")
    monitor_run.add_argument("monitor_id")
    monitor_run.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    api_base = args.api_base.rstrip("/")

    if args.command == "signup":
        payload = _request(
            "POST",
            f"{api_base}/auth/signup",
            json_body={"email": args.email, "password": args.password, "display_name": args.display_name},
        )
        print("Clawifi account created.")
        print(f"Email: {payload['account']['email']}")
        print(f"Credits: {payload['credits']['available']}")
        if payload.get("requires_email_verification"):
            print("Email verification is required before an API key is issued.")
            return
        print("Set this key in your agent runtime:")
        print(f"export CLAWIFI_API_KEY={payload['api_key']}")
        raise SystemExit(0)

    if args.command == "verify-email":
        payload = _request("POST", f"{api_base}/auth/verify-email", json_body={"token": args.token})
        print("Clawifi email verified.")
        print(f"Email: {payload['account']['email']}")
        print(f"Credits: {payload['credits']['available']}")
        print(f"export CLAWIFI_SESSION_TOKEN={payload['session_token']}")
        print(f"export CLAWIFI_API_KEY={payload['api_key']}")
        raise SystemExit(0)

    if args.command == "login":
        payload = _request(
            "POST",
            f"{api_base}/auth/login",
            json_body={"email": args.email, "password": args.password},
        )
        print("Clawifi session created.")
        print(f"Session expires: {payload['session_expires_at']}")
        print(f"export CLAWIFI_SESSION_TOKEN={payload['session_token']}")
        raise SystemExit(0)

    if args.command == "quicktest":
        api_key = _required_api_key()
        payload = _request(
            "POST",
            f"{api_base}/fetch",
            token=api_key,
            json_body={"url": args.url, "timeout_seconds": 15},
        )
        print(json.dumps({"ok": True, "success": payload.get("success"), "source": payload.get("source")}, indent=2))
        raise SystemExit(0)

    if args.command == "mcp" and args.mcp_command == "config":
        _required_api_key()
        print(json.dumps({
            "mcpServers": {
                "clawifi": {
                    "command": "clawifi-mcp",
                    "env": {
                        "CLAWIFI_API_KEY": "${CLAWIFI_API_KEY}",
                        "CLAWIFI_API_BASE": api_base
                    }
                }
            }
        }, indent=2))
        raise SystemExit(0)

    if args.command == "browser":
        api_key = _required_api_key()
        local_api_base = args.local_api_base.rstrip("/")
        if args.browser_command == "pair":
            payload = _request(
                "POST",
                f"{local_api_base}/browser/bridge/pairing",
                token=api_key,
                json_body={},
            )
            print("One-time WebBridge pairing code:")
            print(payload["code"])
            print(f"Expires in {payload['expires_in_seconds']} seconds.")
            print("Paste it into the Clawifi WebBridge extension. It can be used once.")
        elif args.browser_command == "doctor":
            payload = _request("GET", f"{local_api_base}/browser/doctor", token=api_key)
            print(json.dumps(payload, indent=2, sort_keys=True))
            if not payload.get("ok", False):
                raise SystemExit(1)
        elif args.browser_command == "start":
            request_payload = {
                "url": args.url,
                "mode": args.mode,
                "ttl_seconds": args.ttl_seconds,
                **({"profile_id": args.profile_id} if args.profile_id else {}),
            }
            payload = _request(
                "POST",
                f"{local_api_base}/browser/sessions",
                token=api_key,
                json_body=request_payload,
            )
            print(json.dumps(payload, indent=2, sort_keys=True))
        elif args.browser_command == "status":
            suffix = f"/{args.session_id}" if args.session_id else ""
            payload = _request("GET", f"{local_api_base}/browser/sessions{suffix}", token=api_key)
            print(json.dumps(payload, indent=2, sort_keys=True))
        elif args.browser_command == "stop":
            if args.all:
                payload = _request(
                    "DELETE",
                    f"{local_api_base}/browser/sessions",
                    token=api_key,
                    json_body={"session_ids": None},
                )
            else:
                payload = _request(
                    "DELETE",
                    f"{local_api_base}/browser/sessions/{args.session_id}",
                    token=api_key,
                )
            print(json.dumps(payload, indent=2, sort_keys=True))
        elif args.browser_command == "smoke":
            request_payload = {
                "url": args.url,
                "mode": args.mode,
                "ttl_seconds": args.ttl_seconds,
                **({"profile_id": args.profile_id} if args.profile_id else {}),
            }
            created = _request(
                "POST",
                f"{local_api_base}/browser/sessions",
                token=api_key,
                json_body=request_payload,
            )
            session_id = created.get("session_id")
            cleanup = None
            try:
                if not session_id or created.get("status") != "ready":
                    raise SystemExit("Browser smoke failed: session did not become ready")
            finally:
                if session_id:
                    cleanup = _request(
                        "DELETE",
                        f"{local_api_base}/browser/sessions/{session_id}",
                        token=api_key,
                    )
            print(json.dumps({"ok": True, "session": created, "cleanup": cleanup}, indent=2, sort_keys=True))
        raise SystemExit(0)

    if args.command == "monitors":
        api_key = _required_api_key()
        if args.monitor_command == "create":
            payload = _request(
                "POST",
                f"{api_base}/monitors",
                token=api_key,
                json_body={
                    "name": args.name,
                    "url": args.url,
                    "schedule": {"interval_seconds": args.interval_seconds},
                    "formats": args.formats or ["markdown", "text", "metadata", "links"],
                    "diff_modes": args.diff_modes or ["text"],
                },
            )
            _print_monitor_payload(payload, as_json=args.json)
        elif args.monitor_command == "list":
            suffix = "?include_deleted=true" if args.include_deleted else ""
            payload = _request("GET", f"{api_base}/monitors{suffix}", token=api_key)
            _print_monitor_payload(payload, as_json=args.json)
        elif args.monitor_command == "get":
            payload = _request("GET", f"{api_base}/monitors/{args.monitor_id}", token=api_key)
            _print_monitor_payload(payload, as_json=args.json)
        elif args.monitor_command == "pause":
            payload = _request("POST", f"{api_base}/monitors/{args.monitor_id}/pause", token=api_key, json_body={})
            _print_monitor_payload(payload, as_json=args.json)
        elif args.monitor_command == "resume":
            payload = _request(
                "POST",
                f"{api_base}/monitors/{args.monitor_id}/resume",
                token=api_key,
                json_body={"run_immediately": args.run_immediately},
            )
            _print_monitor_payload(payload, as_json=args.json)
        elif args.monitor_command == "delete":
            payload = _request("DELETE", f"{api_base}/monitors/{args.monitor_id}", token=api_key)
            _print_monitor_payload(payload, as_json=args.json)
        elif args.monitor_command == "run":
            payload = _request("POST", f"{api_base}/monitors/{args.monitor_id}/run", token=api_key)
            _print_monitor_payload(payload, as_json=args.json)
        raise SystemExit(0)


def _required_api_key() -> str:
    api_key = os.getenv("CLAWIFI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("CLAWIFI_API_KEY is required. Run `clawifi signup --email you@example.com --password ...` first.")
    return api_key


def _request(method: str, url: str, *, json_body: dict | None = None, token: str | None = None) -> dict:
    body = json.dumps(json_body or {}, separators=(",", ":")).encode("utf-8") if json_body is not None else None
    headers = {"Content-Type": "application/json", "User-Agent": "clawifi-cli/0.1.2 (+https://clawifi.qzz.io)"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Clawifi API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Clawifi API unreachable: {exc.reason}") from exc


def _print_monitor_payload(payload: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if "monitors" in payload:
        print(f"Monitors: {payload.get('total', len(payload['monitors']))}")
        for monitor in payload["monitors"]:
            print(f"- {monitor.get('monitor_id')} {monitor.get('status')} {monitor.get('name')}")
        return
    label = payload.get("monitor_id") or payload.get("tick_id") or payload.get("status") or "ok"
    print(f"Monitor result: {label}")


if __name__ == "__main__":
    run()
