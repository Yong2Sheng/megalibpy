"""Build the English default site and Simplified Chinese under zh_CN/."""

import argparse
from importlib.util import find_spec
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from babel.messages.pofile import read_po


def check_translations(source):
    """Reject missing/fuzzy prose translations; notebooks intentionally stay English."""
    # Fresh extraction avoids checking stale POT files after a page is removed.
    with TemporaryDirectory(prefix="megalibpy-gettext-") as temporary:
        templates = Path(temporary)
        subprocess.run([
            sys.executable, "-m", "sphinx", "-q", "-W", "-b", "gettext",
            str(source), str(templates),
        ], check=True)
        for template in templates.rglob("*.pot"):
            domain = template.relative_to(templates)
            if domain.parts[0] == "tutorials" and domain.name != "index.pot":
                continue
            translation = source / "locales" / "zh_CN" / "LC_MESSAGES" / domain.with_suffix(".po")
            with template.open(encoding="utf-8") as stream:
                messages = read_po(stream, abort_invalid=True)
            if not translation.exists():
                raise RuntimeError(f"Missing Chinese catalog: {domain}")
            with translation.open(encoding="utf-8") as stream:
                catalog = read_po(stream, locale="zh_CN", abort_invalid=True)
            missing = [m.id for m in messages if m.id and (
                m.id not in catalog or not catalog[m.id].string
                or "fuzzy" in catalog[m.id].flags)]
            if missing:
                raise RuntimeError(f"Update Chinese translations in {domain}: {missing!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Combined HTML site directory")
    parser.add_argument("--title", help="Optional title, including a PR preview label")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    if find_spec("jieba") is None:
        raise RuntimeError("Install jieba from environment.yml for Chinese search indexing")
    check_translations(source)
    for language, suffix in (("en", ""), ("zh_CN", "zh_CN")):
        command = [
            sys.executable, "-m", "sphinx", "-E", "-W", "--keep-going", "-b", "html",
            "-D", f"language={language}",
            "-d", str(source / "_build" / "doctrees" / language),
        ]
        if args.title:
            command.extend(["-D", f"html_title={args.title}"])
        command.extend([str(source), str(args.output.resolve() / suffix)])
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
