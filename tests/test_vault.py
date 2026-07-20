import tempfile
import unittest
from pathlib import Path

from kerberus.vault import Vault


class VaultTests(unittest.TestCase):
    def test_encrypted_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "vault.kbv"
            vault = Vault(path)
            vault.create("password-lunga-di-test")
            vault.state["messages"].append({"text": "segreto"})
            vault.save()
            self.assertNotIn(b"segreto", path.read_bytes())
            reopened = Vault(path)
            reopened.unlock("password-lunga-di-test")
            self.assertEqual(reopened.state["messages"][0]["text"], "segreto")
            self.assertFalse(reopened.state["settings"]["stream_proof_enabled"])
            self.assertEqual(reopened.state["settings"]["theme"], "default")
            self.assertEqual(reopened.state["settings"]["text_scale"], 100)
            self.assertEqual(reopened.state["settings"]["ui_density"], "comfortable")
            self.assertEqual(reopened.state["attachment_transfers"], {})
            self.assertEqual(reopened.state["attachment_seen"], {})
            self.assertNotIn("ipinfo_token", reopened.state["settings"])
            with self.assertRaises(ValueError):
                Vault(path).unlock("password-completamente-errata")


if __name__ == "__main__":
    unittest.main()
