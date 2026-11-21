"""Experiment allocation, retries and index protection."""

import json

import pytest

from megalibpy import SimulationWorkspace


def test_failed_cosima_is_retained_and_cannot_retry(tmp_path):
    experiment = SimulationWorkspace(tmp_path / "experiment")
    def fail(target):
        raise RuntimeError("before executor allocation")
    with pytest.raises(RuntimeError, match="before executor"):
        experiment.execute("cosima", "simulation", fail)
    with pytest.raises(ValueError, match="new workspace"):
        experiment.execute("cosima", "simulation", fail)
    data = json.loads(experiment.index_path.read_text())
    assert len(data["executions"]) == 1
    assert next(iter(data["executions"].values()))["status"] == "failed"
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
