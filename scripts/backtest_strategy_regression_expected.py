from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

EXCEPTION_PATTERN = re.compile(
    r'^(TypeError|AttributeError|ValueError|IndexError|KeyError|ModuleNotFoundError|ImportError|'
    r'AssertionError|FileNotFoundError|RuntimeError|SyntaxError):'
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Run strategy regression run.py scripts and generate expected.json files.'
    )
    parser.add_argument(
        'target',
        nargs='?',
        default='tests/functional/strategies_regression',
        help='Strategy regression root, category, strategy directory, or run.py path.',
    )
    parser.add_argument('--workers', type=int, default=8, help='Number of parallel workers.')
    parser.add_argument('--timeout', type=int, default=180, help='Timeout per run.py in seconds.')
    parser.add_argument(
        '--keep-result',
        action='store_true',
        help='Keep backtest_result.json after writing expected.json.',
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Overwrite existing expected.json. Without this, existing expected.json is skipped.',
    )
    parser.add_argument(
        '--report',
        default='logs/strategy_regression_expected_generation.json',
        help='Path to write JSON report.',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Optional max number of run.py files to process, useful for smoke checks.',
    )
    return parser.parse_args()


def repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / 'pyproject.toml').exists() and (parent / 'backtrader').is_dir():
            return parent
    raise RuntimeError('Cannot find repository root')


def resolve_target(root: Path, target_text: str) -> Path:
    target = Path(target_text)
    if not target.is_absolute():
        direct = root / target
        if direct.exists():
            return direct.resolve()
        regression_child = root / 'tests/functional/strategies_regression' / target
        if regression_child.exists():
            return regression_child.resolve()
    return target.resolve()


def discover_run_files(target: Path) -> list[Path]:
    if target.is_file():
        if target.name != 'run.py':
            raise ValueError(f'Target file is not run.py: {target}')
        return [target]
    if not target.exists():
        raise FileNotFoundError(target)
    return sorted(target.rglob('run.py'))


def make_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    back_trader = root.parent / 'back_trader'
    pythonpath = [str(root)]
    if back_trader.exists():
        pythonpath.append(str(back_trader))
    existing = env.get('PYTHONPATH')
    if existing:
        pythonpath.append(existing)
    env['PYTHONPATH'] = os.pathsep.join(item for item in pythonpath if item)
    return env


def extract_root_error(stderr: str) -> str:
    for line in reversed(stderr.splitlines()):
        stripped = line.strip()
        if EXCEPTION_PATTERN.match(stripped):
            return stripped
    return ''


