from __future__ import annotations

import ipaddress
import http.client
import json
import re
import socket
import ssl
import urllib.parse
import urllib.error
from html.parser import HTMLParser


MAX_HTML = 1_000_000
MAX_IMAGE = 3_000_000
USER_AGENT = "Kerberus-LinkPreview/1.0"
URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


class LinkPreviewError(ValueError):
    pass


def extract_url(text: str) -> str:
    match = URL_RE.search(text)
    return match.group(0).rstrip(".,;:!?)\"]}") if match else ""


def _validate_url(url: str) -> urllib.parse.SplitResult:
    parsed, _ = _resolve_url(url)
    return parsed


def _resolve_url(url: str) -> tuple[urllib.parse.SplitResult, tuple[str, ...]]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise LinkPreviewError("URL non supportato")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal", ".i2p")):
        raise LinkPreviewError("Host locale non consentito")
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            }
        except OSError as exc:
            raise LinkPreviewError("Host non risolvibile") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise LinkPreviewError("Indirizzo locale o riservato non consentito")
    return parsed, tuple(str(address) for address in addresses)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, address: str, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


class _PinnedHTTPSConnection(_PinnedHTTPConnection):
    def connect(self) -> None:
        raw = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)


def _download(url: str, limit: int, accepted_types: tuple[str, ...]) -> tuple[bytes, str, str]:
    current = url
    for _ in range(6):
        parsed, addresses = _resolve_url(current)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        connection_type = _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
        connection = connection_type(parsed.hostname or "", port, addresses[0], 8)
        path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        default_port = 443 if parsed.scheme == "https" else 80
        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        if port != default_port:
            host = f"{host}:{port}"
        try:
            connection.request("GET", path, headers={
                "Host": host, "User-Agent": USER_AGENT, "Accept": ", ".join(accepted_types),
                "Connection": "close",
            })
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise LinkPreviewError("Redirect senza destinazione")
                current = urllib.parse.urljoin(current, location)
                continue
            if response.status < 200 or response.status >= 300:
                raise LinkPreviewError(f"Risposta HTTP {response.status}")
            content_type = response.headers.get_content_type().lower()
            if not any(content_type == value or content_type.startswith(value) for value in accepted_types):
                raise LinkPreviewError(f"Tipo contenuto non supportato: {content_type}")
            declared = int(response.getheader("Content-Length", "0") or 0)
            if declared > limit:
                raise LinkPreviewError("Anteprima troppo grande")
            data = response.read(limit + 1)
            if len(data) > limit:
                raise LinkPreviewError("Anteprima troppo grande")
            return data, content_type, current
        finally:
            connection.close()
    raise LinkPreviewError("Troppi redirect")


class _MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.metadata: dict[str, str] = {}
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            content = values.get("content", "").strip()
            if key and content and key not in self.metadata:
                self.metadata[key] = content
        elif tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self._title_parts).split())


def _short(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _youtube_id(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/").split("/", 1)[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            candidate = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/")):
            candidate = parsed.path.split("/")[2]
        else:
            candidate = ""
    else:
        candidate = ""
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", candidate) else ""


def _page_metadata(raw: bytes, final_url: str, fallback_host: str) -> tuple[dict, str]:
    parser = _MetadataParser()
    parser.feed(raw.decode("utf-8", "replace"))
    meta = parser.metadata
    values = {
        "url": final_url,
        "site": _short(meta.get("og:site_name") or fallback_host, 100),
        "title": _short(meta.get("og:title") or meta.get("twitter:title") or parser.title or fallback_host, 300),
        "author": _short(meta.get("author"), 120),
        "description": _short(
            meta.get("og:description") or meta.get("twitter:description") or meta.get("description"), 500
        ),
    }
    image_url = str(meta.get("og:image") or meta.get("twitter:image") or "")
    return values, urllib.parse.urljoin(final_url, image_url) if image_url else ""


def fetch_link_preview(url: str) -> dict:
    parsed = _validate_url(url)
    result = {
        "url": url,
        "site": parsed.hostname or "Link",
        "title": parsed.hostname or url,
        "author": "",
        "description": "",
        "image": b"",
    }
    video_id = _youtube_id(url)
    if video_id:
        endpoint = "https://www.youtube.com/oembed?" + urllib.parse.urlencode({"url": url, "format": "json"})
        try:
            raw, _, _ = _download(endpoint, 256_000, ("application/json",))
            value = json.loads(raw.decode("utf-8"))
            result.update({
                "site": "YouTube",
                "title": _short(value.get("title"), 300),
                "author": _short(value.get("author_name"), 120),
            })
            image_url = str(value.get("thumbnail_url") or "")
        except (urllib.error.URLError, LinkPreviewError, ValueError):
            try:
                raw, _, final_url = _download(url, MAX_HTML, ("text/html", "application/xhtml+xml"))
                values, image_url = _page_metadata(raw, final_url, "YouTube")
                result.update(values)
                result["site"] = "YouTube"
            except (urllib.error.URLError, LinkPreviewError):
                result.update({"site": "YouTube", "title": "Video YouTube"})
                image_url = ""
        image_url = image_url or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    else:
        raw, _, final_url = _download(url, MAX_HTML, ("text/html", "application/xhtml+xml"))
        values, image_url = _page_metadata(raw, final_url, parsed.hostname or "Link")
        result.update(values)
    if image_url:
        try:
            result["image"], _, _ = _download(image_url, MAX_IMAGE, ("image/",))
        except (OSError, LinkPreviewError):
            result["image"] = b""
    return result
