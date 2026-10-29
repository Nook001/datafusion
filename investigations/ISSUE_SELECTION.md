# InfraLab 第一轮 Issue 筛选

核查日期：2026-10-29。结论：选择 **[#20942：多个 COUNT(DISTINCT) 的执行效率](https://github.com/apache/datafusion/issues/20942)**，调查范围限定为不带 GROUP BY 的多个精确 distinct count。先复现、分析，不修改优化器，不提交修复。

## 方法与证据

重新搜索当前 open Issues，覆盖 performance、memory、regression；不沿用 bootstrap 阶段的推荐结论。检索记录、完整 Issue、评论和相关 PR 元数据保存在 [evidence](evidence/)；JSON 包含读取时间与查询字符串。对 10 个候选逐项读取 Assignee、评论中的 `take`/`untake`、作者意向，再检索 PR 并读取相关实现的实际状态。搜索结果中的 state 可能为空，不能据此判定 PR 已关闭；以下判断使用 `fetch_issue`/`fetch_pr` 的状态。

GitHub connector 的两个 PR 检索曾遇到 secondary rate limit；错误原样保留，稍后补查 #23338。未将一次搜索无结果解释为严格的“没有任何人在做”。未向外发布评论、认领、提交或 PR。

本地原始 checkout 为 `14aa185dd23d83d100eff3e3824bffd60df15e41`。通过 `git fetch origin main` 核对后，最新 upstream 为 `e4f9b030e1f2a09ca816fa1313f2f9abeb308bb7`，相差一个 temporal display format 修复。正式实验使用后者的 detached worktree `/tmp/infralab-datafusion/investigation-src`，聚合相关源码在这两个版本之间无差异。

## 候选比较

下列 10 项在核查时均为 open。难度按本机 6 CPU equivalents、32 GiB RAM 判断；“已关闭 PR”均另行核查 merged 状态。

| Issue                                                                                         | 工程价值与调查空间                                                                    | 负责人、已有工作及关联 PR                                                                                            | 本地难度 / 重复风险             | 决定                                                  |
| --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ------------------------------- | ----------------------------------------------------- |
| [20942](https://github.com/apache/datafusion/issues/20942) 多个 COUNT(DISTINCT)               | 分析聚合阶段并行、distinct 状态合并及重写开销；缺少当前版本的分阶段系统对照           | 无 Assignee、无评论认领；作者 Dandandan 的 #20940 已关闭未合并；关联 grouped 问题 #21087 的 #21088 也已关闭未合并    | 中 / 低至中，需承认两份历史实现 | **入围并选择**                                        |
| [23338](https://github.com/apache/datafusion/issues/23338) sorted aggregation 无条件选择      | 原报告给出 p=1/8 对照，但现有 aggregate stream 和 ordering 机制已演化，需重新验证原因 | 无 Assignee；vukrosic 表示“若高优先级愿意调查，请 tag”，没有实际认领或进展；按编号搜索未找到实现 PR                  | 中 / 中，存在条件性贡献意向     | **入围**，优先级次于无意向记录者                      |
| [21554](https://github.com/apache/datafusion/issues/21554) 重复构建 Parquet pruning setup     | 小文件扫描 CPU；缓存收益是否覆盖构建、查找和失效成本值得量化                          | 无 Assignee；kosiew 曾实现 #21566，closed/unmerged；#26438 closed/unmerged；#24323 已合并 benchmark                  | 中高 / 中，有历史方案和作者     | **入围**，收益证明与正确性门槛更高                    |
| [6916](https://github.com/apache/datafusion/issues/6916) 默认 batch size                      | 旧报告在不同硬件上结果相反，有跨 workload 分析空间                                    | 无 Assignee、无 `take`；#8388 closed/unmerged；原 coalescing 评论中的阈值现已变化                                    | 中 / 低，但范围广               | 保留，第一轮难收敛为独立改进                          |
| [24929](https://github.com/apache/datafusion/issues/24929) SingleDistinctToGroupBy 内存放大   | 真实内存回退，但原文已深入复现定位，最严重案例已修                                    | 无 Assignee；mkleen 曾 `take` 后 `untake`；#25288 merged 修复 min/max；讨论准备拆分 sum/avg/count 后续项             | 低中 / 中                       | 不选，调查新颖性不足                                  |
| [17098](https://github.com/apache/datafusion/issues/17098) ORDER BY LIMIT 1                   | TopK 专用路径、min/max rewrite                                                        | 无 Assignee；Thearas `take` 后 `untake`；已有 #18514、#18509、#25657 多条实现线索                                    | 中 / 中高                       | 不选，需先拆清已有工作覆盖范围                        |
| [19216](https://github.com/apache/datafusion/issues/19216) 小内存外部排序失败                 | 无需完整 ClickBench，评论已有 2M 行/64 MB 小复现；仍有协调与 merge 调度分析空间       | 无 Assignee；cetra3 已提供 memory coordinator / merge prototype 分支，其他贡献者也在实验                             | 中高 / **高**                   | 排除，已有积极实现与可靠复现                          |
| [24230](https://github.com/apache/datafusion/issues/24230) spill quota 失败后计数不归零       | 长生命周期进程 spill 容量泄漏                                                         | 无 Assignee；Himanshu-2005-code 明确认领；#24407 因与其工作重复而 closed/unmerged；quota 分支已部分修复              | 低 / **高**                     | 排除，不重演历史重复贡献                              |
| [22189](https://github.com/apache/datafusion/issues/22189) Parquet metrics 内存增长           | 有强实际影响，但新评论已有 heap profile、局部 patch 与 review 意向                    | Assignee xudong963；vaibhavbodhane 表示愿分享/提交 patch；#22406 merged，#22353 closed/unmerged；alamb 已承诺 review | 中 / **高**                     | 排除；与 bootstrap 推荐相比，提高“无人积极实现”的权重 |
| [26705](https://github.com/apache/datafusion/issues/26705) partial aggregate state 未预留内存 | median/array_agg 跨阶段所有权与 memory accounting                                     | 无 Assignee，但 mohitgurav20 明确 `take`；已有 related 测试 PR #26728                                                | 中高 / **高**                   | 排除                                                  |

## 三项深入核查

### 20942 多 distinct 聚合

**状态与已有工作。** [Issue 快照](evidence/issue-20942.json) 无 Assignee、无评论。[#20940](evidence/pr-20940.json) 是原作者的历史 `MultiDistinctToCrossJoin` 实现，2026-05-29 closed/unmerged；它有旧版速度数据，不能将本轮表述为首次发现。[相关 #21088](evidence/pr-21088.json) 面向 grouped 多 distinct，2026-06-02 closed/unmerged，也需承认与参考。按编号、`MultiDistinct` 名称及相关 Issue 扩展检索，未发现当前 open 的同类实现。当前不以“存在旧 PR”推断作者仍在积极实施。

**源码核对。** `optimizer/src/optimizer.rs` 注册 `SingleDistinctToGroupBy`，没有多 distinct 分支规则。`single_distinct_to_groupby.rs::is_single_distinct_agg` 收集不同实参，要求 `fields_set.len() == 1`；两个不同列不会进入该重写。预检 `EXPLAIN` 是 `Final Aggregate -> CoalescePartitions -> Partial Aggregate -> MemTable`。这说明不是“查询完全不并行”：Partial 确实有并行，疑点在 fallback accumulator 路径、状态体积和单分区 Final。

**验证设计。** 通过公开 SQL/API 构造三组：native、拆分为单 distinct 的 CROSS JOIN、相同拆分但关闭 `SingleDistinctToGroupBy`。第三组排除“拆 SQL”与“重写算法”混淆。扫 NDV、partition、数据类型，并检查 NULL、all-NULL、同一实参等控制。工具为 optimized Rust runner、DataFusion operator metrics、`PeakRecordingPool`、`perf`、`/usr/bin/time -v`；数据生成和规划不进入执行计时，无外部数据/集群依赖。

**价值与风险。** 可能揭示低 NDV 与高 NDV、integer 与 string 之间完全不同的收益边界，形成可评审的 cost/gating 证据，而不是再提交一个 blanket rewrite。旧 PR 的扫描重复、NULL/空输入语义和复杂输入子树仍是潜在副作用。用户上限 32 GiB 足够运行几百万行的独立进程对照。

### 23338 sorted aggregation 选择

**负责人核查。** [完整评论](evidence/issue-23338.json) 只有 alamb 的 cost model/stream 优化建议，以及 vukrosic 的条件性调查意向，没有 `take` 或实际实现链接。[补查 PR](evidence/pr-search-23338-retry.json) 无匹配，但搜索本身不能排除未引用 Issue 的实现。因此风险高于 #20942。

**源码核对。** 当前 `physical-plan/src/aggregates/mod.rs` 已使用 `GroupClusteringMode`，并有 clustered partial/final/single stream；文档描述 order-preserving repartition。原 Issue 的 `InputOrderMode::Sorted` 和“必须插入 SortExec”不能直接作为当下根因。应在相同物理 batches 上仅切换排序元数据，复核每一级 plan 的排序要求和具体 stream，而不是额外执行一次排序作为对照。

**验证成本与价值。** Rust `MemTable/TestMemoryExec` 排序属性、最终输出校验、NDV×p 控制和 `perf` 足够，数据 1–4M 行。旧 benchmark 已定位一定结构，因此首轮可能主要证明症状已变化；若确认仍有退化，再区分 merge、stream bookkeeping 与排序成本。没有先选择它，是因为存在贡献意向且代码演化使旧 benchmark 的因果解释更不稳定。

### 21554 Parquet pruning setup 缓存

**负责人核查。** [评论](evidence/issue-21554.json) 指向 kosiew 的 #21566；[实际状态](evidence/pr-21566.json) 为 closed/unmerged。#26438 同样 closed/unmerged，其作者声明不为 bot 发布的代码背书，不视作可直接复用的已验证实现。近期未找到名称匹配的 open PR；历史作者关系仍需在将来实现前协调。

**源码核对。** `datasource-parquet/src/opener/mod.rs` 每文件重写/简化 projection/predicate，并构造 pruning predicates。已有 `benchmarks/benches/parquet_pruning_setup_cache.rs` 生成 128 个相同 schema 的文件，是刻意有利于缓存的基线。历史 focused 结果约 7% 收益，不能外推为 ClickBench 或实际服务收益。

**验证成本与价值。** 需固定输入行数扫描文件数、schema 多样性、predicate 复杂度、dynamic filter 更新频率，用 CPU profile 区分 adaptation/build/evaluation。缓存 key 必须覆盖分区 literal、adapter 状态、schema、表达式与动态版本，错误缓存可影响结果。可本地验证，但已有可信实现和基准，第一轮新增诊断空间小于 #20942，失效正确性的专业门槛更高。

## 最终选择与边界

选择 #20942，基于其无当前认领/积极实现证据、低硬件门槛、可严格校验的一行结果，以及可用三个控制计划区分算法与执行结构。目标是独立确认当前症状、测量适用边界、建立因果解释；不默认历史 PR 的 blanket rewrite 正确或有利。原报告中“不能并行”的说法将用实际计划与 profiler 校正。

最终复现和结论见 [20942/REPORT.md](20942/REPORT.md)。若初始收益不能复现，也保留负结果和反例，不通过调参隐藏不利于假设的数据。正式修复须待本轮分析 Review 后另定，并在提交前再次检查 ownership/PR 状态。
