import os
from pathlib import Path
import tomllib
import unittest
from unittest.mock import patch

import build_release
import build_source_release
import installer
import kerberus_app
from kerberus import __version__


ROOT = Path(__file__).resolve().parents[1]


class ReleaseBuildTests(unittest.TestCase):
    def test_version_070_is_shared_by_app_package_and_installer(self):
        self.assertEqual(__version__, "0.7.0")
        self.assertEqual(installer.APP_VERSION, __version__)
        project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
        self.assertEqual(project["project"]["dynamic"], ["version"])
        self.assertEqual(project["tool"]["setuptools"]["dynamic"]["version"]["attr"], "kerberus.__version__")

    def test_release_tag_must_match_application_version(self):
        build_source_release.validate_tag("v0.7.0")
        with self.assertRaisesRegex(RuntimeError, "v0.7.0"):
            build_source_release.validate_tag("v0.6.0")
        with patch.dict(os.environ, {"GITHUB_REF_TYPE": "tag", "GITHUB_REF_NAME": "v0.6.0"}):
            with self.assertRaisesRegex(RuntimeError, "v0.7.0"):
                build_release.validate_release_tag()

    def test_application_release_self_test_checks_embedded_version_and_imports(self):
        self.assertEqual(kerberus_app.release_self_test("0.7.0"), 0)
        self.assertEqual(kerberus_app.release_self_test("0.6.0"), 4)

    def test_source_archive_rejects_an_uncommitted_version_bump(self):
        with patch("build_source_release.subprocess.check_output", return_value='__version__ = "0.6.0"\n'):
            with self.assertRaisesRegex(RuntimeError, "crea il commit"):
                build_source_release.validate_committed_version()
        with patch("build_source_release.subprocess.check_output", return_value='__version__ = "0.7.0"\n'):
            build_source_release.validate_committed_version()

    def test_workflow_has_one_final_publisher_after_all_builds(self):
        workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text("utf-8")
        self.assertEqual(workflow.count("softprops/action-gh-release"), 1)
        self.assertIn("needs: [windows-build, linux-build, source-build]", workflow)
        self.assertIn("release/Kerberus-*-src.tar.gz", workflow)
        self.assertIn("release/kerberus_i2p-*.whl", workflow)

    def test_source_distribution_excludes_python_bytecode(self):
        manifest = (ROOT / "MANIFEST.in").read_text("utf-8")
        self.assertIn("global-exclude *.pyc *.pyo", manifest)


if __name__ == "__main__":
    unittest.main()
