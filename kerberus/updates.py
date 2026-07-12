from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path


API_URL = "https://api.github.com/repos/ImHisako/Kerberus/releases/latest"
RELEASES_URL = "https://github.com/ImHisako/Kerberus/releases"
USER_AGENT = "Kerberus-Update/1"
MAX_METADATA = 2_000_000
MAX_ARTIFACT = 300_000_000


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    tag: str
    page_url: str
    asset_name: str
    asset_url: str
    checksum_name: str
    checksum_url: str
    notes: str = ""


def _version(value: str) -> tuple[int, ...]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", value.strip())
    if not match:
        raise ValueError(f"Versione release non valida: {value}")
    return tuple(int(part) for part in match.groups())


def _request(url: str):
    return urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        },
    )


def _read_limited(url: str, limit: int) -> bytes:
    with urllib.request.urlopen(_request(url), timeout=20) as response:
        declared = int(response.headers.get("Content-Length", "0") or 0)
        if declared > limit:
            raise RuntimeError("Download di aggiornamento troppo grande")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("Download di aggiornamento troppo grande")
    return data


def check_for_update(current_version: str) -> UpdateInfo | None:
    raw = json.loads(_read_limited(API_URL, MAX_METADATA).decode("utf-8"))
    if raw.get("draft") or raw.get("prerelease"):
        return None
    tag = str(raw.get("tag_name", ""))
    if _version(tag) <= _version(current_version):
        return None
    assets = {str(asset.get("name")): asset for asset in raw.get("assets", [])}
    if os.name == "nt":
        asset_name, checksum_name = "KerberusInstaller.exe", "SHA256SUMS.txt"
    else:
        architecture = platform.machine().lower().replace("amd64", "x86_64")
        asset_name, checksum_name = f"Kerberus-linux-{architecture}", "SHA256SUMS-linux.txt"
    asset = assets.get(asset_name)
    checksum = assets.get(checksum_name)
    if not asset or not checksum:
        raise RuntimeError("La release non contiene artefatto e checksum per questo sistema")
    return UpdateInfo(
        version=tag.removeprefix("v"),
        tag=tag,
        page_url=str(raw.get("html_url") or RELEASES_URL),
        asset_name=asset_name,
        asset_url=str(asset["browser_download_url"]),
        checksum_name=checksum_name,
        checksum_url=str(checksum["browser_download_url"]),
        notes=str(raw.get("body") or "")[:4000],
    )


def download_update(info: UpdateInfo, target_dir: Path) -> Path:
    manifest = _read_limited(info.checksum_url, MAX_METADATA).decode("ascii", "strict")
    expected = ""
    for line in manifest.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == info.asset_name:
            expected = parts[0].lower()
            break
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("Checksum SHA-256 dell'aggiornamento mancante o non valida")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / info.asset_name
    temporary = target.with_suffix(target.suffix + ".download")
    digest = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(_request(info.asset_url), timeout=30) as response, temporary.open("wb") as output:
            declared = int(response.headers.get("Content-Length", "0") or 0)
            if declared > MAX_ARTIFACT:
                raise RuntimeError("Aggiornamento troppo grande")
            while True:
                block = response.read(1024 * 256)
                if not block:
                    break
                total += len(block)
                if total > MAX_ARTIFACT:
                    raise RuntimeError("Aggiornamento troppo grande")
                digest.update(block)
                output.write(block)
        if not digest.hexdigest() == expected:
            raise RuntimeError("Checksum SHA-256 dell'aggiornamento non valida")
        os.replace(temporary, target)
        if os.name != "nt":
            target.chmod(0o755)
        return target
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
