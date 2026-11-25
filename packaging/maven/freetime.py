#!/usr/bin/env python3
"""Select a stable Freetime-Core tag or import its staged Maven publications."""

import argparse
import json
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from sync import (
    CHECKSUMS,
    HERE,
    LIMIT,
    METADATA,
    SEGMENT,
    checked_path,
    hashes,
    metadata_versions,
    sync,
    xml_root,
)

STATE = HERE / "freetime-core.tag"
OUTPUT = HERE.parents[1] / "maven"
VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
MODULES = ("Core", "Design", "Browser", "Donations", "FreetimeWarn", "Notifications")


def version_key(version):
    return tuple(map(int, version.split(".")))


def tag_key(tag):
    if not re.fullmatch("v" + VERSION, tag):
        raise ValueError(f"not a stable Freetime-Core tag: {tag!r}")
    return version_key(tag[1:])


def latest_tag(lines):
    tags = {}
    peeled = {}
    for line in lines:
        match = re.fullmatch(
            rf"([0-9a-f]{{40}})\trefs/tags/(v{VERSION})(\^\{{\}})?", line.rstrip("\n")
        )
        if match:
            commit, tag, dereferenced = match.groups()
            (peeled if dereferenced else tags)[tag] = commit
    if not tags:
        raise ValueError("no stable Freetime-Core tags found")
    tag = max(tags, key=tag_key)
    return tag, peeled.get(tag, tags[tag])


def already_published(tag, state):
    key = tag_key(tag)
    return state.exists() and tag_key(state.read_text(encoding="ascii").strip()) >= key


def merged_metadata(incoming, existing, artifact, version):
    if metadata_versions(incoming, artifact) != {version}:
        raise ValueError(f"staged metadata must list only {version}: {artifact}")
    if not existing.exists():
        return incoming.read_bytes(), {version}
    versions = metadata_versions(existing, artifact)
    if version in versions:
        return existing.read_bytes(), versions

    root = xml_root(existing)
    versioning = root.find("versioning")
    ET.SubElement(versioning.find("versions"), "version").text = version
    for field in ("latest", "release"):
        node = versioning.find(field)
        if node is None:
            ET.SubElement(versioning, field).text = version
        elif re.fullmatch(VERSION, node.text or "") and version_key(
            node.text
        ) < version_key(version):
            node.text = version
    updated = xml_root(incoming).findtext("versioning/lastUpdated")
    if updated and re.fullmatch(r"[0-9]{14}", updated):
        node = versioning.find("lastUpdated")
        if node is None:
            node = ET.SubElement(versioning, "lastUpdated")
        node.text = max(node.text or "", updated)
    ET.indent(root, space="  ")
    return ET.tostring(
        root, encoding="utf-8", xml_declaration=True
    ) + b"\n", versions | {version}


def import_release(staged, output, version):
    if not re.fullmatch(VERSION, version):
        raise ValueError("invalid stable release version")
    # Limit the artifact handoff to the producer's Maven namespace and selected version.
    artifacts = {}
    for path in staged.rglob("*"):
        relative = path.relative_to(staged)
        parts = relative.parts
        if (
            path.is_symlink()
            or parts[:2] != ("com", "freetime")
            and parts != ("com",)
            or any(not SEGMENT.fullmatch(part) for part in parts)
        ):
            raise ValueError(f"unexpected staged path: {relative}")
        if path.is_dir():
            if len(parts) > 4 or (len(parts) == 4 and parts[3] != version):
                raise ValueError(f"unexpected staged directory: {relative}")
            continue
        if not path.is_file() or not (0 < path.stat().st_size <= LIMIT):
            raise ValueError(f"invalid staged file: {relative}")
        if path.suffix.lstrip(".") in CHECKSUMS:
            continue  # The importer regenerates these from the actual bytes.
        if not (
            (len(parts) == 4 and path.name == METADATA)
            or (len(parts) == 5 and parts[3] == version)
        ):
            raise ValueError(f"unexpected staged file: {relative}")
        artifacts.setdefault(parts[2], set()).add(relative.as_posix())

    roots = set(MODULES)
    targets = {
        module + suffix for module in MODULES for suffix in ("-android", "-desktop")
    }
    # Unified releases attach target binaries to the root Maven coordinate.
    split = bool(targets & artifacts.keys())
    expected = roots | targets if split else roots
    if missing := expected - artifacts.keys():
        raise ValueError(f"missing staged publications: {', '.join(sorted(missing))}")

    # Feed the existing importer a local manifest so it performs its normal layout,
    # checksum and immutable-release checks before installing any files.
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        work = Path(temporary)
        pins = {}
        for name, files in sorted(artifacts.items()):
            artifact = f"com/freetime/{name}"
            metadata = f"{artifact}/{METADATA}"
            stem = f"{artifact}/{version}/{name}-{version}"
            binary = "aar" if name.endswith("-android") else "jar"
            required_files = (
                metadata,
                f"{stem}.pom",
                f"{stem}.module",
                f"{stem}.{binary}",
            )
            if not split and name in roots:
                required_files += (f"{stem}-android.aar", f"{stem}-desktop.jar")
            for required in required_files:
                if required not in files:
                    raise ValueError(f"missing staged file: {required}")
            merged, versions = merged_metadata(
                checked_path(staged, metadata),
                checked_path(output, metadata),
                artifact,
                version,
            )
            for relative in sorted(files):
                payload = work / relative
                payload.parent.mkdir(parents=True, exist_ok=True)
                if relative == metadata:
                    payload.write_bytes(merged)
                else:
                    shutil.copyfile(checked_path(staged, relative), payload)
                pins[relative] = hashes(payload)["sha256"]
            for old in versions - {version}:
                if not old or not SEGMENT.fullmatch(old):
                    raise ValueError(f"invalid existing version: {old!r}")
                pom = f"{artifact}/{old}/{name}-{old}.pom"
                pins[pom] = hashes(checked_path(output, pom))["sha256"]
        manifest = work / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "base_url": "https://github.com/FreetimeMaker/Freetime-Core",
                            "files": pins,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return sync(manifest, output, work)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("select", help="read git ls-remote --tags output from stdin")
    publish = commands.add_parser("publish", help="import a staged repository")
    publish.add_argument("tag")
    publish.add_argument("staged", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "select":
            tag, commit = latest_tag(sys.stdin)
            if already_published(tag, STATE):
                print(f"{tag}: already at or beyond this release", file=sys.stderr)
            else:
                print(f"tag={tag}\ncommit={commit}")
        elif not already_published(args.tag, STATE):
            count = import_release(args.staged, OUTPUT, args.tag[1:])
            STATE.write_text(args.tag + "\n", encoding="ascii")
            print(f"Freetime-Core {args.tag}: {count} changed Maven file(s)")
    except (OSError, ValueError, ET.ParseError) as exc:
        sys.exit(f"Freetime-Core update failed: {exc}")


if __name__ == "__main__":
    main()
