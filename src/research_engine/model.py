"""Validated, read-only forecast requests and source-labeled model projections."""

from __future__ import annotations

import math
from typing import Any

from .client import TributaryError, validate_company_id
from .contracts import Evidence, utc_now
from .evidence import stable_id


def _rate(value: Any, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("Model rate must be a JSON number")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError("Model rate is outside the API range")
    return number


def validate_model_state(state: dict[str, Any], company_id: str) -> None:
    if set(state) != {"companyId", "historyYears", "assumptions"}:
        raise ValueError("Unsupported model state fields")
    if state["companyId"] != validate_company_id(company_id):
        raise ValueError("Model company ID does not match the route")
    years = state["historyYears"]
    if isinstance(years, bool) or not isinstance(years, int) or not 3 <= years <= 10:
        raise ValueError("historyYears must be between 3 and 10")
    assumptions = state["assumptions"]
    if not isinstance(assumptions, list) or not 1 <= len(assumptions) <= 10:
        raise ValueError("Model must have 1 to 10 forecast years")
    for item in assumptions:
        if not isinstance(item, dict) or set(item) != {"growth", "margin"}:
            raise ValueError("Each model year needs growth and margin")
        _rate(item["growth"], -100, 1000)
        _rate(item["margin"], -1000, 100)


def discovery_state(company_id: str, forecast_years: int) -> dict[str, Any]:
    state = {
        "companyId": validate_company_id(company_id),
        "historyYears": 8,
        "assumptions": [{"growth": 0.0, "margin": 0.0} for _ in range(forecast_years)],
    }
    validate_model_state(state, company_id)
    return state


def default_state(raw: Any, company_id: str, forecast_years: int) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("company_id") != company_id:
        raise TributaryError("invalid_model_defaults")
    if not isinstance(raw.get("base_fy"), int):
        raise TributaryError("model_has_no_history")
    cases = raw.get("cases")
    base = cases.get("base") if isinstance(cases, dict) else None
    defaults = base.get("defaults") if isinstance(base, dict) else None
    if not isinstance(defaults, list) or len(defaults) != forecast_years:
        raise TributaryError("invalid_model_defaults")
    try:
        assumptions = [
            {"growth": _rate(item["growth"], -100, 1000),
             "margin": _rate(item["margin"], -1000, 100)}
            for item in defaults
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise TributaryError("invalid_model_defaults") from exc
    state = {"companyId": company_id, "historyYears": 8, "assumptions": assumptions}
    validate_model_state(state, company_id)
    return state


def model_evidence(raw: Any, company_id: str, forecast_years: int) -> list[Evidence]:
    """Keep projections separate from SEC-reported financial evidence."""
    if not isinstance(raw, dict) or raw.get("company_id") != company_id:
        raise TributaryError("invalid_model_response")
    cases = raw.get("cases")
    if not isinstance(cases, dict) or set(cases) < {"bear", "base", "bull"}:
        raise TributaryError("invalid_model_response")
    currency = raw.get("currency", "USD")
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
        raise TributaryError("invalid_model_response")
    found: list[Evidence] = []
    expected_fys: list[int] | None = None
    for case in ("bear", "base", "bull"):
        case_data = cases[case]
        years = case_data.get("years") if isinstance(case_data, dict) else None
        if not isinstance(years, list) or len(years) != forecast_years:
            raise TributaryError("invalid_model_response")
        fys: list[int] = []
        for year in years:
            fy = year.get("fy") if isinstance(year, dict) else None
            if isinstance(fy, bool) or not isinstance(fy, int):
                raise TributaryError("invalid_model_response")
            fys.append(fy)
        if fys != list(range(fys[0], fys[0] + forecast_years)):
            raise TributaryError("invalid_model_response")
        if expected_fys is not None and fys != expected_fys:
            raise TributaryError("invalid_model_response")
        expected_fys = fys
        for year in years:
            if not isinstance(year, dict) or not isinstance(year.get("fy"), int):
                raise TributaryError("invalid_model_response")
            inputs = year.get("inputs")
            if not isinstance(inputs, dict):
                raise TributaryError("invalid_model_response")
            try:
                growth = _rate(inputs["growth"], -100, 1000)
                margin = _rate(inputs["margin"], -1000, 100)
            except (KeyError, TypeError, ValueError) as exc:
                raise TributaryError("invalid_model_response") from exc
            payload = {
                "case": case,
                "fy": year["fy"],
                "currency": currency.upper(),
                "growth_assumption_percent": growth,
                "margin_assumption_percent": margin,
                "revenue": year.get("revenue"),
                "operating_income": year.get("operating_income"),
                "free_cash_flow": year.get("fcf"),
                "preview": case_data.get("preview"),
                "origin": "Tributary model defaults and preview policy",
                "classification": "forecast",
            }
            found.append(Evidence(
                id=stable_id("ev", [company_id, payload]), kind="model_projection",
                company_id=company_id,
                source_path=f"/v1/companies/{company_id}/model",
                retrieved_at=utc_now(), payload=payload,
            ))
    return found
