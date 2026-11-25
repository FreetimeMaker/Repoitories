#!/usr/bin/env python3
"""Refresh store listings from the selected F-Droid build reference."""

import base64
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

import yaml

TEXT_FILES = {"title.txt", "short_description.txt", "full_description.txt", "video.txt"}
IMAGE_DIRS = {
    "phoneScreenshots",
    "sevenInchScreenshots",
    "tenInchScreenshots",
    "tvScreenshots",
    "wearScreenshots",
}
IMAGE_STEMS = {"icon", "featureGraphic", "promoGraphic", "tvBanner"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def api(endpoint):
    return json.loads(
        subprocess.check_output(["gh", "api", endpoint], stderr=subprocess.PIPE)
    )


def entries(repo, path, ref):
    result = api(f"repos/{repo}/contents/{quote(path)}?{urlencode({'ref': ref})}")
    if not isinstance(result, list):
        raise ValueError(f"Expected directory: {path}")
    for entry in result:
        name = entry["name"]
        if name in {".", ".."} or "/" in name or "\\" in name:
            raise ValueError(f"Unsafe upstream filename: {name}")
    return result


def download(repo, entry):
    data = api(f"repos/{repo}/git/blobs/{entry['sha']}")
    if data.get("encoding") != "base64":
        raise ValueError(f"Unsupported encoding: {entry['path']}")
    return base64.b64decode(data["content"])


def sync(repo, app, ref):
    locales = entries(repo, "fastlane/metadata/android", ref)
    for locale in locales:
        if locale["type"] != "dir":
            continue
        # Stage the entire locale in memory before changing any local files.
        pending = {}
        screenshot_dirs = []
        try:
            for entry in entries(repo, locale["path"], ref):
                if entry["type"] == "file" and entry["name"] in TEXT_FILES:
                    pending[Path(entry["name"])] = download(repo, entry)
                elif entry["type"] == "dir" and entry["name"] == "images":
                    for image in entries(repo, entry["path"], ref):
                        name = Path(image["name"])
                        if (
                            image["type"] == "file"
                            and name.stem in IMAGE_STEMS
                            and name.suffix.lower() in IMAGE_SUFFIXES
                        ):
                            pending[Path("images") / name] = download(repo, image)
                        elif image["type"] == "dir" and image["name"] in IMAGE_DIRS:
                            directory = Path("images") / name
                            screenshot_dirs.append(directory)
                            for screenshot in entries(repo, image["path"], ref):
                                if (
                                    screenshot["type"] == "file"
                                    and Path(screenshot["name"]).suffix.lower()
                                    in IMAGE_SUFFIXES
                                ):
                                    pending[directory / screenshot["name"]] = download(
                                        repo, screenshot
                                    )
        except (subprocess.CalledProcessError, ValueError, KeyError) as error:
            print(
                f"Warning: keeping local listing for {app}/{locale['name']}: {error}",
                file=sys.stderr,
            )
            continue
        destination = Path("metadata") / app / locale["name"]
        for relative, content in pending.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        # Remove renamed screenshots only after the complete upstream set was fetched.
        for directory in screenshot_dirs:
            local = destination / directory
            if local.exists():
                for old in local.iterdir():
                    if (
                        old.is_file()
                        and old.suffix.lower() in IMAGE_SUFFIXES
                        and directory / old.name not in pending
                    ):
                        old.unlink()
        print(f"Synced {app}@{ref}/{locale['name']}: {len(pending)} files")


def build_ref(metadata):
    data = yaml.safe_load(metadata.read_text())
    version = data.get("CurrentVersionCode")
    if version is not None:
        for build in data.get("Builds", []):
            if str(build.get("versionCode")) == str(version) and not build.get(
                "disable"
            ):
                ref = build.get("commit")
                if isinstance(ref, str) and ref.strip():
                    return ref
    raise ValueError(f"No build reference for CurrentVersionCode {version}")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--build-ref":
        try:
            print(quote(build_ref(Path(sys.argv[2])), safe=""))
        except (OSError, ValueError, yaml.YAMLError) as error:
            sys.exit(str(error))
        return
    target = sys.argv[1] if len(sys.argv) > 1 else None
    for metadata in sorted(Path("metadata").glob("*.yml")):
        if target and metadata.stem != target:
            continue
        match = re.search(
            r"^SourceCode:\s*https://github\.com/([^/\s]+/[^/\s]+)",
            metadata.read_text(),
            re.MULTILINE,
        )
        if not match:
            continue
        repo = match[1].removesuffix(".git")
        try:
            sync(repo, metadata.stem, build_ref(metadata))
        except (
            subprocess.CalledProcessError,
            ValueError,
            KeyError,
            yaml.YAMLError,
        ) as error:
            print(
                f"Warning: keeping local listings for {metadata.stem}: {error}",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
