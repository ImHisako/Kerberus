import os
from pathlib import Path
import tomllib
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

import build_release
import build_source_release
import installer
import kerberus_app
from kerberus import __version__


ROOT = Path(__file__).resolve().parents[1]


class ReleaseBuildTests(unittest.TestCase):
    def test_version_is_semver_and_shared_by_app_package_and_installer(self):
        self.assertRegex(__version__, r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
        self.assertEqual(installer.APP_VERSION, __version__)
        project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
        self.assertEqual(project["project"]["dynamic"], ["version"])
        self.assertEqual(project["tool"]["setuptools"]["dynamic"]["version"]["attr"], "kerberus.__version__")

    def test_release_tag_must_match_application_version(self):
        expected_tag = f"v{__version__}"
        build_source_release.validate_tag(expected_tag)
        with self.assertRaisesRegex(RuntimeError, expected_tag):
            build_source_release.validate_tag("v999.999.999")
        with patch.dict(os.environ, {"GITHUB_REF_TYPE": "tag", "GITHUB_REF_NAME": "v999.999.999"}):
            with self.assertRaisesRegex(RuntimeError, expected_tag):
                build_release.validate_release_tag()

    def test_application_release_self_test_checks_embedded_version_and_imports(self):
        self.assertEqual(kerberus_app.release_self_test(__version__), 0)
        self.assertEqual(kerberus_app.release_self_test("999.999.999"), 4)

    def test_release_builder_self_tests_go_voice_codec(self):
        responses = [
            SimpleNamespace(returncode=0, stdout=b"KVA1" + bytes(20)),
            SimpleNamespace(returncode=0, stdout=bytes(32_000)),
        ]
        with patch("build_release.subprocess.run", side_effect=responses) as run:
            build_release.validate_native_voice_codec(Path("kerberus-native"))
        self.assertEqual(run.call_count, 2)

    def test_frozen_voice_self_test_uses_bundled_go_codec(self):
        codec = Mock()
        codec.encode.return_value = ({"data": "encoded"}, {})
        codec.decode.return_value = (bytes(3_200), {})
        with patch("kerberus.voice.NativeVoiceCodec", return_value=codec):
            self.assertEqual(kerberus_app.voice_self_test(), 0)

    def test_source_archive_rejects_an_uncommitted_version_bump(self):
        with patch(
            "build_source_release.subprocess.check_output",
            return_value='__version__ = "999.999.999"\n',
        ):
            with self.assertRaisesRegex(RuntimeError, "crea il commit"):
                build_source_release.validate_committed_version()
        with patch(
            "build_source_release.subprocess.check_output",
            return_value=f'__version__ = "{__version__}"\n',
        ):
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
