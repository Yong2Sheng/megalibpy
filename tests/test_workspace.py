"""Experiment allocation, retries and index protection."""

import json

import pytest

from megalibpy import SimulationWorkspace


def test_failed_allocation_is_retained_and_cosima_can_retry(tmp_path):
    experiment = SimulationWorkspace(tmp_path / "experiment")
    def fail(target):
        raise RuntimeError("before executor allocation")
    for _ in range(2):
        with pytest.raises(RuntimeError, match="before executor"):
            experiment.execute("cosima", "simulation", fail)
    data = json.loads(experiment.index_path.read_text())
    attempts = data["tasks"]["cosima:simulation"]["attempts"]
    assert [a["number"] for a in attempts] == [1, 2]
    assert all(a["status"] == "failed" for a in attempts)
    assert not (experiment.root / ".workspace.lock").exists()


def test_busy_lock_does_not_get_deleted(tmp_path):
    experiment = SimulationWorkspace(tmp_path)
    lock = tmp_path / ".workspace.lock"
    lock.write_text("busy")
    with pytest.raises(FileExistsError):
        experiment.execute("revan", "baseline", lambda p: None)
    assert lock.read_text() == "busy"


@pytest.mark.parametrize("stage,task", [("../escape", "a"), ("revan", "../escape"),
                                         ("cosima", "other"), ("revan", "")])
def test_invalid_labels_do_not_create_an_experiment(tmp_path, stage, task):
    experiment = SimulationWorkspace(tmp_path / "experiment")
    with pytest.raises(ValueError):
        experiment.execute(stage, task, lambda p: None)
    assert not experiment.root.exists()


def test_unknown_manifest_not_overwritten(tmp_path):
    path = tmp_path / "manifest.json"
    original = '{"unrelated": true}'
    path.write_text(original)
    with pytest.raises(ValueError, match="supported simulation"):
        SimulationWorkspace(tmp_path).execute("revan", "baseline", lambda p: None)
    assert path.read_text() == original
