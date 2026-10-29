#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: See the NOTICE file distributed with this work for additional information regarding copyright ownership
# SPDX-FileContributor: Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements
"""Single-expression ablation: identical SQL, only one optimizer rule differs."""

import json
from pathlib import Path
import subprocess
import time

base = Path(__file__).parent / 'evidence' / 'controls'
base.mkdir(parents=True, exist_ok=True)
binary = '/tmp/infralab-datafusion/target/release/infralab-distinct-probe'
for kind in ('i64', 'utf8'):
    for p in (1, 4):
        for round_index in range(2):
            modes = ['split', 'split_no_rewrite']
            if round_index % 2:
                modes.reverse()
            for mode in modes:
                label = f'{kind}_c1_n2000000_d2000000_p{p}_{mode}_r{round_index}'
                command = [
                    '/usr/bin/time', '-v', '-o', str(base / f'{label}.time.txt'),
                    'taskset', '-c', '0-5', binary,
                    '--rows', '2000000', '--cardinality', '2000000',
                    '--columns', '1', '--partitions', str(p), '--kind', kind,
                    '--mode', mode, '--iterations', '5',
                ]
                with (base / f'{label}.jsonl').open('w') as output, (base / f'{label}.stderr.txt').open('w') as error:
                    subprocess.run(command, stdout=output, stderr=error, check=True, timeout=180)
                (base / f'{label}.command.json').write_text(json.dumps({'command': command, 'finished_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}, indent=2) + '\n')
                print(label, flush=True)

# Same-expression control: the three SQL outputs share one distinct argument.
for kind in ('i64', 'utf8'):
    label = f'{kind}_c3_same_argument'
    command = ['taskset', '-c', '0-5', binary, '--rows', '2000000',
               '--cardinality', '2000000', '--columns', '3', '--partitions', '4',
               '--kind', kind, '--mode', 'same_argument', '--iterations', '5']
    with (base / f'{label}.jsonl').open('w') as output:
        subprocess.run(command, stdout=output, check=True, timeout=180)
    (base / f'{label}.command.json').write_text(json.dumps({'command': command}, indent=2) + '\n')
    print(label, flush=True)
