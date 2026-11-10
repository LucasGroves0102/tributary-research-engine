from uuid import uuid4

import pytest

from research_engine.storage import RunStore


def test_run_lock_rejects_concurrent_execution(tmp_path):
    store = RunStore(tmp_path / "runs")
    run_id = str(uuid4())
    with store.lock(run_id), pytest.raises(RuntimeError, match="already being executed"):  # noqa: SIM117
        with store.lock(run_id):
            pass


def test_read_does_not_create_unknown_run(tmp_path):
    store = RunStore(tmp_path / "runs")
    run_id = str(uuid4())
    with pytest.raises(FileNotFoundError):
        store.load_run(run_id)
    assert not (store.root / run_id).exists()
