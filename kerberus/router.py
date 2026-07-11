from __future__ import annotations

import hashlib
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Callable


I2P_VERSION = "2.12.0"
I2P_WINDOWS_URL = f"https://files.i2p.net/{I2P_VERSION}/i2pinstall_{I2P_VERSION}_windows.exe"
I2P_WINDOWS_SHA256 = "827daf222bfaee4e44c653702213d5c8e30cabd3e589dafe646c4d13c3692e5f"


class RouterInstaller:
    def __init__(self, downloads_path: Path):
        self.downloads_path = downloads_path

    def download_windows(self, progress: Callable[[int, int], None] | None = None) -> Path:
        if os.name != "nt":
            raise RuntimeError("Il bootstrap automatico è attualmente disponibile solo su Windows")
        self.downloads_path.mkdir(parents=True, exist_ok=True)
        target = self.downloads_path / f"i2pinstall_{I2P_VERSION}_windows.exe"
        temp = target.with_suffix(".download")

        def report(blocks: int, block_size: int, total: int) -> None:
            if progress:
                progress(min(blocks * block_size, total), total)

        urllib.request.urlretrieve(I2P_WINDOWS_URL, temp, reporthook=report)
        digest = hashlib.sha256(temp.read_bytes()).hexdigest()
        if digest.lower() != I2P_WINDOWS_SHA256:
            temp.unlink(missing_ok=True)
            raise RuntimeError("Checksum SHA-256 dell'installer I2P non valido")
        os.replace(temp, target)
        return target

    @staticmethod
    def launch_installer(path: Path) -> None:
        subprocess.Popen([str(path)], close_fds=True)

    @staticmethod
    def is_running() -> bool:
        if os.name != "nt":
            return False
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq I2Psvc.exe", "/NH"],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=5,
            check=False,
        )
        return "I2Psvc.exe" in result.stdout

    @staticmethod
    def start_installed() -> bool:
        if os.name != "nt" or RouterInstaller.is_running():
            return RouterInstaller.is_running()
        install_dir = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "i2p"
        executable = install_dir / "I2Psvc.exe"
        config = install_dir / "wrapper.config"
        if not executable.exists() or not config.exists():
            return False
        RouterInstaller.ensure_sam_enabled()
        data_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "I2P"
        data_dir.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            [str(executable), "-c", str(config)],
            cwd=data_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
        return True

    @staticmethod
    def ensure_sam_enabled() -> Path:
        data_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "I2P"
        config_dir = data_dir / "clients.config.d"
        config_dir.mkdir(parents=True, exist_ok=True)
        config = config_dir / "01-net.i2p.sam.SAMBridge-clients.config"
        content = """# Managed by Kerberus - local SAM bridge only
clientApp.0.args=sam.keys 127.0.0.1 7656 i2cp.tcp.host=127.0.0.1 i2cp.tcp.port=7654
clientApp.0.delay=5
clientApp.0.main=net.i2p.sam.SAMBridge
clientApp.0.name=SAM application bridge
clientApp.0.startOnLoad=true
"""
        config.write_text(content, encoding="utf-8")
        return config

    @staticmethod
    def stop_running() -> bool:
        if os.name != "nt":
            return False
        result = subprocess.run(
            ["taskkill", "/IM", "I2Psvc.exe", "/T", "/F"],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=10,
            check=False,
        )
        return result.returncode == 0
