import pytest

from research_engine.client import TributaryClient
from research_engine.contracts import Objective, RunStatus
from research_engine.demo import demo_transport, load_demo_fixture
from research_engine.engine import ResearchEngine
from research_engine.storage import RunStore


@pytest.mark.asyncio
async def test_pinned_demo_runs_without_network_or_real_token(tmp_path):
    assert "SYNTHETIC DATA" in load_demo_fixture()["notice"]
    store = RunStore(tmp_path / "runs")
    async with TributaryClient("fixture-only", "https://fixture.invalid/api/query",
                               transport=demo_transport()) as client:
        engine = ResearchEngine(client, store)
        result = await engine.execute(engine.create(Objective("ACME", "Financial summary"),
                                                    data_mode="fixture"))
    assert result.status == RunStatus.COMPLETED
    report = (store.directory(result.id) / "report.md").read_text()
    assert "Data mode: **fixture**" in report
    assert "A pinned synthetic fixture" in report
    assert "1200000000" in report
