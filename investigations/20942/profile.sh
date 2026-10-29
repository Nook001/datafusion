#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
binary=${INFRALAB_BINARY:-/tmp/infralab-datafusion/target/release/infralab-distinct-probe}
output=${INFRALAB_PROFILE_OUTPUT:-investigations/20942/evidence/profiles}
mkdir -p "$output"
for mode in native split; do
    perf record -F 199 -e cycles:u --call-graph dwarf,8192 \
        -o "$output/$mode.perf.data" -- taskset -c 0-5 "$binary" \
        --rows 2000000 --cardinality 2000000 --partitions 4 --kind i64 \
        --mode "$mode" --iterations 30 \
        > "$output/$mode.jsonl" 2> "$output/$mode-perf-record.txt"
    perf report --stdio --no-children --call-graph none --percent-limit 0.5 \
        --sort dso,symbol -i "$output/$mode.perf.data" > "$output/$mode-flat.txt"
    llvm-cxxfilt < "$output/$mode-flat.txt" > "$output/$mode-llvm-symbolized.txt"
    perf stat -r 3 -e task-clock,cycles,instructions,cache-references,cache-misses,context-switches \
        -o "$output/$mode-stat.txt" -- taskset -c 0-5 "$binary" \
        --rows 2000000 --cardinality 2000000 --partitions 4 --kind i64 \
        --mode "$mode" --iterations 10 \
        > "$output/$mode-stat.jsonl" 2> "$output/$mode-stat.stderr.txt"
done
