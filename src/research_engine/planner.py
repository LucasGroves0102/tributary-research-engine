"""Deterministic, bounded task graph for the initial research workflow."""

from __future__ import annotations

import re

from .contracts import Objective, Task

ALLOWED_TOOLS = {
    "search_companies", "financials", "filings", "risk_section", "mdna_section",
    "segments", "peers", "earnings", "events", "data_notes"
}

TOPIC_TERMS = {
    "risks": {"risk", "risks", "filing", "filings", "disclosure", "uncertainty", "uncertainties"},
    "segments": {"segment", "segments", "product", "products", "geography", "geographic", "drivers"},
    "peers": {"peer", "peers", "compare", "comparison", "competitor", "competitors"},
    "earnings": {"earnings", "outlook", "guidance", "release", "releases"},
    "events": {"event", "events", "material", "changes", "changed"},
    "scenarios": {"forecast", "forecasts", "scenario", "scenarios", "bear", "bull", "base"},
}


def analyze_objective(request: str) -> set[str]:
    words = set(re.findall(r"[a-z]+", request.casefold()))
    topics = {"financials", "data_notes"}
    for topic, terms in TOPIC_TERMS.items():
        if words & terms:
            topics.add(topic)
    return topics


def make_plan(objective: Objective) -> list[Task]:
    topics = analyze_objective(objective.request)
    selected = set(topics)
    if "risks" in topics:
        selected.update({"filings", "events", "risk_section"})
    if "segments" in topics:
        selected.update({"earnings", "mdna_section"})
    tasks = [Task("resolve", "search_companies", description="Resolve an exact company identity",
                  completion_criteria="One unambiguous 10-digit company ID")]
    for name in ("financials", "filings", "risk_section", "mdna_section", "segments",
                 "peers", "earnings", "events", "data_notes"):
        if name in selected:
            tasks.append(Task(
                name, name, ("resolve",), required=name == "financials",
                description=f"Fetch {name.replace('_', ' ')} from the authorized API",
                completion_criteria="Response received or optional source marked unavailable",
            ))
    validate_plan(tasks, objective.budget.max_tool_calls)
    return tasks


def validate_plan(tasks: list[Task], max_tool_calls: int) -> None:
    if len(tasks) > max_tool_calls:
        raise ValueError("Tool-call budget is too small for the research plan")
    ids = [task.id for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate task ID")
    known: set[str] = set()
    for task in tasks:
        if task.tool not in ALLOWED_TOOLS:
            raise ValueError(f"Tool {task.tool} is not allowed")
        if any(dep not in known for dep in task.depends_on):
            raise ValueError(f"Task {task.id} has a missing or forward dependency")
        known.add(task.id)
