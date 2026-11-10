import httpx
import pytest

from research_engine.client import TributaryClient, TributaryError
from research_engine.contract_probe import probe, shape_of


def test_shape_of_never_includes_scalar_values():
    shape = shape_of({"token": "secret", "values": [{"value": "123.45", "valid": True}]})
    rendered = str(shape)
    assert "secret" not in rendered
    assert "123.45" not in rendered
    assert shape["values"]["item_shapes"][0]["value"] == "string"


@pytest.mark.asyncio
async def test_probe_stops_on_permission_failure():
    paths = []

    def respond(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"results": [{"tickers": ["NVDA"], "company_id": "0001045810"}]})
        return httpx.Response(403, json={"detail": "no"})

    async with TributaryClient("token", transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(TributaryError) as error:
            await probe(client, "NVDA")
    assert error.value.status == 403
    assert len(paths) == 2
