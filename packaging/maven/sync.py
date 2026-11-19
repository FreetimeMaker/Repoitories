#!/usr/bin/env python3
"""Import reviewed, checksum-pinned Maven releases without executing them."""

import argparse
import hashlib
import json
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

HERE = Path(__file__).resolve().parent
METADATA = "maven-metadata.xml"
CHECKSUMS = ("sha1", "sha256", "sha512", "md5")
LIMIT = 95 * 1024 * 1024  # Stay below GitHub's per-file limit.
SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.+-]*\Z")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("source redirected; use its final HTTPS repository URL")


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate manifest key: {key}")
        result[key] = value
    return result


def checked_path(root, relative):
    path = root
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError(f"not a regular directory: {path}")
    for part in relative.split("/"):
        if path.exists() and not path.is_dir():
            raise ValueError(f"not a directory: {path}")
        path = path / part
        if path.is_symlink():
            raise ValueError(f"symlink not allowed: {path}")
    if path.exists() and not path.is_file():
        raise ValueError(f"not a regular file: {path}")
    return path


def plan(manifest):
    document = json.loads(
        manifest.read_text(encoding="utf-8"), object_pairs_hook=unique_keys
    )
    if (
        not isinstance(document, dict)
        or set(document) != {"sources"}
        or not isinstance(document["sources"], list)
    ):
        raise ValueError("manifest must contain a sources array")
    files = {}
    artifacts = {}
    for source in document["sources"]:
        if not isinstance(source, dict) or set(source) != {"base_url", "files"}:
            raise ValueError("each source needs exactly base_url and files")
        base = source["base_url"]
        if not isinstance(base, str) or not re.fullmatch(
            r"https://[A-Za-z0-9.-]+(?::[0-9]+)?(?:/[A-Za-z0-9_.+~-]+)*/?", base
        ):
            raise ValueError(
                "base_url must be a direct HTTPS URL without credentials, query or fragment"
            )
        if any(part in (".", "..") for part in urlsplit(base).path.split("/")):
            raise ValueError("base_url contains a relative path segment")
        entries = source["files"]
        if not isinstance(entries, dict) or not entries:
            raise ValueError("each source needs a nonempty path-to-SHA-256 map")
        for relative, digest in entries.items():
            parts = relative.split("/")
            if (
                len(parts) < 3
                or any(not SEGMENT.fullmatch(p) for p in parts)
                or relative.endswith(tuple("." + a for a in CHECKSUMS))
            ):
                raise ValueError(f"invalid Maven path: {relative}")
            if (
                relative in files
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise ValueError(f"duplicate path or invalid SHA-256: {relative}")
            if parts[-1] == METADATA:
                artifact = "/".join(parts[:-1])
                artifacts.setdefault(artifact, set())
            else:
                if len(parts) < 4:
                    raise ValueError(f"invalid release path: {relative}")
                artifact_id, version, name = parts[-3:]
                stem = f"{artifact_id}-{version}"
                if version.upper().endswith("-SNAPSHOT") or not re.fullmatch(
                    re.escape(stem) + r"(?:-[A-Za-z0-9_+.-]+)?\.[A-Za-z0-9_+.-]+", name
                ):
                    raise ValueError(f"not a Maven release file: {relative}")
                artifact = "/".join(parts[:-2])
                artifacts.setdefault(artifact, set()).add(version)
            files[relative] = (base.rstrip("/") + "/" + relative, digest)
    for artifact, versions in artifacts.items():
        if not versions or f"{artifact}/{METADATA}" not in files:
            raise ValueError(f"missing versions or metadata for {artifact}")
        for version in versions:
            name = artifact.rsplit("/", 1)[-1]
            if f"{artifact}/{version}/{name}-{version}.pom" not in files:
                raise ValueError(f"missing POM for {artifact}:{version}")
    return files, artifacts


def hashes(path):
    digests = {name: hashlib.new(name, usedforsecurity=False) for name in CHECKSUMS}
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            for digest in digests.values():
                digest.update(block)
    return {name: digest.hexdigest() for name, digest in digests.items()}


def xml_root(path):
    text = path.read_text(encoding="utf-8-sig")
    if "<!DOCTYPE" in text:
        raise ValueError(f"DOCTYPE not allowed: {path.name}")
    return ET.fromstring(text)


def metadata_versions(path, artifact):
    root = xml_root(path)
    group, name = artifact.rsplit("/", 1)
    versions = {node.text for node in root.findall("versioning/versions/version")}
    if (
        root.tag != "metadata"
        or root.findtext("groupId") != group.replace("/", ".")
        or root.findtext("artifactId") != name
        or not versions
    ):
        raise ValueError(f"invalid metadata for {artifact}")
    for field in ("latest", "release"):
        value = root.findtext(f"versioning/{field}")
        if value is not None and value not in versions:
            raise ValueError(f"metadata {field} is not a listed version for {artifact}")
    return versions


def sync(manifest, output, local=None):
    files, artifacts = plan(manifest)
    if not files:
        return 0
    opener = build_opener(NoRedirect())
    pending = {}
    with tempfile.TemporaryDirectory(dir=output.parent) as work:
        staging = Path(work)
        for index, (relative, (url, expected)) in enumerate(sorted(files.items())):
            target = checked_path(output, relative)
            staged = staging / str(index)
            if target.exists() and hashes(target)["sha256"] == expected:
                payload = target
            else:
                if target.exists() and target.name != METADATA:
                    raise ValueError(
                        f"refusing to overwrite a released file: {relative}"
                    )
                origin = (
                    checked_path(local, relative).open("rb")
                    if local is not None
                    else opener.open(url, timeout=30)
                )
                with origin as stream, staged.open("wb") as writer:
                    remaining = LIMIT
                    while block := stream.read(1024 * 1024):
                        remaining -= len(block)
                        if remaining < 0:
                            raise ValueError(f"file exceeds size limit: {relative}")
                        writer.write(block)
                payload = staged
                pending[target] = staged
            digests = hashes(payload)
            if not payload.stat().st_size or digests["sha256"] != expected:
                raise ValueError(f"empty file or SHA-256 mismatch: {relative}")
            if target.name == METADATA:
                artifact = relative.rsplit("/", 1)[0]
                versions = metadata_versions(payload, artifact)
                if versions != artifacts[artifact] or (
                    target.exists()
                    and not metadata_versions(target, artifact) <= versions
                ):
                    raise ValueError(
                        f"metadata versions do not match the manifest or would drop a previous release: {artifact}"
                    )
            elif target.suffix == ".pom":
                if xml_root(payload).tag not in (
                    "project",
                    "{http://maven.apache.org/POM/4.0.0}project",
                ):
                    raise ValueError(f"not a Maven POM: {relative}")
            for algorithm, digest in digests.items():
                sidecar = checked_path(output, f"{relative}.{algorithm}")
                data = digest.encode("ascii")
                if not sidecar.exists() or sidecar.read_bytes() != data:
                    replacement = staging / f"{index}.{algorithm}"
                    replacement.write_bytes(data)
                    pending[sidecar] = replacement
        # Install version files before metadata that advertises them.
        for target, staged in sorted(
            pending.items(), key=lambda pair: pair[0].name.startswith(METADATA)
        ):
            target.parent.mkdir(parents=True, exist_ok=True)
            staged.replace(target)
    return len(pending)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=HERE / "sources.json")
    parser.add_argument("--output", type=Path, default=HERE.parents[1] / "maven")
    parser.add_argument(
        "--local-repository",
        type=Path,
        help="read manifest paths from a local Maven repository instead of HTTPS",
    )
    args = parser.parse_args()
    try:
        count = sync(args.manifest, args.output, args.local_repository)
    except (OSError, ValueError, ET.ParseError) as exc:
        sys.exit(f"Maven sync failed: {exc}")
    print(f"Maven sync: {count} changed file(s)")


if __name__ == "__main__":
    main()
