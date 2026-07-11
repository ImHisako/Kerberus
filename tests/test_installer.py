import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import installer


class InstallerTests(unittest.TestCase):
    def test_expected_official_downloads_are_pinned(self):
        self.assertEqual(installer.I2P_VERSION, "2.12.0")
        self.assertEqual(
            installer.I2P_URL,
            "https://files.i2p.net/2.12.0/i2pinstall_2.12.0_windows.exe",
        )
        self.assertEqual(
            installer.AZUL_URL,
            "https://cdn.azul.com/zulu/bin/zulu26.30.11-ca-jdk26.0.1-win_x64.msi",
        )

    def test_java_26_version_is_supported(self):
        completed = Mock(stderr='openjdk version "26.0.1"', stdout="")
        with patch("installer.subprocess.run", return_value=completed):
            self.assertEqual(installer.InstallerEngine._java_major(Path("java.exe")), 26)

    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.bin"
            path.write_bytes(b"kerberus")
            self.assertEqual(installer.sha256_file(path), hashlib.sha256(b"kerberus").hexdigest())

    def test_sam_config_is_loopback_only_and_enabled(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"LOCALAPPDATA": folder}):
            path = installer.InstallerEngine.ensure_sam_config()
            content = path.read_text("utf-8")
            self.assertIn("127.0.0.1 7656", content)
            self.assertIn("startOnLoad=true", content)


if __name__ == "__main__":
    unittest.main()
