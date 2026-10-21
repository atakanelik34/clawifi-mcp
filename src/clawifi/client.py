from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterator

import httpx

from clawifi.errors import ClawifiAPIError, ClawifiDryRunUnsupportedError, ClawifiTransportError, parse_retry_after

DEFAULT_API_BASE = "https://api.clawifi.qzz.io"
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}
TERMINAL_CRAWL_STATUSES = {"succeeded", "partial", "failed", "stopped", "interrupted"}
MAX_RETRY_AFTER_SECONDS = 10.0
DRY_RUN_MIN_API_VERSION = (1, 7, 0)
# Billable operations that accept dry_run, and the field their first argument fills. The API (1.7.0) also takes
# dry_run on POST /jobs; any other POST route answers 422 to a dry_run key, even false, so the client sends the key
# only here and only as the JSON boolean true.
ESTIMATE_ROUTES = {
    "fetch": ("/fetch", "url"),
    "scrape": ("/scrape", "url"),
    "extract": ("/extract", "url"),
    "map": ("/map", "url"),
    "crawl": ("/crawl", "seed_url"),
    "search_free": ("/search/free", "query"),
    "search_content": ("/search/content", "query"),
}


@dataclass(frozen=True)
class ClawifiConfig:
    api_key: str | None = None
    api_base: str = DEFAULT_API_BASE
    timeout: float = 30.0
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> "ClawifiConfig":
        timeout = float(os.getenv("CLAWIFI_TIMEOUT", "30"))
        max_retries = int(os.getenv("CLAWIFI_MAX_RETRIES", "2"))
        return cls(
            api_key=os.getenv("CLAWIFI_API_KEY"),
            api_base=os.getenv("CLAWIFI_API_BASE", DEFAULT_API_BASE).rstrip("/"),
            timeout=timeout,
            max_retries=max_retries,
        )

    def __repr__(self) -> str:
        masked = "***" if self.api_key else None
        return f"ClawifiConfig(api_key={masked!r}, api_base={self.api_base!r}, timeout={self.timeout!r}, max_retries={self.max_retries!r})"


class _BaseClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        config: ClawifiConfig | None = None,
    ) -> None:
        env_config = config or ClawifiConfig.from_env()
        self.config = ClawifiConfig(
            api_key=api_key if api_key is not None else env_config.api_key,
            api_base=(api_base or env_config.api_base).rstrip("/"),
            timeout=timeout if timeout is not None else env_config.timeout,
            max_retries=max_retries if max_retries is not None else env_config.max_retries,
        )
        self._dry_run_checked = False

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "clawifi/0.3.0"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.config.api_base}/{path.lstrip('/')}"

    @staticmethod
    def _should_retry(method: str, idempotent: bool, status_code: int, retry_after: float | None = None) -> bool:
        if retry_after is not None and retry_after > MAX_RETRY_AFTER_SECONDS:
            return False
        return (method.upper() in {"GET", "HEAD"} or idempotent) and status_code in RETRYABLE_STATUS_CODES

    def _check_dry_run_manifest(self, manifest: dict[str, Any] | None) -> None:
        version = str((manifest or {}).get("version") or "")
        if _version_tuple(version) < (*DRY_RUN_MIN_API_VERSION, 0):
            shown = version or "unknown"
            raise ClawifiDryRunUnsupportedError(
                f"dry_run needs Clawifi API 1.7.0 or later; {self.config.api_base} reports {shown}. "
                "An older API ignores dry_run and runs (and bills) the call, so nothing was sent."
            )
        self._dry_run_checked = True


