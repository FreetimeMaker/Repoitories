#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

for attempt in 1 2 3; do
    if result=$(git push --porcelain origin HEAD:refs/heads/main); then
        printf '%s\n' "$result"
        exit 0
    fi
    printf '%s\n' "$result" >&2
    if ! grep -Eq '^!.*\[rejected\] \((fetch first|non-fast-forward)\)$' <<< "$result"; then
        exit 1
    fi
    if [[ $attempt == 3 ]]; then
        echo 'main advanced again; retry limit reached.' >&2
        exit 1
    fi

    echo 'main advanced; fetching and rebasing before retrying.'
    fetch_options=(--no-tags)
    if [[ $(git rev-parse --is-shallow-repository) == true ]]; then
        fetch_options+=(--unshallow)
    fi
    git fetch "${fetch_options[@]}" origin refs/heads/main
    if ! GIT_EDITOR=true git -c user.name='github-actions[bot]' \
        -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
        -c rerere.enabled=false rebase --no-autostash FETCH_HEAD; then
        GIT_EDITOR=true git rebase --abort || true
        echo 'Could not rebase automatically; rerun the update against current main.' >&2
        exit 1
    fi
done
