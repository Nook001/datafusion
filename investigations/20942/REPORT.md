# Issue 20942 多 distinct 聚合的独立复现与根因分析

## 结论

在 upstream `main` 的 `e4f9b030e1f2a09ca816fa1313f2f9abeb308bb7` 上成功复现：对多个不同列的 `COUNT(DISTINCT)`，现有计划保留并行 Partial 聚合，却将 distinct 状态集中到单分区 Final，逐个 accumulator 重建全局去重集合。高基数时，这一步占据关键路径。将 SQL 拆成单 distinct 分支后，已有 `SingleDistinctToGroupBy` 可以使用按 key 分区的去重路径，最后只合并标量 count。

本地代表用例中执行时间改善 **2.25–4.15 倍**，但这不是适用于所有查询的默认修复：单分区 integer 用例会变慢，高基数 integer 的 memory pool 峰值会增加约 **2.15 倍**。本轮只提交诊断程序与证据，没有修改 DataFusion 引擎、优化器规则或默认配置。

筛选与重复工作核查见 [ISSUE_SELECTION.md](../ISSUE_SELECTION.md)。本报告独立测量当前实现，不宣称首次发现问题；原 Issue 与两份已关闭未合并的历史方案为 [#20942](https://github.com/apache/datafusion/issues/20942)、[#20940](https://github.com/apache/datafusion/pull/20940)、[#21088](https://github.com/apache/datafusion/pull/21088)。截至本轮核查，无 Assignee、无认领评论，未发现当前 open 的同类实现。未向 GitHub 发布评论或 PR。

## 版本与环境

| 项目        | 实际值                                                                                            |
| ----------- | ------------------------------------------------------------------------------------------------- |
| 日期        | 2026-10-29，具体 UTC 时间见每个 `.command.json`                                                   |
| 引擎源码    | `e4f9b030e1f2a09ca816fa1313f2f9abeb308bb7`；DataFusion package 55.1.0                             |
| 原 checkout | `14aa185dd23d83d100eff3e3824bffd60df15e41`；正式实验另建 detached worktree，原工作区不切换分支    |
| 平台        | Rocky Linux 9.8，x86_64，AMD EPYC 9654P                                                           |
| 实际限制    | cgroup `cpu.max=600000 100000`，`memory.max=34359738368`，即 6 CPU equivalents、32 GiB            |
| 运行方式    | `taskset -c 0-5`；Tokio worker threads 固定 6；SQL target partitions 扫 1/2/4/6                   |
| 工具链      | Rust/Cargo 1.99.1；LLVM 23.1.1；mimalloc 0.1.52；Tokio 1.54.1；Arrow 60                           |
| 构建        | `opt-level=3`、`codegen-units=16`、无 LTO、line tables、无 strip；DataFusion 仅启用 `sql` feature |
| 数据        | Rust 构造的常驻 MemTable；无 Parquet、网络请求、磁盘输入或 spill；每批 8192 行                    |
| 内存观测    | 4 GiB GreedyMemoryPool 外包 `PeakRecordingPool`；另读 `/proc/self/status` 和 `/usr/bin/time -v`   |

完整依赖由 [Cargo.lock](repro/Cargo.lock) 锁定；[dependencies.txt](evidence/dependencies.txt)、[Rust](evidence/rustc.txt)、[CPU](evidence/cpu.json)、[cgroup](evidence/cgroup-limits.txt)、[binary SHA-256](evidence/binary.sha256) 和 [ELF build ID](evidence/binary-build-id.txt) 可供复核。实验时的 harness 原文保存在 [harness-at-run.rs.txt](evidence/harness-at-run.rs.txt)。构建耗时 4m17s，详见 [build.log](evidence/build.log)；编译结束后才测量性能。

宿主机虽暴露 96 cores/754 GiB RAM，实验没有将这些视为可独占资源。CPU frequency/boost 未锁定；共享宿主机的噪声由交替顺序与重复进程减轻，不能完全消除。

## 最小实验与对照

正式入口是 [repro/src/main.rs](repro/src/main.rs)。默认生成 2,000,000 行、3 列。第 j 列数值为 `(row + 7*j) % NDV`；string/view 编码为带列前缀的固定格式字符串，长度超过 StringView 的 inline 上限。各 partition 使用连续、不重叠的输入行范围。数据和 oracle 在计时前生成。

### 三组 SQL

**A / native**：

```sql
SELECT count(DISTINCT a0) AS c0,
       count(DISTINCT a1) AS c1,
       count(DISTINCT a2) AS c2
FROM t;
```

**B / split**：

```sql
SELECT q0.c0, q1.c1, q2.c2
FROM (SELECT count(DISTINCT a0) AS c0 FROM t) q0
CROSS JOIN (SELECT count(DISTINCT a1) AS c1 FROM t) q1
CROSS JOIN (SELECT count(DISTINCT a2) AS c2 FROM t) q2;
```

**C / split_no_rewrite**：SQL 与 B 完全相同，仅通过公开 `SessionStateBuilder::with_optimizer_rules` 删除名为 `single_distinct_aggregation_to_group_by` 的规则，其他规则保留。它是隔离控制，不是引擎 patch。

A/B 不能单独证明因果，因为同时改变了扫描分支、scheduling、聚合算法。B/C 保持 SQL 与数据不变，隔离单 distinct rewrite；另用 `--columns 1` 消除多分支差异，再比较 B/C。`same_argument` 将三个输出都改为 `count(DISTINCT a0)`，检查同一实参的优化路径。

### 可执行命令

从主 checkout 根目录运行；默认路径对应本机已创建的 worktree：

```bash
source .envrc.local
git worktree add --detach /tmp/infralab-datafusion/investigation-src \
  e4f9b030e1f2a09ca816fa1313f2f9abeb308bb7
bash investigations/20942/build.sh

taskset -c 0-5 /tmp/infralab-datafusion/target/release/infralab-distinct-probe \
  --rows 2000000 --cardinality 2000000 --columns 3 \
  --partitions 4 --kind i64 --mode native --iterations 5
# 将 --mode 换为 split 或 split_no_rewrite，其他参数保持不变。
```

已有 worktree 时省略 `git worktree add`。`build.sh` 校验源码 SHA，使用独立 harness manifest 和保存的 lockfile；`INFRALAB_SOURCE` 可指定同 SHA 的另一 worktree。首次建立诊断 crate 时由上游 lockfile 生成其 lockfile，后续构建使用 `--locked`。引擎源码无 patch。

本轮实际批量命令：

```bash
python3 investigations/20942/run_experiments.py --quick \
  --output investigations/20942/evidence/quick
python3 investigations/20942/run_experiments.py
python3 investigations/20942/run_controls.py
python3 investigations/20942/run_experiments.py --view \
  --output investigations/20942/evidence/view
python3 investigations/20942/summarize.py
python3 investigations/20942/summarize.py investigations/20942/evidence/controls
python3 investigations/20942/summarize.py investigations/20942/evidence/view
```

`run_experiments.py` 接受 `--binary` 和 `--output`，可将复核结果保存到新目录，不覆盖本轮证据。`run_controls.py` 的默认 binary 路径见脚本。每个进程独立建表，先一次 warmup，再计 3 次；两轮进程顺序分别为 A/B/C 与 C/B/A。主矩阵 96 个进程、288 个计时样本；single-expression/同实参控制 18 个进程、90 个样本；Utf8View 补验 24 个进程、72 个样本。下表均排除 warmup，普通矩阵每格 6 个样本、来自 2 个独立进程；不是 6 台独立机器。

每次创建新的 physical plan，防止 metrics 累加。执行时间只包围 `collect(plan, task_ctx)`，不含生成数据、oracle、规划、读取 metrics 或 JSON 输出。`planning_ms` 包含为导出 logical plan 额外执行的一次优化，不能当作生产端到端规划基准。所有输出按数值 domain 的独立 oracle 验证，NULL 不进入 distinct 集合；all-NULL 与每 17 行一个 NULL 的控制也通过。

## 实际结果

### 4 分区代表用例

下列均为 2M 行、3 个不同实参；时间单位 ms，中位数 `[min, max]`。完整结果在 [matrix summary](evidence/matrix/summary.csv) 与 [view summary](evidence/view/summary.csv)，每次原始 SQL、计划和分区 metrics 同目录保存。

| 输入类型 / NDV  | A native                | B split                 | C split_no_rewrite      | A/B       |
| --------------- | ----------------------- | ----------------------- | ----------------------- | --------- |
| Int64 / 200K    | 29.80 [29.14, 30.27]    | 16.04 [15.93, 17.37]    | 23.49 [22.15, 24.10]    | 1.86x     |
| Int64 / 2M      | 163.50 [162.89, 165.35] | 50.28 [48.97, 51.71]    | 139.73 [133.36, 143.64] | **3.25x** |
| Utf8 / 200K     | 142.48 [140.63, 155.14] | 63.32 [62.14, 64.52]    | 91.27 [89.67, 98.83]    | **2.25x** |
| Utf8 / 2M       | 513.13 [501.94, 515.13] | 133.34 [131.32, 136.56] | 461.92 [455.69, 473.24] | **3.85x** |
| Utf8View / 200K | 183.17 [181.92, 188.72] | 70.68 [69.64, 72.09]    | 118.55 [116.10, 122.74] | **2.59x** |
| Utf8View / 2M   | 535.65 [520.94, 567.50] | 129.01 [125.81, 132.43] | 470.13 [467.07, 475.25] | **4.15x** |

三组全都返回预期结果。C 有部分改善但保留明显开销，说明不能把 B 的收益全部归因于“拆成多个查询”；单 distinct 重写是一个主要因素。

### 并行度与基数边界

Utf8、NDV=200K、3 distinct 的中位数：

| partitions | A native ms | B split ms | A 的 Final merge 总计 ms |
| ---------- | ----------- | ---------- | ------------------------ |
| 1          | 174.21      | 110.56     | 0：Single 模式           |
| 2          | 151.01      | 61.26      | 38.60                    |
| 4          | 142.48      | 63.32      | 75.64                    |
| 6          | 164.02      | 71.61      | 108.59                   |

增加 p 没有让 A 持续加速。这里各 partition 都覆盖相同 200K domain，p 增加使 Final 收到更多重复 distinct 状态。这个数据布局是显式选择的实验轴，不代表所有数据的分区分布。

反例同样保留：Int64、p=1、NDV=128 时 A=14.22 ms、B=20.31 ms（B 慢约 43%）；NDV=2M 时 A=173.63 ms、B=200.32 ms。p=4、NDV=128 的 A/B 约 3.64/3.70 ms，区间重叠，不宣称有显著差异。all-NULL 小数据控制里 B 也有额外 overhead。

### 单表达式消融

2M 行、NDV=2M、仅 1 个 distinct；B/C 的 SQL 完全相同，没有 CROSS JOIN。每格来自两进程、10 个计时样本，见 [controls summary](evidence/controls/summary.csv)。

| 类型 / p  | B：rule on | C：rule off | C 的 Final merge ms |
| --------- | ---------- | ----------- | ------------------- |
| Int64 / 1 | 67.20      | 51.34       | 0                   |
| Int64 / 4 | 21.10      | 52.01       | 39.65               |
| Utf8 / 1  | 139.54     | 120.46      | 0                   |
| Utf8 / 4  | 51.65      | 159.15      | 124.77              |

p=4 的 B 消除大状态的单分区合并；p=1 没有这项代价，额外 GROUP BY 路径反而更慢。这是支持根因、也限制优化适用范围的直接干预证据。同实参三个输出的控制进入去重/共享表达式路径，p=4 下 Int64=22.58 ms、Utf8=51.95 ms，接近对应的单表达式 rule-on 结果。

### 内存与 CPU 代价

4 分区的 memory pool 峰值中位数（MiB）：

| 类型 / NDV      | A native | B split    | C split_no_rewrite |
| --------------- | -------- | ---------- | ------------------ |
| Int64 / 2M      | 108.00   | **232.63** | 54.42              |
| Utf8 / 200K     | 183.75   | 99.66      | 108.65             |
| Utf8View / 200K | 246.75   | 136.66     | 145.40             |

pool 降低不等于 RSS 同比例降低：Utf8/200K 的进程 VmHWM 最大值分别约 790/786 MiB，基本相当；Int64/2M 则约 500/611 MiB，B 确实更高。RSS 包含输入表、生成阶段、warmup、allocator 保留和未记账临时内存，不用 `VmHWM - baseline RSS` 冒充精确 query allocation。全主矩阵最大进程 VmHWM 约 2.06 GiB，远低于本机 32 GiB 限制。本实验没有证明内存泄漏或 memory pool accounting 错误。

## 专业诊断与因果链

### 实际执行结构

从原始计划删去 projection/metrics 后，A 的结构为：

```text
AggregateExec Final: 三个 distinct accumulators，单分区
  CoalescePartitionsExec
    AggregateExec Partial: 每个输入 partition 有三个 accumulators
      MemTable: P partitions
```

B 的每个单 distinct 分支变为：

```text
Final scalar count
  CoalescePartitions
    Partial scalar count
      FinalPartitioned GROUP BY distinct_key
        Hash Repartition(distinct_key, P)
          Partial GROUP BY distinct_key
            MemTable: P partitions（只投影该列）
```

三个单行分支再 CROSS JOIN。原始计划见 [Int64 A](evidence/i64_n2000000_d2000000_p4_null0_native_r0.plan.txt)、[Int64 B](evidence/i64_n2000000_d2000000_p4_null0_split_r0.plan.txt)、[Utf8 A](evidence/utf8_n2000000_d200000_p4_null0_native_r0.plan.txt)。

### 源码与 metrics 相互印证

1. **进入不同算法的门槛。** [`is_single_distinct_agg`](https://github.com/apache/datafusion/blob/e4f9b030e1f2a09ca816fa1313f2f9abeb308bb7/datafusion/optimizer/src/single_distinct_to_groupby.rs#L110) 在 `fields_set.len() != 1` 时返回 false。A 的三个不同实参不满足；B 的每个分支满足。这个门槛保证现有单-domain 重写正确，不能简单删除条件来“修复”多 distinct。
2. **Final 串行合并。** [`aggregate_batch`](https://github.com/apache/datafusion/blob/e4f9b030e1f2a09ca816fa1313f2f9abeb308bb7/datafusion/physical-plan/src/aggregates/aggregate_stream.rs#L455) 按 accumulator 逐个 `try_for_each`；Final 输入调用 `merge_batch`。Int64/2M/p4 中 A 的三项 merge 合计中位数 **119.30 ms**，约为 163.50 ms 执行 wall time 的 73%；Utf8/2M/p4 为 **399.82 / 513.13 ms**。B 的最终 scalar merge 接近零，大状态去重转到分区 GROUP BY。
3. **状态内容不是一个 count。** [`PrimitiveDistinctCountAccumulator`](https://github.com/apache/datafusion/blob/e4f9b030e1f2a09ca816fa1313f2f9abeb308bb7/datafusion/functions-aggregate-common/src/aggregate/count_distinct/native.rs#L59) 将 HashSet 的所有 distinct 值导出为 List scalar，Final 再 `extend` 到全局 HashSet；[string accumulator](https://github.com/apache/datafusion/blob/e4f9b030e1f2a09ca816fa1313f2f9abeb308bb7/datafusion/functions-aggregate-common/src/aggregate/count_distinct/bytes.rs#L47) 同样输出值集合并重新 insert。对 M 个实参，Final 处理的值规模约为 `sum_j sum_partition NDV(j, partition)`，不是 M×P 个整数计数。
4. **去重分区的作用。** B 按 distinct_key hash 分发，使同值进入同一 FinalPartitioned bucket。去重完成后才能安全地合并 count；不能直接把原始各 partition 的 distinct counts 相加。当前实验用有重叠 domain 的输入，能检出这种错误捷径。

单分区实验还显示 C 常比 A 省内存或更快，可能涉及分支调度和同时存活的多个集合的 working set；该次级效应没有用专门 cache ablation 完全分离，**不将其写成已证明的唯一根因**。

### perf 采样与硬件计数

实际命令与可重复入口见 [profile.sh](profile.sh)，关键命令为：

```bash
perf record -F 199 -e cycles:u --call-graph dwarf,8192 -o native.perf.data -- \
  taskset -c 0-5 /tmp/infralab-datafusion/target/release/infralab-distinct-probe \
  --rows 2000000 --cardinality 2000000 --partitions 4 \
  --kind i64 --mode native --iterations 30
perf report --stdio --no-children --call-graph none --percent-limit 0.5 \
  --sort dso,symbol -i native.perf.data | llvm-cxxfilt
```

针对同一 Int64 高基数用例，A 的 1,925 个 cycle samples 无 lost samples；约 **48.39%** 在 `HashMap<i64, ()>::insert`、**44.18%** 在 `reserve_rehash`、4.65% 在将 HashSet iterator 导出到 Vec 的路径。B 的热点变为 `GroupValuesPrimitive::intern`（57.33%）及其 table rehash（29.58%）。它仍然需要 hashing，不能表述为“避免了所有哈希”。旧 perf/GNU c++filt 未正确 demangle Rust v0，使用本机 `llvm-cxxfilt` 得到可读符号，见 [A report](evidence/profiles/native-llvm-symbolized.txt)、[B report](evidence/profiles/split-llvm-symbolized.txt)。

独立 `perf stat -r 3` 进程观测：

| 指标            | A native      | B split        |
| --------------- | ------------- | -------------- |
| process elapsed | 1.871 s       | 0.652 s        |
| task-clock      | 3374 ms       | 3334 ms        |
| 平均 CPU 利用   | 1.803 CPUs    | 5.117 CPUs     |
| instructions    | 19.03 billion | 15.31 billion  |
| cache misses    | 98.79 million | 118.90 million |
| IPC             | 1.56          | 1.28           |

这些 counter 覆盖整个进程，包括生成数据、一次 warmup、10 次 measured query、规划和 JSON，不是单个 query 的精确硬件计数。尽管如此，“wall 明显下降、CPU time 近似不变、更多 CPU 同时工作”的组合，与减少单分区 critical path 一致；绝不能推断为 3 倍 CPU 资源节省或 cache misses 降低。原始文件见 [native stat](evidence/profiles/native-stat.txt)、[split stat](evidence/profiles/split-stat.txt)。采样运行只用于定位，表中主要性能数字来自未挂 profiler 的矩阵。

原始 DWARF callgraph 采样以 `*.perf.data.gz` 压缩保存在同一目录，解压后可用 `perf report -i` 复核；解压前原始文件的 SHA-256 在 `RAW_PERF_SHA256SUMS`。硬件 counters 在本机权限下为用户态事件。JSON 中保留每次独立结果，另有 [verify_evidence.py](verify_evidence.py) 使用 Python oracle 复核所有未挂 profiler 的输出。

## 假设检验与根因强度

| 假设                                     | 隔离证据                                                                           | 判定                      |
| ---------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------- |
| 只是扫描或 I/O 慢                        | 常驻相同 MemTable；生成、规划、输出排除在执行计时外                                | 排除外部 I/O 为本用例主因 |
| 完全没有并行                             | A 有 P 个 Partial；p=1/4 低 NDV 呈明显加速                                         | 原 Issue 的笼统措辞需修正 |
| 单分区 Final distinct merge 是高基数瓶颈 | Final merge 占主导；相同单表达式 SQL 的 rule on/off；p 增加导致重复状态 merge 增长 | **强证据支持**            |
| 仅拆分 SQL 就能解释全部收益              | C 保持分支，却仍有昂贵 merge；B/C 在单表达式下依然明显不同                         | 排除“仅分支化”解释        |
| default 开启 rewrite 总更好              | p=1 integer 回退；低 NDV 无稳定收益；integer pool/RSS 增大                         | **被反例否定**            |
| 测到的是精确内存泄漏                     | pool/RSS 含义不同，未做跨 query 生命周期泄漏检验                                   | 本轮没有此结论            |

主要根因已经定位到 **多实参绕过单 distinct 重写 → fallback 集合状态跨阶段传递 → 单分区 Final 串行再去重**。HashSet 插入、扩容和状态物化是被 metrics/profiler 共同观测到的具体成本。多分支中途缓存局部性、不同集合结构的单线程效率，以及部分 transient memory accounting 不在本轮已完全证明的范围内。

## 候选优化方向与副作用

以下只是待 Review 的方向，没有选择或实现正式修复方案：

- **保守的多 distinct 分支规划。** 在可复用输入、较高 NDV、p>1 且内存预算合适时评估，利用已有单 distinct 分区去重。不能 blanket 开启；本轮高基数 integer 的 pool 增量就是反例。
- **减少 Final 集合重建/扩容。** 调查 distinct state 传递、预分配、可合并集合或按 key 分区的专用执行路径；须区分真的减少工作与只是增加并行。不能把 count(DISTINCT) 的部分 counts 直接相加。
- **共享输入或 dedicated multi-distinct physical path。** 如果分支导致昂贵扫描/子查询重复，可探索单次扫描 fan-out 或其他执行结构；这会增加调度、内存所有权和取消处理的复杂度，需另行设计。

需要在 Review 中约束的语义/成本：NULL、空输入仍须返回 scalar 0；GROUP BY 的 NULL key 和缺失分支不能用简单 CROSS JOIN 替代；相同 distinct 表达式应共享工作；volatile filter/UDF、错误表达式及重复求值不能改变结果；Parquet/远端 source 的重复 metadata、解码和子树执行可能抵消收益。NDV 估计缺失时应保守，而不是假定高基数。

## 尚未解决与复核建议

1. 未运行真实 ClickBench、Parquet、宽 payload、昂贵 predicate/remote I/O，也未测试 grouped 多 distinct；本轮数字不能外推到这些场景。
2. 已测 NULL/all-NULL、同实参，未覆盖空表、复杂表达式、volatile 函数、所有 SQL 类型；本轮结果校验不是通用 rewrite 的正确性证明。
3. 尚无端到端 planning+execution 基准、跨硬件结果或正式 cost model。当前只证明“存在可复现且规模可观的改进空间”，不证明某个默认阈值正确。
4. 所有数据来自单宿主机，重复样本存在同进程相关性；保留 min/max 与逐样本记录，不以伪精确统计声称普适收益。
5. 具体修复待分析 Review 后确定；若继续，先向历史作者与维护者确认范围，并重新核查是否已有新 PR。

本轮没有 core patch，因此没有用完整 workspace/extended 测试暗示修复已可提交。实际验证包括 optimized build、全部实验的独立结果 oracle、脚本语法与格式检查。仓库文档检查脚本不覆盖 `investigations/`，需额外显式运行 Prettier；具体检查记录见本目录 evidence 的 validation 文件。
