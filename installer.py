from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from tkinter import BOTH, LEFT, RIGHT, X, Button, Frame, Label, StringVar, Tk, messagebox, ttk

from kerberus import __version__

APP_VERSION = __version__
I2P_VERSION = "2.12.0"
I2P_URL = f"https://files.i2p.net/{I2P_VERSION}/i2pinstall_{I2P_VERSION}_windows.exe"
I2P_SHA256 = "827daf222bfaee4e44c653702213d5c8e30cabd3e589dafe646c4d13c3692e5f"
AZUL_VERSION = "26.0.1+8"
AZUL_FILENAME = "zulu26.30.11-ca-jdk26.0.1-win_x64.msi"
AZUL_URL = f"https://cdn.azul.com/zulu/bin/{AZUL_FILENAME}"
AZUL_SHA256 = "65af411f44027667a7b6d0fc5dbe20f8563acfc5722e633ae021344b237ef691"
USER_AGENT = f"Kerberus-Installer/{APP_VERSION}"


def local_app_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class InstallerEngine:
    def __init__(self, notify):
        self.notify = notify
        self.install_dir = local_app_data() / "Programs" / "Kerberus"
        self.download_dir = local_app_data() / "Kerberus" / "downloads"
        self.log_path = local_app_data() / "Kerberus" / "installer.log"

    def log(self, message: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")
        self.notify("status", message)

    def download(self, url: str, target: Path, expected_sha256: str, start: int, end: int) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".download")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response, temporary.open("wb") as output:
            total = int(response.headers.get("Content-Length", "0"))
            done = 0
            while True:
                block = response.read(1024 * 256)
                if not block:
                    break
                output.write(block)
                done += len(block)
                if total:
                    self.notify("progress", start + int((end - start) * done / total))
        actual = sha256_file(temporary)
        if actual.lower() != expected_sha256.lower():
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"Checksum non valida per {target.name}")
        os.replace(temporary, target)
        return target

    def install_application(self) -> Path:
        self.log("Installazione dell'applicazione Kerberus...")
        payload = resource_path("payload", "Kerberus.exe")
        if not payload.exists():
            development = Path(__file__).resolve().parent / "dist" / "Kerberus.exe"
            payload = development if development.exists() else payload
        if not payload.exists():
            raise RuntimeError("Payload Kerberus.exe mancante nell'installer")
        self.install_dir.mkdir(parents=True, exist_ok=True)
        target = self.install_dir / "Kerberus.exe"
        temporary = self.install_dir / "Kerberus.exe.new"
        shutil.copy2(payload, temporary)
        try:
            os.replace(temporary, target)
        except PermissionError:
            self.log("Chiusura della versione precedente di Kerberus...")
            subprocess.run(
                ["taskkill", "/IM", "Kerberus.exe", "/T", "/F"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            os.replace(temporary, target)
        self.notify("progress", 15)
        return target

    def _system_java(self) -> Path | None:
        candidates: list[Path] = []
        for name in ("java.exe", "javaw.exe"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        candidates.extend(program_files.glob("Zulu/*/bin/java.exe"))
        for candidate in candidates:
            if self._java_major(candidate) >= 17:
                return candidate
        return None

    @staticmethod
    def _java_major(java: Path) -> int:
        executable = java.with_name("java.exe") if java.name.lower() == "javaw.exe" else java
        try:
            result = subprocess.run(
                [str(executable), "-version"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            match = re.search(r'version "(?:1\.)?(\d+)', result.stderr + result.stdout)
            return int(match.group(1)) if match else 0
        except (OSError, subprocess.SubprocessError):
            return 0

    @staticmethod
    def _verify_azul_signature(path: Path) -> None:
        script = (
            "$m=Join-Path $PSHOME 'Modules\\Microsoft.PowerShell.Security\\Microsoft.PowerShell.Security.psd1';"
            "Import-Module $m -Force -ErrorAction Stop;"
            "$s=Get-AuthenticodeSignature -LiteralPath $env:KERBERUS_SIGNATURE_PATH;"
            "$o=[PSCustomObject]@{Status=$s.Status.ToString();"
            "Subject=if($s.SignerCertificate){$s.SignerCertificate.Subject}else{''}};"
            "$o|ConvertTo-Json -Compress"
        )
        encoded_script = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_script],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env={**os.environ, "KERBERUS_SIGNATURE_PATH": str(path.resolve())},
            check=False,
        )
        try:
            signature = json.loads(result.stdout.strip().lstrip("\ufeff"))
        except (json.JSONDecodeError, AttributeError):
            signature = {}
        valid_status = str(signature.get("Status", "")).casefold() == "valid"
        allowed_publisher = "Azul Systems, Inc." in str(signature.get("Subject", ""))
        if result.returncode != 0 or not valid_status or not allowed_publisher:
            detail = signature.get("Status") or result.stderr.strip().splitlines()[-1:] or "output non valido"
            raise RuntimeError(f"Firma Authenticode del pacchetto Azul non valida ({detail})")

    def ensure_java(self) -> Path:
        existing = self._system_java()
        if existing:
            self.log(f"Java {self._java_major(existing)} disponibile.")
            self.notify("progress", 35)
            return existing
        self.log(f"Download e verifica Azul JDK {AZUL_VERSION}...")
        package = self.download_dir / AZUL_FILENAME
        if not package.exists() or sha256_file(package).lower() != AZUL_SHA256:
            self.download(AZUL_URL, package, AZUL_SHA256, 15, 32)
        self._verify_azul_signature(package)
        self.notify("attention", f"Kerberus installerà Azul JDK {AZUL_VERSION}. Accetta la richiesta UAC.")
        msi = str(package).replace("'", "''")
        elevation = (
            "$p=Start-Process -FilePath 'msiexec.exe' "
            f"-ArgumentList @('/i','{msi}','/qn','/norestart') "
            "-Verb RunAs -Wait -PassThru; exit $p.ExitCode"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", elevation],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if result.returncode not in (0, 3010):
            raise RuntimeError(f"Installazione Azul JDK non riuscita: {result.returncode}")
        java = self._system_java()
        if not java:
            raise RuntimeError("Azul JDK risulta installato ma java.exe non è stato trovato")
        self.notify("progress", 35)
        return java

    @staticmethod
    def installed_i2p_version() -> str:
        roots = (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "i2p",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "i2p",
        )
        for root in roots:
            history = root / "history.txt"
            if not (root / "I2Psvc.exe").exists() or not history.exists():
                continue
            match = re.search(r"\b(\d+\.\d+\.\d+)\b", history.read_text("utf-8", errors="ignore")[:200])
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def i2p_installed() -> bool:
        return bool(InstallerEngine.installed_i2p_version())

    def ensure_i2p(self, java: Path | None = None) -> None:
        installed_version = self.installed_i2p_version()
        if installed_version == I2P_VERSION:
            self.log(f"I2P {I2P_VERSION} è già installato.")
            self.notify("progress", 78)
            self.ensure_sam_config()
            return
        if java is None:
            raise RuntimeError("Il router I2P standard richiede Java 17 o successivo")
        self.log("Download e verifica dell'installer ufficiale I2P...")
        installer = self.download_dir / f"i2pinstall_{I2P_VERSION}_windows.exe"
        if not installer.exists() or sha256_file(installer).lower() != I2P_SHA256:
            self.download(I2P_URL, installer, I2P_SHA256, 35, 70)
        else:
            self.notify("progress", 70)
        self.log("Completa la finestra di installazione I2P appena aperta.")
        self.notify("attention", "Completa l'installazione I2P usando il percorso predefinito, poi chiudi la finestra dell'installer.")
        installer_path = str(installer).replace("'", "''")
        elevation = (
            f"$p=Start-Process -FilePath '{installer_path}' "
            "-Verb RunAs -Wait -PassThru; exit $p.ExitCode"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", elevation],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"L'installer I2P è terminato con codice {result.returncode}")
        if not self.i2p_installed():
            raise RuntimeError("I2P non risulta installato. Ripeti usando il percorso predefinito.")
        self.ensure_sam_config()
        self.notify("progress", 78)

    @staticmethod
    def ensure_sam_config() -> Path:
        config_dir = local_app_data() / "I2P" / "clients.config.d"
        config_dir.mkdir(parents=True, exist_ok=True)
        target = config_dir / "01-net.i2p.sam.SAMBridge-clients.config"
        target.write_text(
            """# Managed by Kerberus - local SAM bridge only
clientApp.0.args=sam.keys 127.0.0.1 7656 i2cp.tcp.host=127.0.0.1 i2cp.tcp.port=7654
clientApp.0.delay=5
clientApp.0.main=net.i2p.sam.SAMBridge
clientApp.0.name=SAM application bridge
clientApp.0.startOnLoad=true
""",
            encoding="utf-8",
        )
        return target

    def create_shortcuts(self, executable: Path) -> None:
        self.log("Creazione dei collegamenti...")
        desktop = Path.home() / "Desktop" / "Kerberus.lnk"
        start_menu = Path(os.environ.get("APPDATA", Path.home())) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Kerberus.lnk"
        for shortcut in (desktop, start_menu):
            shortcut.parent.mkdir(parents=True, exist_ok=True)
            exe = str(executable).replace("'", "''")
            link = str(shortcut).replace("'", "''")
            work = str(self.install_dir).replace("'", "''")
            script = (
                "$shell=New-Object -ComObject WScript.Shell;"
                f"$link=$shell.CreateShortcut('{link}');"
                f"$link.TargetPath='{exe}';$link.WorkingDirectory='{work}';"
                f"$link.IconLocation='{exe},0';$link.Save()"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=True,
            )
        self.notify("progress", 92)

    def install(self) -> Path:
        self.notify("progress", 3)
        executable = self.install_application()
        if self.installed_i2p_version() == I2P_VERSION:
            self.ensure_i2p()
        else:
            # Kerberus.exe non usa Java. Il runtime serve soltanto al router I2P
            # standard scaricato da questo installer.
            self.ensure_i2p(self.ensure_java())
        self.create_shortcuts(executable)
        self.log("Installazione completata.")
        self.notify("progress", 100)
        return executable


class InstallerWindow:
    def __init__(self):
        self.root = Tk()
        self.root.title("Installa Kerberus")
        self.root.geometry("620x430")
        self.root.resizable(False, False)
        self.root.configure(bg="#0c0f13")
        self.events = queue.Queue()
        self.installing = False
        self.status = StringVar(value="Pronto per l'installazione")
        self._build()
        self.root.after(80, self._drain_events)

    def _build(self) -> None:
        header = Frame(self.root, bg="#12161b", height=58)
        header.pack(fill=X)
        header.pack_propagate(False)
        Label(header, text="K", bg="#174d3b", fg="#35d09a", font=("Segoe UI", 16, "bold"), width=3).pack(side=LEFT, padx=(18, 10), pady=11)
        Label(header, text="Kerberus Installer", bg="#12161b", fg="#f2f5f7", font=("Segoe UI", 12, "bold")).pack(side=LEFT, pady=17)
        body = Frame(self.root, bg="#0c0f13")
        body.pack(fill=BOTH, expand=True, padx=34, pady=28)
        Label(body, text="Comunicazione privata, pronta all'uso", bg="#0c0f13", fg="#f2f5f7", font=("Segoe UI", 20, "bold"), anchor="w").pack(fill=X)
        Label(
            body,
            text="Installa Kerberus e I2P. Java viene aggiunto solo se il router I2P standard ne ha bisogno; ogni download viene verificato.",
            bg="#0c0f13",
            fg="#909aa6",
            font=("Segoe UI", 10),
            wraplength=540,
            justify=LEFT,
            anchor="w",
        ).pack(fill=X, pady=(8, 24))
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Kerberus.Horizontal.TProgressbar", troughcolor="#20262e", background="#35d09a", borderwidth=0)
        self.progress = ttk.Progressbar(body, maximum=100, style="Kerberus.Horizontal.TProgressbar")
        self.progress.pack(fill=X, ipady=5)
        Label(body, textvariable=self.status, bg="#0c0f13", fg="#909aa6", font=("Segoe UI", 9), anchor="w").pack(fill=X, pady=(10, 24))
        features = "Python e librerie incluse   ·   ML-KEM-768   ·   I2P SAM locale   ·   Collegamenti automatici"
        Label(body, text=features, bg="#171c22", fg="#aeb8c4", font=("Segoe UI", 9), padx=14, pady=13, anchor="w").pack(fill=X)
        actions = Frame(body, bg="#0c0f13")
        actions.pack(fill=X, pady=(24, 0))
        self.close_button = Button(actions, text="Annulla", command=self.root.destroy, bg="#20262e", fg="#f2f5f7", activebackground="#29313b", activeforeground="#ffffff", relief="flat", padx=18, pady=9, font=("Segoe UI", 10))
        self.close_button.pack(side=RIGHT)
        self.install_button = Button(actions, text="Installa", command=self.start, bg="#35d09a", fg="#07120e", activebackground="#50ddb0", activeforeground="#07120e", relief="flat", padx=24, pady=9, font=("Segoe UI", 10, "bold"))
        self.install_button.pack(side=RIGHT, padx=(0, 10))

    def notify(self, kind: str, value) -> None:
        self.events.put((kind, value))

    def start(self) -> None:
        if self.installing:
            return
        self.installing = True
        self.install_button.configure(state="disabled")
        self.close_button.configure(state="disabled")

        def work() -> None:
            try:
                executable = InstallerEngine(self.notify).install()
                self.notify("done", executable)
            except Exception as exc:
                self.notify("error", str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _drain_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self.progress["value"] = value
                elif kind == "status":
                    self.status.set(value)
                elif kind == "attention":
                    messagebox.showinfo("Installazione I2P", value, parent=self.root)
                elif kind == "error":
                    self.installing = False
                    self.install_button.configure(state="normal")
                    self.close_button.configure(state="normal")
                    messagebox.showerror("Installazione non riuscita", value, parent=self.root)
                elif kind == "done":
                    self.status.set("Kerberus è pronto")
                    self.install_button.configure(text="Apri Kerberus", state="normal", command=lambda: self._launch(Path(value)))
                    self.close_button.configure(text="Chiudi", state="normal")
                    self._launch(Path(value))
        except queue.Empty:
            pass
        self.root.after(80, self._drain_events)

    @staticmethod
    def _launch(executable: Path) -> None:
        subprocess.Popen([str(executable)], cwd=executable.parent, close_fds=True)

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    if os.name != "nt":
        messagebox.showerror("Kerberus", "Questo installer è destinato a Windows 10/11.")
        return 1
    if "--self-test" in sys.argv:
        payload = resource_path("payload", "Kerberus.exe")
        return 0 if payload.exists() else 2
    InstallerWindow().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
