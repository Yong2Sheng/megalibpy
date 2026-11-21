"""Streaming checksums and atomic execution records."""

import hashlib
import json
from pathlib import Path


def read_execution(path, execution_id=None):
    """Read a standalone record or one identified execution in a workspace."""
    path = Path(path).expanduser().resolve(strict=True)
    content = path.read_bytes()
    data = json.loads(content)
    if data.get("kind") == "simulation_workspace" and data.get("schema_version") == 2:
        if execution_id is None:
            raise ValueError("A central workspace reference requires an execution_id")
        try:
            record = data["executions"][execution_id]
        except KeyError as exc:
            raise ValueError("Upstream execution identity changed or is missing") from exc
        content = json.dumps(record, sort_keys=True, ensure_ascii=False).encode()
        root = (path.parent / record["execution_dir"]).resolve()
        if not root.is_relative_to(path.parent):
            raise ValueError("Execution directory must remain within the workspace")
        return content, record, root
    if data.get("schema_version") not in (1, 2) or "tool" not in data:
        raise ValueError("Unsupported upstream manifest schema")
    return content, data, path.parent


def resolve_upstream(reference):
    """Resolve an exact execution; unrelated workspace updates do not change its hash."""
    path = Path(reference.manifest_path).expanduser().resolve(strict=True)
    content, upstream, root = read_execution(path, reference.execution_id)
    if upstream.get("status") != "succeeded":
        raise ValueError("Upstream execution must have succeeded")
    if reference.execution_id is not None and reference.execution_id != upstream.get("execution_id"):
        raise ValueError("Upstream execution identity changed")
    products = upstream.get("outputs", {}).get(reference.output_group)
    if not isinstance(products, list) or not products:
        raise ValueError(f"Missing upstream product group: {reference.output_group!r}")
    paths = []
    for product in products:
        selected = (root / product).resolve(strict=True)
        if not selected.is_relative_to(root) or not selected.is_file():
            raise ValueError("Upstream products must be files within their execution directory")
        paths.append(selected)
    if reference.paths is not None:
        requested = tuple((root / p).resolve(strict=True) for p in reference.paths)
        if not requested or len(set(requested)) != len(requested) or not set(requested) <= set(paths):
            raise ValueError("Selected upstream paths must be a nonempty unique subset of the product group")
        paths = list(requested)
    return content, {
        "execution_id": upstream.get("execution_id"), "manifest_path": str(path),
        "manifest_sha256": hashlib.sha256(content).hexdigest(),
        "output_group": reference.output_group, "paths": [str(p) for p in paths],
    }


def capture_upstream(workspace, references):
    """Keep local ID links; archive only selected external execution records."""
    records = []
    for index, reference in enumerate(references):
        content, record = resolve_upstream(reference)
        if workspace.owner is None or Path(record["manifest_path"]) != workspace.manifest_path:
            snapshot = workspace.snapshot(f"upstream-{index:04d}.json", content)
            record["manifest_snapshot"] = str(snapshot.relative_to(workspace.root))
        records.append(record)
    return records


def sha256(path: Path) -> str:
    """Return a file's hexadecimal SHA-256 checksum using bounded read buffers.

    Parameters
    ----------
    path : pathlib.Path
        Readable regular file to hash.

    Returns
    -------
    str
        Lowercase hexadecimal checksum of the file's bytes.

    Raises
    ------
    OSError
        The file cannot be opened or read.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, *, hash_limit: int | None = None) -> dict:
    """Record file identity, optionally avoiding full reads of large files.

    Parameters
    ----------
    path : pathlib.Path
        Existing regular file. Its resolved absolute path is recorded.
    hash_limit : int or None, optional
        Maximum file size to hash, in bytes. ``None`` hashes all sizes.

    Returns
    -------
    dict
        Path, size in bytes, modification time in nanoseconds, checksum, and
        hash policy. Files exceeding the limit have ``sha256=None`` and
        ``hash_policy="size_and_mtime_only"``.

    Raises
    ------
    OSError
        The file cannot be resolved, inspected, or read.
    """
    path = path.resolve(strict=True)
    stat = path.stat()
    record = {"path": str(path), "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if hash_limit is None or stat.st_size <= hash_limit:
        record.update(sha256=sha256(path), hash_policy="sha256")
    else:
        record.update(sha256=None, hash_policy="size_and_mtime_only")
    return record


def write_manifest(path: Path, data: dict) -> None:
    """Write a UTF-8 JSON record through a temporary file and atomic replacement.

    Parameters
    ----------
    path : pathlib.Path
        Manifest destination in an existing directory.
    data : dict
        JSON-serializable execution metadata. Unicode text is retained.

    Raises
    ------
    OSError
        The temporary file cannot be written or the destination replaced.
    TypeError
        A value cannot be serialized as JSON.

    Notes
    -----
    Atomic replacement prevents readers seeing partially written JSON; this
    function does not promise persistence across power loss or filesystem failure.
    """
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)
