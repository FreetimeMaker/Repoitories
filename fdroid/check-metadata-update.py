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


def main():
    app, candidate = sys.argv[1:]
    previous = subprocess.check_output(
        ["git", "--no-pager", "show", f"HEAD:fdroid/metadata/{app}.yml"],
        text=True,
        encoding="utf-8",
    )
    try:
        validate(
            yaml.safe_load(previous),
            yaml.safe_load(Path(candidate).read_text(encoding="utf-8")),
        )
    except ValueError as error:
        sys.exit(f"{app}: {error}")


if __name__ == "__main__":
    main()
