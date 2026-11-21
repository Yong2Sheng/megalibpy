"""Exercise real subprocess boundaries with a tiny stand-in for Cosima."""

import gzip
import json
import os
import subprocess
from pathlib import Path
import sys
import time

import pytest

from megalibpy import Cosima, ExecutionError, MEGAlibRuntime


@pytest.fixture
def inputs(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "detector.setup").write_text("# detector configuration\n")
    (source_dir / "pointing.ori").write_text("# pointing configuration\n")
    (source_dir / "spectrum.dat").write_text("100 1\n200 1\n")
    source = source_dir / "example.source"
    source.write_text(
        "# Keep comments and unsupported-but-valid parameters\n"
        "Geometry detector.setup\nRun Burst\nBurst.FileName old-output # output\n"
        "Burst.Time 1\nBurst.OrientationSky Galactic File NoLoop pointing.ori\n"
        "Burst.Source GRB\nGRB.Spectrum File spectrum.dat\nUnknownDirective KeepMe\n"
    )
    executable = tmp_path / "fake-cosima"
    executable.write_text(f"#!{sys.executable}\n" + '''
import gzip, os, pathlib, subprocess, sys, time
mode = os.environ.get("COSIMA_TEST_MODE", "success")
print("fake cosima", flush=True)
print("marker=" + os.environ.get("COSIMA_SETUP_MARKER", "absent"), flush=True)
print("pythonpath=" + os.environ.get("PYTHONPATH", "absent"), flush=True)
print("librarypath=" + os.environ.get("LD_LIBRARY_PATH", "absent"), flush=True)
print("diagnostic stderr", file=sys.stderr, flush=True)
if mode == "exit":
    sys.exit(7)
if mode == "sleep":
    subprocess.Popen([sys.executable, "-c",
        "import time,pathlib; time.sleep(0.6); pathlib.Path('late-child').write_text('bad')"])
    time.sleep(20)
if mode == "missing":
    sys.exit(0)
lines = pathlib.Path(sys.argv[-1]).read_text().splitlines()
prefix = next(line.split("#")[0].split()[1] for line in lines if ".FileName " in line)
if mode == "partial":
    pathlib.Path(prefix + ".inc1.id1.sim.gz.partial").write_text("unfinished")
    sys.exit(0)
for number in (1, 2):
    path = pathlib.Path(prefix + f".inc2.id{number}.sim" + (".gz" if "-z" in sys.argv else ""))
    if "-z" in sys.argv:
        with gzip.open(path, "wt") as f:
            f.write("# simulated event file\\n")
    else:
        path.write_text("# simulated event file\\n")
''')
    executable.chmod(0o755)
    return source, executable


def manifest(result):
    return result.record


def test_direct_snapshots_relative_files_and_multiple_outputs(inputs, tmp_path):
    source, executable = inputs
    original = source.read_bytes()
    cwd = Path.cwd()
    result = Cosima(executable=executable).simulate(source, seed=42, output_dir=tmp_path / "run")
    record = manifest(result)
    assert record["status"] == "succeeded"
    assert record["seed"] == 42
    assert record["runtime"]["mode"] == "direct"
    assert record["runtime"]["executable"]["sha256"]
    assert len(result.outputs["sim"]) == 2
    for output in result.outputs["sim"]:
        with gzip.open(output, "rt") as stream:
            assert "event file" in stream.read()
    assert source.read_bytes() == original
    assert (result.output_dir / "inputs/original.source").read_bytes() == original
    executed = (result.output_dir / "inputs/executed.source").read_text()
    assert "UnknownDirective KeepMe" in executed
    assert "# output" in executed
    assert f"Geometry {source.parent / 'detector.setup'}" in executed
    assert f"File NoLoop {source.parent / 'pointing.ori'}" in executed
    assert f"Spectrum File {source.parent / 'spectrum.dat'}" in executed
    assert len(record["dependencies"]) == 3
    assert record["dependency_capture"]["complete"] is False
    assert "fake cosima" in result.stdout_path.read_text()
    assert "diagnostic stderr" in result.stderr_path.read_text()
    assert Path.cwd() == cwd


