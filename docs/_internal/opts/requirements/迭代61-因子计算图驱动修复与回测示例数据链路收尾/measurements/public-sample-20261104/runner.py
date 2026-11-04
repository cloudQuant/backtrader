"""Offline preregistered local sample runner; launched only under profile.sb."""
from __future__ import annotations

import argparse
import copy
import gc
import hashlib
import importlib.util
import importlib.metadata
import json
import os
import platform
from pathlib import Path
import sys
import time

ROOT = Path('/Users/yunjinqi/Documents/new_projects/backtrader')
DATA = ROOT / 'tests/datas/a_stocks'
WORK = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def source_paths():
    paths = sorted((ROOT / 'backtrader').rglob('*.py'))
    for directory in ('025_factor_single', '026_factor_multi', '027_alpha003_panel_acceptance'):
        paths.extend(sorted((ROOT / 'examples/backtest' / directory).glob('*.py')))
    paths.append(ROOT / 'tests/unit/test_iter61_example_modes.py')
    return sorted(set(paths))


def input_paths():
    metadata = DATA / '_metadata'
    paths = {metadata / 'manifest.json', metadata / 'observed_calendar.csv'}
    for selected in selection().values():
        for entry in selected:
            paths.add(DATA / entry['file'])
    return sorted(paths)


def selection():
    manifest = json.loads((DATA / '_metadata/manifest.json').read_text(encoding='utf-8'))
    entries = list(manifest['output']['symbols'])
    selected = {}
    for count in (4, 20):
        step = len(entries) / float(count)
        selected[str(count)] = [
            {'index': int(i * step), 'symbol': entries[int(i * step)]['symbol'],
             'file': entries[int(i * step)]['file']}
            for i in range(count)
        ]
    return selected


def file_hashes(paths):
    return {str(p): sha(p) for p in paths}


