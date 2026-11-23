#!/usr/bin/env python3
"""Approve candidate metadata only after strict builds in disposable containers."""

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml


def versions_to_test(previous, candidate):
    known = {int(build["versionCode"]): build for build in previous.get("Builds", [])}
    versions = {
        int(build["versionCode"])
        for build in candidate.get("Builds", [])
        if known.get(int(build["versionCode"])) != build
    }
    versions.add(int(candidate["CurrentVersionCode"]))
    for code in versions:
        builds = [
            b for b in candidate.get("Builds", []) if int(b["versionCode"]) == code
        ]
        if len(builds) != 1 or builds[0].get("disable"):
            raise ValueError(f"Expected one enabled build for version {code}")
    return sorted(versions)


def main():
    spec = importlib.util.spec_from_file_location("guard", "check-metadata-update.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    output = Path("tested-updates")
    output.mkdir(exist_ok=False)
    for result in sorted(Path("update-results").glob("*/result.json")):
        data = json.loads(result.read_text(encoding="utf-8"))
        if not data["changed"]:
            continue
        app = data["app_id"]
        if app not in {p.stem for p in Path("metadata").glob("*.yml")}:
            raise ValueError(f"Unknown app: {app}")
        metadata = Path("metadata") / f"{app}.yml"
        candidate = result.parent / "metadata" / metadata.name
        original = metadata.read_bytes()
        previous = yaml.safe_load(original)
        updated = yaml.safe_load(candidate.read_bytes())
        guard.validate(previous, updated)
        try:
            shutil.copyfile(candidate, metadata)
            for code in versions_to_test(previous, updated):
                results = (Path("fdroid-results") / app / str(code)).resolve()
                results.mkdir(parents=True, exist_ok=False)
                apk = results / "tmp" / f"{app}_{code}.apk"
                with tempfile.TemporaryDirectory() as temporary:
                    staged = Path(temporary)
                    (staged / "metadata").mkdir()
                    shutil.copyfile(candidate, staged / "metadata" / metadata.name)
                    if (metadata.parent / app).is_dir():
                        shutil.copytree(
                            metadata.parent / app, staged / "metadata" / app
                        )
                    shutil.copytree("srclibs", staged / "srclibs")
                    subprocess.run(
                        [
                            "docker",
                            "run",
                            "--rm",
                            "--mount",
                            f"type=bind,source={staged},target=/input,readonly",
                            "--mount",
                            f"type=bind,source={results},target=/output",
                            "--mount",
                            f"type=bind,source={Path('test-metadata-build.sh').resolve()},target=/build-test.sh,readonly",
                            "--env",
                            f"APP_ID={app}",
                            "--env",
                            f"VERSION_CODE={code}",
                            "--entrypoint",
                            "/bin/bash",
                            os.environ["BUILD_IMAGE"],
                            "/build-test.sh",
                        ],
                        check=True,
                    )
                if not apk.is_file() or not apk.stat().st_size:
                    raise ValueError(f"Build produced no APK: {apk}")
            shutil.copytree(result.parent, output / result.parent.name)
        finally:
            metadata.write_bytes(original)
    # Keep the artifact nonempty even when no updates were found.
    (output / "build-tests-complete.txt").write_text("All candidate builds passed.\n")


if __name__ == "__main__":
    main()
