#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: See the NOTICE file distributed with this work for additional information regarding copyright ownership
# SPDX-FileContributor: Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements
"""Check all saved unprofiled query outputs with a Python domain oracle."""

import json
from pathlib import Path

base = Path(__file__).parent / 'evidence'
summary = {}
for group in ('quick', 'matrix', 'controls', 'view', 'final-smoke'):
    files = sorted((base / group).glob('*.jsonl'))
    assert files, group
    total = measured = 0
    max_rss = 0
    for file in files:
        records = [json.loads(line) for line in file.read_text().splitlines()]
        assert records and records[0]['warmup']
        for r in records:
            n, d, null_every = r['rows'], r['cardinality'], r['null_every']
            if null_every == 0:
                expected = [min(n, d)] * r['columns']
            elif null_every == 1:
                expected = [0] * r['columns']
            else:
                expected = [len({(row + 7*c) % d for row in range(n) if row % null_every}) for c in range(r['columns'])]
            if r['mode'] == 'same_argument':
                expected = [expected[0]] * r['columns']
            assert r['result'] == expected, (file, r['iteration'], r['result'], expected)
            assert r['pool_peak_bytes'] < 4 * 2**30
            assert r['execution_ms'] >= 0
            assert not any(m['value'] for node in r['node_metrics'] for m in node['metrics'] if m['name'] == 'spill_count')
            total += 1
            measured += not r['warmup']
            max_rss = max(max_rss, r['process_peak_rss_kib'])
    summary[group] = {'processes': len(files), 'records': total, 'measured': measured, 'max_process_peak_rss_kib': max_rss}
print(json.dumps(summary, indent=2))
