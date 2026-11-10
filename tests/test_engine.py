
import httpx
import pytest

from research_engine.client import TributaryClient
from research_engine.contracts import Objective, RunStatus
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
            return httpx.Response(200, json={"results": [{"ticker": "NVDA", "company_id": "0001045810"}]})
        if request.url.path.endswith("/financials"):
            return httpx.Response(200, json={"metrics": {"revenue": [FIGURE]}})
        if request.url.path.endswith("/sections/item_1a"):
            return httpx.Response(200, json={
                "accession_no": "0001045810-26-000075", "section_key": "item_1a",
                "text": "The company faces competition and supply risk.",
            })
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
            return httpx.Response(200, json={"results": [{"ticker": "NVDA", "company_id": "0001045810"}]})
        if request.url.path.endswith("/financials"):
            financial_attempts += 1
            if financial_attempts == 1:
                raise TimeoutError()
            return httpx.Response(200, json={"data": [FIGURE]})
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
        return httpx.Response(200, json={"results": [{"ticker": "NVDA", "company_id": "0001045810"}]})

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