def preregistration():
    versions = {}
    origins = {}
    for package in ('backtrader', 'numpy', 'pandas', 'fincore'):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = 'NOT_INSTALLED'
        spec = importlib.util.find_spec(package)
        origins[package] = None if spec is None else spec.origin
    return {
        'source_sha256': file_hashes(source_paths()),
        'input_sha256': file_hashes(input_paths()),
        'selection': selection(),
        'harness_sha256': sha(Path(__file__)),
        'sandbox_sha256': sha(WORK / 'profile.sb'),
        'launch_sha256': sha(WORK / 'launch.sh'),
        'probe_sha256': sha(WORK / 'probe.py'),
        'environment': {'python': sys.executable, 'python_version': sys.version,
                        'platform': platform.platform(), 'distributions': versions,
                        'module_origins': origins},
        'sample': {'smoke': {'assets': 4, 'sessions': 243}, 'full': {'assets': 20, 'sessions': 243}},
        'modes': ['native', 'build'], 'loops': ['runonce', 'runnext'],
        'scope': 'local current source and public daily sample; not the historical 500-asset baseline',
    }


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def execute(stage):
    registered = json.loads((WORK / 'preregister.json').read_text(encoding='utf-8'))
    current = preregistration()
    if registered != current:
        raise RuntimeError('source, harness, profile or input hashes changed; re-register before running')
    if stage == 'full':
        smoke = json.loads((WORK / 'smoke/results.json').read_text(encoding='utf-8'))
        if smoke.get('passed') is not True:
            raise RuntimeError('a passing registered smoke run is required before the full run')
    import numpy as np
    import pandas as pd
    import backtrader as bt
    import backtrader.research as research
    from backtrader.errors import DependencyError

    def evaluation_unavailable(*args, **kwargs):
        raise DependencyError('offline sample run: research evaluation intentionally unavailable')
    research.evaluate_frames = evaluation_unavailable
    helpers = load('iter61_local_helpers', ROOT / 'tests/unit/test_iter61_example_modes.py')
    count = current['sample'][stage]['assets']
    results = {'stage': stage, 'python': sys.executable, 'python_version': sys.version,
               'backtrader_path': bt.__file__, 'numpy': np.__version__, 'pandas': pd.__version__,
               'source_sha256': current['source_sha256'], 'input_sha256': current['input_sha256'],
               'runs': [], 'comparisons': []}
    target = WORK / stage
    target.mkdir(exist_ok=False)
    for key in ('025', '026', '027'):
        frames = {}
        for mode in ('native', 'build'):
            for runnext in (False, True):
                if preregistration() != registered:
                    raise RuntimeError('registered sources or inputs changed before a run')
                label = f'{key}-{mode}-{int(runnext)}'
                runner = helpers.load_runner(key)
                cfg = helpers.config_for(runner, DATA)
                cfg['factor_mode'] = mode
                cfg['data']['max_symbols'] = count
                runner._load_config = lambda cfg=cfg: copy.deepcopy(cfg)
                coverage = []
                method = '_run_factor' if key == '027' else '_run_native_collection'
                original = getattr(runner, method)
                def capture(*args, _original=original, **kwargs):
                    output = _original(*args, **kwargs)
                    strategy, panel = output[:2]
                    for name, instances in strategy._factor_instances_by_name.items():
                        for instance in instances:
                            diag = instance.lifecycle_diagnostics
                            coverage.append({'factor': name, 'matches': bool(diag['coverage_matches']),
                                             'coverage_count': int(diag['coverage_count']),
                                             'grid_count': int(diag['grid_count'])})
                    return output
                setattr(runner, method, capture)
                sys.path.insert(0, str(helpers.RUNNERS[key].parent))
                output = target / label
                args = ['--output-dir', str(output), '--data-dir', str(DATA), '--max-symbols', str(count), '--factor-mode', mode]
                if key != '027':
                    args.extend(['--asset-batch-size', '0'])
                if runnext:
                    args.append('--runnext')
                start = time.perf_counter()
                record = {'key': key, 'mode': mode, 'loop': 'runnext' if runnext else 'runonce', 'args': args}
                try:
                    code = runner.main(args)
                    if preregistration() != registered:
                        raise RuntimeError('registered sources or inputs changed during a run')
                    record.update(exit=code, seconds=round(time.perf_counter() - start, 6), coverage=coverage)
                    if code == 0:
                        summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
                        frame = pd.read_csv(output / 'factor_values.csv')
                        names = helpers.NAMES[key]
                        stats = {}
                        for name in names:
                            values = pd.to_numeric(frame[name], errors='raise').to_numpy(dtype=float)
                            finite, nan, inf = np.isfinite(values), np.isnan(values), np.isinf(values)
                            stats[name] = {'finite': int(finite.sum()), 'nan': int(nan.sum()), 'inf': int(inf.sum()),
                                           'nan_mask_sha256': hashlib.sha256(nan.tobytes()).hexdigest()}
                        record.update(summary=summary, columns=stats, rows=len(frame), output_sha256=sha(output / 'factor_values.csv'))
                        record['checks'] = {
                            'dimensions': summary.get('symbols') == count and summary.get('dates') == 243 and len(frame) == count * 243,
                            'zero_broker': summary.get('broker') == {'submit': 0, 'cancel': 0},
                            'factor_mode': summary.get('factor_mode') == mode and summary.get('factor_calculation') == 'RAN',
                            'status': summary.get('status') == ('COMPLETED' if key == '027' else 'PANEL_ONLY'),
                            'coverage': bool(coverage) and all(x['matches'] and x['coverage_count'] == x['grid_count'] == 243 for x in coverage),
                            'finite_and_no_inf': all(s['finite'] > 0 and s['inf'] == 0 for s in stats.values()),
                            'keys_unique': not frame.duplicated(['time', 'asset']).any(),
                        }
                        frames[(mode, runnext)] = frame
                except Exception as exc:
                    record['exception'] = f'{type(exc).__name__}: {exc}'
                results['runs'].append(record)
                (target / 'results.json').write_text(json.dumps(results, indent=2, ensure_ascii=False))
                gc.collect()
        baseline = frames.get(('native', False))
        if baseline is not None:
            for variant, frame in frames.items():
                same_keys = baseline[['time', 'asset']].equals(frame[['time', 'asset']])
                columns = {}
                for name in helpers.NAMES[key]:
                    a = pd.to_numeric(baseline[name], errors='raise').to_numpy(dtype=float)
                    b = pd.to_numeric(frame[name], errors='raise').to_numpy(dtype=float)
                    columns[name] = {'nan_mask_equal': bool(np.array_equal(np.isnan(a), np.isnan(b))),
                                     'values_close': bool(a.shape == b.shape and np.allclose(a, b, rtol=1e-12, atol=1e-12, equal_nan=True))}
                results['comparisons'].append({'key': key, 'variant': str(variant), 'keys_equal': bool(same_keys), 'columns': columns})
        (target / 'results.json').write_text(json.dumps(results, indent=2, ensure_ascii=False))
    passed = len(results['runs']) == 12 and all(r.get('exit') == 0 and bool(r.get('checks')) and not r.get('exception') and all(r['checks'].values()) for r in results['runs'])
    passed = passed and len(results['comparisons']) == 12 and all(c['keys_equal'] and all(v['nan_mask_equal'] and v['values_close'] for v in c['columns'].values()) for c in results['comparisons'])
    results['passed'] = bool(passed)
    (target / 'results.json').write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print('PASS' if passed else 'FAIL', target / 'results.json')
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('register', 'smoke', 'full'))
    action = parser.parse_args().action
    if action == 'register':
        p = WORK / 'preregister.json'
        if p.exists():
            raise SystemExit('registration already exists; create a new temporary directory')
        p.write_text(json.dumps(preregistration(), indent=2, ensure_ascii=False), encoding='utf-8')
        print(p)
        return 0
    return execute(action)


if __name__ == '__main__':
    raise SystemExit(main())
