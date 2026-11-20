"""Run tools with bounded log memory and persistent failure diagnostics."""

from datetime import datetime, timezone
from importlib.metadata import version
import os
from pathlib import Path
import platform
import signal
import subprocess
import time

from .errors import ExecutionError
from .models import ExecutionResult
from .provenance import file_record, write_manifest
from .workspace import Workspace


def _now():
    return datetime.now(timezone.utc).isoformat()


def _source_revision():
    # Editable installs can change without a version bump. Record revision and
    # dirty status without disclosing filenames or the patch itself.
    for root in Path(__file__).resolve().parents:
        if (root / ".git").exists() and (root / "pyproject.toml").is_file():
            try:
                revision = subprocess.check_output(
                    ["git", "-C", str(root), "rev-parse", "HEAD"],
                    stderr=subprocess.DEVNULL, text=True, timeout=5,
                ).strip()
                dirty = subprocess.check_output(
                    ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"],
                    stderr=subprocess.DEVNULL, text=True, timeout=5,
                ).strip()
                return {"commit": revision, "dirty": bool(dirty)}
            except (OSError, subprocess.SubprocessError):
                break
    return None


def _stop(process):
    """Terminate the entire process group, including startup-script children."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


class Executor:
    """Common synchronous execution lifecycle for MEGAlib command-line tools."""

    def __init__(self, runtime):
        self.runtime = runtime

    def execute(self, tool, output_dir, prepare, *, timeout=None):
        if os.name != "posix":
            raise NotImplementedError("MEGAlib execution currently requires a POSIX host")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        workspace = Workspace.create(output_dir)
        root = workspace.root
        manifest = {
            "schema_version": 1, "tool": tool, "status": "preparing",
            "started_at": _now(), "finished_at": None, "returncode": None,
            "software": {"megalibpy": version("megalibpy"),
                         "python": platform.python_version(), "platform": platform.platform(),
                         "source_revision": _source_revision()},
            "runtime": {"mode": "setup_script" if self.runtime.setup_script else "direct"},
            "logs": {"stdout": "logs/stdout.log", "stderr": "logs/stderr.log"},
            "outputs": {},
        }
        write_manifest(workspace.manifest_path, manifest)
        process = None
        started = time.monotonic()
        executable_record = root / "logs/executable.txt"
        stdout_path, stderr_path = root / "logs/stdout.log", root / "logs/stderr.log"
        stdout_path.touch()
        stderr_path.touch()
        try:
            if self.runtime.setup_script:
                script = self.runtime.setup_script
                snapshot = root / "inputs/setup.sh"
                snapshot.write_bytes(script.read_bytes())
                manifest["runtime"]["setup_script"] = {
                    "original_path": str(script), "snapshot": "inputs/setup.sh",
                    **file_record(snapshot),
                }
                # Execute the original location: scripts may use BASH_SOURCE to
                # locate installation files. The snapshot is an audit artifact.
            plan = prepare(workspace)
            manifest.update(command=list(plan.command), cwd=str(plan.cwd),
                            output_patterns=plan.output_patterns, **plan.metadata)
            command, env = self.runtime.launch(plan.command, executable_record)
            manifest.update(status="running", launch_command=command)
            write_manifest(workspace.manifest_path, manifest)
            with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
                process = subprocess.Popen(
                    command, cwd=plan.cwd, env=env, stdout=out, stderr=err,
                    start_new_session=True,
                )
                try:
                    manifest["returncode"] = process.wait(timeout=timeout)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    _stop(process)
                    manifest["returncode"] = process.returncode
                    raise
            if process.returncode != 0:
                raise RuntimeError(f"{tool} exited with status {process.returncode}")
            outputs = {}
            for key, pattern in plan.output_patterns.items():
                paths = tuple(sorted((root / "products").glob(pattern)))
                paths = tuple(p for p in paths if p.is_file() and p.stat().st_size > 0)
                if not paths:
                    raise RuntimeError(f"No nonempty {key} output matched {pattern!r}")
                outputs[key] = paths
            manifest["outputs"] = {
                key: [str(p.relative_to(root)) for p in paths] for key, paths in outputs.items()
            }
            manifest["validation"] = "zero exit status and nonempty output files; no scientific validation"
            manifest["status"] = "succeeded"
        except BaseException as exc:
            if process is not None and process.poll() is None:
                _stop(process)
                manifest["returncode"] = process.returncode
            manifest["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
            manifest["error"] = {"type": type(exc).__name__, "message": str(exc)}
            if isinstance(exc, subprocess.TimeoutExpired):
                manifest["error"]["message"] = f"Execution exceeded timeout of {timeout} seconds"
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise ExecutionError(manifest["error"]["message"], workspace.manifest_path,
                                 manifest["returncode"]) from exc
        finally:
            # Capture the actual tool resolved inside the initialized child.
            try:
                if executable_record.is_file():
                    executable = Path(executable_record.read_text().strip())
                    if executable.is_file():
                        manifest["runtime"]["executable"] = file_record(executable)
            except OSError as exc:
                manifest["runtime"]["executable_record_error"] = str(exc)
            manifest["finished_at"] = _now()
            manifest["duration_seconds"] = time.monotonic() - started
            write_manifest(workspace.manifest_path, manifest)
        return ExecutionResult(root, outputs, workspace.manifest_path, stdout_path, stderr_path)
