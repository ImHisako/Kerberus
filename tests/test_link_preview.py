import json
from email.message import Message
import unittest
import urllib.parse
from unittest.mock import patch

from kerberus.link_preview import LinkPreviewError, _download, _validate_url, extract_url, fetch_link_preview


class LinkPreviewTests(unittest.TestCase):
    def test_extracts_first_http_url(self):
        self.assertEqual(
            extract_url("guarda https://example.com/video?id=1, poi dimmi"),
            "https://example.com/video?id=1",
        )

    def test_blocks_loopback_and_private_addresses(self):
        for url in ("http://127.0.0.1/admin", "http://10.0.0.1/", "http://[::1]/"):
            with self.subTest(url=url), self.assertRaises(LinkPreviewError):
                _validate_url(url)

    @patch("kerberus.link_preview._resolve_url")
    @patch("kerberus.link_preview._PinnedHTTPConnection")
    def test_download_connects_to_the_validated_ip_not_a_second_dns_lookup(self, connection_type, resolve):
        resolve.return_value = (urllib.parse.urlsplit("http://attacker.example/card"), ("93.184.216.34",))
        headers = Message()
        headers["Content-Type"] = "text/html"
        response = type("Response", (), {
            "status": 200,
            "headers": headers,
            "getheader": lambda self, name, default=None: default,
            "read": lambda self, _limit: b"<title>safe</title>",
        })()
        connection_type.return_value.getresponse.return_value = response
        data, _, _ = _download("http://attacker.example/card", 1000, ("text/html",))
        self.assertEqual(data, b"<title>safe</title>")
        self.assertEqual(connection_type.call_args.args[2], "93.184.216.34")

    @patch("kerberus.link_preview._validate_url", side_effect=lambda url: urllib.parse.urlsplit(url))
    @patch("kerberus.link_preview._download")
    def test_youtube_oembed_produces_title_author_and_thumbnail(self, download, _validate):
        metadata = json.dumps({
            "title": "Video di test",
            "author_name": "Autore",
            "thumbnail_url": "https://i.ytimg.com/vi/dpIYpofOt7A/hqdefault.jpg",
        }).encode()
        download.side_effect = [
            (metadata, "application/json", "https://www.youtube.com/oembed"),
            (b"image-bytes", "image/jpeg", "https://i.ytimg.com/thumbnail.jpg"),
        ]
        preview = fetch_link_preview("https://www.youtube.com/watch?v=dpIYpofOt7A")
        self.assertEqual(preview["site"], "YouTube")
        self.assertEqual(preview["title"], "Video di test")
        self.assertEqual(preview["author"], "Autore")
        self.assertEqual(preview["image"], b"image-bytes")

    @patch("kerberus.link_preview._validate_url", side_effect=lambda url: urllib.parse.urlsplit(url))
    @patch("kerberus.link_preview._download")
    def test_open_graph_preview_resolves_relative_image(self, download, _validate):
        html = b"""<html><head><title>Fallback</title>
        <meta property='og:site_name' content='Example'>
        <meta property='og:title' content='Titolo card'>
        <meta property='og:description' content='Descrizione'>
        <meta property='og:image' content='/cover.jpg'></head></html>"""
        download.side_effect = [
            (html, "text/html", "https://example.com/page"),
            (b"cover", "image/jpeg", "https://example.com/cover.jpg"),
        ]
        preview = fetch_link_preview("https://example.com/page")
        self.assertEqual(preview["site"], "Example")
        self.assertEqual(preview["title"], "Titolo card")
        self.assertEqual(preview["description"], "Descrizione")
        self.assertEqual(download.call_args_list[1].args[0], "https://example.com/cover.jpg")


if __name__ == "__main__":
    unittest.main()
