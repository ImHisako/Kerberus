from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
RELEASE = ROOT / "release"
NATIVE_DIR = ROOT / "native"


def build_native_helper() -> Path:
    executable = "kerberus-native.exe" if os.name == "nt" else "kerberus-native"
    target = ROOT / "build" / "native" / executable
    target.parent.mkdir(parents=True, exist_ok=True)
    go = shutil.which("go")
    if not go:
        raise RuntimeError("Go è richiesto soltanto per creare la release; installa Go 1.24 o successivo")
    subprocess.run(
        [go, "build", "-trimpath", "-ldflags=-s -w", "-o", str(target), "."],
        cwd=NATIVE_DIR,
        check=True,
    )
    return target


def run_pyinstaller(arguments: list[str]) -> None:
    import PyInstaller.__main__

    PyInstaller.__main__.run(arguments)


def main() -> int:
    if os.name not in ("nt", "posix"):
        raise RuntimeError("Sistema operativo non supportato")
    installer_only = "--installer-only" in sys.argv
    if not installer_only:
        native_helper = build_native_helper()
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
            f"--add-binary={native_helper}{os.pathsep}.",
            f"--distpath={DIST}",
            f"--workpath={ROOT / 'build' / 'app'}",
            f"--specpath={ROOT / 'build' / 'spec'}",
        ])
    app = DIST / ("Kerberus.exe" if os.name == "nt" else "Kerberus")
    if not app.exists():
        raise RuntimeError("La build di Kerberus non è stata prodotta")
    crypto_test = subprocess.run([str(app), "--crypto-self-test"], timeout=60, check=False)
    if crypto_test.returncode != 0:
        raise RuntimeError(f"Self-test ML-KEM della build fallito: {crypto_test.returncode}")
    RELEASE.mkdir(exist_ok=True)
    if os.name != "nt":
        architecture = platform.machine().lower().replace("amd64", "x86_64")
        portable = RELEASE / f"Kerberus-linux-{architecture}"
        shutil.copy2(app, portable)
        portable.chmod(0o755)
        install_script = ROOT / "install-linux.sh"
        shutil.copy2(install_script, RELEASE / install_script.name)
        (RELEASE / install_script.name).chmod(0o755)
        artifacts = (portable, RELEASE / install_script.name)
        checksums = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in artifacts]
        (RELEASE / "SHA256SUMS-linux.txt").write_text("\n".join(checksums) + "\n", encoding="ascii")
        print(f"Release Linux pronta in {RELEASE}")
        return 0
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
