"""Aggiorna la versione applicativa e i riferimenti della release."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
VERSION_FILE = Path("kerberus/__init__.py")
RELEASE_FILES = (Path("README.md"), Path("README.it.md"), Path("RELEASE.md"))
SEMVER = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")
VERSION_ASSIGNMENT = re.compile(r'(?m)^__version__\s*=\s*["\']([^"\']+)["\'](?=\r?$)')


def read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return stream.read()


def write_text(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(content)


def validate_version(version: str) -> str:
    if SEMVER.fullmatch(version) is None:
        raise ValueError(
            f"Versione non valida: {version!r}. Usa il formato MAJOR.MINOR.PATCH, per esempio 1.2.3."
        )
    return version


def version_tuple(version: str) -> tuple[int, int, int]:
    major, minor, patch = validate_version(version).split(".")
    return int(major), int(minor), int(patch)


def current_version(root: Path = ROOT) -> str:
    content = read_text(root / VERSION_FILE)
    match = VERSION_ASSIGNMENT.search(content)
    if match is None:
        raise RuntimeError(f"Versione non trovata in {VERSION_FILE}")
    return validate_version(match.group(1))


def planned_changes(new_version: str, root: Path = ROOT) -> dict[Path, str]:
    """Prepara tutte le modifiche prima di scrivere qualunque file."""
    new_version = validate_version(new_version)
    old_version = current_version(root)
    if new_version == old_version:
        raise ValueError(f"Kerberus è già alla versione {new_version}")
    if version_tuple(new_version) < version_tuple(old_version):
        raise ValueError(
            f"La nuova versione {new_version} deve essere superiore a quella corrente {old_version}"
        )

    changes: dict[Path, str] = {}
    version_path = root / VERSION_FILE
    version_content = read_text(version_path)
    changes[version_path] = VERSION_ASSIGNMENT.sub(
        f'__version__ = "{new_version}"', version_content, count=1
    )

    for relative_path in RELEASE_FILES:
        path = root / relative_path
        content = read_text(path)
        if old_version not in content:
            raise RuntimeError(
                f"{relative_path} non contiene la versione corrente {old_version}; aggiornamento annullato"
            )
        changes[path] = content.replace(old_version, new_version)

    changelog_path = root / "CHANGELOG.md"
    changelog = read_text(changelog_path)
    heading = f"## {new_version}"
    if re.search(rf"(?m)^{re.escape(heading)}$", changelog) is None:
        title_match = re.match(r"^(# .+?\r?\n)", changelog)
        if title_match is None:
            raise RuntimeError("CHANGELOG.md non ha un titolo riconoscibile")
        changelog = (
            changelog[: title_match.end()]
            + f"\n{heading}\n\n- TODO: descrivere le modifiche della release.\n"
            + changelog[title_match.end() :]
        )
    changes[changelog_path] = changelog
    return changes


def bump_version(new_version: str, root: Path = ROOT) -> tuple[str, list[Path]]:
    old_version = current_version(root)
    changes = planned_changes(new_version, root)
    for path, content in changes.items():
        write_text(path, content)
    return old_version, list(changes)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggiorna la versione di Kerberus da un solo comando."
    )
    parser.add_argument("version", help="Nuova versione MAJOR.MINOR.PATCH, per esempio 1.2.3")
    args = parser.parse_args()

    try:
        old_version, changed = bump_version(args.version)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))

    print(f"Kerberus {old_version} -> {args.version}")
    for path in changed:
        print(f"  aggiornato: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
