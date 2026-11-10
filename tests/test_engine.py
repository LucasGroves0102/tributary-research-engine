
import json

import httpx
import pytest

from research_engine.client import TributaryClient
from research_engine.contracts import Objective, RunStatus
from research_engine.demo import load_demo_fixture
from research_engine.engine import ResearchEngine
from research_engine.storage import RunStore

FIGURE = {
    "metric": "revenue",
    "value": "100.25",
    "unit": "USD",
    "period_end": "2026-07-31",
    "currency": "USD",
    "value_source": "reported",
    "citation": {"accession_no": "0001045810-26-000075", "form": "10-Q"},
}


@pytest.mark.asyncio
async def test_run_creates_verified_evidence_and_private_trace(tmp_path):
    paths = []

    def respond(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"results": [{"tickers": ["NVDA"], "company_id": "0001045810"}]})
        if request.url.path.endswith("/financials"):
            return httpx.Response(200, json={"company_id": "0001045810", "rows": [FIGURE]})
        if request.url.path.endswith("/sections/1A"):
            return httpx.Response(200, json={"sections": [{
                "section_key": "1A", "text": "The company faces competition and supply risk.",
                "citation": {"accession_no": "0001045810-26-000075", "section_key": "1A"},
            }]})
        return httpx.Response(200, json={"items": []})

    store = RunStore(tmp_path / "runs")
    async with TributaryClient("private-token", transport=httpx.MockTransport(respond)) as client:
        engine = ResearchEngine(client, store)
        run = engine.create(Objective("NVDA", "Financial performance and risks"))
        finished = await engine.execute(run)
        assert finished.status == RunStatus.PARTIAL
        assert (store.directory(run.id) / "report.md").exists()
        evidence = store.read_json(run.id, "evidence.json")
        assert len(evidence["evidence"]) >= 2
        assert evidence["evidence"][0]["payload"]["citation"]["accession_no"] == "0001045810-26-000075"
        trace = (store.directory(run.id) / "trace.jsonl").read_text()
        persisted_run = (store.directory(run.id) / "run.json").read_text()
        report = (store.directory(run.id) / "report.md").read_text()
        assert "private-token" not in trace
        assert "Financial performance and risks" not in trace
        assert "Financial performance and risks" not in persisted_run
        assert "Financial performance and risks" not in report
        assert "Filing excerpts for analyst review" in report
        assert "Research outcome: **partial**" in report
        assert (store.directory(run.id) / "trace.jsonl").stat().st_mode & 0o777 == 0o600
        before = len(paths)
        assert (await engine.execute(store.load_run(run.id))).status == RunStatus.PARTIAL
        assert len(paths) == before


@pytest.mark.asyncio
async def test_auth_failure_stops_without_follow_on_calls(tmp_path):
    count = 0

    def respond(request):
        nonlocal count
        count += 1
        return httpx.Response(401, json={"detail": "expired"})

    store = RunStore(tmp_path / "runs")
    async with TributaryClient("token", transport=httpx.MockTransport(respond)) as client:
        engine = ResearchEngine(client, store)
        run = await engine.execute(engine.create(Objective("NVDA", "Summary")))
    assert run.status == RunStatus.FAILED
    assert count == 1
    assert not (store.directory(run.id) / "evidence.json").exists()


@pytest.mark.asyncio
async def test_resume_does_not_repeat_completed_tasks(tmp_path, monkeypatch):
    searches = 0
    financial_attempts = 0

    def respond(request):
        nonlocal searches, financial_attempts
        if request.url.path.endswith("/search"):
            searches += 1
            return httpx.Response(200, json={"results": [{"tickers": ["NVDA"], "company_id": "0001045810"}]})
        if request.url.path.endswith("/financials"):
            financial_attempts += 1
            if financial_attempts == 1:
                raise TimeoutError()
            return httpx.Response(200, json={"company_id": "0001045810", "rows": [FIGURE]})
        return httpx.Response(200, json={"items": []})

    store = RunStore(tmp_path / "runs")
    async with TributaryClient("token", transport=httpx.MockTransport(respond), max_retries=0) as client:
        engine = ResearchEngine(client, store)
        run = engine.create(Objective("NVDA", "Summary"))
        first = await engine.execute(run)
        assert first.status == RunStatus.PAUSED
        monkeypatch.setattr("research_engine.engine.make_plan", lambda _: (_ for _ in ()).throw(
            AssertionError("Plan was regenerated")))
        second = await engine.execute(store.load_run(run.id))
    assert second.status == RunStatus.COMPLETED
    assert searches == 1
    assert financial_attempts == 2


@pytest.mark.asyncio
async def test_resume_fails_closed_on_missing_completed_checkpoint(tmp_path):
    count = 0

    def respond(request):
        nonlocal count
        count += 1
        return httpx.Response(200, json={"results": [{"tickers": ["NVDA"], "company_id": "0001045810"}]})

    store = RunStore(tmp_path / "runs")
    async with TributaryClient("token", transport=httpx.MockTransport(respond)) as client:
        engine = ResearchEngine(client, store)
        run = engine.create(Objective("NVDA", "Summary"))
        run.task_status["resolve"] = "completed"
        run.company_id = "0001045810"
        run.status = RunStatus.PAUSED
        store.save_run(run)
        result = await engine.execute(run)
    assert result.status == RunStatus.FAILED
    assert "Checkpoint missing result" in result.errors[-1]
    assert count == 0


@pytest.mark.asyncio
async def test_scenarios_use_server_defaults_and_stay_separate_from_reported_facts(tmp_path):
    responses = load_demo_fixture()["responses"]
    posted = []

    def respond(request):
        path = request.url.path
        if path.endswith("/model"):
            posted.append(json.loads(request.content))
            key = "model_defaults" if len(posted) == 1 else "model_scenarios"
            return httpx.Response(200, json=responses[key])
        key = "search" if path.endswith("/search") else path.rsplit("/", 1)[-1].replace("-", "_")
        return httpx.Response(200, json=responses[key])

    store = RunStore(tmp_path / "runs")
    async with TributaryClient("token", transport=httpx.MockTransport(respond)) as client:
        engine = ResearchEngine(client, store)
        run = await engine.execute(engine.create(Objective("ACME", "Financial summary and scenarios")))
    assert run.status == RunStatus.COMPLETED
    assert len(posted) == 2
    assert posted[0]["assumptions"] == [{"growth": 0.0, "margin": 0.0}] * 3
    assert posted[1]["assumptions"] == responses["model_defaults"]["cases"]["base"]["defaults"]
    evidence = store.read_json(run.id, "evidence.json")["evidence"]
    forecasts = [item for item in evidence if item["kind"] == "model_projection"]
    assert {item["payload"]["case"] for item in forecasts} == {"bear", "base", "bull"}
    assert all(item["payload"]["classification"] == "forecast" for item in forecasts)
    assert all(item["kind"] != "model_projection" for item in evidence[:3])
    report = (store.directory(run.id) / "report.md").read_text()
    assert "Model scenarios (forecasts, not reported results)" in report
    assert "server preview scenarios" in report
