"""Render package listings from the same snapshot that Pages will serve."""

import gzip
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from html import escape
from pathlib import Path


def package_catalog(site):
    index = site / "fdroid/repo/index-v2.json"
    apps = {}
    if index.is_file():
        for app_id, app in json.loads(index.read_text(encoding="utf-8"))[
            "packages"
        ].items():
            if app.get("versions"):
                names = app.get("metadata", {}).get("name", {})
                name = names.get("en-US") or next(iter(names.values()), app_id)
                versions = set()
                for version in app["versions"].values():
                    manifest = version["manifest"]
                    code = manifest["versionCode"]
                    title = manifest.get("versionName")
                    versions.add((code, f"{title} ({code})" if title else str(code)))
                apps[app_id] = (name, [title for _, title in sorted(versions, reverse=True)])

    apt = defaultdict(set)
    for index in (site / "apt/dists").glob("*/main/binary-*/Packages.gz"):
        with gzip.open(index, "rt", encoding="utf-8") as stream:
            for stanza in stream.read().split("\n\n"):
                fields = dict(line.split(": ", 1) for line in stanza.splitlines()
                              if line.startswith(("Package: ", "Version: ", "Architecture: ")))
                if fields:
                    apt[fields["Package"]].add(f"{fields['Version']} · {fields['Architecture']}")

    yum = defaultdict(set)
    for index in (site / "yum").glob("*/repodata/repomd.xml"):
        location = ET.parse(index).find("{*}data[@type='primary']/{*}location")
        if location is None:
            raise ValueError(f"No primary RPM index in {index}")
        primary = index.parent.parent / location.attrib["href"]
        if primary.suffix == ".zst":
            xml = subprocess.check_output(["zstd", "-dc", "--", str(primary)])
            root = ET.fromstring(xml)
        elif primary.suffix == ".gz":
            with gzip.open(primary, "rb") as stream:
                root = ET.parse(stream).getroot()
        else:
            raise ValueError(f"Unsupported RPM primary index format: {primary}")
        for package in root.findall("{*}package"):
            name = package.findtext("{*}name")
            arch = package.findtext("{*}arch")
            version = package.find("{*}version").attrib
            epoch = version.get("epoch", "0")
            prefix = f"{epoch}:" if epoch != "0" else ""
            yum[name].add(f"{prefix}{version['ver']}-{version['rel']} · {arch}")

    maven = site / "maven"
    artifacts = defaultdict(set)
    for pom in maven.rglob("*.pom"):
        *group, artifact, version, _ = pom.relative_to(maven).parts
        artifacts[f"{'.'.join(group)}:{artifact}"].add(version)
    return {
        "fdroid": [(name, app_id, versions) for app_id, (name, versions) in apps.items()],
        **{
            kind: [(name, "", sorted(versions)) for name, versions in packages.items()]
            for kind, packages in (("apt", apt), ("yum", yum), ("maven", artifacts))
        },
    }



def render(site):
    page = site / "index.html"
    html = page.read_text(encoding="utf-8")
    for name, entries in package_catalog(site).items():
        count = len(entries)
        label = {"fdroid": "app", "maven": "artifact"}.get(name, "package")
        if count != 1:
            label += "s"
        html, matches = re.subn(
            rf'(<p class="eyebrow" data-count="{name}">)[^<]*(</p>)',
            rf"\g<1>{count} {label} available\g<2>",
            html,
        )
        if matches != 1:
            raise ValueError(f"Expected one package count placeholder for {name}")
        rows = []
        for title, detail, versions in sorted(
            entries, key=lambda entry: (entry[0].casefold(), entry)
        ):
            suffix = f"<small><code>{escape(detail)}</code></small>" if detail else ""
            releases = ", ".join(escape(version) for version in versions)
            rows.append(
                f"<li><span>{escape(title)}</span>{suffix}"
                f"<small>{releases}</small></li>"
            )
        listing = (
            "<ul>" + "".join(rows) + "</ul>"
            if rows
            else "<p>Nothing published yet.</p>"
        )
        marker = f"<!-- catalog:{name} -->"
        if html.count(marker) != 1:
            raise ValueError(f"Expected one package list placeholder for {name}")
        html = html.replace(marker, listing)
    page.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    render(Path(sys.argv[1]))
