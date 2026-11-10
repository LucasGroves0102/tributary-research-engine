"""Pinned synthetic API responses for offline workflow demonstration."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import httpx


def load_demo_fixture() -> dict[str, Any]:
    source = files("research_engine").joinpath("fixtures/acme.json")
    fixture = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(fixture, dict):
        raise TypeError("Invalid demo fixture")
    if fixture.get("fixture_version") != "1.0":
        raise ValueError("Unsupported demo fixture version")
    return dict(fixture)


def demo_transport() -> httpx.MockTransport:
    responses = load_demo_fixture()["responses"]

    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/search"):
            key = "search"
        elif path.endswith("/sections/item_1a"):
            key = "risk_section"
        elif path.endswith("/sections/item_7"):
            key = "mdna_section"
        else:
            key = path.rsplit("/", 1)[-1].replace("-", "_")
        if key not in responses:
            return httpx.Response(404, json={"detail": "fixture route absent"})
        return httpx.Response(200, json=responses[key])

    return httpx.MockTransport(respond)
