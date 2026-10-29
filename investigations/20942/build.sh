#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
repo_root=$(git rev-parse --show-toplevel)
investigation_source=${INFRALAB_SOURCE:-/tmp/infralab-datafusion/investigation-src}
expected_revision=e4f9b030e1f2a09ca816fa1313f2f9abeb308bb7
if [[ $(git -C "$investigation_source" rev-parse HEAD) != "$expected_revision" ]]; then
    echo "Expected source revision $expected_revision in $investigation_source" >&2
    exit 1
fi
export CARGO_HOME=${CARGO_HOME:-/tmp/infralab-datafusion/cargo}
export CARGO_TARGET_DIR=${CARGO_TARGET_DIR:-/tmp/infralab-datafusion/target}
mkdir -p "$investigation_source/investigations/20942/repro/src"
cp "$repo_root/investigations/20942/repro/Cargo.toml" "$investigation_source/investigations/20942/repro/"
cp "$repo_root/investigations/20942/repro/src/main.rs" "$investigation_source/investigations/20942/repro/src/"
if [[ -f "$repo_root/investigations/20942/repro/Cargo.lock" ]]; then
    cp "$repo_root/investigations/20942/repro/Cargo.lock" "$investigation_source/investigations/20942/repro/"
    lock_args=(--locked)
else
    cp "$investigation_source/Cargo.lock" "$investigation_source/investigations/20942/repro/"
    lock_args=()
fi
cargo build --manifest-path "$investigation_source/investigations/20942/repro/Cargo.toml" --release -j 6 "${lock_args[@]}"
cp "$investigation_source/investigations/20942/repro/Cargo.lock" "$repo_root/investigations/20942/repro/"
