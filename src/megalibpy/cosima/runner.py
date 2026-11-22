"""Cosima simulation with configuration snapshots and explicit provenance."""

from pathlib import Path
import re
import secrets
import shutil

from ..execution import ExecutionPlan, MEGAlibRuntime, SimulationWorkspace
from ..execution.executor import Executor
from ..execution.provenance import encode_content, file_record, sha256
import hashlib


def _tokens(line):
    return line.split("#", 1)[0].split()


def _prepare_source(source, workspace, seed, compressed, executable, dependencies, hash_limit):
    original = source.read_bytes()
    text = original.decode("utf-8")
    lines = text.splitlines(keepends=True)
    runs = [t[1] for line in lines if (t := _tokens(line)) and t[0].lower() == "run" and len(t) == 2]
    if len(runs) != 1:
        raise ValueError("Cosima v1 requires exactly one inline Run declaration")
    if any(t and t[0].lower() == "include" for t in map(_tokens, lines)):
        raise ValueError("Included source files are not supported yet; use a self-contained source file")
    if any(t and t[0].lower() in {"activator", "activation", "createcrosssectionfiles"}
           for t in map(_tokens, lines)):
        raise ValueError("Cosima v1 supports ordinary event simulation, not activation/cross-section jobs")
    key = runs[0] + ".FileName"
    matches = [i for i, line in enumerate(lines)
               if (t := _tokens(line)) and t[0].lower() == key.lower()]
    if len(matches) != 1 or len(_tokens(lines[matches[0]])) != 2:
        raise ValueError(f"Expected exactly one {key} directive with an output prefix")
    # Use a fixed output prefix in a fresh workspace; do not trust source FileName
    # paths or assume that an existing .inc1.id1 file belongs to this execution.
    prefix = workspace.root / "products/events"
    if re.search(r"\s|\$", str(prefix)):
        raise ValueError("Cosima output paths must not contain whitespace or '$'")
    if workspace.archive_inputs:
        workspace.snapshot("original.source", original)
    external = set(dependencies)
    unresolved = []
    for index, line in enumerate(lines):
        tokens = _tokens(line)
        if not tokens:
            continue
        if index == matches[0]:
            comment = " #" + line.split("#", 1)[1].rstrip("\r\n") if "#" in line else ""
            lines[index] = f"{tokens[0]} {prefix}{comment}\n"
            continue
        directive = tokens[0].lower()
        # File paths interpreted relative to the source location must be rebased
        # before moving that file into inputs/. Unrecognized directives survive.
        positions = []
        if directive == "geometry" and len(tokens) == 2:
            positions = [1]
        elif directive.endswith((".orientationsky", ".orientation")):
            if any(t.lower() == "file" for t in tokens[1:]):
                positions = [len(tokens) - 1]
        elif directive.endswith((".spectrum", ".beam")):
            positions = [j for j, value in enumerate(tokens[1:], 1)
                         if (source.parent / value).is_file() or Path(value).is_file()]
            if len(tokens) > 2 and tokens[1].lower() == "file":
                positions.append(2)
        replacements = {}
        for position in set(positions):
            value = tokens[position]
            # Environment expansion belongs to the selected MEGAlib runtime.
            # The parent Python environment may define different values.
            if "$" in value or "~" in value:
                unresolved.append({"directive": tokens[0], "reference": value})
                continue
            path = Path(value)
            if not path.is_absolute():
                path = source.parent / path
            path = path.resolve(strict=True)
            if not path.is_file():
                raise ValueError(f"Input is not a regular file: {path}")
            if re.search(r"\s|\$", str(path)):
                raise ValueError(f"Cosima configuration file references cannot contain whitespace or '$': {path}")
            external.add(path)
            replacements[value] = str(path)
        if replacements:
            # Replace complete tokens only, preserving whitespace and comments.
            body, separator, comment = line.partition("#")
            body = re.sub(r"\S+", lambda m: replacements.get(m.group(), m.group()), body)
            lines[index] = body + separator + comment
    executed_bytes = "".join(lines).encode("utf-8")
    executed = workspace.snapshot("executed.source", executed_bytes)
    dependency_records = []
    for index, path in enumerate(sorted(external)):
        record = file_record(path, hash_limit=hash_limit)
        # Archive small declared/discovered files, but retain original locations
        # for dependencies referenced by geometry includes and other files.
        if workspace.archive_inputs and record["sha256"] is not None:
            target = workspace.root / "inputs" / f"dependency-{index:04d}{path.suffix}"
            shutil.copyfile(path, target)
            if sha256(target) != record["sha256"]:
                raise RuntimeError(f"Input changed while taking snapshot: {path}")
            record["snapshot"] = str(target.relative_to(workspace.root))
        dependency_records.append(record)
    command = (executable, "-z" if compressed else "-u", "-s", str(seed), str(executed))
    return ExecutionPlan(command, source.parent,
                         {"sim": "events*.sim.gz" if compressed else "events*.sim"}, {
        "seed": seed,
        "source": {"original_path": str(source),
                   "original_snapshot": "inputs/original.source" if workspace.archive_inputs else None,
                   "original_sha256": hashlib.sha256(original).hexdigest(),
                   "executed_snapshot": "inputs/executed.source" if workspace.archive_inputs else None,
                   "executed_sha256": hashlib.sha256(executed_bytes).hexdigest(),
                   "original": encode_content(original), "executed": encode_content(executed_bytes),
                   "retention": "archive" if workspace.archive_inputs else "manifest"},
        "dependencies": dependency_records,
        "dependency_capture": {
            "scope": "best_effort_top_level_and_explicit_files",
            "complete": False,
            "unresolved_references": unresolved,
            "limitations": "Nested geometry/includes and runtime-expanded paths are not automatically archived. "
                          "External files are still read from original locations; keep them immutable during execution.",
            "hash_limit_bytes": hash_limit,
            "retention": "eligible_files_archived" if workspace.archive_inputs else "references_only",
        },
    })


