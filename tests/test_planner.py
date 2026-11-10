import pytest

from research_engine.contracts import Budget, Objective
from research_engine.planner import analyze_objective, make_plan, validate_plan


def test_full_research_objective_selects_relevant_sources():
    objective = Objective(
        "NVDA",
        "Analyze revenue growth drivers, principal risks, peers, and bear/base/bull scenarios",
    )
    assert {task.tool for task in make_plan(objective)} == {
        "search_companies", "financials", "data_notes", "filings", "risk_section",
        "segments", "mdna_section", "earnings", "events", "peers",
        "model_defaults", "model_scenarios",
    }
    assert "scenarios" in analyze_objective(objective.request)


def test_small_budget_rejects_plan_before_api_calls():
    objective = Objective("NVDA", "Compare peers and risks", Budget(max_tool_calls=3))
    with pytest.raises(ValueError, match="budget"):
        make_plan(objective)


def test_simple_summary_has_bounded_plan():
    plan = make_plan(Objective("NVDA", "Financial summary", Budget(max_tool_calls=3)))
    assert [task.id for task in plan] == ["resolve", "financials", "data_notes"]
    validate_plan(plan, 3)
