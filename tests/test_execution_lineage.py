"""Execution lineage supports fan-out without a workflow scheduler."""

import hashlib
import json
import sys
from uuid import UUID

import pytest

from megalibpy import ExecutionError, MEGAlibRuntime
from megalibpy.execution import ExecutionInput, ExecutionPlan
from megalibpy.execution.executor import Executor


def execute(tmp_path, name, *, upstream=(), metadata=None):
    def prepare(workspace):
        command = (sys.executable, "-c", "from pathlib import Path; "
                   f"Path({str(workspace.root / 'products/data')!r}).write_text('events')")
        return ExecutionPlan(command, workspace.root, {"events": "data"},
                             metadata or {}, upstream=upstream)
    return Executor(MEGAlibRuntime.direct(archive_inputs=True)).execute("stand-in", tmp_path / name, prepare)


def test_fan_out_preserves_identity_and_exact_parent_snapshot(tmp_path):
    parent = execute(tmp_path, "parent")
    original = parent.manifest_path.read_bytes()
    reference = parent.as_input("events")
    a = execute(tmp_path, "branch-a", upstream=(reference,), metadata={"configuration": "A"})
    b = execute(tmp_path, "branch-b", upstream=(reference,), metadata={"configuration": "B"})
    leaf = execute(tmp_path, "leaf", upstream=(a.as_input("events"),))
    assert len({parent.execution_id, a.execution_id, b.execution_id, leaf.execution_id}) == 4
    for result in (parent, a, b, leaf):
        UUID(result.execution_id)
    for child in (a, b):
        record = json.loads(child.manifest_path.read_text())
        edge, = record["upstream"]
        assert record["execution_id"] == child.execution_id
        assert edge["execution_id"] == parent.execution_id
        assert edge["paths"] == [str(p) for p in parent.outputs["events"]]
        assert edge["manifest_sha256"] == hashlib.sha256(original).hexdigest()
        assert (child.output_dir / edge["manifest_snapshot"]).read_bytes() == original
    assert json.loads(leaf.manifest_path.read_text())["upstream"][0]["execution_id"] == a.execution_id
    assert parent.manifest_path.read_bytes() == original
    with pytest.raises(KeyError):
        parent.as_input("missing")


def test_legacy_manifest_and_multiple_parents(tmp_path):
    parent = execute(tmp_path, "parent")
    other = execute(tmp_path, "other")
    record = json.loads(parent.manifest_path.read_text())
    record["schema_version"] = 1
    del record["execution_id"]
    parent.manifest_path.write_text(json.dumps(record))
    child = execute(tmp_path, "child", upstream=(ExecutionInput(parent.manifest_path, "events"),
                                               other.as_input("events")))
    edges = json.loads(child.manifest_path.read_text())["upstream"]
    assert edges[0]["execution_id"] is None
    assert edges[0]["manifest_sha256"]
    assert edges[1]["execution_id"] == other.execution_id


@pytest.mark.parametrize("corruption", ["failed", "missing-group", "escape", "identity"])
def test_invalid_upstream_fails_before_launch_with_diagnostics(tmp_path, corruption):
    parent = execute(tmp_path, "parent")
    record = json.loads(parent.manifest_path.read_text())
    if corruption == "failed":
        record["status"] = "failed"
    elif corruption == "missing-group":
        record["outputs"] = {}
    elif corruption == "escape":
        outside = tmp_path / "outside"
        outside.write_text("unrelated")
        record["outputs"]["events"] = [str(outside)]
    else:
        record["execution_id"] = "replaced"
    parent.manifest_path.write_text(json.dumps(record))
    with pytest.raises(ExecutionError) as error:
        execute(tmp_path, "child", upstream=(parent.as_input("events"),))
    failed = json.loads(error.value.manifest_path.read_text())
    assert failed["status"] == "failed"
    assert failed["execution_id"]
    assert not (error.value.manifest_path.parent / "products/data").exists()


@pytest.mark.parametrize("key", ["execution_id", "upstream", "status", "command"])
def test_metadata_cannot_replace_execution_identity(tmp_path, key):
    with pytest.raises(ExecutionError, match="reserved") as error:
        execute(tmp_path, "child", metadata={key: "override"})
    record = json.loads(error.value.manifest_path.read_text())
    UUID(record["execution_id"])
    assert record["status"] == "failed"
