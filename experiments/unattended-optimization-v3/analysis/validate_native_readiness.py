"""Fresh v3 setup controls, only while the model launcher is parked. No inference."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from development.core import file_hash, write_new
from development.prepare import prepare_native
from evaluation.prepare import prepare


def main():
    status = json.loads((ROOT / 'state/launch/status.json').read_text())
    if status['status'] != 'awaiting_exact_owner_readiness_no_inference':
        raise RuntimeError('native readiness controls require the parked, inference-free launcher')
    out = ROOT / 'setup/fresh-native-readiness-01'
    out.mkdir(parents=True, exist_ok=False)
    report = {'stage': 'v3_setup_not_measured_campaign', 'status': 'running',
              'started_unix': time.time(), 'model_calls': 0, 'steps': [],
              'script_sha256': file_hash(__file__)}
    try:
        prepare_native(ROOT, ROOT / 'setup/native-validation-01')
        report['steps'].append({'name': 'fresh_native_preparation', 'status': 'pass'})
        prepare(ROOT / 'setup/final-fixtures-preparation',
                ROOT / 'development/native/definitions.draft.json')
        report['steps'].append({'name': 'fresh_final_fixture_preparation', 'status': 'pass'})
        commands = [
            ('evaluator_controls', [sys.executable, '-B', '-m', 'evaluation.validate_setup',
                                   '--output', 'setup/evaluator-controls-01']),
            ('guard_controls', [sys.executable, '-B', 'tests/evaluation/validate_guard_controls.py']),
            ('native_build_repair_and_guard_pages', [sys.executable, '-B', 'tests/development/test_native.py']),
        ]
        for name, argv in commands:
            current = json.loads((ROOT / 'state/launch/status.json').read_text())
            if current['status'] != 'awaiting_exact_owner_readiness_no_inference':
                raise RuntimeError('launcher left parked state before setup controls completed')
            started = time.time()
            log = out / (name + '.log')
            with log.open('xb') as stream:
                result = subprocess.run(argv, cwd=ROOT, stdout=stream,
                                        stderr=subprocess.STDOUT, check=False)
            row = {'name': name, 'argv': argv, 'status': 'pass' if result.returncode == 0 else 'fail',
                   'returncode': result.returncode, 'started_unix': started,
                   'finished_unix': time.time(), 'log': str(log.relative_to(ROOT)),
                   'log_sha256': file_hash(log)}
            report['steps'].append(row)
            print(json.dumps(row), flush=True)
            if result.returncode:
                raise RuntimeError('fresh native setup control failed: ' + name)
        report['status'] = 'pass'
    except BaseException as exc:
        report.update(status='fail', error_category=type(exc).__name__, error=str(exc))
        raise
    finally:
        report['finished_unix'] = time.time()
        write_new(out / 'result.json', report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
