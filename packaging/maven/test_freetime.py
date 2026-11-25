import hashlib
import tempfile
import unittest
from pathlib import Path

from freetime import MODULES, already_published, import_release, latest_tag
from sync import metadata_versions, xml_root


def stage(root, version, unified=False):
    for module in MODULES:
        targets = (
            (("", "jar"),)
            if unified
            else (("", "jar"), ("-android", "aar"), ("-desktop", "jar"))
        )
        for suffix, binary in targets:
            name = module + suffix
            artifact = root / "com/freetime" / name
            release = artifact / version
            release.mkdir(parents=True)
            for extension, payload in (
                ("pom", "<project/>"),
                ("module", "{}"),
                (binary, version),
            ):
                (release / f"{name}-{version}.{extension}").write_text(payload)
            if unified:
                for classifier in ("android.aar", "desktop.jar"):
                    (release / f"{name}-{version}-{classifier}").write_text(version)
            (artifact / "maven-metadata.xml").write_text(
                f"<metadata><groupId>com.freetime</groupId><artifactId>{name}</artifactId>"
                f"<versioning><latest>{version}</latest><release>{version}</release>"
                f"<versions><version>{version}</version></versions></versioning></metadata>"
            )


class FreetimeTest(unittest.TestCase):
    def test_select_numeric_stable_tag_and_peel(self):
        refs = [
            f"{'a' * 40}\trefs/tags/v4.9.0\n",
            f"{'b' * 40}\trefs/tags/v4.10.0\n",
            f"{'c' * 40}\trefs/tags/v4.10.0^{{}}\n",
            f"{'d' * 40}\trefs/tags/v5.0.0-rc1\n",
            f"{'e' * 40}\trefs/tags/6.0.0\n",
        ]
        self.assertEqual(latest_tag(refs), ("v4.10.0", "c" * 40))
        with self.assertRaisesRegex(ValueError, "no stable"):
            latest_tag(refs[-2:])

    def test_skip_published_tag(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "state"
            self.assertFalse(already_published("v4.0.0", state))
            state.write_text("v4.0.0\n")
            self.assertTrue(already_published("v4.0.0", state))
            self.assertTrue(already_published("v3.9.0", state))
            self.assertFalse(already_published("v4.1.0", state))

    def test_merge_preserves_releases_and_regenerates_metadata_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "maven"
            for version in ("4.0.0", "4.1.0"):
                stage(root / version, version)
                self.assertGreater(import_release(root / version, output, version), 0)
            artifact = output / "com/freetime/Core"
            self.assertEqual((artifact / "4.0.0/Core-4.0.0.jar").read_text(), "4.0.0")
            metadata = artifact / "maven-metadata.xml"
            self.assertEqual(
                metadata_versions(metadata, "com/freetime/Core"), {"4.0.0", "4.1.0"}
            )
            self.assertEqual(xml_root(metadata).findtext("versioning/latest"), "4.1.0")
            self.assertEqual(
                metadata.with_suffix(".xml.sha256").read_text(),
                hashlib.sha256(metadata.read_bytes()).hexdigest(),
            )
            self.assertEqual(import_release(root / "4.1.0", output, "4.1.0"), 0)
            (root / "4.1.0/com/freetime/Core/4.1.0/Core-4.1.0.jar").write_text(
                "changed"
            )
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                import_release(root / "4.1.0", output, "4.1.0")
            self.assertEqual((artifact / "4.1.0/Core-4.1.0.jar").read_text(), "4.1.0")

    def test_unified_publication_requires_both_target_binaries(self):
        with tempfile.TemporaryDirectory() as temp:
            staged, output = Path(temp) / "staged", Path(temp) / "maven"
            stage(staged, "4.0.1", unified=True)
            target = Path("com/freetime/Core/4.0.1/Core-4.0.1-desktop.jar")
            (staged / target).unlink()
            with self.assertRaisesRegex(ValueError, "missing staged file.*desktop.jar"):
                import_release(staged, output, "4.0.1")
            self.assertFalse(output.exists())
            (staged / target).write_text("desktop")
            self.assertGreater(import_release(staged, output, "4.0.1"), 0)
            self.assertEqual((output / target).read_text(), "desktop")

    def test_incomplete_publication_does_not_create_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            staged, output = Path(temp) / "staged", Path(temp) / "maven"
            stage(staged, "4.0.0")
            (staged / "com/freetime/Core-android/4.0.0/Core-android-4.0.0.aar").unlink()
            with self.assertRaisesRegex(ValueError, "missing staged file"):
                import_release(staged, output, "4.0.0")
            self.assertFalse(output.exists())
