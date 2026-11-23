#!/usr/bin/env bash
# Only run inside the disposable buildserver container: --on-server removes sudo.
set -euo pipefail
exec > >(tee /output/build.log) 2>&1
source /etc/profile.d/bsenv.sh

export fdroidserver=/opt/metadata-fdroidserver
FDROID_SERVER_REVISION=fc2c86473e66a44fc641f403c338a8b2cccfad88
git init "$fdroidserver"
git -C "$fdroidserver" remote add origin https://gitlab.com/fdroid/fdroidserver.git
git -C "$fdroidserver" fetch --depth 1 origin "$FDROID_SERVER_REVISION"
git -C "$fdroidserver" checkout --detach FETCH_HEAD
export PATH="$fdroidserver:$PATH"
export PYTHONPATH="$fdroidserver:$fdroidserver/examples"
export PYTHONUNBUFFERED=true
export ANDROID_HOME=/opt/android-sdk
export GRADLE_USER_HOME=/home/vagrant/.gradle

apt-get update
apt-get install -y --no-install-recommends openjdk-21-jdk-headless
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
sdkmanager "platform-tools" "build-tools;35.0.0"

mkdir -p /work/{build,logs,repo,tmp,unsigned}
cp -r /input/metadata /input/srclibs /work/
cd /work
printf 'sdk_path: /opt/android-sdk\n' > config.yml

collect_results() {
    for path in metadata logs repo/status tmp; do
        if [ -e "/work/$path" ]; then
            cp -r "/work/$path" /output/
        fi
    done
}
trap collect_results EXIT

chown -R vagrant:vagrant /work "$fdroidserver"
run_as_builder() {
    sudo --user vagrant env \
        HOME=/home/vagrant PATH="$PATH" PYTHONPATH="$PYTHONPATH" \
        PYTHONUNBUFFERED="$PYTHONUNBUFFERED" JAVA_HOME="$JAVA_HOME" \
        ANDROID_HOME="$ANDROID_HOME" ANDROID_SDK_ROOT="$ANDROID_HOME" \
        GRADLE_USER_HOME="$GRADLE_USER_HOME" "$@"
}
run_as_builder /usr/bin/python3 "$fdroidserver/fdroid" \
    scanner --verbose --refresh --exit-code "$APP_ID:$VERSION_CODE"
run_as_builder /usr/bin/python3 "$fdroidserver/fdroid" \
    build --verbose --on-server --stop --test --refresh-scanner --scan-binary --no-tarball \
    "$APP_ID:$VERSION_CODE"
