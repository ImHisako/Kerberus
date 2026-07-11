from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
RELEASE = ROOT / "release"


def run_pyinstaller(arguments: list[str]) -> None:
    import PyInstaller.__main__

    PyInstaller.__main__.run(arguments)


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("La release Windows deve essere compilata su Windows")
    installer_only = "--installer-only" in sys.argv
    if not installer_only:
        run_pyinstaller([
            str(ROOT / "kerberus_app.py"),
            "--name=Kerberus",
            "--onefile",
            "--windowed",
            "--noconfirm",
            "--clean",
            "--collect-all=pqcrypto",
            "--collect-data=kerberus",
            "--hidden-import=pqcrypto.kem.ml_kem_768",
            "--hidden-import=nacl.bindings",
            f"--distpath={DIST}",
            f"--workpath={ROOT / 'build' / 'app'}",
            f"--specpath={ROOT / 'build' / 'spec'}",
        ])
    app = DIST / "Kerberus.exe"
    if not app.exists():
        raise RuntimeError("La build di Kerberus.exe non è stata prodotta")
    run_pyinstaller([
        str(ROOT / "installer.py"),
        "--name=KerberusInstaller",
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--clean",
        f"--add-binary={app}{os.pathsep}payload",
        f"--distpath={DIST}",
        f"--workpath={ROOT / 'build' / 'installer'}",
        f"--specpath={ROOT / 'build' / 'spec'}",
    ])
    installer = DIST / "KerberusInstaller.exe"
    if not installer.exists():
        raise RuntimeError("La build di KerberusInstaller.exe non è stata prodotta")
    result = subprocess.run([str(installer), "--self-test"], timeout=60, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Self-test installer fallito: {result.returncode}")
    RELEASE.mkdir(exist_ok=True)
    for artifact in (app, installer):
        shutil.copy2(artifact, RELEASE / artifact.name)
    checksums = []
    for artifact in (app, installer):
        target = RELEASE / artifact.name
        checksums.append(f"{hashlib.sha256(target.read_bytes()).hexdigest()}  {target.name}")
    (RELEASE / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="ascii")
    print(f"Release pronta in {RELEASE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
