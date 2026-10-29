<!-- SPDX-License-Identifier: Apache-2.0 -->

# InfraLab development bootstrap

Baseline established on 29 October 2026 at commit
`14aa185dd23d83d100eff3e3824bffd60df15e41` (`main`, matching the local
`origin/main` reference). DataFusion identifies itself as 55.1.0. The minimal
runtime and pruning tests pass, as do all 246 Parquet integration tests and
`select.slt`. The strongest next investigation is memory retained by Parquet
metrics in scans of many small files, coordinated with the existing contributors.

## Environment and dependencies

| Item                      | Observed baseline                                                                                                                              |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Host                      | `zebra-01`, Rocky Linux 9.8, x86_64, kernel 5.14.0-687.60.1.el9_8                                                                              |
| Hardware                  | AMD EPYC 9654P, 96 exposed cores, one NUMA node, 384 MiB L3; host RAM 754 GiB                                                                  |
| Effective resource limits | User cgroup: **6 CPU equivalents** (`cpu.max = 600000 100000`) and **32 GiB RAM**; the SQL test runner also reports parallelism 6              |
| Storage                   | Checkout on NFS, about 1.6 TiB free; local `/tmp` about 1.7 TiB free at inspection; user quotas were not established                           |
| Rust                      | Pinned and installed 1.99.1, LLVM 23.1.1, Cargo 1.99.1; rustfmt and Clippy installed; workspace MSRV 1.95.0, edition 2024                      |
| Native tools              | GCC 11.5, Clang 21.1.8, CMake 4.4.4, Ninja 1.10.2, pkg-config, OpenSSL 3.5.8                                                                   |
| Supporting tools          | Git, Python 3.15.2, Node 26.12.1, npm 12.2.1, curl and unzip                                                                                   |
| Protocol compiler         | System `protoc` 3.14 is below the documented 3.15 minimum; installed official `protoc` 33.0 under `/tmp/infralab-datafusion/tools/protoc-33.0` |

The 51-member Cargo workspace uses Arrow/Parquet 60.0.0 and resolves dependencies
through `Cargo.lock`. Rust and a C toolchain are the basic requirements;
protobuf generation additionally needs `protoc`, and optional native dependencies
use CMake/pkg-config/OpenSSL. Docker-backed services are optional for particular
integration tests. The repository also provides `flake.nix` and `.devcontainer/`.

An ignored `.envrc.local` activates the local Cargo cache, target directory,
eight build jobs and the newer protocol compiler. Activate it explicitly from
the repository root:

```bash
source .envrc.local
rustc --version
protoc --version
```

The file exports these settings; the checked-in toolchain file selects Rust:

```bash
export CARGO_HOME=/tmp/infralab-datafusion/cargo
export CARGO_TARGET_DIR=/tmp/infralab-datafusion/target
export CARGO_BUILD_JOBS=8
export PROTOC=/tmp/infralab-datafusion/tools/protoc-33.0/bin/protoc
export PATH="/tmp/infralab-datafusion/tools/protoc-33.0/bin:$PATH"
```

`/tmp` caches are disposable. To recreate the protocol compiler:

```bash
mkdir -p /tmp/infralab-datafusion/tools
curl --fail --location --retry 2 \
  https://github.com/protocolbuffers/protobuf/releases/download/v33.0/protoc-33.0-linux-x86_64.zip \
  --output /tmp/infralab-datafusion/tools/protoc-33.0-linux-x86_64.zip
unzip -oq /tmp/infralab-datafusion/tools/protoc-33.0-linux-x86_64.zip \
  -d /tmp/infralab-datafusion/tools/protoc-33.0
```

The downloaded archive's SHA-256 was
`d99c011b799e9e412064244f0be417e5d76c9b6ace13a2ac735330fa7d57ad8f`.

## Commands and results

Commands below ran from the repository root with the environment above unless
noted. Captured outputs are in [the bootstrap logs](../dev/infralab/logs/).
All Cargo commands used `--locked`; no manifests or lockfiles were changed.

