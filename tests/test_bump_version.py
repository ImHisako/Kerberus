from pathlib import Path
import tempfile
import unittest

import bump_version


class BumpVersionTests(unittest.TestCase):
    def make_repository(self, root: Path) -> None:
        (root / "kerberus").mkdir()
        (root / "kerberus" / "__init__.py").write_text(
            '"""Test package."""\n\n__version__ = "1.2.3"\n', encoding="utf-8"
        )
        for name in ("README.md", "README.it.md", "RELEASE.md"):
            (root / name).write_text("release 1.2.3 / tag v1.2.3\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## 1.2.3\n\n- Versione precedente.\n", encoding="utf-8"
        )

    def test_updates_release_references_and_adds_changelog_section(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_repository(root)

            old_version, changed = bump_version.bump_version("1.3.0", root)

            self.assertEqual(old_version, "1.2.3")
            self.assertEqual(len(changed), 5)
            self.assertIn('__version__ = "1.3.0"', (root / "kerberus" / "__init__.py").read_text("utf-8"))
            for name in ("README.md", "README.it.md", "RELEASE.md"):
                self.assertEqual((root / name).read_text("utf-8"), "release 1.3.0 / tag v1.3.0\n")
            changelog = (root / "CHANGELOG.md").read_text("utf-8")
            self.assertLess(changelog.index("## 1.3.0"), changelog.index("## 1.2.3"))
            self.assertIn("TODO", changelog)

    def test_rejects_invalid_or_unchanged_versions_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_repository(root)
            original = (root / "kerberus" / "__init__.py").read_text("utf-8")

            for version in ("1.2", "v1.2.4", "01.2.4", "1.2.2", "1.2.3"):
                with self.subTest(version=version), self.assertRaises(ValueError):
                    bump_version.bump_version(version, root)

            self.assertEqual((root / "kerberus" / "__init__.py").read_text("utf-8"), original)

    def test_missing_release_reference_aborts_every_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_repository(root)
            (root / "README.md").write_text("nessuna versione\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "README.md"):
                bump_version.bump_version("1.2.4", root)

            self.assertEqual(bump_version.current_version(root), "1.2.3")


if __name__ == "__main__":
    unittest.main()
