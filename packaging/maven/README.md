# Maven repository updates

`Update Maven repository` runs hourly at :52 UTC, on manual dispatch from
`main`, and on pushes to `main` that change the updater or its workflow. It
checks out `main`, syncs to the root `maven/` directory, and commits and pushes
only changed Maven files and the Freetime-Core release marker. It does not force-push; if `main` advances in the
meantime, it fetches, rebases, and retries. If the rebase conflicts, rerun the job.
Branch rules must allow the Actions token to push.

## Freetime-Core releases

The workflow selects the numerically highest stable `vX.Y.Z` tag from
[`FreetimeMaker/Freetime-Core`](https://github.com/FreetimeMaker/Freetime-Core),
ignoring prereleases, and checks out its resolved commit. Only the latest tag
is built; intermediate releases are not backfilled. The workflow skips the
recorded tag and older tags before installing build tools. The marker
`packaging/maven/freetime-core.tag` is pushed with the Maven files, so a failed
build or push does not mark a release as published. Treat upstream tags as
immutable.

The build job has read-only repository access and does not persist checkout
credentials. It uses Temurin 25 (matching upstream CI), installs the Android
platform from the tagged `gradle/libs.versions.toml` (`compileSdk = "37"` in
`v4.0.0`), and runs `./gradlew stagePublications -PreleaseVersion=X.Y.Z` using
Bash. Only `build/public-maven/` goes to the write-enabled job, which does not
check out or run upstream code. It validates that the root, Android, and desktop
publications are present, preserves existing versioned files, merges artifact
metadata, and regenerates checksums.

The checksum-pinned HTTPS manifest below still syncs when the upstream tag is
unchanged or its build fails. An empty manifest is a no-op for that sync. Keep
manifest sources separate from the automatically managed Freetime-Core
coordinates to avoid conflicting metadata pins.

## Published HTTPS repositories

Edit `sources.json` in a reviewed change. The top-level `sources` array takes
objects with two fields:

- `base_url`: the direct public HTTPS repository root; no credentials,
  redirects, query strings, or fragments.
- `files`: an object mapping each repository-relative path to the lowercase
  SHA-256 of that exact file. Derive pins from a trusted release, e.g. with
  `sha256sum`, and only mirror artifacts you have permission to redistribute.

Use Maven paths: `group/as/path/artifact/version/artifact-version.pom` and the
same layout for the main binary, classifiers, Gradle `.module` files, and
signatures as applicable. Include `group/as/path/artifact/maven-metadata.xml`
with exactly the release versions listed in the manifest for that artifact.
A POM is required for every version (POM-only publications such as BOMs are
supported). Include all needed publication files; the importer does not resolve
transitive dependencies or infer missing artifacts. Do not list checksum
sidecars; SHA-1, SHA-256, SHA-512, and MD5 sidecars are derived from verified
bytes. Snapshots and group-level plugin discovery metadata are not supported.

When adding a version, retain existing releases in the manifest and update the
metadata pin. If upstream metadata lists versions you do not intend to mirror,
publish a curated repository with matching metadata instead. The updater never
prunes files or replaces a versioned file with different bytes. Matching local
files are reused, so metadata changes and new versions are picked up by changing
pins, not by following a mutable `latest` URL or discovering new releases.

## Gradle `maven-publish`

In the **trusted producer project**, keep its real `MavenPublication` definitions
and add a file-backed publishing repository. For example, in `build.gradle.kts`:

```kotlin
publishing {
    repositories {
        maven {
            name = "Staging"
            url = uri(layout.buildDirectory.dir("maven-staging").get().asFile)
        }
    }
}
```

Run `./gradlew publishAllPublicationsToStagingRepository` from the producer
project. Use the resulting `build/maven-staging/`, not `publishToMavenLocal`
(which writes local-specific metadata). Retain earlier release files and
repository metadata in staging when publishing additional versions. For a
multi-project build, configure a shared staging repository if needed.

For other producers, serve that staged Maven tree at a trusted HTTPS URL and
list its files and pins in `sources.json` as above. To test or ingest the same publication directly from disk,
run from this repository root:

```sh
python3 packaging/maven/sync.py --local-repository /path/to/producer/build/maven-staging
```

The override reads all manifest paths from that one directory, with the same
validation. Add `--manifest /path/to/sources.json` for a separate manifest and
`--output /path/to/existing-parent/maven` to avoid modifying the checkout. The
local command does not run Git.

## Serving the output

`maven/` on `main` is the persisted repository. For public consumption the raw
GitHub branch URL is `https://raw.githubusercontent.com/FreetimeMaker/Repoitories/main/maven/`.
The updater does not deploy Pages. Pushes using `GITHUB_TOKEN` do not trigger
other push workflows; if using the Pages endpoint, run the existing Pages
workflow separately to deploy the updated branch.

Run the local tests with `python3 -B -m unittest discover -s packaging/maven`.
The Gradle integration test is skipped when `gradle` is not installed.
