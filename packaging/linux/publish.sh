#!/usr/bin/env bash
set -euo pipefail
kind=$1
work=$2
[[ $kind == apt || $kind == yum ]]
[[ ${GITHUB_REF:-} == refs/heads/main ]]
test -s "$work/public.gpg"

state="$kind-source-state.json"
test -s "$work/$state"
paths=("$kind/" public.gpg "packaging/linux/$state")
rsync -a --delete -- "$work/$kind/" "$kind/"
install -m 644 -- "$work/public.gpg" public.gpg
install -m 644 -- "$work/$state" "packaging/linux/$state"
git add -A -- "${paths[@]}"
if ! git diff --cached --quiet -- "${paths[@]}"; then
    git -c user.name='github-actions[bot]' \
        -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
        commit -m "Update ${kind^^} repository" -- "${paths[@]}"
    git push origin HEAD:refs/heads/main
fi
