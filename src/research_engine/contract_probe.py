"""Privacy-conscious inspection of API response shapes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .client import TributaryClient, TributaryError
from .engine import resolve_company_id


def shape_of(value: Any, depth: int = 0) -> Any:
    """Describe field names and types, never scalar values."""
    if depth >= 6:
        return "truncated"
    if isinstance(value, dict):
        return {str(key): shape_of(item, depth + 1) for key, item in list(value.items())[:100]}
    if isinstance(value, list):
        return {"type": "array", "count": len(value),
                "item_shapes": [shape_of(item, depth + 1) for item in value[:2]]}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "unknown"


async def probe(client: TributaryClient, company: str) -> dict[str, Any]:
    search = await client.search_companies(company)
    company_id = resolve_company_id(search, company)
    if company_id is None:
        raise ValueError("Company search was empty or ambiguous")
    shapes: dict[str, Any] = {"search": shape_of(search)}
    calls: dict[str, Callable[[], Awaitable[Any]]] = {
        "financials": lambda: client.financials(company_id),
        "filings": lambda: client.filings(company_id),
        "risk_section": lambda: client.section(company_id, "1A"),
        "mdna_section": lambda: client.section(company_id, "7"),
        "segments": lambda: client.segments(company_id),
        "peers": lambda: client.peers(company_id),
        "earnings": lambda: client.earnings(company_id),
        "events": lambda: client.events(company_id),
        "data_notes": lambda: client.data_notes(company_id),
    }
    for name, operation in calls.items():
        try:
            shapes[name] = shape_of(await operation())
        except TributaryError as exc:
            if exc.status in {401, 403}:
                raise
            shapes[name] = {"error_kind": exc.kind, "status": exc.status}
    return {"company_id": company_id, "shapes": shapes}