def tail(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[-limit:]


def normalize_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): normalize_json_value(val) for key, val in value.items()}
    if isinstance(value, list):
        return [normalize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [normalize_json_value(item) for item in value]
    return value


def read_result(result_path: Path) -> Any:
    return normalize_json_value(json.loads(result_path.read_text(encoding='utf-8')))


def standard_expected_payload(payload: Any) -> dict[str, Any]:
    from strategies.benchmark_metrics import BENCHMARK_METRIC_KEYS, canonicalize_metric_payload

    metrics = canonicalize_metric_payload(payload, engine='python')
    if not metrics:
        metrics = canonicalize_metric_payload({'metrics': payload}, engine='python')
    return {key: normalize_json_value(metrics.get(key)) for key in BENCHMARK_METRIC_KEYS}


def run_one(run_py: Path, root: Path, timeout: int, keep_result: bool, overwrite: bool) -> dict[str, Any]:
    started = time.time()
    strategy_dir = run_py.parent
    result_path = strategy_dir / 'backtest_result.json'
    expected_path = strategy_dir / 'expected.json'
    original_result = result_path.read_text(encoding='utf-8') if result_path.exists() else None

    if expected_path.exists() and not overwrite:
        return {
            'path': str(run_py.relative_to(root)),
            'status': 'skipped_existing',
            'seconds': round(time.time() - started, 3),
        }

    try:
        process = subprocess.run(
            [sys.executable, str(run_py)],
            cwd=str(strategy_dir),
            env=make_env(root),
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if process.returncode != 0:
            return {
                'path': str(run_py.relative_to(root)),
                'status': 'failed',
                'returncode': process.returncode,
                'seconds': round(time.time() - started, 3),
                'root_error': extract_root_error(process.stderr),
                'stdout_tail': tail(process.stdout, 1500),
                'stderr_tail': tail(process.stderr, 5000),
            }
        if not result_path.exists():
            return {
                'path': str(run_py.relative_to(root)),
                'status': 'missing_result',
                'returncode': process.returncode,
                'seconds': round(time.time() - started, 3),
                'stdout_tail': tail(process.stdout, 1500),
                'stderr_tail': tail(process.stderr, 5000),
            }
        payload = standard_expected_payload(read_result(result_path))
        expected_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )
        return {
            'path': str(run_py.relative_to(root)),
            'status': 'written',
            'expected_path': str(expected_path.relative_to(root)),
            'seconds': round(time.time() - started, 3),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode('utf-8', 'replace') if isinstance(exc.stdout, bytes) else (exc.stdout or '')
        stderr = exc.stderr.decode('utf-8', 'replace') if isinstance(exc.stderr, bytes) else (exc.stderr or '')
        return {
            'path': str(run_py.relative_to(root)),
            'status': 'timeout',
            'returncode': 124,
            'seconds': round(time.time() - started, 3),
            'root_error': 'TimeoutExpired',
            'stdout_tail': tail(stdout, 1500),
            'stderr_tail': tail(stderr, 5000),
        }
    except Exception as exc:
        return {
            'path': str(run_py.relative_to(root)),
            'status': 'error',
            'seconds': round(time.time() - started, 3),
            'root_error': f'{type(exc).__name__}: {exc}',
        }
    finally:
        if not keep_result:
            if original_result is None:
                if result_path.exists():
                    result_path.unlink()
            else:
                result_path.write_text(original_result, encoding='utf-8')


def write_report(report_path: Path, payload: dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> int:
    args = parse_args()
    root = repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    target = resolve_target(root, args.target)
    run_files = discover_run_files(target)
    if args.limit is not None:
        run_files = run_files[: args.limit]

    report_path = (root / args.report).resolve() if not Path(args.report).is_absolute() else Path(args.report)
    print(f'repo_root: {root}', flush=True)
    print(f'target: {target}', flush=True)
    print(f'run.py files: {len(run_files)} workers={args.workers} timeout={args.timeout}', flush=True)

    started = time.time()
    results: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    with futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {
            executor.submit(run_one, run_py, root, args.timeout, args.keep_result, args.overwrite): run_py
            for run_py in run_files
        }
        for idx, future in enumerate(futures.as_completed(future_map), 1):
            item = future.result()
            results.append(item)
            counts[item['status']] += 1
            if idx % 25 == 0 or idx == len(run_files):
                summary = ' '.join(f'{key}={counts[key]}' for key in sorted(counts))
                print(f'PROGRESS completed={idx} {summary} elapsed={round(time.time() - started, 1)}', flush=True)

    results.sort(key=lambda item: item['path'])
    failures = [item for item in results if item['status'] in {'failed', 'timeout', 'missing_result', 'error'}]
    payload = {
        'target': str(target),
        'total': len(results),
        'counts': dict(counts),
        'failure_count': len(failures),
        'failures': failures,
        'results': results,
    }
    write_report(report_path, payload)
    print(f'REPORT {report_path}', flush=True)
    print(f'COUNTS {dict(counts)}', flush=True)
    if failures:
        root_errors = Counter(item.get('root_error') or item['status'] for item in failures)
        for root_error, count in root_errors.most_common(30):
            print(f'ROOT {count}: {root_error}', flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
