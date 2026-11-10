"""Small, fail-closed client for the documented Tributary Query API."""

from __future__ import annotations

import asyncio
import json
import math
import random
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Self

import httpx


class TributaryError(Exception):
    def __init__(self, kind: str, status: int | None = None):
        self.kind = kind
        self.status = status
        super().__init__(f"Tributary {kind}" + (f" (HTTP {status})" if status else ""))


class TributaryClient:
    def __init__(
        self,
        token: str,
        base_url: str = "https://tributary.lucasgroves.dev/api/query",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 2,
        max_response_bytes: int = 25_000_000,
    ) -> None:
        if not token.strip():
            raise ValueError("A Tributary bearer token is required")
        parsed = httpx.URL(base_url)
        if parsed.scheme != "https" and parsed.host not in {"localhost", "127.0.0.1"}:
            raise ValueError("Tributary base URL must use HTTPS")
        if transport is None and parsed.host not in {
            "tributary.lucasgroves.dev", "localhost", "127.0.0.1"
        }:
            raise ValueError("Refusing to send a bearer token to an unknown host")
        if parsed.path.rstrip("/") != "/api/query":
            raise ValueError("Tributary base URL must end at /api/query")
        if parsed.query or parsed.fragment or parsed.userinfo:
            raise ValueError("Tributary base URL must not contain credentials or query parameters")
        if max_retries < 0 or max_retries > 5:
            raise ValueError("max_retries must be between 0 and 5")
        if not 1 <= max_response_bytes <= 100_000_000:
            raise ValueError("max_response_bytes must be between 1 and 100,000,000")
        self.max_retries = max_retries
        self.max_response_bytes = max_response_bytes
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=httpx.Timeout(20.0, connect=5.0),
            limits=httpx.Limits(max_connections=3, max_keepalive_connections=3),
            follow_redirects=False,
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not path.startswith("v1/") or ".." in path or "//" in path:
            raise ValueError("Invalid API path")
        for attempt in range(self.max_retries + 1):
            try:
                async with self._http.stream("GET", path, params=params) as response:
                    if response.status_code == 200:
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > self.max_response_bytes:
                                raise TributaryError("response_too_large", response.status_code)
                        try:
                            return json.loads(body)
                        except ValueError as exc:
                            raise TributaryError("invalid_json", response.status_code) from exc
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == self.max_retries:
                    raise TributaryError("unavailable") from exc
                await asyncio.sleep(min(2**attempt + random.random(), 5))
                continue
            if response.status_code in {401, 403}:
                raise TributaryError("unauthorized" if response.status_code == 401 else "forbidden", response.status_code)
            if response.status_code == 404:
                raise TributaryError("not_found", 404)
            if response.status_code == 422:
                raise TributaryError("invalid_request", 422)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self.max_retries:
                    raise TributaryError("rate_limited" if response.status_code == 429 else "server_error", response.status_code)
                delay = retry_delay(response.headers.get("Retry-After"), attempt)
                await asyncio.sleep(delay)
                continue
            raise TributaryError("http_error", response.status_code)
        raise AssertionError("retry loop exhausted")

    async def search_companies(self, query: str) -> Any:
        return await self._get("v1/companies/search", {"q": query})

    async def financials(self, company_id: str, *, quarters: int = 20) -> Any:
        return await self._get(
            f"v1/companies/{validate_company_id(company_id)}/financials",
            {"view": "quarter", "quarters": quarters, "basis": "fiscal", "readings": "true"},
        )

    async def filings(self, company_id: str) -> Any:
        return await self._get(f"v1/companies/{validate_company_id(company_id)}/filings")

    async def section(self, company_id: str, section_key: str) -> Any:
        if section_key not in {"item_1a", "item_7"}:
            raise ValueError("Unsupported filing section")
        return await self._get(f"v1/companies/{validate_company_id(company_id)}/sections/{section_key}")

    async def segments(self, company_id: str) -> Any:
        return await self._get(f"v1/companies/{validate_company_id(company_id)}/segments")

    async def peers(self, company_id: str) -> Any:
        return await self._get(f"v1/companies/{validate_company_id(company_id)}/peers")

    async def earnings(self, company_id: str) -> Any:
        return await self._get(f"v1/companies/{validate_company_id(company_id)}/earnings")

    async def events(self, company_id: str) -> Any:
        return await self._get(f"v1/companies/{validate_company_id(company_id)}/events")

    async def data_notes(self, company_id: str) -> Any:
        return await self._get(f"v1/companies/{validate_company_id(company_id)}/data-notes")


def validate_company_id(company_id: str) -> str:
    if len(company_id) != 10 or not company_id.isascii() or not company_id.isdigit():
        raise ValueError("company_id must be a 10-digit CIK string")
    return company_id


def retry_delay(header: str | None, attempt: int) -> float:
    if header:
        try:
            seconds = float(header)
            if math.isfinite(seconds):
                return max(seconds, 0)
        except ValueError:
            try:
                then = parsedate_to_datetime(header)
                if then.tzinfo is not None:
                    return float(max((then - datetime.now(UTC)).total_seconds(), 0))
            except (TypeError, ValueError, OverflowError):
                pass
    return float(min(2**attempt + random.random(), 5))
