"""Retain focused, non-model readiness suites after native setup is idle."""
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from development.core import file_hash, write_new


def main():
    if json.loads((ROOT / 'state/launch/status.json').read_text())['status'] != 'awaiting_exact_owner_readiness_no_inference':
        raise RuntimeError('readiness regressions require parked launcher')
    out = ROOT / 'setup/readiness-regressions-01'
    out.mkdir(parents=True, exist_ok=False)
    suites = [('development_core', 'tests/development', 'test_core.py'),
              ('development_synthetic', 'tests/development', 'test_native_synthetic.py'),
              ('owner', 'tests/owner', 'test_*.py'),
              ('runtime', 'tests/runtime', 'test_*.py'),
              ('audit', 'tests/audit', 'test_*.py'),
              ('evaluation', 'tests/evaluation', 'test_*.py')]
    report = {'status': 'running', 'stage': 'v3_setup_regressions', 'model_calls': 0,
              'started_unix': time.time(), 'script_sha256': file_hash(__file__), 'suites': []}
    try:
        for name, directory, pattern in suites:
            argv = [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', directory, '-p', pattern, '-v']
            log = out / (name + '.log')
            with log.open('xb') as stream:
                result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False)
            matches = re.findall(r'Ran (\d+) tests? in', log.read_text())
            row = {'name': name, 'argv': argv, 'status': 'pass' if result.returncode == 0 else 'fail',
                   'returncode': result.returncode, 'tests_reported': int(matches[-1]) if matches else None,
                   'log': str(log.relative_to(ROOT)), 'log_sha256': file_hash(log)}
            report['suites'].append(row)
            print(json.dumps(row), flush=True)
            if result.returncode or not matches:
                raise RuntimeError('readiness suite failed or did not report tests: ' + name)
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
