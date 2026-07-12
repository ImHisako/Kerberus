from __future__ import annotations

import http.client
import ipaddress
import os
import socket
import ssl
import struct
import urllib.request
from collections.abc import Callable


class DnsPolicyError(ConnectionError):
    pass


def _read_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        block = sock.recv(size - len(data))
        if not block:
            raise DnsPolicyError("Connessione DNS cifrata chiusa")
        data.extend(block)
    return bytes(data)


def _query(hostname: str, qtype: int) -> tuple[int, bytes]:
    request_id = int.from_bytes(os.urandom(2), "big")
    labels = hostname.rstrip(".").split(".")
    if not labels or any(not label or len(label.encode("idna")) > 63 for label in labels):
        raise DnsPolicyError("Hostname DNS non valido")
    question = b"".join(bytes((len(label.encode("idna")),)) + label.encode("idna") for label in labels) + b"\0"
    return request_id, struct.pack("!HHHHHH", request_id, 0x0100, 1, 0, 0, 0) + question + struct.pack("!HH", qtype, 1)


def _skip_name(packet: bytes, offset: int) -> int:
    while offset < len(packet):
        size = packet[offset]
        if size == 0:
            return offset + 1
        if size & 0xC0 == 0xC0:
            if offset + 1 >= len(packet):
                break
            return offset + 2
        offset += size + 1
    raise DnsPolicyError("Risposta DNS troncata")


def _answers(packet: bytes, request_id: int, qtype: int) -> list[str]:
    if len(packet) < 12:
        raise DnsPolicyError("Risposta DNS troppo corta")
    ident, flags, questions, answers, _, _ = struct.unpack("!HHHHHH", packet[:12])
    if ident != request_id or flags & 0x000F:
        raise DnsPolicyError("Risposta DNS non valida")
    offset = 12
    for _ in range(questions):
        offset = _skip_name(packet, offset) + 4
    found: list[str] = []
    for _ in range(answers):
        offset = _skip_name(packet, offset)
        if offset + 10 > len(packet):
            raise DnsPolicyError("Risposta DNS troncata")
        kind, dns_class, _ttl, length = struct.unpack("!HHIH", packet[offset:offset + 10])
        offset += 10
        value = packet[offset:offset + length]
        offset += length
        if dns_class == 1 and kind == qtype and length in (4, 16):
            found.append(str(ipaddress.ip_address(value)))
    return found


def resolve_dot(hostname: str, resolver_host: str, bootstrap_ip: str, port: int = 853) -> list[str]:
    ipaddress.ip_address(bootstrap_ip)
    context = ssl.create_default_context()
    results: list[str] = []
    with socket.create_connection((bootstrap_ip, port), timeout=5) as raw:
        with context.wrap_socket(raw, server_hostname=resolver_host) as secured:
            secured.settimeout(5)
            for qtype in (1, 28):
                request_id, query = _query(hostname, qtype)
                secured.sendall(struct.pack("!H", len(query)) + query)
                length = struct.unpack("!H", _read_exact(secured, 2))[0]
                if length > 65535:
                    raise DnsPolicyError("Risposta DNS troppo grande")
                results.extend(_answers(_read_exact(secured, length), request_id, qtype))
    if not results:
        raise DnsPolicyError(f"Nessun indirizzo trovato per {hostname}")
    return results


def resolve_doh(hostname: str, resolver_host: str, bootstrap_ip: str, port: int = 443) -> list[str]:
    ipaddress.ip_address(bootstrap_ip)
    context = ssl.create_default_context()
    results: list[str] = []
    for qtype in (1, 28):
        request_id, query = _query(hostname, qtype)
        with socket.create_connection((bootstrap_ip, port), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname=resolver_host) as secured:
                secured.settimeout(5)
                secured.sendall(
                    (
                        "POST /dns-query HTTP/1.1\r\n"
                        f"Host: {resolver_host}\r\n"
                        "Content-Type: application/dns-message\r\n"
                        "Accept: application/dns-message\r\n"
                        f"Content-Length: {len(query)}\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode("ascii") + query
                )
                response = http.client.HTTPResponse(secured)
                response.begin()
                if response.status != 200 or response.getheader("Content-Type", "").split(";", 1)[0] != "application/dns-message":
                    raise DnsPolicyError(f"DoH ha risposto HTTP {response.status}")
                packet = response.read(65536)
                results.extend(_answers(packet, request_id, qtype))
    if not results:
        raise DnsPolicyError(f"Nessun indirizzo trovato per {hostname}")
    return results


def resolver_from_settings(settings: dict) -> Callable[[str], list[str]] | None:
    mode = str(settings.get("dns_mode", "none"))
    if mode == "system":
        return None
    if mode == "none":
        return lambda hostname: (_ for _ in ()).throw(DnsPolicyError(f"DNS disabilitato: {hostname}"))
    resolver_host = "base.dns.mullvad.net" if mode == "mullvad" else str(settings.get("dns_host", ""))
    bootstraps = (
        ["194.242.2.4", "2a07:e340::4"]
        if mode == "mullvad"
        else [str(settings.get("dns_ipv4", "")), str(settings.get("dns_ipv6", ""))]
    )
    bootstraps = [value for value in bootstraps if value]
    if not resolver_host or not bootstraps:
        raise DnsPolicyError("Endpoint DNS cifrato incompleto")
    port = int(settings.get("dns_port", 853))
    resolver = resolve_doh if port == 443 else resolve_dot

    def encrypted(hostname: str) -> list[str]:
        last_error: Exception | None = None
        for bootstrap in bootstraps:
            try:
                return resolver(hostname, resolver_host, bootstrap, port)
            except (OSError, DnsPolicyError) as exc:
                last_error = exc
        raise DnsPolicyError(f"Resolver cifrato non raggiungibile: {last_error}")

    return encrypted


class _ResolvedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, resolver: Callable[[str], list[str]], **kwargs):
        self._resolver = resolver
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        addresses = self._resolver(self.host)
        error: OSError | None = None
        for address in addresses:
            try:
                self.sock = socket.create_connection((address, self.port), self.timeout, self.source_address)
                server_hostname = self._tunnel_host or self.host
                if self._tunnel_host:
                    self._tunnel()
                self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)
                return
            except OSError as exc:
                error = exc
        raise DnsPolicyError(f"Connessione a {self.host} fallita: {error}")


class _ResolvedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, resolver: Callable[[str], list[str]]):
        super().__init__()
        self._resolver = resolver

    def https_open(self, request):
        resolver = self._resolver

        def factory(host: str, **kwargs):
            return _ResolvedHTTPSConnection(host, resolver, **kwargs)

        return self.do_open(factory, request)


def build_opener(settings: dict):
    resolver = resolver_from_settings(settings)
    if resolver is None:
        return urllib.request.build_opener()
    return urllib.request.build_opener(_ResolvedHTTPSHandler(resolver))