def test_setup_script_quoting_and_parent_isolation(inputs, tmp_path, monkeypatch):
    source, executable = inputs
    tool_dir = tmp_path / "tools with spaces"
    tool_dir.mkdir()
    executable.rename(tool_dir / "cosima")
    setup = tmp_path / "setup ' ; unsafe-looking.sh"
    setup.write_text('export PATH="' + str(tool_dir) + ':$PATH"\nexport COSIMA_SETUP_MARKER=child\n')
    monkeypatch.setenv("PYTHONPATH", "parent-only-python")
    monkeypatch.setenv("LD_LIBRARY_PATH", "parent-only-library")
    result = Cosima(MEGAlibRuntime.from_setup_script(setup)).simulate(
        source, seed=1, compressed=False, output_dir=tmp_path / "run"
    )
    assert "marker=child" in result.stdout_path.read_text()
    assert "pythonpath=absent" in result.stdout_path.read_text()
    assert "librarypath=absent" in result.stdout_path.read_text()
    assert os.environ["PYTHONPATH"] == "parent-only-python"
    assert os.environ.get("COSIMA_SETUP_MARKER") is None
    assert result.outputs["sim"][0].suffix == ".sim"
    record = manifest(result)
    assert record["runtime"]["mode"] == "setup_script"
    assert record["runtime"]["setup_script"]["sha256"]
    assert record["runtime"]["executable"]["path"] == str(tool_dir / "cosima")


@pytest.mark.parametrize("mode, expected_returncode", [("exit", 7), ("missing", 0), ("partial", 0)])
def test_failure_and_missing_output_keep_records(inputs, tmp_path, monkeypatch, mode, expected_returncode):
    source, executable = inputs
    monkeypatch.setenv("COSIMA_TEST_MODE", mode)
    with pytest.raises(ExecutionError) as error:
        Cosima(executable=executable).simulate(source, output_dir=tmp_path / "run")
    record = next(iter(json.loads(error.value.manifest_path.read_text())["executions"].values()))
    assert record["status"] == "failed"
    assert record["returncode"] == expected_returncode
    assert record["finished_at"]
    assert 0 < record["seed"] < 2**31
    assert (tmp_path / "run/cosima/logs/cosima-001.stderr.log").is_file()


def test_setup_failure_does_not_execute_tool(inputs, tmp_path):
    source, executable = inputs
    setup = tmp_path / "setup.sh"
    setup.write_text("return 23\n")
    with pytest.raises(ExecutionError) as error:
        Cosima(MEGAlibRuntime.from_setup_script(setup), executable=executable).simulate(
            source, output_dir=tmp_path / "run"
        )
    assert error.value.returncode == 23
    assert "setup failed" in (tmp_path / "run/cosima/logs/cosima-001.stderr.log").read_text()
    assert not list((tmp_path / "run/cosima/products").iterdir())


def test_timeout_kills_child_group(inputs, tmp_path, monkeypatch):
    source, executable = inputs
    monkeypatch.setenv("COSIMA_TEST_MODE", "sleep")
    with pytest.raises(ExecutionError, match="timeout") as error:
        Cosima(executable=executable).simulate(source, timeout=0.2, output_dir=tmp_path / "run")
    assert next(iter(json.loads(error.value.manifest_path.read_text())["executions"].values()))["status"] == "failed"
    time.sleep(0.8)
    assert not (source.parent / "late-child").exists()


def test_missing_executable_is_preparation_failure(inputs, tmp_path):
    source, _ = inputs
    with pytest.raises(ExecutionError, match="Cannot find") as error:
        Cosima(executable="megalibpy-nonexistent-cosima").simulate(source, output_dir=tmp_path / "run")
    assert next(iter(json.loads(error.value.manifest_path.read_text())["executions"].values()))["returncode"] is None


def test_existing_workspace_is_not_reused(inputs, tmp_path):
    source, executable = inputs
    directory = tmp_path / "run"
    directory.mkdir()
    (directory / "cosima").mkdir()
    sentinel = directory / "keep"
    sentinel.write_text("existing data")
    with pytest.raises(FileExistsError):
        Cosima(executable=executable).simulate(source, output_dir=directory)
    assert sentinel.read_text() == "existing data"


def test_input_validation_records_failure(inputs, tmp_path):
    source, executable = inputs
    source.write_text(source.read_text() + "Run Second\n")
    with pytest.raises(ExecutionError, match="exactly one") as error:
        Cosima(executable=executable).simulate(source, output_dir=tmp_path / "run")
    assert next(iter(json.loads(error.value.manifest_path.read_text())["executions"].values()))["status"] == "failed"