| Actual command                                                                   | Result                                                                                                                                                                                                                                                               |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rustup show`, `rustc -Vv`, `cargo -V`                                           | Initially blocked by a missing named toolchain and a read-only rustup directory. `rustc +stable -Vv` confirmed the installed stable compiler was exactly 1.99.1. After the permission change, `rustup show` installed the pinned named toolchain and its components. |
| `git submodule update --init --recursive`                                        | Initial clone was interrupted. A retry encountered an incomplete `datafusion-testing` checkout; recovery completed all three pinned fixture checkouts.                                                                                                               |
| `RUSTUP_TOOLCHAIN=stable cargo build --locked -j 8 -p datafusion-common-runtime` | Initial sandbox attempt could not resolve `index.crates.io`; stopped it and retried with network permission. **Pass**, build reported 22.09 s.                                                                                                                       |
| `RUSTUP_TOOLCHAIN=stable cargo test --locked -j 8 -p datafusion-common-runtime`  | **Pass**, 4 unit tests; no doctests.                                                                                                                                                                                                                                 |
| `cargo test --locked --profile ci -j 8 -p datafusion-pruning --lib`              | **Pass**, 115 tests; build reported 36.40 s.                                                                                                                                                                                                                         |
| `cargo test --locked --profile ci -j 8 -p datafusion --test parquet_integration` | First attempt: 236 passed, 10 failed because `parquet-testing/data` was absent. After fixture recovery, identical command **passed all 246**.                                                                                                                        |
| `cargo test --locked --profile ci -j 8 --test sqllogictests -- select.slt`       | **Pass**, one SQL logic test file, exit 0. It logged approximately 1.1 MiB of peak memory-accounting drift; this diagnostic alone does not establish a leak.                                                                                                         |
| `cargo metadata --locked --offline --no-deps --format-version 1`                 | **Pass**, 51 workspace members.                                                                                                                                                                                                                                      |
| `perf stat -e task-clock,cycles,instructions true`                               | **Pass**, user-mode cycles and instructions available despite `perf_event_paranoid=2`.                                                                                                                                                                               |

Additional successful commands:

```bash
cargo build --locked --profile ci -j 8 -p datafusion-cli
"$CARGO_TARGET_DIR/ci/datafusion-cli" --command \
  'SELECT sum(value) AS total FROM generate_series(1, 1000);'
"$CARGO_TARGET_DIR/ci/datafusion-cli" --command \
  'SET datafusion.execution.target_partitions = 2; EXPLAIN ANALYZE SELECT sum(value) AS total FROM generate_series(1, 10000);'
cargo fmt --all -- --check
npm_config_cache=/tmp/infralab-datafusion/npm \
  ./ci/scripts/doc_prettier_check.sh --write --allow-dirty
