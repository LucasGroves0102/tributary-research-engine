"""Conservative extraction and verification of numeric filing evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .contracts import Evidence, Finding, utc_now

METRIC_NAME = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
UNIT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_/%.-]{0,39}$")
ACCESSION = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")


def stable_id(prefix: str, value: Any) -> str:
    packed = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return prefix + "_" + hashlib.sha256(packed.encode()).hexdigest()[:20]


def _objects(value: Any, inherited_metric: str | None = None) -> Iterator[tuple[dict[str, Any], str | None]]:
    if isinstance(value, list):
        for item in value:
            yield from _objects(item, inherited_metric)
    elif isinstance(value, dict):
        yield value, inherited_metric
        for key, item in value.items():
            metric = key if isinstance(key, str) and isinstance(item, (dict, list)) else inherited_metric
            yield from _objects(item, metric)


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def financial_evidence(raw: Any, company_id: str) -> tuple[list[Evidence], list[Finding]]:
    """Only publish figures with usable periods, units, and filing citations.

    Unknown response shapes remain unreported. This is intentionally stricter than
    interpreting plausible looking numbers in arbitrary JSON.
    """
    evidences: list[Evidence] = []
    findings: list[Finding] = []
    seen: set[str] = set()
    for item, inherited_metric in _objects(raw):
        metric = item.get("metric") or item.get("metric_name") or inherited_metric
        value = item.get("value")
        period_end = item.get("period_end")
        unit = item.get("unit")
        citation = item.get("citation")
        if not (isinstance(metric, str) and isinstance(unit, str) and _valid_date(period_end)):
            continue
        if not METRIC_NAME.fullmatch(metric) or not UNIT_NAME.fullmatch(unit):
            continue
        period_start = item.get("period_start")
        if period_start is not None and (not _valid_date(period_start) or period_start > period_end):
            continue
        if not isinstance(citation, dict) or not isinstance(citation.get("accession_no"), str):
            continue
        if not isinstance(value, str):
            continue
        try:
            number = Decimal(str(value))
            if not number.is_finite():
                continue
        except (InvalidOperation, ValueError):
            continue
        reading = item.get("reading") or item.get("readings")
        if isinstance(reading, dict):
            if any(reading.get(key) for key in ("not_meaningful", "old", "not_applicable")):
                continue
            reading = reading.get("status") or reading.get("kind")
        if reading in {"not_meaningful", "old", "not_applicable"}:
            continue
        source = item.get("value_source")
        if source not in {"reported", "derived"}:
            continue
        accession = citation["accession_no"]
        if not ACCESSION.fullmatch(accession):
            continue
        payload = {
            "metric": metric,
            "value": str(number),
            "unit": unit,
            "currency": item.get("currency"),
            "period_start": period_start,
            "period_end": period_end,
            "fiscal_label": item.get("fiscal_label"),
            "value_source": source,
            "citation": {
                "accession_no": accession,
                "form": citation.get("form"),
                "filed": citation.get("filed"),
                "xbrl_tag": citation.get("xbrl_tag"),
                "filing_url": citation.get("filing_url"),
            },
            "inputs": item.get("inputs") if source == "derived" else None,
        }
        evidence_id = stable_id("ev", [company_id, payload])
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        evidences.append(
            Evidence(
                id=evidence_id,
                kind="financial_figure",
                company_id=company_id,
                source_path=f"/v1/companies/{company_id}/financials",
                retrieved_at=utc_now(),
                payload=payload,
            )
        )
        statement = f"{metric}: {number} {unit} for period ending {period_end}"
        findings.append(
            Finding(
                id=stable_id("finding", evidence_id),
                category=source,
                statement=statement,
                evidence_ids=[evidence_id],
                verification="unverified" if source == "derived" and not payload["inputs"] else "verified",
                reason="Derived figure has no component inputs" if source == "derived" and not payload["inputs"] else None,
            )
        )
    return evidences, findings


def verify_findings(evidences: list[Evidence], findings: list[Finding]) -> None:
    index = {ev.id: ev for ev in evidences}
    for finding in findings:
        if not finding.evidence_ids or any(eid not in index for eid in finding.evidence_ids):
            finding.verification = "unverified"
            finding.reason = "Missing evidence reference"
        elif finding.category in {"reported", "derived"} and any(
            index[eid].kind != "financial_figure" for eid in finding.evidence_ids
        ):
            finding.verification = "unverified"
            finding.reason = "Numerical claim lacks structured financial evidence"
        elif finding.category in {"reported", "derived"}:
            if len(finding.evidence_ids) != 1:
                finding.verification = "unverified"
                finding.reason = "Numerical claim must reference one exact figure"
                continue
            payload = index[finding.evidence_ids[0]].payload
            try:
                expected = (f"{payload['metric']}: {Decimal(payload['value'])} {payload['unit']} "
                            f"for period ending {payload['period_end']}")
            except (KeyError, InvalidOperation, ValueError):
                finding.verification = "unverified"
                finding.reason = "Evidence figure is malformed"
                continue
            if finding.statement != expected or finding.category != payload.get("value_source"):
                finding.verification = "unverified"
                finding.reason = "Claim does not match its evidence figure"


SECTION_TERMS = {
    "item_1a": re.compile(r"\b(risk|risks|uncertainty|uncertainties|dependence|competition)\b", re.IGNORECASE),
    "item_7": re.compile(r"\b(revenue|demand|margin|cash flow|growth|segment)\b", re.IGNORECASE),
}


def section_evidence(raw: Any, company_id: str, section_key: str) -> list[Evidence]:
    """Locate bounded, exact-offset excerpts without interpreting filing text."""
    if section_key not in SECTION_TERMS:
        raise ValueError("Unsupported section key")
    found: list[Evidence] = []
    for item, _ in _objects(raw):
        accession = item.get("accession_no")
        content = item.get("text") or item.get("content")
        if not isinstance(accession, str) or not ACCESSION.fullmatch(accession):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        if item.get("section_key", section_key) != section_key:
            continue
        digest = hashlib.sha256(content.encode()).hexdigest()
        selected: list[tuple[int, int]] = []
        for match in SECTION_TERMS[section_key].finditer(content[:200_000]):
            start = max(0, match.start() - 120)
            end = min(len(content), match.end() + 360)
            if selected and start <= selected[-1][1]:
                continue
            selected.append((start, end))
            if len(selected) == 3:
                break
        for start, end in selected:
            payload = {
                "accession_no": accession,
                "section_key": section_key,
                "char_start": start,
                "char_end": end,
                "text_sha256": digest,
                "excerpt": content[start:end],
                "trust": "untrusted_filing_text",
            }
            found.append(Evidence(
                id=stable_id("ev", [company_id, payload]), kind="filing_passage",
                company_id=company_id,
                source_path=f"/v1/companies/{company_id}/sections/{section_key}",
                retrieved_at=utc_now(), payload=payload,
            ))
        if found:
            break
    return found
