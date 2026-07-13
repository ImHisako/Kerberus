from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def _is_i2p_router(name: str, cmdline: list[str]) -> bool:
    process_name = name.lower()
    command = " ".join(cmdline).lower()
    if process_name.startswith(("i2p", "i2psvc")):
        return True
    return process_name in {"java", "java.exe", "javaw", "javaw.exe"} and (
        "router.jar" in command or "i2p" in command
    )


def collect_i2p_peer_connections(limit: int = 64) -> list[dict[str, Any]]:
    """Return public, established TCP peers owned by the local I2P router.

    These are observable transport peers, not a disclosure of the precise hops
    selected inside individual I2P tunnels.
    """
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("La diagnostica di rete richiede il componente psutil") from exc

    peers: dict[tuple[str, int], dict[str, Any]] = {}
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            info = process.info
            name = str(info.get("name") or "")
            cmdline = [str(part) for part in (info.get("cmdline") or [])]
            if not _is_i2p_router(name, cmdline):
                continue
            for connection in process.net_connections(kind="inet"):
                if str(connection.status).upper() != "ESTABLISHED" or not connection.raddr:
                    continue
                ip = str(connection.raddr.ip)
                port = int(connection.raddr.port)
                try:
                    if not ipaddress.ip_address(ip).is_global:
                        continue
                except ValueError:
                    continue
                peers[(ip, port)] = {
                    "ip": ip,
                    "port": port,
                    "process": name or "I2P",
                    "transport": "TCP",
                }
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
            continue
    return [peers[key] for key in sorted(peers)[: max(1, min(int(limit), 256))]]


def lookup_ip_geolocation(ip: str, timeout: float = 8.0) -> dict[str, str]:
    """Look up one public IP through the free, keyless ipwho.is endpoint."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError as exc:
        raise ValueError("Indirizzo IP non valido") from exc
    if not address.is_global:
        raise ValueError("Le informazioni sono disponibili solo per IP pubblici")

    request = Request(
        f"https://ipwho.is/{quote(str(address), safe=':')}",
        headers={"Accept": "application/json", "User-Agent": "Kerberus-I2P/0.4"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(65_537)
    except HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError("Limite giornaliero del servizio IP raggiunto") from exc
        raise RuntimeError(f"Il servizio IP ha risposto con errore HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Servizio informazioni IP non raggiungibile: {exc}") from exc
    if len(raw) > 65_536:
        raise RuntimeError("Risposta del servizio IP troppo grande")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Risposta del servizio IP non valida") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Risposta del servizio IP non valida")
    if payload.get("success") is False:
        message = str(payload.get("message") or "richiesta rifiutata")
        raise RuntimeError(f"Informazioni IP non disponibili: {message}")
    connection = payload.get("connection") if isinstance(payload.get("connection"), dict) else {}
    return {
        "ip": str(payload.get("ip") or address),
        "asn": str(connection.get("asn") or ""),
        "as_name": str(connection.get("org") or connection.get("isp") or ""),
        "as_domain": str(connection.get("domain") or ""),
        "country_code": str(payload.get("country_code") or ""),
        "country": str(payload.get("country") or ""),
        "continent_code": str(payload.get("continent_code") or ""),
        "continent": str(payload.get("continent") or ""),
        "region": str(payload.get("region") or ""),
        "city": str(payload.get("city") or ""),
    }
