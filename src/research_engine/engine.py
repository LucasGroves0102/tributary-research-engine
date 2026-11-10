"""Resumable read-only research workflow."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import Any

from .client import TributaryClient, TributaryError, validate_company_id
from .contracts import (
    SCHEMA_VERSION,
    Evidence,
    Finding,
    Objective,
    Run,
    RunStatus,
    TaskStatus,
    utc_now,
)
from .evidence import financial_evidence, section_evidence, verify_findings
from .model import default_state, discovery_state, model_evidence
from .planner import analyze_objective, make_plan, validate_plan
from .storage import RunStore


class ResearchEngine:
    def __init__(self, client: TributaryClient, store: RunStore) -> None:
        self.client = client
        self.store = store

    def create(self, objective: Objective, *, data_mode: str = "live") -> Run:
        plan = make_plan(objective)
        run = Run.new(objective, plan, sorted(analyze_objective(objective.request)), data_mode)
        run.status = RunStatus.PLANNED
        run.task_status = {task.id: TaskStatus.PENDING for task in plan}
        self.store.save_run(run)
        self.store.append_trace(run.id, {
            "schema_version": SCHEMA_VERSION, "at": utc_now(), "run_id": run.id,
            "task_id": "run", "event": "state", "status": RunStatus.PLANNED,
        })
        return run

    async def execute(self, run: Run) -> Run:
        with self.store.lock(run.id):
            return await self._execute_locked(self.store.load_run(run.id))

    async def _execute_locked(self, run: Run) -> Run:
        run._last_status = run.status
        if run.status in {RunStatus.COMPLETED, RunStatus.PARTIAL}:
            return run
        if run.status in {RunStatus.CANCELLED, RunStatus.BUDGET_EXCEEDED}:
            raise ValueError(f"Cannot resume a {run.status} run")
        plan = run.plan
        validate_plan(plan, run.objective.budget.max_tool_calls)
        results = self._load_results(run)
        for task in plan:
            if run.task_status.get(task.id) == TaskStatus.COMPLETED and task.id not in results:
                run.status = RunStatus.FAILED
                run.errors.append(f"Checkpoint missing result for completed task {task.id}")
                self._save(run)
                return run
        if run.task_status.get("resolve") == TaskStatus.COMPLETED:
            resolved = results["resolve"].get("company_id") if isinstance(results["resolve"], dict) else None
            if resolved != run.company_id:
                run.status = RunStatus.FAILED
                run.errors.append("Checkpoint company identity mismatch")
                self._save(run)
                return run
        remaining = run.objective.budget.max_duration_seconds - run.elapsed_seconds
        if remaining <= 0:
            run.status = RunStatus.BUDGET_EXCEEDED
            run.errors.append("Run duration budget exceeded")
            self._save(run)
            return run
        run._last_tick = time.monotonic()
        deadline = run._last_tick + remaining
        run.status = RunStatus.RUNNING
        self._save(run)
        for task in plan:
            if run.task_status.get(task.id) == TaskStatus.COMPLETED:
                continue
            if any(run.task_status.get(dep) != TaskStatus.COMPLETED for dep in task.depends_on):
                if task.required:
                    run.status = RunStatus.FAILED
                    run.errors.append(f"Task {task.id} dependency failed")
                    self._save(run)
                    return run
                run.task_status[task.id] = TaskStatus.SKIPPED
                run.errors.append(f"Optional task {task.id} skipped after dependency failure")
                self._save(run)
                continue
            if run.tool_calls >= run.objective.budget.max_tool_calls:
                run.status = RunStatus.BUDGET_EXCEEDED
                run.errors.append("Tool-call budget exceeded")
                self._save(run)
                return run
            if time.monotonic() >= deadline:
                run.status = RunStatus.PAUSED
                run.errors.append("Run duration budget reached")
                self._save(run)
                return run
            run.task_status[task.id] = TaskStatus.RUNNING
            run.tool_calls += 1
            self._save(run)
            started = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    self._invoke(task.tool, run, results), timeout=max(0.1, deadline - time.monotonic())
                )
            except TimeoutError:
                run.status = RunStatus.PAUSED
                run.task_status[task.id] = TaskStatus.PENDING
                run.errors.append("Run duration budget reached")
                self._trace(run, task.id, "tool", "timeout", started, "timeout")
                self._save(run)
                return run
            except TributaryError as exc:
                run.task_status[task.id] = TaskStatus.FAILED
                self._trace(run, task.id, "tool", "error", started, exc.kind)
                if exc.status in {401, 403} or task.required:
                    run.status = RunStatus.FAILED
                    run.errors.append(f"{task.id}: {exc.kind}")
                    self._save(run)
                    return run
                run.errors.append(f"Optional source {task.id} unavailable: {exc.kind}")
                self._save(run)
                continue
            except Exception:
                run.status = RunStatus.FAILED
                run.task_status[task.id] = TaskStatus.FAILED
                self._trace(run, task.id, "tool", "error", started, "unexpected")
                run.errors.append(f"{task.id}: unexpected tool error")
                self._save(run)
                raise
            if task.id == "resolve":
                run.company_id = resolve_company_id(result, run.objective.company)
                if run.company_id is None:
                    run.status = RunStatus.FAILED
                    run.task_status[task.id] = TaskStatus.FAILED
                    run.errors.append("Company search was empty or ambiguous")
                    self._trace(run, task.id, "tool", "error", started, "ambiguous_company")
                    self._save(run)
                    return run
                # Search results can include unrelated entities; keep only the resolved ID.
                results[task.id] = {"company_id": run.company_id}
            else:
                results[task.id] = result
            run.task_status[task.id] = TaskStatus.COMPLETED
            self.store.write_json(run.id, "results.json", results)
            self._trace(run, task.id, "tool", "ok", started)
            self._save(run)
        run.status = RunStatus.VERIFYING
        self._save(run)
        assert run.company_id is not None
        evidence, findings = financial_evidence(results.get("financials"), run.company_id)
        for task_id, section_key in (("risk_section", "1A"), ("mdna_section", "7")):
            if task_id in results:
                evidence.extend(section_evidence(results[task_id], run.company_id, section_key))
        if "model_scenarios" in results:
            evidence.extend(model_evidence(results["model_scenarios"], run.company_id,
                                           run.objective.forecast_years))
        verify_findings(evidence, findings)
        self.store.write_json(run.id, "evidence.json", {
            "schema_version": SCHEMA_VERSION,
            "run_id": run.id,
            "evidence": [asdict(item) for item in evidence],
        })
        self.store.write_json(run.id, "findings.json", {
            "schema_version": SCHEMA_VERSION,
            "run_id": run.id,
            "findings": [asdict(item) for item in findings],
        })
        run.unfulfilled = unmet_requirements(run, evidence, findings)
        self.store.write_report(run.id, compose_report(run, evidence, findings))
        run.status = RunStatus.PARTIAL if run.unfulfilled else RunStatus.COMPLETED
        self._trace(run, "report", "completed", "partial" if run.unfulfilled else "ok",
                    time.monotonic())
        self._save(run)
        return run

    def _load_results(self, run: Run) -> dict[str, Any]:
        try:
            result = self.store.read_json(run.id, "results.json")
            return result if isinstance(result, dict) else {}
        except FileNotFoundError:
            return {}

    async def _invoke(self, tool: str, run: Run, results: dict[str, Any]) -> Any:
        if tool == "search_companies":
            return await self.client.search_companies(run.objective.company)
        if run.company_id is None:
            raise ValueError("Company must be resolved first")
        if tool in {"risk_section", "mdna_section"}:
            return await self.client.section(run.company_id,
                                             "1A" if tool == "risk_section" else "7")
        if tool == "model_defaults":
            raw = await self.client.model(
                run.company_id, discovery_state(run.company_id, run.objective.forecast_years)
            )
            default_state(raw, run.company_id, run.objective.forecast_years)
            return raw
        if tool == "model_scenarios":
            state = default_state(results["model_defaults"], run.company_id,
                                  run.objective.forecast_years)
            raw = await self.client.model(run.company_id, state)
            model_evidence(raw, run.company_id, run.objective.forecast_years)
            return raw
        method = getattr(self.client, tool)
        return await method(run.company_id)

    def _save(self, run: Run) -> None:
        last_tick = getattr(run, "_last_tick", None)
        if last_tick is not None:
            now = time.monotonic()
            run.elapsed_seconds += max(now - last_tick, 0)
            run._last_tick = now
        run.updated_at = utc_now()
        self.store.save_run(run)
        previous = getattr(run, "_last_status", None)
        if previous is not None and previous != run.status:
            self.store.append_trace(run.id, {
                "schema_version": SCHEMA_VERSION,
                "at": run.updated_at,
                "run_id": run.id,
                "task_id": "run",
                "event": "state",
                "status": run.status,
            })
            run._last_status = run.status

    def _trace(
        self, run: Run, task_id: str, event: str, status: str, started: float,
        error_kind: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "at": utc_now(),
            "run_id": run.id,
            "task_id": task_id,
            "event": event,
            "status": status,
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
        if error_kind:
            entry["error_kind"] = error_kind
        self.store.append_trace(run.id, entry)


def resolve_company_id(raw: Any, query: str) -> str | None:
    if len(query) == 10 and query.isascii() and query.isdigit():
        return validate_company_id(query)
    if isinstance(raw, list):
        candidates = raw
    elif isinstance(raw, dict):
        candidates = next((raw[key] for key in ("results", "companies", "items") if isinstance(raw.get(key), list)), [])
    else:
        candidates = []
    matches = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        company_id = candidate.get("company_id") or candidate.get("cik")
        try:
            company_id = validate_company_id(str(company_id))
        except ValueError:
            continue
        names = [candidate.get(key) for key in ("ticker", "symbol", "name", "company_name")]
        tickers = candidate.get("tickers")
        if isinstance(tickers, list):
            names.extend(tickers)
        if any(isinstance(name, str) and name.casefold() == query.casefold() for name in names):
            matches.append(company_id)
    if len(set(matches)) == 1:
        return matches[0]
    if not matches and len(candidates) == 1 and isinstance(candidates[0], dict):
        candidate = candidates[0]
        try:
            return validate_company_id(str(candidate.get("company_id") or candidate.get("cik")))
        except ValueError:
            pass
    return None


def compose_report(run: Run, evidence: list[Evidence], findings: list[Finding]) -> str:
    indexed = {item.id: item for item in evidence}
    verified = [item for item in findings if item.verification == "verified"]
    unverified = [item for item in findings if item.verification != "verified"]
    verified.sort(key=lambda item: indexed[item.evidence_ids[0]].payload["period_end"], reverse=True)
    source_label = ("A pinned synthetic fixture" if run.data_mode == "fixture"
                    else "The authorized Tributary API")
    lines = [
        f"# Research: {run.objective.company}", "",
        f"Data mode: **{run.data_mode}**", "",
        f"Research outcome: **{'partial' if run.unfulfilled else 'completed'}**", "",
        "Objective: read-only company financial research", "",
        f"Company ID: `{run.company_id}`", "",
        "## Executive summary", "",
    ]
    if verified:
        lines.append(f"{source_label} supplied {len(verified)} verified, source-linked "
                     "historical figures. These are observations, not forecasts or investment advice.")
        for metric in ("revenue", "operating_income", "free_cash_flow", "net_income"):
            latest = next((indexed[item.evidence_ids[0]] for item in verified
                           if indexed[item.evidence_ids[0]].payload["metric"] == metric), None)
            if latest:
                payload = latest.payload
                lines.append(f"- Latest {metric}: {payload['value']} {payload['unit']} "
                             f"(period ending {payload['period_end']}; filing "
                             f"`{payload['citation']['accession_no']}`).")
    else:
        lines.append("No numerical figures met the citation, period, and unit requirements. "
                     "The financial response needs contract review before claims can be made.")
    lines.extend(["", "## Historical financial evidence", ""])
    if verified:
        lines.append("| Period end | Metric | Value | Unit | Source | Filing | Evidence |")
        lines.append("| --- | --- | ---: | --- | --- | --- | --- |")
        for finding in verified[:100]:
            ev = indexed[finding.evidence_ids[0]]
            payload = ev.payload
            lines.append(f"| {payload['period_end']} | {payload['metric']} | {payload['value']} | "
                         f"{payload['unit']} | {finding.category} | "
                         f"`{payload['citation']['accession_no']}` | `{ev.id}` |")
        if len(verified) > 100:
            lines.append(f"{len(verified) - 100} additional verified figures are in `evidence.json`.")
    else:
        lines.append("No figures met the verification requirements.")
    if unverified:
        lines.extend(["", "## Unverified figures", ""])
        for finding in unverified[:30]:
            lines.append(f"- {finding.statement} — {finding.reason or 'Verification failed'} "
                         f"(evidence `{finding.evidence_ids[0]}`).")
    passages = [item for item in evidence if item.kind == "filing_passage"]
    if passages:
        lines.extend(["", "## Filing excerpts for analyst review", ""])
        lines.append("These are excerpts from filing sections, not verified interpretations.")
        for item in passages[:8]:
            payload = item.payload
            lines.append(f"- `{payload['section_key']}` in filing "
                         f"`{payload['accession_no']}`, characters "
                         f"{payload['char_start']}–{payload['char_end']}, evidence `{item.id}`:")
            lines.append("")
            lines.append("    " + payload["excerpt"].replace("\n", " ").replace("\r", " "))
    projections = [item for item in evidence if item.kind == "model_projection"]
    if projections:
        lines.extend(["", "## Model scenarios (forecasts, not reported results)", ""])
        lines.append("Tributary computed these projections from its model defaults. Bear and bull "
                     "are server preview scenarios; growth and margin are assumptions, not facts.")
        lines.extend(["", ("| Case | Fiscal year | Revenue | Operating income | Free cash flow | "
                           "Growth assumption | Margin assumption | Evidence |"),
                      "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"])
        for item in sorted(projections, key=lambda ev: (
            {"bear": 0, "base": 1, "bull": 2}[ev.payload["case"]], ev.payload["fy"]
        )):
            payload = item.payload
            lines.append(f"| {payload['case']} | {payload['fy']} | "
                         f"{payload['revenue']} {payload['currency']} | "
                         f"{payload['operating_income']} {payload['currency']} | "
                         f"{payload['free_cash_flow']} {payload['currency']} | "
                         f"{payload['growth_assumption_percent']}% | "
                         f"{payload['margin_assumption_percent']}% | `{item.id}` |")
    lines.extend(["", "## Research coverage", ""])
    for name in ("filings", "risk_section", "mdna_section", "segments", "peers", "earnings", "events", "data_notes", "model_defaults", "model_scenarios"):
        state = run.task_status.get(name, "not_planned")
        lines.append(f"- {name.replace('_', ' ').title()}: {state}")
    lines.extend(["", "## Limitations and unresolved work", ""])
    lines.append("- Filing passages are shown only as source excerpts; no business or risk "
                 "interpretation is asserted without a verified claim-to-source link.")
    lines.append("- No price, consensus estimate, transcript, or valuation is inferred from filings.")
    for error in run.errors:
        lines.append(f"- {error}")
    for requirement in run.unfulfilled:
        lines.append(f"- Unfulfilled objective requirement: {requirement}")
    lines.extend(["", "## Reproducibility", "",
                  (f"Run ID: `{run.id}`. Machine-readable evidence is in `evidence.json`; "
                   "redacted execution metadata is in `trace.jsonl`."), ""])
    return "\n".join(lines)


def unmet_requirements(run: Run, evidence: list[Evidence], findings: list[Finding]) -> list[str]:
    unmet = []
    if not any(item.verification == "verified" for item in findings):
        unmet.append("verified historical financial figures")
    for topic, requirement in (
        ("risks", "interpreted, source-linked risk analysis"),
        ("segments", "interpreted segment and growth-driver analysis"),
        ("peers", "verified peer comparison"),
        ("earnings", "earnings and outlook analysis"),
        ("events", "material-event analysis"),
    ):
        if topic in run.topics:
            unmet.append(requirement)
    if "scenarios" in run.topics:
        cases = {item.payload.get("case") for item in evidence if item.kind == "model_projection"}
        if not {"bear", "base", "bull"} <= cases:
            unmet.append("bear/base/bull model scenarios")
    if any(status == TaskStatus.FAILED for status in run.task_status.values()):
        unmet.append("all selected API sources available")
    return unmet