class Cosima:
    """Execute ordinary single-run Cosima event simulations.

    Parameters
    ----------
    runtime : MEGAlibRuntime, optional
        Defaults to direct execution. A setup-script runtime initializes MEGAlib
        in a separate Bash process without modifying the calling Python process.
    executable : str, optional
        Command name or executable path, defaulting to ``cosima``. Direct mode
        resolves it before changing the child working directory; setup-script
        mode resolves it inside the initialized child environment.

    Attributes
    ----------
    runtime : MEGAlibRuntime
        Runtime used for every call to :meth:`simulate` on this instance.
    executable : str
        Executable command or path supplied to the selected runtime.

    Notes
    -----
    Constructing this object does not start a process or check MEGAlib's
    availability. Checks occur when :meth:`simulate` is called. This wrapper
    requires a separate MEGAlib installation and does not import PyROOT.
    """

    def __init__(self, runtime=None, *, executable="cosima"):
        self.runtime = runtime if runtime is not None else MEGAlibRuntime.direct()
        self.executable = str(executable)

    def simulate(self, source_file, *, output_dir=None, workspace=None, seed=None, compressed=True,
                 timeout=None, dependencies=(), hash_limit_bytes=0, log_mode="full"):
        """Simulate events with Cosima and save an execution record.

        Parameters
        ----------
        source_file : str or pathlib.Path
            UTF-8 Cosima source file with one inline ``Run`` declaration and
            one corresponding ``FileName`` directive. Relative paths to this
            file are resolved against the calling Python working directory.
            Supported relative references inside the file are resolved against
            the source file's directory. The original file is never modified.
        output_dir : str or pathlib.Path or None, optional
            Experiment root. Missing parents are created; the Cosima stage must
            not already exist. Its absolute path cannot contain whitespace or
            ``$``. Creates cosima/inputs, logs and products, plus one root
            manifest.json. A new experiment is required for every rerun.
            Supply exactly one of ``output_dir`` or ``workspace``.
        workspace : SimulationWorkspace or str or pathlib.Path or None, optional
            Experiment object or root, default none. Writes directly into cosima/
            without an attempt directory. Exactly one Cosima execution is allowed,
            including failure; retries need a new workspace.
        seed : int or None, optional
            Positive integer in ``[1, 2147483647]`` passed to Cosima's ``-s``
            option. Defaults to ``None``, which generates and records a random
            seed in that range. Boolean values are rejected.
        compressed : bool, optional
            If ``True`` (default), pass ``-z`` and discover ``*.sim.gz`` files.
            If ``False``, pass ``-u`` and discover uncompressed ``*.sim`` files.
        timeout : float or None, optional
            Positive wall-clock limit in seconds for the child process,
            including environment initialization and Cosima execution.
            Defaults to ``None`` (no limit). Preparation and snapshot copying
            occur before this timer. A timeout terminates the process group
            and raises ``ExecutionError``.
        dependencies : iterable of str or pathlib.Path, optional
            Additional external files to record, defaulting to an empty tuple.
            Relative paths are resolved against the source directory. These
            declarations supplement supported automatically discovered inputs;
            they do not rewrite arbitrary directives or recursively discover
            geometry includes.
        hash_limit_bytes : int or None, optional
            Maximum external dependency size to hash, in bytes. Default zero
            records path, size and mtime without reading nonempty resources.
            None hashes all discovered/declared resources. Copies are made only
            when runtime.archive_inputs=True and a file is within this hash limit.
            Compact mode never copies geometry/orientation/spectrum dependencies.
            Source bytes and checksums are stored in the manifest by default.
        log_mode : str, optional
            "full" (default) streams complete stdout/stderr. "summary" streams
            stdout from the last line starting "Summary for run " to EOF,
            including the complete summary and shutdown text without a size cap.
            Earlier stdout is discarded while reading, not written first.
            Stderr is always retained in full. If no summary marker appears,
            stdout is absent and logs.capture marks summary_missing; no arbitrary
            tail is substituted. Empty logs are removed. This is a Python
            capture option, not a native MEGAlib flag.

        Returns
        -------
        megalibpy.ExecutionResult
            Successful execution with absolute paths to the workspace, logs,
            and manifest. ``result.outputs["sim"]`` is a sorted tuple of one or
            more nonempty simulation files; no ``inc1.id1`` naming assumption
            is made. ``result.returncode`` is zero.

        Raises
        ------
        ValueError
            The seed, hash limit, or timeout is invalid before preparation.
            No execution manifest is created for these argument errors.
        FileExistsError
            The execution directory already exists. It is never overwritten
            or reused, even if it is empty.
        OSError
            The execution directory or its initial record cannot be created.
        megalibpy.ExecutionError
            Source/setup preparation, program discovery, process startup,
            native execution, timeout, or output validation fails after the
            execution record is created. Inspect ``error.manifest_path``,
            ``error.returncode``, and the files in ``logs/`` for diagnostics.
            Unsupported source layouts are reported through this exception.
        KeyboardInterrupt
            The caller interrupts execution. The process group is terminated,
            the attempt is recorded as interrupted, and the interrupt is
            propagated to the caller.
        NotImplementedError
            The host is not POSIX-compatible.

        Notes
        -----
        This synchronous method blocks until the child finishes or fails.
        It preserves the parent Python environment and working directory.
        Source comments and unknown directives are retained in the execution
        copy; ``FileName`` is redirected to ``products/events`` and supported
        input paths are rebased. Source ``Include`` directives and
        activation/cross-section jobs are not supported in this version.

        Dependency capture is explicitly incomplete. Nested geometry includes
        and runtime-expanded paths require external archival, and external
        inputs must remain unchanged while the tool runs. Success checks only
        the exit status and nonempty output files; it does not establish
        scientific validity or complete gzip integrity.

        Examples
        --------
        In an already initialized MEGAlib environment:

        >>> result = Cosima().simulate(  # doctest: +SKIP
        ...     "small.source", output_dir="experiment/cosima-001", seed=12345
        ... )
        >>> result.outputs["sim"]  # doctest: +SKIP

        To initialize a separate MEGAlib environment, pass a
        :class:`~megalibpy.MEGAlibRuntime` created with ``from_setup_script``
        to the ``Cosima`` constructor.
        """
        if seed is None:
            seed = secrets.randbelow(2**31 - 1) + 1
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 < seed < 2**31:
            raise ValueError("seed must be an integer between 1 and 2147483647")
        if hash_limit_bytes is not None and hash_limit_bytes < 0:
            raise ValueError("hash_limit_bytes must be nonnegative or None")
        if (output_dir is None) == (workspace is None):
            raise ValueError("Supply exactly one of output_dir or workspace")
        source = Path(source_file).expanduser().resolve()
        files = []
        for path in dependencies:
            path = Path(path).expanduser()
            files.append((source.parent / path).resolve() if not path.is_absolute() else path.resolve())
        def execute(target):
            return Executor(self.runtime).execute(
                "cosima", target,
                lambda attempt: _prepare_source(source, attempt, seed, compressed,
                                                self.executable, files, hash_limit_bytes),
                timeout=timeout, log_mode=log_mode,
            )
        if workspace is not None:
            experiment = workspace if isinstance(workspace, SimulationWorkspace) else SimulationWorkspace(workspace)
            return experiment.execute("cosima", "simulation", execute)
        return SimulationWorkspace(output_dir).execute("cosima", "simulation", execute)
