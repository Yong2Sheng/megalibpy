"""Cosima simulation with configuration snapshots and explicit provenance."""

from pathlib import Path
import re
import secrets
import shutil

from ..execution import ExecutionPlan, MEGAlibRuntime
from ..execution.executor import Executor
from ..execution.provenance import file_record, sha256


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
    snapshot = workspace.root / "inputs/original.source"
    snapshot.write_bytes(original)
    executed = workspace.root / "inputs/executed.source"
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
    executed.write_text("".join(lines), encoding="utf-8")
    dependency_records = []
    for index, path in enumerate(sorted(external)):
        record = file_record(path, hash_limit=hash_limit)
        # Archive small declared/discovered files, but retain original locations
        # for dependencies referenced by geometry includes and other files.
        if record["sha256"] is not None:
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
                   "original_snapshot": "inputs/original.source",
                   "original_sha256": sha256(snapshot),
                   "executed_snapshot": "inputs/executed.source",
                   "executed_sha256": sha256(executed)},
        "dependencies": dependency_records,
        "dependency_capture": {
            "scope": "best_effort_top_level_and_explicit_files",
            "complete": False,
            "unresolved_references": unresolved,
            "limitations": "Nested geometry/includes and runtime-expanded paths are not automatically archived. "
                          "External files are still read from original locations; keep them immutable during execution.",
            "hash_limit_bytes": hash_limit,
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
        Command name or absolute executable path. Defaults to ``cosima``.
    """

    def __init__(self, runtime=None, *, executable="cosima"):
        self.runtime = runtime if runtime is not None else MEGAlibRuntime.direct()
        self.executable = str(executable)

    def simulate(self, source_file, *, output_dir, seed=None, compressed=True,
                 timeout=None, dependencies=(), hash_limit_bytes=64 * 1024 * 1024):
        """Run Cosima and return an :class:`~megalibpy.ExecutionResult`.

        ``output_dir`` must not exist. Source comments and unknown directives are
        preserved; only the output FileName and supported external file paths are
        rewritten in the execution snapshot. The original file is never edited.
        Relative supported input paths are resolved against the source directory.

        ``seed`` is a positive 31-bit integer; when omitted one is generated and
        recorded. ``timeout`` is in seconds and covers setup plus tool execution.
        ``dependencies`` lists additional files to record, resolved against the
        original source directory. Files up to ``hash_limit_bytes`` are hashed and
        copied; larger external files record size and mtime only. Set the limit to
        ``None`` to hash and archive every declared/discovered dependency.

        Dependency capture is explicitly incomplete: geometry include trees and
        runtime-expanded paths require external archival. Outputs are checked for
        nonzero size, not scientific validity or full gzip integrity.

        Raises
        ------
        ExecutionError
            Preparation, process execution, timeout, or output validation failed.
            The exception provides the manifest location and process return code.
        FileExistsError
            The execution directory already exists; it is never overwritten.
        """
        if seed is None:
            seed = secrets.randbelow(2**31 - 1) + 1
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 < seed < 2**31:
            raise ValueError("seed must be an integer between 1 and 2147483647")
        if hash_limit_bytes is not None and hash_limit_bytes < 0:
            raise ValueError("hash_limit_bytes must be nonnegative or None")
        source = Path(source_file).expanduser().resolve()
        files = []
        for path in dependencies:
            path = Path(path).expanduser()
            files.append((source.parent / path).resolve() if not path.is_absolute() else path.resolve())
        return Executor(self.runtime).execute(
            "cosima", output_dir,
            lambda workspace: _prepare_source(source, workspace, seed, compressed,
                                               self.executable, files, hash_limit_bytes),
            timeout=timeout,
        )
