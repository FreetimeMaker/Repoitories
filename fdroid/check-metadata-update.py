#!/usr/bin/env python3
"""Reject metadata updates that introduce historical build versions."""

import subprocess
import sys
from pathlib import Path

import yaml


def validate(previous, updated):
    old_codes = {int(build["versionCode"]) for build in previous.get("Builds", [])}
    current = int(previous["CurrentVersionCode"])
    newest = max(old_codes | {current})
    if int(updated["CurrentVersionCode"]) < current:
        raise ValueError("CurrentVersionCode must not move backwards")
    for build in updated.get("Builds", []):
        code = int(build["versionCode"])
        if code not in old_codes and code <= newest:
            raise ValueError(
                f"Cannot add historical build {code}; latest known code is {newest}"
            )


# checkupdates has already fetched the app repository; inspect the candidate ref,
# not whichever tag it happened to leave checked out.
FORBIDDEN_MAVEN = r"https?://repo[.]free-time[.]me/maven([/[:space:]\"'(){}?#]|$)"


def blocked_builds(app, previous, updated):
    known = {int(build["versionCode"]): build for build in previous.get("Builds", [])}
    current = int(updated["CurrentVersionCode"])
    for build in updated.get("Builds", []):
        code = int(build["versionCode"])
        if build.get("disable") or (code != current and known.get(code) == build):
            continue
        ref = build["commit"]
        checkout = Path("build") / app
        commit = subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "--verify", "--end-of-options", ref + "^{commit}"],
            text=True,
        ).strip()
        result = subprocess.run(
            ["git", "-C", str(checkout), "grep", "-iE", "-l", "-e", FORBIDDEN_MAVEN,
             commit, "--", "*.gradle", "*.gradle.kts", "*.gradle.properties", "gradle.properties", "*.toml"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            yield code
        elif result.returncode != 1:
            raise ValueError(f"Could not inspect build {code}: {result.stderr.strip()}")


def main():
    app, candidate = sys.argv[1:]
    previous = subprocess.check_output(
        ["git", "--no-pager", "show", f"HEAD:fdroid/metadata/{app}.yml"],
        text=True,
        encoding="utf-8",
    )
    try:
        previous = yaml.safe_load(previous)
        updated = yaml.safe_load(Path(candidate).read_text(encoding="utf-8"))
        validate(previous, updated)
        if previous != updated and (blocked := list(blocked_builds(app, previous, updated))):
            print(f"{app}: skipping update; build(s) {blocked} reference repo.free-time.me/maven", file=sys.stderr)
            sys.exit(3)
    except ValueError as error:
        sys.exit(f"{app}: {error}")


if __name__ == "__main__":
    main()
