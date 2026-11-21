"""Preserve native MEGAlib configuration syntax instead of normalizing XML."""

from pathlib import Path
import re


_IGNORED = re.compile(rb"<!--.*?-->|<\?.*?\?>", re.DOTALL)
_ENVELOPE = re.compile(
    rb"\s*<RevanConfigurationFile(?:\s+[^<>]*)?>.*</RevanConfigurationFile\s*>\s*",
    re.DOTALL,
)
_LEAF = re.compile(
    rb"<(?P<name>[^\s<>/]+)(?:\s+[^<>]*?)?>"
    rb"(?P<body>[^<>]*)</(?P=name)\s*>",
    re.DOTALL,
)
_HOME = re.compile(rb"\s*(?P<prefix>~/|\$HOME/|\$\{HOME\}/)")


def prepare_configuration(content: bytes, home: Path):
    """Return native bytes, observed leaf values and explicit HOME edits.

    This is a conservative text inspector, not an XML or native-settings parser.
    MEGAlib writes names such as ``SpectrumBefore)`` and stores values without
    XML escaping. Re-serialization can reject or change those native values.
    Comments and processing instructions are masked only for inspection; their
    bytes and all unrelated configuration text remain untouched.
    """
    # Enforce the documented encoding without changing BOMs, whitespace or EOLs.
    content.decode("utf-8")
    masked = _IGNORED.sub(lambda m: b" " * len(m.group()), content)
    if not _ENVELOPE.fullmatch(masked):
        raise ValueError("Expected a native RevanConfigurationFile opening and closing root; "
                         "refusing implicit native defaults")
    leaves = []
    edits = []
    replacements = []
    home_prefix = str(home).encode("utf-8").rstrip(b"/") + b"/"
    for match in _LEAF.finditer(masked):
        name = match["name"].decode("utf-8")
        start, end = match.span("body")
        body = content[start:end]
        normalized = _IGNORED.sub(b"", body).replace(b"\n", b"").replace(b"\r", b"").strip()
        prefix = _HOME.match(match["body"])
        if prefix:
            first, last = prefix.span("prefix")
            replacements.append((start + first, start + last, home_prefix))
            normalized = (_IGNORED.sub(b"", body[:first] + home_prefix + body[last:])
                          .replace(b"\n", b"").replace(b"\r", b"").strip())
            edits.append({"field": name, "original": _IGNORED.sub(b"", body).strip().decode("utf-8"),
                          "executed": normalized.decode("utf-8")})
        leaves.append((name, normalized.decode("utf-8")))
    executed = content
    for start, end, value in reversed(replacements):
        executed = executed[:start] + value + executed[end:]
    return executed, leaves, edits
