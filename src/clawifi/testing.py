from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx


def fixture_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__).resolve()).parent
    for candidate in [current, *current.parents]:
        manifest = candidate / "tests" / "fixtures" / "sdk" / "manifest.json"
        if manifest.exists():
            return manifest.parent
    raise FileNotFoundError("could not locate tests/fixtures/sdk/manifest.json")


def load_fixture_manifest(root: Path | None = None) -> dict[str, Any]:
    manifest_path = (root or fixture_root()) / "manifest.json"
    return _load_json(manifest_path)


def fixture_transport(*, errors: set[str] | None = None, root: Path | None = None) -> httpx.MockTransport:
    fixture_dir = root or fixture_root()
    manifest = load_fixture_manifest(fixture_dir)
    routes = _routes_from_manifest(manifest)
    error_routes = errors or set()

    def handler(request: httpx.Request) -> httpx.Response:
        route_key = f"{request.method.upper()} {request.url.path}"
        metadata = routes.get(route_key)
        if metadata is None and route_key.startswith("GET /jobs/"):
            metadata = routes["POST /jobs"]
        if metadata is None and route_key.startswith("GET /crawls/"):
            metadata = routes["POST /crawl"]
        if metadata is None:
            return httpx.Response(404, json=_not_found_payload(route_key), headers={"X-Clawifi-Request-ID": "req_sdk_fixture"})

        fixture_name = metadata["error_fixture"] if route_key in error_routes else metadata["success_fixture"]
        status_code = 422 if route_key in error_routes else 200
        return httpx.Response(
            status_code,
            json=_load_json(fixture_dir / fixture_name),
            headers={"X-Clawifi-Request-ID": "req_sdk_fixture"},
        )

    return httpx.MockTransport(handler)


def _routes_from_manifest(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    operations = manifest.get("operations", {})
    return {f"{metadata['method'].upper()} {metadata['path']}": metadata for metadata in operations.values()}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"fixture must be a JSON object: {path}")
    return payload


def _not_found_payload(route_key: str) -> dict[str, Any]:
    return {
        "error": {
            "code": "fixture_not_found",
            "message": f"No SDK fixture exists for {route_key}",
            "details": {"request_id": "req_sdk_fixture", "retryable": False},
        }
    }
