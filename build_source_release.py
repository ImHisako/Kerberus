from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

from kerberus import __version__


ROOT = Path(__file__).resolve().parent
RELEASE = ROOT / "release"


def validate_tag(tag: str) -> None:
    if not tag:
        return
    expected = f"v{__version__}"
    if tag != expected:
        raise RuntimeError(f"Il tag {tag} non corrisponde alla versione {expected}")


def validate_committed_version() -> None:
    committed = subprocess.check_output(
        ["git", "show", "HEAD:kerberus/__init__.py"], cwd=ROOT, text=True,
    )
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', committed, re.MULTILINE)
    committed_version = match.group(1) if match else ""
    if committed_version != __version__:
        raise RuntimeError(
            f"Il commit HEAD contiene la versione {committed_version or '(assente)'}, "
            f"ma il working tree contiene {__version__}: crea il commit prima dell'archivio sorgente"
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crea gli artefatti sorgente di Kerberus")
    parser.add_argument("--tag", default="", help="Tag release da verificare, per esempio v0.7.0")
    args = parser.parse_args(argv)
    environment_tag = os.environ.get("GITHUB_REF_NAME", "") if os.environ.get("GITHUB_REF_TYPE") == "tag" else ""
    validate_tag(args.tag or environment_tag)
    validate_committed_version()

    RELEASE.mkdir(exist_ok=True)
    for pattern in ("kerberus_i2p-*", "Kerberus-*-src.tar.gz", "SHA256SUMS-source.txt"):
        for path in RELEASE.glob(pattern):
            if path.is_file():
                path.unlink()

    subprocess.run(
        [
            sys.executable, "-m", "build", "--sdist", "--wheel",
            "--outdir", str(RELEASE), str(ROOT),
        ],
        # Avoid shadowing the `build` package with PyInstaller's local build/ directory.
        cwd=ROOT.parent,
        check=True,
    )
    source_archive = RELEASE / f"Kerberus-{__version__}-src.tar.gz"
    subprocess.run(
        [
            "git", "archive", "--format=tar.gz", f"--prefix=Kerberus-{__version__}/",
            f"--output={source_archive}", "HEAD",
        ],
        cwd=ROOT,
        check=True,
    )
    artifacts = sorted([
        source_archive,
        *RELEASE.glob(f"kerberus_i2p-{__version__}*"),
    ], key=lambda path: path.name.lower())
    if len(artifacts) != 3:
        raise RuntimeError(f"Artefatti sorgente incompleti: {[path.name for path in artifacts]}")
    manifest = RELEASE / "SHA256SUMS-source.txt"
    manifest.write_text(
        "\n".join(f"{sha256(path)}  {path.name}" for path in artifacts) + "\n",
        encoding="ascii",
    )
    print(f"Release sorgente Kerberus {__version__} pronta in {RELEASE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
