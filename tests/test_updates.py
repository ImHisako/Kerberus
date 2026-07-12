import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kerberus.updates import UpdateInfo, check_for_update, download_update


class FakeResponse:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        if size < 0:
            size = len(self.data) - self.offset
        chunk = self.data[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class UpdateTests(unittest.TestCase):
    def test_check_rejects_rollback_and_selects_platform_assets(self):
        release = {
            "tag_name": "v0.4.0",
            "draft": False,
            "prerelease": False,
            "html_url": "https://github.com/ImHisako/Kerberus/releases/tag/v0.4.0",
            "assets": [
                {"name": "KerberusInstaller.exe", "browser_download_url": "https://example/installer"},
                {"name": "SHA256SUMS.txt", "browser_download_url": "https://example/sums"},
            ],
        }
        with patch("kerberus.updates.os.name", "nt"), patch(
            "kerberus.updates._read_limited", return_value=json.dumps(release).encode()
        ):
            info = check_for_update("0.3.0")
            self.assertEqual(info.version, "0.4.0")
            self.assertIsNone(check_for_update("0.4.0"))

    def test_download_requires_matching_release_checksum(self):
        payload = b"verified update"
        digest = hashlib.sha256(payload).hexdigest()
        info = UpdateInfo(
            "0.4.0", "v0.4.0", "https://example/release", "KerberusInstaller.exe",
            "https://example/installer", "SHA256SUMS.txt", "https://example/sums",
        )
        manifest = f"{digest}  KerberusInstaller.exe\n".encode()
        with tempfile.TemporaryDirectory() as folder, patch(
            "kerberus.updates._read_limited", return_value=manifest
        ), patch("kerberus.updates.urllib.request.urlopen", return_value=FakeResponse(payload)):
            target = download_update(info, Path(folder))
            self.assertEqual(target.read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
