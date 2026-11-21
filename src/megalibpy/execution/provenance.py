"""Streaming checksums and atomic execution records."""

import hashlib
import json
from pathlib import Path


def resolve_upstream(reference):
    """Read and validate a manifest reference without opening product contents."""
    path = Path(reference.manifest_path).expanduser().resolve(strict=True)
    content = path.read_bytes()
    upstream = json.loads(content)
    if upstream.get("schema_version") not in (1, 2):
        raise ValueError("Unsupported upstream manifest schema")
    if upstream.get("status") != "succeeded":
        raise ValueError("Upstream execution must have succeeded")
    if reference.execution_id is not None and reference.execution_id != upstream.get("execution_id"):
        raise ValueError("Upstream execution identity changed")
    group = reference.output_group
    products = upstream.get("outputs", {}).get(group)
    if not isinstance(products, list) or not products:
        raise ValueError(f"Missing upstream product group: {group!r}")
    paths = []
    for product in products:
        selected = (path.parent / product).resolve(strict=True)
        if not selected.is_relative_to(path.parent) or not selected.is_file():
            raise ValueError("Upstream products must be files within their execution directory")
        paths.append(selected)
    if reference.paths is not None:
        requested = tuple((path.parent / p).resolve(strict=True) for p in reference.paths)
        if not requested or len(set(requested)) != len(requested) or not set(requested) <= set(paths):
            raise ValueError("Selected upstream paths must be a nonempty unique subset of the product group")
        paths = list(requested)
    return content, {
        "execution_id": upstream.get("execution_id"), "manifest_path": str(path),
        "manifest_sha256": hashlib.sha256(content).hexdigest(),
        "output_group": group, "paths": [str(p) for p in paths],
    }


def capture_upstream(workspace, references):
    """Archive selected upstream manifests; products are referenced, not copied."""
    records = []
    for index, reference in enumerate(references):
        content, record = resolve_upstream(reference)
        snapshot = workspace.root / "inputs" / f"upstream-{index:04d}.json"
        snapshot.write_bytes(content)
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
