#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: See the NOTICE file distributed with this work for additional information regarding copyright ownership
# SPDX-FileContributor: Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements
"""Summarize captured measurements without treating repeated samples as independent hosts."""

import csv
import json
from collections import defaultdict
from pathlib import Path
import statistics
import sys


def main():
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / 'evidence' / 'matrix'
    groups = defaultdict(list)
    for path in sorted(directory.glob('*.jsonl')):
        for line in path.read_text().splitlines():
            record = json.loads(line)
            if record['warmup']:
                continue
            key = tuple(record[k] for k in ('kind', 'rows', 'cardinality', 'partitions', 'columns', 'null_every', 'mode'))
            record['process'] = path.name
            groups[key].append(record)
    rows = []
    for key, records in sorted(groups.items()):
        times = [r['execution_ms'] for r in records]
        final_merges, updates = [], []
        for r in records:
            metrics = [m for node in r['node_metrics'] for m in node['metrics']]
            final_merges.append(sum(m['value'] for m in metrics if m['name'].endswith('_merge_time')) / 1e6)
            updates.append(sum(m['value'] for m in metrics if m['name'].endswith('_update_time')) / 1e6)
        rows.append(dict(
            zip(('kind', 'rows', 'cardinality', 'partitions', 'columns', 'null_every', 'mode'), key),
            samples=len(times), processes=len({r['process'] for r in records}),
            median_ms=statistics.median(times), min_ms=min(times), max_ms=max(times),
            median_pool_peak_mib=statistics.median(r['pool_peak_bytes'] for r in records) / 2**20,
            max_process_rss_mib=max(r['process_peak_rss_kib'] for r in records) / 1024,
            final_merge_sum_ms=statistics.median(final_merges),
            update_sum_ms=statistics.median(updates),
        ))
    assert rows, f'No completed measurements in {directory}'
    with (directory / 'summary.csv').open('w', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (directory / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
    for row in rows:
        print(f"{row['kind']:4} d={row['cardinality']:7} p={row['partitions']} "
              f"null={row['null_every']:2} {row['mode']:16}: "
              f"{row['median_ms']:8.2f} ms [{row['min_ms']:.2f}, {row['max_ms']:.2f}], "
              f"pool {row['median_pool_peak_mib']:.2f} MiB, merge {row['final_merge_sum_ms']:.2f} ms")


if __name__ == '__main__':
    main()
