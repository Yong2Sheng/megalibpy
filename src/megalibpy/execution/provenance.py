"""Streaming checksums and atomic execution records."""

import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, *, hash_limit: int | None = None) -> dict:
    """Record file identity; large external files may deliberately skip hashing."""
    path = path.resolve(strict=True)
    stat = path.stat()
    record = {"path": str(path), "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if hash_limit is None or stat.st_size <= hash_limit:
        record.update(sha256=sha256(path), hash_policy="sha256")
    else:
        record.update(sha256=None, hash_policy="size_and_mtime_only")
    return record


def write_manifest(path: Path, data: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)