class Clawifi(_BaseClient):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        config: ClawifiConfig | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(api_key=api_key, api_base=api_base, timeout=timeout, max_retries=max_retries, config=config)
        self._client = httpx.Client(timeout=self.config.timeout, transport=transport, headers=self._headers())

    @property
    def is_closed(self) -> bool:
        return self._client.is_closed

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Clawifi":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def request(self, method: str, path: str, *, json: dict[str, Any] | None = None, params: dict[str, Any] | None = None, idempotent: bool = False) -> dict[str, Any]:
        attempts = self.config.max_retries + 1
        for attempt in range(attempts):
            try:
                response = self._client.request(method, self._url(path), json=json, params=params)
            except httpx.HTTPError as exc:
                raise ClawifiTransportError(str(exc)) from exc
            if response.status_code < 400:
                return _decode_response(response)
            payload = _decode_response(response)
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            if attempt < attempts - 1 and self._should_retry(method, idempotent, response.status_code, retry_after):
                if retry_after:
                    time.sleep(retry_after)
                continue
            raise ClawifiAPIError.from_response(response.status_code, payload, request_id=response.headers.get("X-Clawifi-Request-ID"), retry_after=retry_after)
        raise ClawifiTransportError("request retry loop exited unexpectedly")

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("GET", path, params=params)

    def post(self, path: str, *, json: dict[str, Any] | None = None, idempotent: bool = False) -> dict[str, Any]:
        return self.request("POST", path, json=json, idempotent=idempotent)

    def _billable(self, operation: str, first: Any, kwargs: dict[str, Any], dry_run: bool) -> dict[str, Any]:
        path, field = ESTIMATE_ROUTES[operation]
        body = {field: first, **kwargs}
        if _dry_run_flag(dry_run):
            self._require_dry_run()
            body["dry_run"] = True
        return self.post(path, json=body, idempotent=True)

    def _require_dry_run(self) -> None:
        if self._dry_run_checked:
            return
        try:
            manifest = self.get("/product/manifest")
        except (ClawifiAPIError, ClawifiTransportError):
            manifest = None
        self._check_dry_run_manifest(manifest)

    def estimate(self, operation: str, **args: Any) -> dict[str, Any]:
        """Price a billable call without running it (Clawifi API 1.7.0+).

        operation is one of fetch, scrape, extract, map, crawl, search_free or search_content; args are that
        operation's fields (url=, seed_url= or query=, plus options). Returns estimate{minimum,maximum,raises},
        balance and would_402. Raises ClawifiDryRunUnsupportedError, without sending the call, on an older API.
        """
        if operation not in ESTIMATE_ROUTES:
            raise ValueError(f"unknown operation {operation!r}; expected one of {', '.join(sorted(ESTIMATE_ROUTES))}")
        path, _ = ESTIMATE_ROUTES[operation]
        self._require_dry_run()
        body = {key: value for key, value in args.items() if key != "dry_run"}
        return self.post(path, json={**body, "dry_run": True}, idempotent=True)

    def fetch(self, url: str, *, dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
        return self._billable("fetch", url, kwargs, dry_run)

    def scrape(self, url: str, *, dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
        return self._billable("scrape", url, kwargs, dry_run)

    def schema_assist(self, **kwargs: Any) -> dict[str, Any]:
        _refuse_dry_run("schema_assist", kwargs)
        return self.post("/schema/assist", json=kwargs, idempotent=True)

    def search_free(self, query: str, *, dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
        return self._billable("search_free", query, kwargs, dry_run)

    def search_content(self, query: str, *, full: bool | None = None, dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
        """Search and read the top results. Compact by default; full=True returns the full output."""
        if full is not None:
            kwargs["full"] = full
        return self._billable("search_content", query, kwargs, dry_run)

    def extract(self, url: str, *, dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
        return self._billable("extract", url, kwargs, dry_run)

    def map(self, url: str, *, dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
        return self._billable("map", url, kwargs, dry_run)

    def crawl(self, seed_url: str, *, dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
        return self._billable("crawl", seed_url, kwargs, dry_run)

    def create_job(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post("/jobs", json={"operation": operation, "payload": payload})

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self.get(f"/jobs/{job_id}")

    def poll_job(self, job_id: str, *, interval_seconds: float = 0.5, timeout_seconds: float = 60.0) -> dict[str, Any]:
        return _poll(lambda: self.get_job(job_id), status_key="status", terminal=TERMINAL_JOB_STATUSES, interval_seconds=interval_seconds, timeout_seconds=timeout_seconds)

    def get_crawl(self, crawl_id: str) -> dict[str, Any]:
        return self.get(f"/crawls/{crawl_id}")

    def poll_crawl(self, crawl_id: str, *, interval_seconds: float = 0.5, timeout_seconds: float = 60.0) -> dict[str, Any]:
        return _poll(lambda: self.get_crawl(crawl_id), status_key="status", terminal=TERMINAL_CRAWL_STATUSES, interval_seconds=interval_seconds, timeout_seconds=timeout_seconds)

    def list_history(self, **params: Any) -> dict[str, Any]:
        return self.get("/history", params=params)

    def iter_history(self, **params: Any) -> Iterator[dict[str, Any]]:
        yield from _iter_cursor(lambda cursor: self.list_history(**({**params, "cursor": cursor} if cursor else params)), "items")

    def list_monitors(self, **params: Any) -> dict[str, Any]:
        return self.get("/monitors", params=params)

    def iter_monitors(self, **params: Any) -> Iterator[dict[str, Any]]:
        yield from _iter_cursor(lambda cursor: self.list_monitors(**({**params, "cursor": cursor} if cursor else params)), "monitors")

    def account(self) -> dict[str, Any]:
        return self.get("/account/me")

    def credits(self) -> dict[str, Any]:
        return self.get("/usage")

    def billing_plans(self) -> dict[str, Any]:
        """Plans, credit packs and credit_costs (credits per operation). Needs no API key."""
        return self.get("/billing/plans")


class AsyncClawifi(_BaseClient):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        config: ClawifiConfig | None = None,
        transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(api_key=api_key, api_base=api_base, timeout=timeout, max_retries=max_retries, config=config)
        self._client = httpx.AsyncClient(timeout=self.config.timeout, transport=transport, headers=self._headers())

    @property
    def is_closed(self) -> bool:
        return self._client.is_closed

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "AsyncClawifi":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def request(self, method: str, path: str, *, json: dict[str, Any] | None = None, params: dict[str, Any] | None = None, idempotent: bool = False) -> dict[str, Any]:
        attempts = self.config.max_retries + 1
        for attempt in range(attempts):
            try:
                response = await self._client.request(method, self._url(path), json=json, params=params)
            except httpx.HTTPError as exc:
                raise ClawifiTransportError(str(exc)) from exc
            if response.status_code < 400:
                return _decode_response(response)
            payload = _decode_response(response)
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            if attempt < attempts - 1 and self._should_retry(method, idempotent, response.status_code, retry_after):
                if retry_after:
                    await asyncio.sleep(retry_after)
                continue
            raise ClawifiAPIError.from_response(response.status_code, payload, request_id=response.headers.get("X-Clawifi-Request-ID"), retry_after=retry_after)
        raise ClawifiTransportError("request retry loop exited unexpectedly")

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, *, json: dict[str, Any] | None = None, idempotent: bool = False) -> dict[str, Any]:
        return await self.request("POST", path, json=json, idempotent=idempotent)

    async def _billable(self, operation: str, first: Any, kwargs: dict[str, Any], dry_run: bool) -> dict[str, Any]:
        path, field = ESTIMATE_ROUTES[operation]
        body = {field: first, **kwargs}
        if _dry_run_flag(dry_run):
            await self._require_dry_run()
            body["dry_run"] = True
        return await self.post(path, json=body, idempotent=True)

    async def _require_dry_run(self) -> None:
        if self._dry_run_checked:
            return
        try:
            manifest = await self.get("/product/manifest")
        except (ClawifiAPIError, ClawifiTransportError):
            manifest = None
        self._check_dry_run_manifest(manifest)

    async def estimate(self, operation: str, **args: Any) -> dict[str, Any]:
        """Price a billable call without running it (Clawifi API 1.7.0+).

        operation is one of fetch, scrape, extract, map, crawl, search_free or search_content; args are that
        operation's fields (url=, seed_url= or query=, plus options). Returns estimate{minimum,maximum,raises},
        balance and would_402. Raises ClawifiDryRunUnsupportedError, without sending the call, on an older API.
        """
        if operation not in ESTIMATE_ROUTES:
            raise ValueError(f"unknown operation {operation!r}; expected one of {', '.join(sorted(ESTIMATE_ROUTES))}")
        path, _ = ESTIMATE_ROUTES[operation]
        await self._require_dry_run()
        body = {key: value for key, value in args.items() if key != "dry_run"}
        return await self.post(path, json={**body, "dry_run": True}, idempotent=True)

    async def fetch(self, url: str, *, dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
        return await self._billable("fetch", url, kwargs, dry_run)

    async def scrape(self, url: str, *, dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
        return await self._billable("scrape", url, kwargs, dry_run)

    async def schema_assist(self, **kwargs: Any) -> dict[str, Any]:
        _refuse_dry_run("schema_assist", kwargs)
        return await self.post("/schema/assist", json=kwargs, idempotent=True)

    async def search_free(self, query: str, *, dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
        return await self._billable("search_free", query, kwargs, dry_run)

    async def search_content(self, query: str, *, full: bool | None = None, dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
        """Search and read the top results. Compact by default; full=True returns the full output."""
        if full is not None:
            kwargs["full"] = full
        return await self._billable("search_content", query, kwargs, dry_run)

    async def extract(self, url: str, *, dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
        return await self._billable("extract", url, kwargs, dry_run)

    async def map(self, url: str, *, dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
        return await self._billable("map", url, kwargs, dry_run)

    async def crawl(self, seed_url: str, *, dry_run: bool = False, **kwargs: Any) -> dict[str, Any]:
        return await self._billable("crawl", seed_url, kwargs, dry_run)

    async def create_job(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.post("/jobs", json={"operation": operation, "payload": payload})

    async def get_job(self, job_id: str) -> dict[str, Any]:
        return await self.get(f"/jobs/{job_id}")

    async def poll_job(self, job_id: str, *, interval_seconds: float = 0.5, timeout_seconds: float = 60.0) -> dict[str, Any]:
        return await _apoll(lambda: self.get_job(job_id), status_key="status", terminal=TERMINAL_JOB_STATUSES, interval_seconds=interval_seconds, timeout_seconds=timeout_seconds)

    async def get_crawl(self, crawl_id: str) -> dict[str, Any]:
        return await self.get(f"/crawls/{crawl_id}")

    async def poll_crawl(self, crawl_id: str, *, interval_seconds: float = 0.5, timeout_seconds: float = 60.0) -> dict[str, Any]:
        return await _apoll(lambda: self.get_crawl(crawl_id), status_key="status", terminal=TERMINAL_CRAWL_STATUSES, interval_seconds=interval_seconds, timeout_seconds=timeout_seconds)

    async def list_history(self, **params: Any) -> dict[str, Any]:
        return await self.get("/history", params=params)

    async def iter_history(self, **params: Any) -> AsyncIterator[dict[str, Any]]:
        async for item in _aiter_cursor(lambda cursor: self.list_history(**({**params, "cursor": cursor} if cursor else params)), "items"):
            yield item

    async def list_monitors(self, **params: Any) -> dict[str, Any]:
        return await self.get("/monitors", params=params)

    async def iter_monitors(self, **params: Any) -> AsyncIterator[dict[str, Any]]:
        async for item in _aiter_cursor(lambda cursor: self.list_monitors(**({**params, "cursor": cursor} if cursor else params)), "monitors"):
            yield item

    async def account(self) -> dict[str, Any]:
        return await self.get("/account/me")

    async def credits(self) -> dict[str, Any]:
        return await self.get("/usage")

    async def billing_plans(self) -> dict[str, Any]:
        """Plans, credit packs and credit_costs (credits per operation). Needs no API key."""
        return await self.get("/billing/plans")


_VERSION = re.compile(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*?)\s*$", re.I)
# What may follow X.Y.Z on a final release: a post-release (1.7.0.post1, 1.7.0-post2) and/or a local label (+abc).
_FINAL_SUFFIX = re.compile(r"^(?:[-_.]?post[-_.]?\d*)?(?:\+[a-z0-9.]+)?$", re.I)


def _version_tuple(version: str) -> tuple[int, int, int, int]:
    """(major, minor, patch, release) where release is 0 for a final or post release and -1 for anything else
    (1.7.0rc1, 1.7.0a1, 1.7.0b2, 1.7.0.dev3, an unknown suffix), so a pre-release sorts below its final release."""
    match = _VERSION.match(version or "")
    if not match:
        return (0, 0, 0, 0)
    major, minor, patch, suffix = match.groups()
    release = 0 if _FINAL_SUFFIX.match(suffix) else -1
    return (int(major), int(minor or 0), int(patch or 0), release)


def _dry_run_flag(dry_run: Any) -> bool:
    """True only for the boolean True. False and None mean no dry_run key in the body; any other value is refused,
    because the API answers a non-boolean dry_run with 422 and treating "yes" as false would run and bill the call."""
    if dry_run is True:
        return True
    if dry_run is False or dry_run is None:
        return False
    raise TypeError(f"dry_run must be True or False, not {dry_run!r}")


def _refuse_dry_run(operation: str, body: dict[str, Any]) -> None:
    """Drop a dry_run key on a route that cannot dry-run (the API would answer 422 even to false); refuse True."""
    if "dry_run" in body and _dry_run_flag(body.pop("dry_run")):
        raise ClawifiDryRunUnsupportedError(f"{operation} cannot be dry-run; it is not billed per call")


def _decode_response(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ClawifiTransportError("Clawifi response was not JSON") from exc
    if not isinstance(payload, dict):
        raise ClawifiTransportError("Clawifi response JSON must be an object")
    return payload


def _poll(fetch_status, *, status_key: str, terminal: set[str], interval_seconds: float, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        payload = fetch_status()
        if str(payload.get(status_key)) in terminal:
            return payload
        if time.monotonic() >= deadline:
            raise TimeoutError("poll timed out")
        time.sleep(interval_seconds)


async def _apoll(fetch_status, *, status_key: str, terminal: set[str], interval_seconds: float, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        payload = await fetch_status()
        if str(payload.get(status_key)) in terminal:
            return payload
        if time.monotonic() >= deadline:
            raise TimeoutError("poll timed out")
        await asyncio.sleep(interval_seconds)


def _iter_cursor(fetch_page, item_key: str) -> Iterator[dict[str, Any]]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        page = fetch_page(cursor)
        yield from page.get(item_key, [])
        cursor = page.get("next_cursor")
        if not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)


async def _aiter_cursor(fetch_page, item_key: str) -> AsyncIterator[dict[str, Any]]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        page = await fetch_page(cursor)
        for item in page.get(item_key, []):
            yield item
        cursor = page.get("next_cursor")
        if not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
