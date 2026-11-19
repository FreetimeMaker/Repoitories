import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fetch


class FetchTests(unittest.TestCase):
    source = {"github_latest": "Owner/Repo", "asset_prefix": "pkg_"}
    url = "https://github.com/Owner/Repo/releases/download/v1/pkg_1.deb"
    sha256 = "a" * 64

    def setUp(self):
        self.asset = {
            "name": "pkg_1.deb",
            "digest": f"sha256:{self.sha256}",
            "browser_download_url": self.url,
            "state": "uploaded",
        }
        self.release = {
            "tag_name": "v1",
            "draft": False,
            "prerelease": False,
            "assets": [self.asset],
        }

    def test_resolves_mixed_sources_and_checks_duplicates(self):
        pin = {"url": self.url.replace("pkg_1", "old"), "sha256": self.sha256}
        with patch.object(fetch, "latest_release", return_value=self.release):
            self.assertEqual(
                fetch.resolve([self.source, pin], "deb"),
                [
                    (pin["url"], self.sha256, "old.deb"),
                    (self.url, self.sha256, "pkg_1.deb"),
                ],
            )
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                fetch.resolve([self.source, dict(pin, url=self.url)], "deb")

    def test_rejects_bad_latest_metadata(self):
        bad_releases = [
            dict(self.release, draft=True),
            dict(self.release, prerelease=True),
            dict(self.release, tag_name="../v1"),
            dict(self.release, assets=[]),
            dict(self.release, assets=[self.asset, self.asset]),
        ]
        for update in (
            {"digest": None},
            {"digest": "sha256:123"},
            {"state": "new"},
            {"name": "pkg_../bad.deb"},
            {"browser_download_url": self.url.replace("Owner/Repo", "Other/Repo")},
        ):
            bad_releases.append(dict(self.release, assets=[dict(self.asset, **update)]))
        for release in bad_releases:
            with (
                self.subTest(release=release),
                patch.object(fetch, "latest_release", return_value=release),
            ):
                with self.assertRaises(ValueError):
                    fetch.resolve([self.source], "deb")

    def test_checksum_mismatch_is_not_staged(self):
        def download(args, *, check):
            Path(args[args.index("--output") + 1]).write_bytes(b"unexpected bytes")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(fetch.subprocess, "run", download),
        ):
            dest = Path(tmp) / "packages"
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                fetch.stage(dest, [(self.url, self.sha256, "pkg_1.deb")])
            self.assertEqual(list(dest.iterdir()), [])

    def test_state_skips_only_unchanged_scheduled_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "sources.json"
            manifest.write_text(json.dumps({"apt": [self.source], "yum": []}))
            output = root / "output"
            env = {"GITHUB_OUTPUT": str(output), "LINUX_GPG_FINGERPRINT": "a" * 40}
            state = root / "apt-source-state.json"
            with (
                patch.object(fetch, "ROOT", root),
                patch.dict(fetch.os.environ, env, clear=True),
                patch.object(fetch, "latest_release", return_value=self.release),
                patch.object(fetch, "stage") as stage,
            ):
                for event, changed, expected in [
                    ("schedule", None, True),
                    ("schedule", None, False),
                    ("workflow_dispatch", None, True),
                    ("push", None, True),
                    ("schedule", "fingerprint", True),
                    ("schedule", "digest", True),
                ]:
                    with self.subTest(event=event, changed=changed):
                        fetch.os.environ["GITHUB_EVENT_NAME"] = event
                        if changed == "fingerprint":
                            fetch.os.environ["LINUX_GPG_FINGERPRINT"] = "b" * 40
                        if changed == "digest":
                            self.asset["digest"] = "sha256:" + "b" * 64
                        output.write_text("")
                        stage.reset_mock()
                        work = root / "work"
                        work.mkdir(exist_ok=True)
                        fetch.main("apt", work)
                        self.assertEqual(stage.called, expected)
                        self.assertEqual(
                            output.read_text(), f"ready={str(expected).lower()}\n"
                        )
                        if expected:
                            (work / state.name).replace(state)
                        else:
                            self.assertFalse((work / state.name).exists())
