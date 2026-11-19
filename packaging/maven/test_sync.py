import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from sync import sync


class SyncTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.source = self.root / "source"
        self.target = self.root / "maven"
        self.manifest = self.root / "sources.json"

    def write_manifest(self, entries=None):
        self.manifest.write_text(
            json.dumps(
                {
                    "sources": []
                    if entries is None
                    else [
                        {"base_url": "https://example.invalid/maven", "files": entries}
                    ]
                }
            ),
            encoding="utf-8",
        )

    def test_empty_manifest(self):
        self.write_manifest()
        self.assertEqual(sync(self.manifest, self.target), 0)
        self.assertFalse(self.target.exists())

    def test_path_traversal(self):
        self.write_manifest({"org/../thing/maven-metadata.xml": "0" * 64})
        with self.assertRaisesRegex(ValueError, "invalid Maven path"):
            sync(self.manifest, self.target, self.source)
        self.assertFalse(self.target.exists())

    @unittest.skipUnless(shutil.which("gradle"), "Gradle is not installed")
    def test_gradle_publication(self):
        (self.root / "settings.gradle").write_text("rootProject.name = 'fixture'\n")
        (self.root / "build.gradle").write_text("""
plugins { id 'java-library'; id 'maven-publish' }
group = 'org.example'
version = '1.0'
publishing {
    publications { library(MavenPublication) { from components.java } }
    repositories { maven { name = 'Staging'; url = uri('source') } }
}
""")
        result = subprocess.run(
            [
                "gradle",
                "--offline",
                "--no-daemon",
                "--console=plain",
                "publishAllPublicationsToStagingRepository",
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        entries = {
            file.relative_to(self.source).as_posix(): hashlib.sha256(
                file.read_bytes()
            ).hexdigest()
            for file in self.source.rglob("*")
            if file.suffix in {".jar", ".pom", ".module", ".xml"}
        }
        self.assertEqual(len(entries), 4)
        bad = dict(entries)
        jar = next(path for path in entries if path.endswith(".jar"))
        bad[jar] = "0" * 64
        self.write_manifest(bad)
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            sync(self.manifest, self.target, self.source)
        self.assertFalse(self.target.exists())

        self.write_manifest(entries)
        self.assertEqual(sync(self.manifest, self.target, self.source), 20)
        for path, digest in entries.items():
            self.assertEqual(
                (self.target / path).read_bytes(), (self.source / path).read_bytes()
            )
            self.assertEqual((self.target / (path + ".sha256")).read_text(), digest)
        # A repeat run needs no upstream access.
        self.assertEqual(sync(self.manifest, self.target), 0)
        self.write_manifest(bad)
        with self.assertRaisesRegex(ValueError, "overwrite a released file"):
            sync(self.manifest, self.target, self.source)


if __name__ == "__main__":
    unittest.main()
