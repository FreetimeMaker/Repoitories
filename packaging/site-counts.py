"""Render package listings from the same snapshot that Pages will serve."""

import gzip
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
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
                apps[app_id] = names.get("en-US") or next(iter(names.values()), app_id)

    apt = set()
    for index in (site / "apt/dists").glob("*/main/binary-*/Packages.gz"):
        with gzip.open(index, "rt", encoding="utf-8") as stream:
            apt.update(
                line.split(":", 1)[1].strip()
                for line in stream
                if line.startswith("Package:")
            )

    yum = set()
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
        yum.update(
            entry.text for entry in root.findall("{*}package/{*}name") if entry.text
        )

    maven = site / "maven"
    artifacts = set()
    for pom in maven.rglob("*.pom"):
        *group, artifact, _, _ = pom.relative_to(maven).parts
        artifacts.add(f"{'.'.join(group)}:{artifact}")
    return {
        "fdroid": [(name, app_id) for app_id, name in apps.items()],
        "apt": [(name, "") for name in apt],
        "yum": [(name, "") for name in yum],
        "maven": [(name, "") for name in artifacts],
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
        for title, detail in sorted(
            entries, key=lambda entry: (entry[0].casefold(), entry)
        ):
            suffix = f"<small><code>{escape(detail)}</code></small>" if detail else ""
            rows.append(f"<li><span>{escape(title)}</span>{suffix}</li>")
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
