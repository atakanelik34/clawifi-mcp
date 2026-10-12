from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterator

import httpx

from clawifi.errors import ClawifiAPIError, ClawifiTransportError

DEFAULT_API_BASE = "https://api.clawifi.qzz.io"
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}
TERMINAL_CRAWL_STATUSES = {"succeeded", "partial", "failed", "stopped", "interrupted"}


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

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "clawifi/0.1.2"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.config.api_base}/{path.lstrip('/')}"

    @staticmethod
    def _should_retry(method: str, idempotent: bool, status_code: int) -> bool:
        return (method.upper() in {"GET", "HEAD"} or idempotent) and status_code in RETRYABLE_STATUS_CODES


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
            if attempt < attempts - 1 and self._should_retry(method, idempotent, response.status_code):
                continue
            raise ClawifiAPIError.from_response(response.status_code, payload, request_id=response.headers.get("X-Clawifi-Request-ID"))
        raise ClawifiTransportError("request retry loop exited unexpectedly")

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("GET", path, params=params)

    def post(self, path: str, *, json: dict[str, Any] | None = None, idempotent: bool = False) -> dict[str, Any]:
        return self.request("POST", path, json=json, idempotent=idempotent)

    def fetch(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return self.post("/fetch", json={"url": url, **kwargs}, idempotent=True)

    def scrape(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return self.post("/scrape", json={"url": url, **kwargs}, idempotent=True)

    def schema_assist(self, **kwargs: Any) -> dict[str, Any]:
        return self.post("/schema/assist", json=kwargs, idempotent=True)

    def search_free(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return self.post("/search/free", json={"query": query, **kwargs}, idempotent=True)

    def extract(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return self.post("/extract", json={"url": url, **kwargs}, idempotent=True)

    def map(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return self.post("/map", json={"url": url, **kwargs}, idempotent=True)

    def crawl(self, seed_url: str, **kwargs: Any) -> dict[str, Any]:
        return self.post("/crawl", json={"seed_url": seed_url, **kwargs}, idempotent=True)

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
            if attempt < attempts - 1 and self._should_retry(method, idempotent, response.status_code):
                continue
            raise ClawifiAPIError.from_response(response.status_code, payload, request_id=response.headers.get("X-Clawifi-Request-ID"))
        raise ClawifiTransportError("request retry loop exited unexpectedly")

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, *, json: dict[str, Any] | None = None, idempotent: bool = False) -> dict[str, Any]:
        return await self.request("POST", path, json=json, idempotent=idempotent)

    async def fetch(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return await self.post("/fetch", json={"url": url, **kwargs}, idempotent=True)

    async def scrape(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return await self.post("/scrape", json={"url": url, **kwargs}, idempotent=True)

    async def schema_assist(self, **kwargs: Any) -> dict[str, Any]:
        return await self.post("/schema/assist", json=kwargs, idempotent=True)

    async def search_free(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return await self.post("/search/free", json={"query": query, **kwargs}, idempotent=True)

    async def extract(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return await self.post("/extract", json={"url": url, **kwargs}, idempotent=True)

    async def map(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return await self.post("/map", json={"url": url, **kwargs}, idempotent=True)

    async def crawl(self, seed_url: str, **kwargs: Any) -> dict[str, Any]:
        return await self.post("/crawl", json={"seed_url": seed_url, **kwargs}, idempotent=True)

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
