#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: See the NOTICE file distributed with this work for additional information regarding copyright ownership
# SPDX-FileContributor: Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements
"""Run isolated, alternating SQL controls; retain raw JSON and OS measurements."""

import argparse
import json
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', default='/tmp/infralab-datafusion/target/release/infralab-distinct-probe')
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'evidence' / 'matrix')
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--view', action='store_true', help='Confirm the string-view type separately')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = []
    if args.view:
        configurations = [
            (2000000, cardinality, p, 'view', 0)
            for cardinality in (200000, 2000000) for p in (1, 4)
        ]
        rounds, iterations = 2, 3
    elif args.quick:
        configurations = [(200000, 20000, 4, 'i64', 0)]
        rounds, iterations = 1, 2
    else:
        configurations = [
            (2000000, cardinality, p, kind, 0)
            for kind in ('i64', 'utf8')
            for cardinality in (128, 200000, 2000000)
            for p in (1, 4)
        ]
        configurations += [
            (2000000, 200000, p, 'utf8', 0) for p in (2, 6)
        ]
        configurations += [(200000, 20000, 4, 'i64', n) for n in (1, 17)]
        rounds, iterations = 2, 3
    for rows, cardinality, p, kind, null_every in configurations:
        for round_index in range(rounds):
            modes = ['native', 'split', 'split_no_rewrite']
            if round_index % 2:
                modes.reverse()
            for mode in modes:
                cases.append((rows, cardinality, p, kind, null_every, round_index, mode))
    for i, (rows, cardinality, p, kind, null_every, round_index, mode) in enumerate(cases):
        label = f'{kind}_n{rows}_d{cardinality}_p{p}_null{null_every}_{mode}_r{round_index}'
        command = [
            '/usr/bin/time', '-v', '-o', str(args.output / f'{label}.time.txt'),
            'taskset', '-c', '0-5', args.binary,
            '--rows', str(rows), '--cardinality', str(cardinality),
            '--partitions', str(p), '--kind', kind, '--mode', mode,
            '--null-every', str(null_every), '--iterations', str(iterations),
        ]
        meta = {'command': command, 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        start = time.monotonic()
        with (args.output / f'{label}.jsonl').open('w') as stdout, (args.output / f'{label}.stderr.txt').open('w') as stderr:
            result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=180, check=False)
        meta.update(exit_code=result.returncode, process_wall_s=time.monotonic() - start)
        (args.output / f'{label}.command.json').write_text(json.dumps(meta, indent=2) + '\n')
        if result.returncode:
            raise RuntimeError(f'{label}: exit {result.returncode}; inspect captured stderr')
        records = [json.loads(line) for line in (args.output / f'{label}.jsonl').read_text().splitlines()]
        assert len(records) == iterations + 1
        assert all(record['result'] == records[0]['result'] for record in records)
        timings = ', '.join(format(r['execution_ms'], '.2f') for r in records if not r['warmup'])
        print(f'{i+1}/{len(cases)} {label}: {timings}', flush=True)


if __name__ == '__main__':
    main()
