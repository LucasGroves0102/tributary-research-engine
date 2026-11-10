from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from research_engine.client import TributaryClient, TributaryError, retry_delay


@pytest.mark.asyncio
async def test_client_sends_token_only_in_header_and_fails_closed():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(403, json={"detail": "hidden"})

    async with TributaryClient("secret-token", transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(TributaryError) as error:
            await client.financials("0001045810")
    assert error.value.kind == "forbidden"
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer secret-token"
    assert "secret-token" not in str(requests[0].url)


@pytest.mark.asyncio
async def test_client_retries_rate_limit_and_honors_success():
    count = 0

    def respond(request):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"results": []})

    async with TributaryClient("token", transport=httpx.MockTransport(respond)) as client:
        assert await client.search_companies("NVDA") == {"results": []}
    assert count == 2


def test_client_rejects_insecure_remote_url():
    with pytest.raises(ValueError, match="HTTPS"):
        TributaryClient("token", "http://example.com/api/query")
    with pytest.raises(ValueError, match="unknown host"):
        TributaryClient("token", "https://example.com/api/query")


@pytest.mark.asyncio
async def test_client_rejects_oversized_response_without_parsing():
    def respond(request):
        return httpx.Response(200, content=b"{" + b"x" * 200 + b"}")

    async with TributaryClient("token", transport=httpx.MockTransport(respond),
                               max_response_bytes=100) as client:
        with pytest.raises(TributaryError) as error:
            await client.search_companies("NVDA")
    assert error.value.kind == "response_too_large"


def test_retry_after_http_date_is_respected():
    header = format_datetime(datetime.now(UTC) + timedelta(seconds=10))
    assert 8 <= retry_delay(header, 0) <= 10
