"""Run tools with bounded log memory and persistent failure diagnostics."""

from datetime import datetime, timezone
from dataclasses import replace
from contextlib import nullcontext
import tempfile
from importlib.metadata import version
import os
from pathlib import Path
import platform
import signal
import subprocess
import time
from uuid import uuid4

from .errors import ExecutionError
from .models import ExecutionResult
from .logs import StreamLog
from .provenance import capture_upstream, encode_content, file_record
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
    """Manage one synchronous MEGAlib execution attempt at a time.

    Parameters
    ----------
    runtime : MEGAlibRuntime
        Direct or setup-script runtime used to prepare each child process.

    Notes
    -----
    This shared implementation is intended for tool adapters such as ``Cosima``.
    It writes manifests and streams logs to disk without changing the parent
    environment or working directory.
    """

    def __init__(self, runtime):
        self.runtime = runtime

    def execute(self, tool, output_dir, prepare, *, timeout=None, log_mode=None):
        """Prepare a fresh workspace, execute a plan, and validate its outputs.

        Parameters
        ----------
        tool : str
            Tool label recorded in the manifest, for example ``"cosima"``.
        output_dir : str or pathlib.Path
            Workspace path, which must not exist. Parent directories are created.
        prepare : callable
            Function receiving a ``Workspace`` and returning an ``ExecutionPlan``.
            It may create input snapshots and supply tool-specific metadata.
        timeout : float or None, optional
            Positive time limit in seconds for the child, including any setup
            script. ``None`` waits without a limit. Preparation and final record
            writing are not included in this limit.

        Returns
        -------
        ExecutionResult
            Paths to the successful execution's outputs, manifest, and logs.

        Raises
        ------
        ValueError
            ``timeout`` is nonpositive.
        NotImplementedError
            The host is not POSIX-compatible.
        FileExistsError
            The output directory already exists.
        OSError
            The initial workspace or execution record cannot be created.
        ExecutionError
            Preparation, launch, execution, timeout, or output checks fail after
            record creation. The manifest retains failure details.
        KeyboardInterrupt
            Execution is interrupted; the process group is stopped and the
            interrupted state is recorded before propagating the interrupt.
        """
        if os.name != "posix":
            raise NotImplementedError("MEGAlib execution currently requires a POSIX host")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        mode = self.runtime.log_mode if log_mode is None else log_mode
        if mode not in ("full", "tail", "summary") or (mode == "summary" and tool != "cosima"):
            raise ValueError("log_mode must be full/tail, or summary for Cosima")
        if not isinstance(self.runtime.archive_inputs, bool):
            raise ValueError("archive_inputs must be bool")
        if not isinstance(self.runtime.log_tail_bytes, int) or isinstance(self.runtime.log_tail_bytes, bool) or self.runtime.log_tail_bytes <= 0:
            raise ValueError("log_tail_bytes must be a positive integer")
        workspace = output_dir if isinstance(output_dir, Workspace) else Workspace.create(output_dir)
        workspace = replace(workspace, archive_inputs=self.runtime.archive_inputs)
        root = workspace.root
        manifest = {
            "schema_version": 2, "execution_id": workspace.execution_id or str(uuid4()),
            "tool": tool, "status": "preparing", "upstream": [],
            "started_at": _now(), "finished_at": None, "returncode": None,
            "software": {"megalibpy": version("megalibpy"),
                         "python": platform.python_version(), "platform": platform.platform(),
                         "source_revision": _source_revision()},
            "runtime": {"mode": "setup_script" if self.runtime.setup_script else "direct"},
            "logs": {"stdout": str(workspace.log_path("stdout.log").relative_to(root)),
                     "stderr": str(workspace.log_path("stderr.log").relative_to(root))},
            "outputs": {},
        }
        workspace.save(manifest)
        process = None
        started = time.monotonic()
        temporary = None
        executable_record = None
        pumps = []
        stdout_path, stderr_path = workspace.log_path("stdout.log"), workspace.log_path("stderr.log")
        with workspace.owner._locked() if workspace.owner is not None else nullcontext():
            workspace.logs_dir.mkdir(exist_ok=True)
            stdout_path.touch()
            stderr_path.touch()
        try:
            if self.runtime.setup_script:
                script = self.runtime.setup_script
                content = script.read_bytes()
                manifest["runtime"]["setup_script"] = {
                    "original_path": str(script), "snapshot": None,
                    **file_record(script), "retention": "manifest" if self.runtime.archive_inputs else "reference",
                    **(encode_content(content) if self.runtime.archive_inputs else {}),
                }
                # Execute the original location: scripts may use BASH_SOURCE to
                # locate installation files. The snapshot is an audit artifact.
            plan = prepare(workspace)
            reserved = set(manifest) | {
                "command", "cwd", "output_patterns", "launch_command", "validation",
                "error", "duration_seconds",
                "tool_environment",
            }
            if reserved.intersection(plan.metadata):
                raise ValueError("Tool metadata cannot override reserved execution fields")
            manifest["upstream"] = capture_upstream(workspace, plan.upstream)
            manifest.update(command=list(plan.command), cwd=str(plan.cwd),
                            output_patterns=plan.output_patterns, **plan.metadata)
            manifest["tool_environment"] = plan.environment
            temporary = tempfile.TemporaryDirectory(prefix="megalibpy-launch-")
            executable_record = Path(temporary.name) / "executable.txt"
            command, env = self.runtime.launch(plan.command, executable_record,
                                              tool_environment=plan.environment)
            bootstrap = executable_record.parent / "launch.sh"
            if self.runtime.setup_script and bootstrap.is_file():
                manifest["runtime"]["bootstrap"] = {
                    "snapshot": None, **encode_content(bootstrap.read_bytes()),
                    "retention": "temporary_removed_after_execution",
                }
            manifest.update(status="running", launch_command=command)
            workspace.save(manifest)
            process = subprocess.Popen(
                command, cwd=plan.cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,
            )
            pumps = [StreamLog(process.stdout, stdout_path, mode, self.runtime.log_tail_bytes),
                     StreamLog(process.stderr, stderr_path, "full" if mode == "full" else "tail", self.runtime.log_tail_bytes)]
            for pump in pumps:
                pump.start()
            try:
                manifest["returncode"] = process.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                _stop(process)
                manifest["returncode"] = process.returncode
                raise
            for pump in pumps:
                pump.join(timeout=3)
            if any(pump.is_alive() for pump in pumps):
                _stop(process)
                raise RuntimeError("Native child left log pipes open after exit")
            if any(pump.error is not None for pump in pumps):
                raise RuntimeError(f"Log capture failed: {[str(p.error) for p in pumps if p.error]}")
            if process.returncode != 0:
                raise RuntimeError(f"{tool} exited with status {process.returncode}")
            outputs = {}
            for key, pattern in plan.output_patterns.items():
                paths = tuple(sorted(workspace.products_dir.glob(pattern)))
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
                                 manifest["returncode"], manifest["execution_id"]) from exc
        finally:
            # Capture the actual tool resolved inside the initialized child.
            try:
                if executable_record is not None and executable_record.is_file():
                    executable = Path(executable_record.read_text().strip())
                    if executable.is_file():
                        manifest["runtime"]["executable"] = file_record(executable)
            except OSError as exc:
                manifest["runtime"]["executable_record_error"] = str(exc)
            for pump in pumps:
                pump.join(timeout=3)
            if pumps:
                manifest["logs"]["capture"] = {"stdout": pumps[0].metadata(), "stderr": pumps[1].metadata()}
            with workspace.owner._locked() if workspace.owner is not None else nullcontext():
                for key, path in (("stdout", stdout_path), ("stderr", stderr_path)):
                    if not path.exists() or path.stat().st_size == 0:
                        path.unlink(missing_ok=True)
                        manifest["logs"][key] = None
                for path in workspace.transient_files:
                    path.unlink(missing_ok=True)
                for folder in (workspace.inputs_dir, workspace.logs_dir):
                    try:
                        folder.rmdir()
                    except OSError:
                        pass
            if temporary is not None:
                temporary.cleanup()
            manifest["finished_at"] = _now()
            manifest["duration_seconds"] = time.monotonic() - started
            workspace.save(manifest)
        return ExecutionResult(root, outputs, workspace.manifest_path,
                               stdout_path if manifest["logs"]["stdout"] is not None else None,
                               stderr_path if manifest["logs"]["stderr"] is not None else None,
                               execution_id=manifest["execution_id"])
