import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from kerberus.router import RouterInstaller


class RouterTests(unittest.TestCase):
    @patch("kerberus.router.sys.platform", "win32")
    @patch("kerberus.router.subprocess.run")
    def test_stop_running_targets_i2p_process_tree(self, run):
        run.return_value = Mock(returncode=0)
        self.assertTrue(RouterInstaller.stop_running())
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["taskkill", "/IM", "I2Psvc.exe"])
        self.assertIn("/T", command)

    @patch("kerberus.router.sys.platform", "linux")
    def test_linux_sam_config_uses_private_user_directory(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"I2P_CONFIG_DIR": folder}):
            path = RouterInstaller.ensure_sam_enabled()
            self.assertEqual(path.parent, Path(folder) / "clients.config.d")
            self.assertIn("127.0.0.1 7656", path.read_text("utf-8"))

    @patch("kerberus.router.sys.platform", "linux")
    @patch("kerberus.router.subprocess.run")
    @patch("kerberus.router.shutil.which", return_value="/usr/bin/i2prouter")
    @patch.object(RouterInstaller, "is_running", return_value=False)
    @patch.object(RouterInstaller, "ensure_sam_enabled")
    def test_linux_starts_installed_user_router(self, _config, _running, _which, run):
        run.return_value = Mock(returncode=0)
        self.assertTrue(RouterInstaller.start_installed())
        self.assertEqual(run.call_args.args[0], ["/usr/bin/i2prouter", "start"])
        RouterInstaller._started_by_kerberus = False


if __name__ == "__main__":
    unittest.main()
