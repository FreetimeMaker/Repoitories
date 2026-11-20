# Freetime Repository

This Repository is Sponsored by 

[![Sponsor](https://readme.cash/i/2cn66a5gez.svg)](https://readme.cash/c/2cn66a5gez)

GitHub Actions publishes one static site from the package trees on `main`.
An update to one package format does not replace the other formats.

| Format         | Endpoint                                | Setup and publishing                                                        |
| -------------- | --------------------------------------- | --------------------------------------------------------------------------- |
| F-Droid        | `https://repo.free-time.me/fdroid/repo` | [F-Droid apps and client setup](fdroid/README.md)                           |
| APT            | `https://repo.free-time.me/apt`         | [Linux publishing and client setup](packaging/linux/README.md#client-setup) |
| YUM / DNF      | `https://repo.free-time.me/yum/x86_64`  | [Linux publishing and client setup](packaging/linux/README.md#client-setup) |
| Maven / Gradle | `https://repo.free-time.me/maven`       | [Source sync and Gradle publishing](packaging/maven/README.md)              |

## First deployment

1. In **Settings → Pages**, set the source to **GitHub Actions**. Configure
   `repo.free-time.me` as the custom domain and point its DNS CNAME to
   `freetimemaker.github.io`. Enable HTTPS once GitHub provisions the certificate.
2. Keep the existing F-Droid keystores and Actions secrets. On `main`, run
   **Update F-Droid repository** to regenerate and sign the main and archive
   indexes. Deployment rejects indexes that still advertise the old domain.
   Existing clients need to add the new URL; the old hostname is not redirected
   by this project. The F-Droid signing fingerprint is unchanged.
3. Configure the [Linux signing key](packaging/linux/README.md). APT and YUM
   fetch packages from the latest GitHub releases of XMRiGUI-Linux and
   gemfury-cli. The [Maven workflow](packaging/maven/README.md) builds
   Freetime-Core from its highest stable version tag. Each workflow checks
   for updates hourly and can also be run manually from `main`.
4. Each successful update run triggers **Deploy Freetime Repository**. You can
   also run it manually. Branch rules must let the update workflows push to
   `main`. Updates automatically fetch, rebase, and retry if `main` advances.
   If generated files conflict, rerun the update against the new `main`.

The deploy uses only committed public package paths and never includes local
private keys or F-Droid build configuration. GitHub Pages has a 1 GB published
site limit; move package hosting to object storage before the combined tree
outgrows it.
