# fdroid

This repository hosts an [F-Droid](https://f-droid.org/) repo for my apps. This allows you to install and update apps very easily.

### Apps

<!-- This table is auto-generated. Do not edit -->

| Icon                                                                                                                                                            | Name                                                                              | Description                                                                  | Version    |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ---------- |
| <a href="https://github.com/FreetimeMaker/Dualist"><img src="repo/icons/Dualist.png" alt="Dualist icon" width="36px" height="36px"></a>                         | [**Dualist**](https://github.com/FreetimeMaker/Dualist)                           | Modern, adaptive, and offline-first To-Do List app.                          | 1.1.8 (10) |
| <a href="https://github.com/FreetimeMaker/GeoWeather"><img src="repo/icons/GeoWeather.png" alt="GeoWeather icon" width="36px" height="36px"></a>                | [**GeoWeather**](https://github.com/FreetimeMaker/GeoWeather)                     | Modern weather app with 16-day forecast for multiple cities                  | 4.7.4 (93) |
| <a href="https://github.com/FreetimeMaker/Luma-Store-Android"><img src="repo/icons/Luma-Store.png" alt="Luma Store Icon" width="36px" height="36px"></a>        | [**Luma Store**](https://github.com/FreetimeMaker/Luma-Store-Android)             | Discover, install and update apps from Luma Store and optional repositories. | 4.4.3 (33) |
| <a href="https://github.com/FreetimeMaker/SuperSMP-Companion-App"><img src="repo/icons/SSMPC.png" alt="SuperSMP Companion icon" width="36px" height="36px"></a> | [**SuperSMP Companion**](https://github.com/FreetimeMaker/SuperSMP-Companion-App) | Vote, shop & explore SuperSMP anywhere! Companion app for server features    | 2.0.1 (23) |

<!-- end apps table -->

### Build-tested metadata updates

Automatic updates are staged as workflow artifacts first. Before metadata is
committed to `main`, `test-updates` builds every new or changed build recipe and
the candidate current version in the official F-Droid buildserver container.
Like GeoWeather and Luma Store CI, it runs `fdroid scanner --verbose --refresh
--exit-code`, followed by `fdroid build --verbose --on-server --stop --test
--refresh-scanner --scan-binary --no-tarball`.
Scanner errors, failed builds, missing APKs and reference-binary comparison
failures block the update. No scanner bypass or `--force` is used. A failure
blocks the entire update batch; metadata on `main` stays unchanged.

The job runs on GitHub-hosted `ubuntu-latest` with Docker image
`registry.gitlab.com/fdroid/fdroidserver:buildserver-trixie`. No self-hosted
runner, Vagrant box, KVM setup or additional repository variables are needed.
The image digest is recorded in the `fdroid-build-results` artifact, together
with logs and unsigned APKs. Each version gets a fresh disposable container.
The tooling revision and Java/build-tools setup match GeoWeather and Luma Store.

Only candidate metadata, app metadata assets and srclib recipes are mounted
read-only into the container. Signing keys and checkout credentials are not
exposed. Unlike pre-release app CI, these release checks retain the real
metadata's `Binaries` field to verify the published reference APK when specified.
A failed test blocks the batch. This is not a submission to F-Droid's official
build infrastructure.

### How to use

1. At first, you should [install the F-Droid app](https://f-droid.org/), it's an alternative app store for Android.
2. Now you can copy the following [link](https://repo.free-time.me/fdroid/repo), then add this repository to your F-Droid client:

   ```
   https://repo.free-time.me/fdroid/repo
   ```

   Alternatively, you can also scan this QR code:

    <p align="center">
      <img src="repo/index.png?raw=true" alt="F-Droid repo QR code"/>
    </p>

3. Open the link in F-Droid. It will ask you to add the repository. Everything should already be filled in correctly, so just press "OK".
4. You can now install my apps, e.g. start by searching for "Notality" in the F-Droid client.

Please note that some apps published here might contain [Anti-Features](https://f-droid.org/en/docs/Anti-Features/). If you can't find an app by searching for it, you can go to settings and enable "Include anti-feature apps".

### Website

The site is built with [Jekyll](https://jekyllrb.com/). The `index.html` generated
by `fdroidserver` (in `repo/`) is served **directly and unmodified** at `/repo/`,
together with its relative assets (`index.css`, `index.png`, `icons/`, ...). No
wrapper, layout or plugin is needed.

To run it locally:

```bash
bundle install
bundle exec jekyll serve --livereload
```

To build the static site into `_site/`:

```bash
bundle exec jekyll build
```

The site is deployed with **GitHub Pages** (custom domain via `CNAME`). A GitHub
Actions workflow (`.github/workflows/jekyll.yml`) builds Jekyll and publishes
`_site/` automatically on every push to `main`.

Note: This is a Jekyll project now. **Vercel** cannot build it (it expected the
previous Next.js setup with `package.json`/`pages/`), so Vercel should be disabled
for the domain; GitHub Pages is the host.

### [License](../LICENSE)

The license is for the files in this repository, _except_ those in the `fdroid` directory. These files _might_ be licensed differently; you can use an F-Droid client to get the details for each app.

### CI build toolchains

The update workflow installs Eclipse Temurin JDKs for Java 11 and 16–25 and
exposes them to Gradle Java toolchains. Temurin does not publish Java 12–15.
The build launcher defaults to Java 17;
projects can select their compiler toolchain in Gradle or specify Gradle daemon
JVM criteria where supported by their wrapper version.

Before building, the workflow accepts Android SDK licenses and installs Android platforms listed by `sdkmanager` from `platforms;android-24`
through `platforms;android-37.2`, inclusive. Other package families (such as
build tools, NDKs, and emulator images) are not installed in full. To preinstall
additional packages, set the repository Actions variable
`FDROID_ANDROID_SDK_PACKAGES` to one `sdkmanager` package ID per line
(e.g. `build-tools;35.0.0`).

GitHub Actions caches JDK installations, Gradle and pip downloads, and Android
platforms that are not preinstalled on the runner. The SDK cache is saved before
the build, with a two-minute timeout and a 1 GiB input limit. SDK tools and NDKs
are not included in this cache. Cache misses still run the usual installation steps.
Signing keys, credentials, local Gradle
configuration, and built APKs are not cached. GitHub may evict caches to stay
within the repository's cache storage limit.

The runner installs the native build tools (compiler, Make, CMake, Ninja, and
pkg-config) before invoking F-Droid. F-Droid uses the selected recipe for
source libraries and submodules; Gradle resolves plugins and direct and
transitive dependencies using the selected revision's repository declarations.
Cached downloads are reused, but the build is not forced offline. If dependency
resolution fails, the build stops before signing and index generation.