def test_large_explicit_dependency_is_not_hashed_or_copied(inputs, tmp_path):
    source, executable = inputs
    external = source.parent / "large.dat"
    external.write_text("large" * 100)
    result = Cosima(executable=executable).simulate(
        source, output_dir=tmp_path / "run", dependencies=["large.dat"], hash_limit_bytes=100
    )
    entry = next(d for d in manifest(result)["dependencies"] if d["path"] == str(external))
    assert entry["sha256"] is None
    assert entry["hash_policy"] == "size_and_mtime_only"
    assert "snapshot" not in entry


@pytest.mark.parametrize("seed", [0, -1, 2**31, True, 1.5])
def test_invalid_seed_does_not_start(inputs, tmp_path, seed):
    source, executable = inputs
    with pytest.raises(ValueError, match="seed"):
        Cosima(executable=executable).simulate(source, seed=seed, output_dir=tmp_path / "run")
    assert not (tmp_path / "run").exists()


def test_direct_relative_executable_resolves_before_cwd_change(inputs, tmp_path, monkeypatch):
    source, executable = inputs
    monkeypatch.chdir(tmp_path)
    result = Cosima(executable="./" + executable.name).simulate(source, output_dir=tmp_path / "run")
    assert manifest(result)["runtime"]["executable"]["path"] == str(executable)


def test_missing_source_and_setup_retain_failure_manifest(inputs, tmp_path):
    source, executable = inputs
    with pytest.raises(ExecutionError) as error:
        Cosima(executable=executable).simulate(tmp_path / "missing.source", output_dir=tmp_path / "missing-source")
    assert next(iter(json.loads(error.value.manifest_path.read_text())["executions"].values()))["error"]["type"] == "FileNotFoundError"
    with pytest.raises(ExecutionError) as error:
        Cosima(MEGAlibRuntime.from_setup_script(tmp_path / "missing.sh")).simulate(
            source, output_dir=tmp_path / "missing-setup"
        )
    assert next(iter(json.loads(error.value.manifest_path.read_text())["executions"].values()))["status"] == "failed"


def test_source_include_rejected_without_running(inputs, tmp_path):
    source, executable = inputs
    source.write_text(source.read_text() + "Include other.source\n")
    with pytest.raises(ExecutionError, match="Included source"):
        Cosima(executable=executable).simulate(source, output_dir=tmp_path / "run")
    assert not list((tmp_path / "run/cosima/products").iterdir())


def test_setup_uses_script_file_not_multiline_shell_argument(inputs, tmp_path):
    source, executable = inputs
    setup = tmp_path / "setup.sh"
    setup.write_text("export COSIMA_SETUP_MARKER=child\n")
    result = Cosima(MEGAlibRuntime.from_setup_script(setup), executable=executable).simulate(
        source, output_dir=tmp_path / "run"
    )
    record = manifest(result)
    argv = record["launch_command"]
    assert "-c" not in argv
    assert all("\n" not in argument for argument in argv)
    bootstrap = result.output_dir / record["runtime"]["bootstrap"]["snapshot"]
    assert bootstrap.is_file()
    assert str(bootstrap) in argv
    assert 'source "$1"' in bootstrap.read_text()
    assert "marker=child" in result.stdout_path.read_text()


@pytest.mark.skipif(not Path("/proc/self/cmdline").exists(), reason="Linux /proc regression")
def test_root_64004_style_shell_detection(inputs, tmp_path):
    source, executable = inputs
    setup = tmp_path / "root-style-setup.sh"
    setup.write_text('''# Reproduce ROOT 6.40.04's shell-name discovery on Linux.
trueExe=$(cut -d '' -f1 /proc/$$/cmdline)
name=$(basename "$trueExe")
if [ "$name" != "bash" ]; then
    printf 'Unexpected shell: %s\\n' "$name" >&2
    return 37
fi
''')
    # Multiline -c argv reproduces the old ROOT detector's bad shell name.
    old = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c",
         'source "$1"\nstatus=$?\nif [ "$status" -ne 0 ]; then exit "$status"; fi\n',
         "megalibpy-test", str(setup)],
        capture_output=True, text=True,
    )
    assert old.returncode == 37
    result = Cosima(MEGAlibRuntime.from_setup_script(setup), executable=executable).simulate(
        source, output_dir=tmp_path / "run"
    )
    assert result.returncode == 0
    assert result.stderr_path.read_text().strip() == "diagnostic stderr"
