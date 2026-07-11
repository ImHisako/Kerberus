from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


APP_NAME = "Kerberus"
PROTOCOL_VERSION = 1


def app_data_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(slots=True)
class AppConfig:
    sam_host: str = "127.0.0.1"
    sam_port: int = 7656
    strict_pq: bool = True
    vault_path: Path = app_data_dir() / "vault.kbv"
    sam_keys_path: Path = app_data_dir() / "sam-destination.txt"
    downloads_path: Path = app_data_dir() / "downloads"

