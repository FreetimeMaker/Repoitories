"""Resolve and stage public GitHub release assets with SHA-256 verification."""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = r"[A-Za-z0-9_-]+/[A-Za-z0-9_-][A-Za-z0-9_.-]*"
FILENAME = r"[A-Za-z0-9][A-Za-z0-9_.+-]*"
CURL = [
    "curl",
    "--disable",
    "--fail",
    "--silent",
    "--show-error",
    "--proto",
    "=https",
    "--proto-redir",
    "=https",
    "--retry",
    "3",
    "--connect-timeout",
    "15",
    "--max-time",
    "180",
]

FORMATS = {"apt": ("deb", "pool/main"), "yum": ("rpm", "x86_64/Packages")}
ASSET_URL = re.compile(
    r"https://github\.com/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+/releases/download/"
    r"[A-Za-z0-9_.+%-]+/([A-Za-z0-9][A-Za-z0-9_.+-]*)"
)


def validate(entries, extension):
    if not isinstance(entries, list):
        raise ValueError("Manifest entries must be an array")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.keys() != {"url", "sha256"}:
            raise ValueError("Each entry requires exactly url and sha256")
        url, digest = entry["url"], entry["sha256"]
        match = ASSET_URL.fullmatch(url) if isinstance(url, str) else None
        if not match or not match[1].endswith(f".{extension}"):
            raise ValueError(
                f"Expected a versioned GitHub release asset URL ending in .{extension}"
            )
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("sha256 must contain 64 lowercase hex characters")
        filename = match[1]
        if filename in seen:
            raise ValueError(f"Duplicate asset filename: {filename}")
        seen.add(filename)
        yield url, digest, filename


def latest_release(repo):
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    token = os.environ.get("GH_TOKEN")
    # Read credentials from stdin, not curl arguments or error messages.
    auth = ["--header", "@-"] if token else []
    response = subprocess.check_output(
        [
            *CURL,
            *auth,
            "--header",
            "Accept: application/vnd.github+json",
            "--header",
            "X-GitHub-Api-Version: 2022-11-28",
            url,
        ],
        input=f"Authorization: Bearer {token}\n".encode() if token else None,
    )
    return json.loads(response)


def resolve_latest(entry, extension):
    repo, prefix = entry["github_latest"], entry["asset_prefix"]
    if not isinstance(repo, str) or not re.fullmatch(REPO, repo):
        raise ValueError("github_latest must be a GitHub owner/repo, not a URL")
    if not isinstance(prefix, str) or not re.fullmatch(FILENAME, prefix):
        raise ValueError("asset_prefix must be a safe filename prefix")
    release = latest_release(repo)
    if (
        not isinstance(release, dict)
        or release.get("draft") is not False
        or release.get("prerelease") is not False
    ):
        raise ValueError(f"{repo}: expected a published stable release")
    tag, assets = release.get("tag_name"), release.get("assets")
    if (
        not isinstance(tag, str)
        or not re.fullmatch(r"[A-Za-z0-9_.+-]+", tag)
        or tag in {".", ".."}
    ):
        raise ValueError(f"{repo}: invalid release tag")
    if not isinstance(assets, list) or any(
        not isinstance(asset, dict) or not isinstance(asset.get("name"), str)
        for asset in assets
    ):
        raise ValueError(f"{repo}: invalid release asset list")
    matches = [
        asset
        for asset in assets
        if asset["name"].startswith(prefix) and asset["name"].endswith(f".{extension}")
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{repo}: expected one {prefix}*.{extension} asset; found {len(matches)}"
        )
    asset = matches[0]
    name, digest = asset["name"], asset.get("digest")
    url = f"https://github.com/{repo}/releases/download/{tag}/{name}"
    if (
        asset.get("state") != "uploaded"
        or not re.fullmatch(FILENAME, name)
        or asset.get("browser_download_url") != url
    ):
        raise ValueError(f"{repo}: invalid release asset name, state, or download URL")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError(f"{repo}: missing or invalid SHA-256 digest for {name}")
    return {"url": url, "sha256": digest.removeprefix("sha256:")}


def resolve(entries, extension):
    if not isinstance(entries, list):
        raise ValueError("Manifest entries must be an array")
    entries = [
        resolve_latest(entry, extension)
        if isinstance(entry, dict) and entry.keys() == {"github_latest", "asset_prefix"}
        else entry
        for entry in entries
    ]
    return sorted(validate(entries, extension))


def stage(directory, assets):
    directory.mkdir(parents=True, exist_ok=False)
    for url, expected, filename in assets:
        partial = directory / (filename + ".partial")
        subprocess.run(
            [
                *CURL,
                "--location",
                "--max-redirs",
                "5",
                "--output",
                str(partial),
                url,
            ],
            check=True,
        )
        with partial.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            partial.unlink()
            raise ValueError(f"SHA-256 mismatch for {filename}")
        partial.rename(directory / filename)


def main(kind, work):
    manifest = json.loads((ROOT / "sources.json").read_text())
    if not isinstance(manifest, dict) or manifest.keys() != FORMATS.keys():
        raise ValueError("Manifest must contain apt and yum arrays")
    extension, subdir = FORMATS[kind]
    assets = resolve(manifest[kind], extension)
    state = (
        json.dumps(
            {
                "fingerprint": os.environ.get("LINUX_GPG_FINGERPRINT", "").upper(),
                "assets": [{"url": url, "sha256": digest} for url, digest, _ in assets],
            },
            indent=2,
        )
        + "\n"
    )
    state_file = ROOT / f"{kind}-source-state.json"
    ready = False
    if not assets:
        print(f"No {kind} assets; leaving the published repository unchanged.")
    elif (
        os.environ.get("GITHUB_EVENT_NAME") == "schedule"
        and state_file.is_file()
        and state_file.read_text() == state
    ):
        print(f"{kind} sources and signing fingerprint unchanged; skipping rebuild.")
    else:
        stage(work / kind / subdir, assets)
        (work / state_file.name).write_text(state)
        ready = True
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a") as stream:
            stream.write(f"ready={str(ready).lower()}\n")


if __name__ == "__main__":
    try:
        main(sys.argv[1], Path(sys.argv[2]))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
