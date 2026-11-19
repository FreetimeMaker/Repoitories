#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
kind=$1
work=$(realpath "$2")
[[ $kind == apt || $kind == yum ]]
cd "$work/$kind"
shopt -s nullglob

if [[ $kind == apt ]]; then
    packages=(pool/main/*.deb)
else
    cd x86_64
    packages=(Packages/*.rpm)
fi
((${#packages[@]} > 0)) || { echo "No staged $kind packages" >&2; exit 1; }
for package in "${packages[@]}"; do
    if [[ $kind == apt ]]; then
        arch=$(dpkg-deb --field "$package" Architecture)
        [[ $arch == amd64 || $arch == all ]] && continue
        expected='amd64 or all'
    else
        arch=$(rpm -qp --qf '%|SOURCEPACKAGE?{source}:{%{ARCH}}|' "$package")
        [[ $arch == x86_64 || $arch == noarch ]] && continue
        expected='x86_64 or noarch'
    fi
    printf '%s: expected architecture %s, got %s\n' "$package" "$expected" "$arch" >&2
    exit 1
done

: "${LINUX_GPG_PRIVATE_KEY:?Set the armored private key secret}"
fingerprint=${LINUX_GPG_FINGERPRINT^^}
[[ $fingerprint =~ ^[0-9A-F]{40}$ ]] || { echo 'Expected a 40-digit key fingerprint' >&2; exit 1; }
private=$(mktemp -d /tmp/linux-sign.XXXXXXXX)
export GNUPGHOME="$private/gnupg"
trap 'gpgconf --kill gpg-agent || true; rm -rf -- "$private"' EXIT
install -d -m 700 "$GNUPGHOME"

printf '%s\n' "$LINUX_GPG_PRIVATE_KEY" | gpg --batch --import
(umask 077; printf '%s\n' "${LINUX_GPG_PASSPHRASE:-}" > "$private/passphrase")
unset LINUX_GPG_PRIVATE_KEY LINUX_GPG_PASSPHRASE
# A single repository certificate is exported in the native formats of APT and RPM.
gpg --batch --export "$fingerprint" > "$work/public.gpg"
test -s "$work/public.gpg"
sign=(gpg --batch --pinentry-mode loopback --passphrase-file "$private/passphrase"
      --local-user "$fingerprint" --digest-algo SHA256)
verify=(gpgv --keyring "$work/public.gpg")

if [[ $kind == apt ]]; then
    suite=dists/stable
    index=$suite/main/binary-amd64
    mkdir -p "$index"
    # Scan from the repository root so Filename entries start with pool/main/.
    dpkg-scanpackages --multiversion pool/main /dev/null > "$index/Packages"
    test -s "$index/Packages"
    gzip -n -c "$index/Packages" > "$index/Packages.gz"
    cd "$suite"
    apt-ftparchive -o APT::FTPArchive::Release::Origin=Freetime \
        -o APT::FTPArchive::Release::Label=Freetime \
        -o APT::FTPArchive::Release::Suite=stable \
        -o APT::FTPArchive::Release::Codename=stable \
        -o APT::FTPArchive::Release::Components=main \
        -o APT::FTPArchive::Release::Architectures=amd64 release . > "$private/Release"
    mv "$private/Release" Release
    "${sign[@]}" --output InRelease --clearsign Release
    "${sign[@]}" --armor --output Release.gpg --detach-sign Release
    "${verify[@]}" InRelease
    "${verify[@]}" Release.gpg Release
else
    gpg --batch --armor --export "$fingerprint" > public.asc
    mkdir "$private/rpmdb"
    rpmkeys --dbpath "$private/rpmdb" --import public.asc
    for package in "${packages[@]}"; do
        rpmsign --define "_gpg_name $fingerprint" --define '_gpg_digest_algo sha256' \
            --define "_gpg_sign_cmd_extra_args --batch --pinentry-mode loopback --passphrase-file $private/passphrase" \
            --resign "$package"
        result=$(rpmkeys --dbpath "$private/rpmdb" --checksig --verbose "$package")
        # checksig alone can succeed on a package that has digests but no signature.
        grep -Eiq '[[:space:]]signature([[:space:],:]|$).*: OK[[:space:]]*$' <<< "$result" || { echo "$result" >&2; exit 1; }
    done
    createrepo_c --checksum sha256 .
    "${sign[@]}" --armor --output repodata/repomd.xml.asc --detach-sign repodata/repomd.xml
    "${verify[@]}" repodata/repomd.xml.asc repodata/repomd.xml
fi
