import unittest
from unittest.mock import Mock, patch

from kerberus.router import RouterInstaller


class RouterTests(unittest.TestCase):
    @patch("kerberus.router.os.name", "nt")
    @patch("kerberus.router.subprocess.run")
    def test_stop_running_targets_i2p_process_tree(self, run):
        run.return_value = Mock(returncode=0)
        self.assertTrue(RouterInstaller.stop_running())
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["taskkill", "/IM", "I2Psvc.exe"])
        self.assertIn("/T", command)


if __name__ == "__main__":
    unittest.main()
