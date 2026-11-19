# APT and YUM repositories

## Package sources

`sources.json` contains `apt` and `yum` arrays. Entries may be mixed:

- **Latest release:** `github_latest` is a public GitHub `owner/repo`, and
  `asset_prefix` is a literal filename prefix. The resolver asks GitHub for
  the latest stable release and requires exactly one uploaded asset with that
  prefix and the format's extension (`.deb` or `.rpm`). It checks the exact
  tag-specific download URL and verifies the bytes against GitHub's asset
  SHA-256 digest. XMRiGUI-Linux and gemfury-cli use this mode.
- **Pinned:** `url` is the exact public GitHub release asset download URL,
  including its tag and filename, and `sha256` is 64 lowercase hex digits
  from `sha256sum` on the original asset. Use a pin if you need to retain a
  specific version or if a release does not provide a usable asset digest.

Only configure trusted upstreams: latest mode automatically publishes their
next matching release. Do not replace bytes at a published package version.
Filenames must be unique within each format.

A nonempty list is the complete set for that format: keep older entries if
they should remain available. An empty list is a no-op, not a request to
unpublish a repository. To retire a whole repository, clear the list and remove
its generated directory in a reviewed change. The build checks package metadata,
not filenames: DEBs must be `amd64` or `all`, and binary RPMs must be `x86_64`
or `noarch`. A failed download, checksum, architecture, or signature check
stops the update before Git publication.

## Shared signing configuration

Set these in **Settings → Secrets and variables → Actions** for both workflows:

| Kind     | Name                    | Value                                                                                                                                    |
| -------- | ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Secret   | `LINUX_GPG_PRIVATE_KEY` | ASCII-armored export of the dedicated repository secret key (`gpg --armor --export-secret-keys FINGERPRINT`), including the armor lines. |
| Secret   | `LINUX_GPG_PASSPHRASE`  | Key passphrase; omit only if the key is unprotected.                                                                                     |
| Variable | `LINUX_GPG_FINGERPRINT` | Full 40-hex-digit primary fingerprint of that certificate.                                                                               |

Use an RSA signing-capable key (RSA 3072 or stronger) for APT and RPM client
compatibility. The key and passphrase are used in an isolated temporary GnuPG
home; only the public certificate is published. Never commit a private key.
Both workflows export binary `public.gpg` at the site root; YUM also exports
the same certificate in ASCII armor at `yum/x86_64/public.asc` for RPM/DNF.
Coordinate key rotation across both repositories and distribute the new
fingerprint and key to clients before switching signatures. Run both workflows
with the new key so neither format is left serving stale signatures.

## Publishing

Changes to the manifest or Linux packaging scripts trigger both update
workflows on `main`. Both also run hourly (APT at :22 and YUM at :37 UTC), or you can dispatch
either workflow on `main` from the Actions tab. Hourly runs skip downloading,
building, and signing when the resolved URLs, digests, and signing fingerprint
match `apt-source-state.json` or `yum-source-state.json` in this directory.
Push and manual runs bypass that check; manually dispatch both workflows to
republish key material when the primary fingerprint has not changed.
Successful builds commit the generated `apt/` or `yum/` tree, `public.gpg`,
and that format's source state together to `main` using `GITHUB_TOKEN`. The repository's branch
rules must permit that push. Pushes are never forced; if another workflow
advances `main` before the push, rerun the failed workflow against current
`main`. The Pages workflow listens for successful Linux updates via `workflow_run`. A push by `GITHUB_TOKEN` does not trigger a
new push workflow. Check that Pages deployed the update before using it.

## Client setup

After the first successful deployment, verify the downloaded public key's
fingerprint against the maintainer's independently published fingerprint
(e.g. inspect it with `gpg --show-keys --with-fingerprint FILE`).

**APT:** Install the verified `https://repo.free-time.me/public.gpg` as
`/etc/apt/keyrings/freetime-repository.gpg` (readable by APT), and add this to
`/etc/apt/sources.list.d/freetime-repository.list`:

```text
deb [arch=amd64 signed-by=/etc/apt/keyrings/freetime-repository.gpg] https://repo.free-time.me/apt/ stable main
```

Run `sudo apt update`. The signed `Release`, `InRelease`, and `Release.gpg`
are under `apt/dists/stable/`; the indexes under
`apt/dists/stable/main/binary-amd64/` authenticate DEBs in `apt/pool/main/`.

**DNF/YUM:** Add the following to `/etc/yum.repos.d/freetime-repository.repo`. Verify the
armored key's fingerprint before accepting any key import prompt.

```ini
[Freetime Repository]
name=Freetime Repository
baseurl=https://repo.free-time.me/yum/x86_64/
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=https://repo.free-time.me/yum/x86_64/public.asc
```

Run `sudo dnf --refresh makecache`. DNF may prompt separately for the metadata
and package keys. The workflow re-signs each RPM, verifies its package
signature, then generates metadata from the signed RPMs in
`yum/x86_64/Packages/` and signs `yum/x86_64/repodata/repomd.xml` as
`repomd.xml.asc` in the same directory. Keep both checks enabled.
