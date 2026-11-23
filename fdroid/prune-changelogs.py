#!/usr/bin/env python3
"""Keep the three newest versioned changelogs per app and locale."""

from pathlib import Path


def prune(metadata=Path("metadata"), app=None):
    apps = [metadata / app] if app else metadata.iterdir()
    for directory in apps:
        if not directory.is_dir():
            continue
        for changelogs in directory.glob("*/changelogs"):
            versions = sorted(
                (
                    path
                    for path in changelogs.glob("*.txt")
                    if path.is_file() and path.stem.isascii() and path.stem.isdecimal()
                ),
                key=lambda path: (int(path.stem), path.name),
                reverse=True,
            )
            for path in versions[3:]:
                path.unlink()
                print(f"Removed old changelog: {path}")


if __name__ == "__main__":
    import sys

    prune(app=sys.argv[1] if len(sys.argv) > 1 else None)