```

The CLI build reported 50.54 s. The sum query returned `500500`; the analyzed
plan reported aggregate/repartition metrics and 10,000 input rows. Rust and
documentation formatting passed, including this report, without changes to
existing tracked files.

Fixture recovery used `git -C datafusion-testing fetch --depth 1 origin 64e2529880aeefb81844ea0de26548332086379d`, then `read-tree`, a detached checkout,
and `restore --worktree .` to populate files missing from the interrupted clone;
the final `git submodule update --init --recursive` succeeded. Fixture revisions:

- `datafusion-testing`: `64e2529880aeefb81844ea0de26548332086379d`
- `parquet-testing`: `107b36603e051aee26bd93e04b871034f6c756c0`
- `testing`: `7df2b70baf4f081ebf8e0c6bd22745cf3cbfd824`

These are correctness baselines using unoptimized builds. Workspace-wide builds,
Clippy, extended tests and optimized performance measurements were not run; the
successful focused runs do not imply full CI coverage. Build durations include
different cache states and are not comparable performance measurements.

## Architecture and diagnostics

The architecture's authoritative local explanation is
[core/src/lib.rs](../datafusion/core/src/lib.rs). SQL passes through `sqlparser`
and `datafusion/sql` into logical plans (`expr`), analysis and logical rewriting
(`optimizer`), physical planning (`core`), physical rewriting
(`physical-optimizer`), and asynchronous execution (`physical-plan`). Operators
consume and emit Arrow record batches through streams on Tokio. Joins, sorting,
aggregation, repartitioning and spilling live in `physical-plan`; memory pools
and runtime state live in `execution`. `physical-expr` evaluates vectorized
expressions; scalar, aggregate, nested and window functions have dedicated
crates. `datasource*`, particularly `datasource-parquet`, handle scans and writes;
`pruning` evaluates metadata predicates to avoid reading containers. `core`
provides `SessionContext`, SQL/DataFrame APIs and integration tests; `datafusion-cli`
is the interactive executable. Proto, Substrait and FFI support integrations.

Useful investigation tools already present:

- `EXPLAIN`/`EXPLAIN ANALYZE`: inspect plans and operator metrics, including
  elapsed work, row counts, bytes, spills and pruning. Parallel operator times
  can exceed query wall time. Metrics and memory-drift diagnostics help separate
  reported reservations from actual process memory.
- [benchmarks/bench.sh](../benchmarks/bench.sh), `dfbench`, Criterion and SQL
  benchmark suites: TPC-H/TPC-DS, ClickBench, joins, windows, wide schemas and
  spilling. `bench.sh compare` and Criterion baselines support comparisons.
- [mem_profile](../benchmarks/src/bin/mem_profile.rs): separate subprocesses per
  query, peak RSS/commit/fault statistics using `mimalloc_extended`. The current
  source accepts ClickBench, H2O, IMDB, sort-TPC-H and TPC-H; the README also
  mentions TPC-DS, which is absent from this binary's subcommands.
- Focused benches: `pruning/benches/{primitive,string}_in_list_pruning.rs`,
  `physical-plan/benches/{multi_group_by,bounded_window,spill_io}.rs`, and
  `benchmarks/benches/parquet_pruning_setup_cache.rs`.
- Installed `perf`, Valgrind 3.26, `strace`, GDB and `/usr/bin/time`. Hardware
  counters were tested; heap profiling and debugging were not. Samply, heaptrack,
  cargo-flamegraph, cargo-nextest and alternate linkers were not found on PATH.
- SQL logic tests, public DataFrame tests, property/fuzz tests, snapshots,
  `dev/rust_lint.sh`, `cargo xtask` and `ci/scripts/` provide regression and CI
  diagnostics. `benchmarks/compile_profile.py` compares build profiles.

Use `release-nonlto` for iterative performance work and `profiling` for optimized
builds with debug information. Use the same profile, compiler, allocator,
features and CPU settings for both revisions. Keep datasets and spill files on
local storage; run benchmarks after compilation stops, alternate baseline and
candidate runs, fix partition counts, and report distributions and peak RSS
alongside memory-pool reservations. Host totals exceed this user's actual quota.

## Candidate issues

Issue status and discussion were checked on 29 October 2026 through the GitHub
connector, with public pages as a fallback during a connector search rate limit.
An unassigned issue can still have active work: the shortlist explicitly accounts
for comments and related PRs. Timings below belong to upstream reports, not this
machine.

### 1 Parquet metrics memory growth

[Issue 22189](https://github.com/apache/datafusion/issues/22189) is the strongest
lead. A downstream report attributes most retained heap memory in a many-file
scan to `ParquetFileMetrics::new`. Filename sharing already landed in
[PR 22406](https://github.com/apache/datafusion/pull/22406), but the number of
registered metrics still grows with files. The local reader and opener both
construct file metrics. Confirm whether those instances duplicate accounting,
then assess sharing or an explicit per-partition mode while preserving visible
metrics and scan-efficiency semantics.

**Validation and tools:** generate small Parquet files locally, vary file count
and schema width at fixed row count, measure metrics-set length and peak RSS,
and use Valgrind Massif or a jemalloc heap profile for allocation attribution.
Rust, Arrow ownership and metrics semantics are the specialist knowledge needed;
no distributed cluster is required. Feasibility is medium, with substantial
memory value for small-file workloads. Maintainer `alamb` explicitly supports
deduplication and an optional aggregation mode and offered review in
[the discussion](https://github.com/apache/datafusion/issues/22189#issuecomment-6504244269).
The issue is assigned to `xudong963`, and `vaibhavbodhane` offered a patch:
coordinate a bounded subtask before implementation.

### 2 Reusable Parquet pruning setup

[Issue 21554](https://github.com/apache/datafusion/issues/21554) targets repeated
schema adaptation, expression simplification and predicate construction for
files sharing a physical schema. The local opener still performs this setup per
file. The earlier implementation,
[PR 21566](https://github.com/apache/datafusion/pull/21566), is closed without
merge, as is related [PR 26438](https://github.com/apache/datafusion/pull/26438).
The focused benchmark from merged
[PR 24323](https://github.com/apache/datafusion/pull/24323) is available locally.

**Validation and tools:** begin with that Criterion benchmark and a CPU profile,
then add mixed-schema and real SQL controls. Inspect prior reviews before
reviving the approach. Cache keys must cover schema, projection, adapter behavior
and predicate state; dynamic filters, partition literals and `input_file_name()`
must remain correct. Rust concurrency and expression-rewrite knowledge matter;
`perf` and Criterion suffice. Feasibility is medium to low because correctness
and cache lifetime are harder than the basic optimization. Maintainers requested
benchmark justification, and the old focused result was only about 7% faster:
broader value remains to be demonstrated. Unassigned, but coordinate with the
previous author `kosiew` rather than silently replacing their work.

### 3 Compact IN list pruning thresholds

[Issue 24710](https://github.com/apache/datafusion/issues/24710) questions the
unmeasured 20-value representation boundary. Local primitive/string benchmarks
already vary list length and container count; construction cost must be measured
separately from evaluation. A benchmark must force both representations for small
lists: the existing automatic selector otherwise keeps them on the legacy path.
Preserve NULL, `NOT IN`, disabled-cap and missing-statistics behavior.

**Validation and tools:** Criterion, pruning tests and SQL/Parquet controls; no
external dataset or specialist profiler is required. This is the most accessible
independent validation task, with modest implementation scope and uncertain
runtime benefit. `adriangb` requested the investigation and `gruuya` identified
the interaction with the default upper cap. However,
[PR 25044](https://github.com/apache/datafusion/pull/25044) is already open and
proposes separating the threshold constant while retaining its value. Contribute
benchmark replication or review to that PR; do not start a competing patch.

Other attractive leads were deprioritized: struct min/max accounting
[26891](https://github.com/apache/datafusion/issues/26891) already has open
[PR 26894](https://github.com/apache/datafusion/pull/26894); dictionary aggregate
work [26696](https://github.com/apache/datafusion/issues/26696) has open
[PR 26703](https://github.com/apache/datafusion/pull/26703) and related Arrow work;
pruning guard factoring [24280](https://github.com/apache/datafusion/issues/24280)
already has a draft and reports negligible end-to-end benefit. Large radix-join,
NUMA and blocked-aggregation epics have a much larger first-contribution scope.

## Contribution requirements and next step

Reviewed [development setup](source/contributor-guide/development_environment.md),
[testing](source/contributor-guide/testing.md),
[contribution rules](source/contributor-guide/index.md),
[AI policy](source/contributor-guide/ai-policy.md),
[review guidance](source/contributor-guide/pr_review.md), the
[PR template](../.github/pull_request_template.md), and `.ai/skills/`.
The applicable benchmark guidance prefers SQL/public behavior and representative
workload axes. SQL logic tests precede internal unit tests when practical.
Check existing PRs and acknowledge prior work before starting; coordinate an
available subtask, keep a first contribution focused, and personally review and
understand all submitted AI-assisted code. No issue comments, assignments,
commits or PRs were created during bootstrap.

Next, independently reproduce the metric-count and RSS slope for issue 22189
on generated local files, then agree a deduplication subtask with its contributors.
Keep an unchanged baseline at this SHA and use separate build targets for a
candidate. Proceed only when the observed slope and semantics justify a fix;
issue 21554 is the fallback if that subtask is already covered.

Before committing a future code change, the repository requires
`cargo fmt --all` and
`cargo clippy --all-targets --all-features -- -D warnings`, relevant public API
tests, benchmarks against `main`, and the prescribed extended test command.
Documentation changes require
`./ci/scripts/doc_prettier_check.sh --write --allow-dirty`.
