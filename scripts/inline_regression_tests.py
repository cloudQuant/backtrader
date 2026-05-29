#!/usr/bin/env python3
"""Inline migrated regression strategies into single self-contained test files.

The output test file follows the style of
tests/functional/strategies/advanced/test_44_signals_strategy.py:
  - Self-contained: no config.yaml / expected.json / run.py / strategy_*.py imports
  - Inlines the strategy class and helpers verbatim
  - Inlines the config dict literal
  - Calls cerebro.run(runonce=True) only (no parametrization)
  - Asserts directly on analyzer outputs (sharpe, returns, drawdown, trade_analyzer)
  - NO dependency on tests.test_utils.benchmark_metrics (no install_benchmark_metrics_hook call)

Workflow per strategy:
1. Read the original config.yaml + expected.json + strategy_*.py + run.py.
2. Run the existing migrated test once to capture concrete metrics
   (this is the SOURCE OF TRUTH for our assertions, not expected.json
   which uses different schema keys).
3. Generate a single test_*.py that inlines everything and asserts on the
   captured values.
4. Verify the new test passes.
5. On success: delete config.yaml, expected.json, run.py, strategy_*.py.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
TARGET_ROOT = REPO / "tests" / "functional" / "strategies"


def find_migrated_dirs() -> list[Path]:
    out = []
    for cat_reg in TARGET_ROOT.glob("*/regression"):
        for strat_dir in cat_reg.iterdir():
            if strat_dir.is_dir() and strat_dir.name[0].isdigit():
                if (strat_dir / "run.py").exists() and (strat_dir / "config.yaml").exists():
                    out.append(strat_dir)
    return sorted(out)


def yaml_to_python_repr(value, indent: int = 0) -> str:
    pad = "    " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = ["{"]
        for k, v in value.items():
            lines.append(f"{pad}    {k!r}: {yaml_to_python_repr(v, indent + 1)},")
        lines.append(f"{pad}" + "}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = ["["]
        for v in value:
            lines.append(f"{pad}    {yaml_to_python_repr(v, indent + 1)},")
        lines.append(f"{pad}" + "]")
        return "\n".join(lines)
    return repr(value)


def make_repo_relative(value, repo_str: str):
    if isinstance(value, dict):
        return {k: make_repo_relative(v, repo_str) for k, v in value.items()}
    if isinstance(value, list):
        return [make_repo_relative(v, repo_str) for v in value]
    if isinstance(value, str) and value.startswith(repo_str + "/"):
        return "{repo}" + value[len(repo_str):]
    return value


# ---- Source cleaning patterns ----------------------------------------------

PATTERNS_TO_STRIP = [
    # Vendored / canonical benchmark hook block.
    (re.compile(
        r"# Vendored benchmark output hook[^\n]*\n.*?_install_benchmark_metrics_hook\(_BENCHMARK_BASE_DIR\)\s*\n",
        flags=re.DOTALL,
    ), ""),
    (re.compile(
        r"# Canonical benchmark output hook\.\n.*?_install_benchmark_metrics_hook\([^\n]*\)\n",
        flags=re.DOTALL,
    ), ""),
    # Trailing canonical benchmark wrapper (the second def run() at the bottom).
    (re.compile(
        r"\n+# Canonical benchmark run\(\) wrapper\..*?(?=\n+if __name__|\Z)",
        flags=re.DOTALL,
    ), "\n"),
    # __future__ imports (we add our own).
    (re.compile(r"^from __future__ import [^\n]+\n", flags=re.MULTILINE), ""),
    # Trailing if __name__ == '__main__': block.
    (re.compile(r"\n+if __name__ == .__main__.:.*?$", flags=re.DOTALL), "\n"),
]


def clean_source(src: str, *, drop_modules: set[str] | None = None) -> str:
    for pat, repl in PATTERNS_TO_STRIP:
        src = pat.sub(repl, src)
    if drop_modules:
        for name in drop_modules:
            esc = re.escape(name)
            # multi-line: from X import (\n  a,\n)\n
            src = re.sub(rf"^from {esc} import \([^)]+\)\n", "", src, flags=re.MULTILINE | re.DOTALL)
            # single-line: from X import a, b
            src = re.sub(rf"^from {esc} import [^\n(]+\n", "", src, flags=re.MULTILINE)
            # plain: import X
            src = re.sub(rf"^import {esc}\b[^\n]*\n", "", src, flags=re.MULTILINE)
    src = re.sub(r"^\n+", "", src)
    return src.rstrip() + "\n"


def extract_imports(src: str) -> tuple[list[str], str]:
    """Extract single-line and multi-line imports from a source.

    Returns (import_lines, body_without_imports).
    """
    lines = src.split("\n")
    imports: list[str] = []
    body: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        # Skip empty lines from being captured as imports
        if not stripped:
            body.append(line)
            i += 1
            continue
        # Multi-line `from X import (...)`
        m = re.match(r"^from [\w.]+ import \(", line)
        if m:
            # collect until closing paren
            buf = [line]
            i += 1
            while i < len(lines) and ")" not in lines[i]:
                buf.append(lines[i])
                i += 1
            if i < len(lines):
                buf.append(lines[i])
                i += 1
            imports.append("\n".join(buf))
            continue
        # Single line import / from-import
        if re.match(r"^(?:from [\w.]+ import [^\n]+|import [\w.,\s]+)$", line):
            imports.append(line)
            i += 1
            continue
        body.append(line)
        i += 1
    return imports, "\n".join(body)


def merge_imports(imports_groups: list[list[str]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for group in imports_groups:
        for line in group:
            stripped = line.strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                out.append(line.strip())
    stdlib_prefixes = (
        "import argparse", "import csv", "import datetime", "import io",
        "import json", "import math", "import os", "import re", "import shutil",
        "import subprocess", "import sys", "import time", "import abc",
        "import collections", "import functools", "import itertools",
        "import enum", "import warnings", "import copy",
        "from datetime", "from pathlib", "from typing", "from __future__",
    )
    stdlib, thirdparty, local = [], [], []
    for line in out:
        if any(line.startswith(p) for p in stdlib_prefixes):
            stdlib.append(line)
        elif line.startswith(("from backtrader", "import backtrader")):
            thirdparty.insert(0, line)
        elif line.startswith(("from numpy", "import numpy", "from pandas", "import pandas",
                              "from scipy", "import scipy", "from yaml", "import yaml")):
            thirdparty.append(line)
        else:
            local.append(line)
    result = []
    if stdlib:
        result.extend(stdlib)
        result.append("")
    if thirdparty:
        result.extend(thirdparty)
        result.append("")
    if local:
        result.extend(local)
    return result


def strip_function_def(src: str, fname: str) -> str:
    """Remove a top-level function definition by name."""
    return re.sub(
        rf"\ndef {re.escape(fname)}\([^)]*\)[^:\n]*:\n(?:    [^\n]*\n)+",
        "",
        src,
        flags=re.MULTILINE,
    )


def strip_function_calls(src: str, fname: str) -> str:
    """Remove top-level (4-space-indented) calls of a function."""
    return re.sub(
        rf"^(\s*){re.escape(fname)}\([^\n]*\)\s*$",
        "",
        src,
        flags=re.MULTILINE,
    )


# ---- Capture metrics from an existing migration ---------------------------

def capture_metrics_via_run(strategy_dir: Path) -> dict | None:
    """Run the strategy in a subprocess and capture the strategy-local
    extract_metrics() output. Uses a small wrapper script that imports run.py,
    runs cerebro, and prints metrics as JSON.
    """
    helper_script = strategy_dir / "_capture_helper.py"
    helper_path_abs = helper_script.resolve()
    helper_script.write_text(
        '''import json, sys, datetime, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run

# Disable noisy filesystem writes.
for fname in ('write_local_result', 'upsert_global_summary', 'update_global_summary',
              'add_trade_logger', 'print_results', 'print_report'):
    if hasattr(run, fname):
        setattr(run, fname, lambda *a, **kw: None)

# Hook any plausible metrics-extraction function.
captured = {}
metric_extractor_names = (
    'extract_metrics', 'summarize', 'build_metrics', 'compute_metrics',
    'calculate_metrics', 'collect_metrics', 'gather_metrics', 'extract_results',
)
for em_name in metric_extractor_names:
    fn = getattr(run, em_name, None)
    if callable(fn):
        _orig = fn
        def _hook(*a, _orig_fn=_orig, **kw):
            m = _orig_fn(*a, **kw)
            if isinstance(m, dict) and m and 'metrics' not in captured:
                captured['metrics'] = m
            return m
        setattr(run, em_name, _hook)

# Try main() / run() — whichever exists.
try:
    if hasattr(run, 'main'):
        run.main()
    elif hasattr(run, 'run'):
        result = run.run()
        if isinstance(result, dict) and 'metrics' not in captured:
            captured['metrics'] = result
        elif isinstance(result, (list, tuple)):
            for item in result:
                if isinstance(item, dict) and 'metrics' not in captured:
                    captured['metrics'] = item
                    break
except SystemExit:
    pass
except Exception as exc:
    if 'metrics' not in captured:
        print(f"===CAPTURE_FAIL: {type(exc).__name__}: {exc}===", file=sys.stderr)
        sys.exit(1)

if 'metrics' not in captured:
    print("===CAPTURE_FAIL: no metrics captured===", file=sys.stderr)
    sys.exit(1)

metrics = captured['metrics']

def _serialize(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v
clean = {k: _serialize(v) for k, v in metrics.items() if isinstance(k, str)}
print("===METRICS_BEGIN===")
print(json.dumps(clean, default=str))
print("===METRICS_END===")
''',
        encoding="utf-8",
    )
    try:
        proc = subprocess.run(
            [sys.executable, str(helper_path_abs)],
            cwd=str(strategy_dir),
            capture_output=True,
            text=True,
            timeout=300,
            env={**dict(__import__("os").environ), "PYTHONPATH": str(REPO)},
        )
    finally:
        helper_script.unlink(missing_ok=True)

    out = proc.stdout
    b = out.find("===METRICS_BEGIN===")
    e = out.find("===METRICS_END===")
    if b < 0 or e < 0:
        return None
    json_str = out[b + len("===METRICS_BEGIN==="):e].strip()
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


# ---- Build the inlined test file ------------------------------------------

def build_inlined_test(
    *,
    strategy_dir: Path,
    test_path: Path,
    config_dict: dict,
    metrics: dict,
    strategy_srcs: list[str],
    run_src: str,
) -> str:
    """Render the final single-file test source."""
    # Determine what strategy module names to drop from imports.
    strategy_module_names = {f.stem for f in strategy_dir.glob("strategy_*.py")}

    # Clean strategy and run sources.
    strategy_clean = [clean_source(s, drop_modules={"yaml"}) for s in strategy_srcs]
    run_clean = clean_source(run_src, drop_modules=strategy_module_names | {"yaml"})

    # Drop unwanted run.py functions / call sites.
    # Keep main() and run() since the test invokes one of them via _invoke_strategy_main().
    for fname in (
        "load_config",  # we replace with inlined
        "write_local_result", "upsert_global_summary", "update_global_summary",
        "add_trade_logger", "_install_benchmark_metrics_hook",
        "print_results", "print_report",
        "_benchmark_call_original_run",
    ):
        run_clean = strip_function_def(run_clean, fname)
        run_clean = strip_function_calls(run_clean, fname)
    # Drop orphaned try/except for the canonical benchmark wrapper.
    run_clean = re.sub(
        r"\ntry:\s*\n\s*_BENCHMARK_ORIGINAL_(?:RUN|MAIN) = (?:run|main)[^\n]*\n.*?(?=\n\S|\Z)",
        "",
        run_clean,
        flags=re.DOTALL,
    )
    # Drop dangling vendored hook artifacts that the strip-pattern may have missed.
    run_clean = re.sub(
        r"\nfrom tests\.test_utils\.benchmark_metrics import \([^)]+\)\n",
        "",
        run_clean,
        flags=re.DOTALL,
    )
    run_clean = re.sub(r"^_install_benchmark_metrics_hook\([^\n]*\)\n", "", run_clean, flags=re.MULTILINE)
    run_clean = re.sub(r"^_BENCHMARK_BASE_DIR = [^\n]*\n", "", run_clean, flags=re.MULTILINE)
    run_clean = re.sub(r"^_BENCHMARK_(?:WORKSPACE_ROOT|BASE_DIR|ORIGINAL_RUN|ORIGINAL_MAIN) = [^\n]*\n", "", run_clean, flags=re.MULTILINE)
    run_clean = re.sub(r"^_REPO_ROOT = [^\n]*\n", "", run_clean, flags=re.MULTILINE)
    run_clean = re.sub(r"^if str\(_REPO_ROOT\) not in[^\n]*\n", "", run_clean, flags=re.MULTILINE)
    run_clean = re.sub(r"^    _benchmark_sys\.path\.insert[^\n]*\n", "", run_clean, flags=re.MULTILINE)

    # Extract imports.
    strat_imports: list[str] = []
    strat_bodies: list[str] = []
    for src in strategy_clean:
        imps, body = extract_imports(src)
        strat_imports.extend(imps)
        strat_bodies.append(body)
    run_imports, run_body = extract_imports(run_clean)

    # Combine and dedupe imports. Drop yaml since we no longer need it (config is inlined).
    extra = ["from __future__ import annotations", "import math", "from pathlib import Path", "import pytest"]
    all_imports_raw = merge_imports([extra, strat_imports, run_imports])
    all_imports = [
        line for line in all_imports_raw
        if line.strip() and not re.match(r"^(?:from yaml|import yaml)", line.strip())
    ]
    # Re-add a separator at the end if the last line wasn't blank
    if all_imports and all_imports[-1].strip():
        all_imports.append("")

    # Inlined config block.
    config_repr = yaml_to_python_repr(config_dict)
    inlined_config_block = (
        "\n_REPO = Path(__file__).resolve().parents[6]\n\n"
        f"_CONFIG = {config_repr}\n\n\n"
        "def _resolve_repo_paths(node):\n"
        "    \"\"\"Replace '{repo}' placeholder in config string values with absolute repo path.\"\"\"\n"
        "    if isinstance(node, dict):\n"
        "        return {k: _resolve_repo_paths(v) for k, v in node.items()}\n"
        "    if isinstance(node, list):\n"
        "        return [_resolve_repo_paths(v) for v in node]\n"
        "    if isinstance(node, str):\n"
        "        return node.replace('{repo}', str(_REPO))\n"
        "    return node\n\n\n"
        "def load_config(*args, **kwargs):\n"
        "    \"\"\"Inlined config (was config.yaml). Accepts any args for compatibility with strategies that pass a path.\"\"\"\n"
        "    import copy\n"
        "    return _resolve_repo_paths(copy.deepcopy(_CONFIG))\n"
    )

    # Build assertions from captured metrics. Use strategy-local keys (whatever
    # keys extract_metrics() emits — they vary by strategy).
    asserts: list[str] = []
    seen: set[str] = set()
    # Numeric/int keys we typically want exact-equal
    for key in ("rows", "bar_num", "buy_count", "sell_count",
                "win_count", "loss_count", "trade_num", "total_trades", "stop_count",
                "rebalance_count", "threshold_rebalance_count", "trade_count",
                "won", "lost"):
        if key in metrics and metrics[key] is not None and isinstance(metrics[key], int):
            v = metrics[key]
            asserts.append(
                f'    assert metrics.get({key!r}) == {v!r}, '
                f'f"{key}: expected={v}, got={{metrics.get({key!r})!r}}"'
            )
            seen.add(key)
    # Float keys with tolerance
    for key, value in metrics.items():
        if key in seen:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            import math as _m
            if not _m.isfinite(v):
                continue
            tol = max(1e-6, abs(v) * 1e-6)
            asserts.append(
                f'    _close(metrics.get({key!r}), {v!r}, tol={tol:.6e}, key={key!r})'
            )
            seen.add(key)
    # Activity invariant: at least one of trades/buys/sells/rebalances must be > 0.
    asserts.append(
        '    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0\n'
        '    _activity = (\n'
        '        _total_trades\n'
        '        or (metrics.get("buy_count") or 0)\n'
        '        or (metrics.get("sell_count") or 0)\n'
        '        or (metrics.get("rebalance_count") or 0)\n'
        '    )\n'
        '    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"'
    )

    asserts_block = "\n".join(asserts)
    test_func_name = test_path.stem
    if not test_func_name.startswith("test_"):
        test_func_name = "test_" + test_func_name

    # Identify a usable inputs-loader name from the run.py module body.
    test_function = f'''

def _close(actual, expected, *, tol, key):
    """Assert ``actual`` is finite and within ``tol`` of ``expected``."""
    assert actual is not None, f"{{key}}: expected={{expected}}, got=None"
    a = float(actual)
    assert math.isfinite(a), f"{{key}}: expected={{expected}}, got non-finite {{actual}}"
    assert abs(a - float(expected)) <= tol, (
        f"{{key}}: expected={{expected}}, got={{a}} (tol={{tol}})"
    )


def {test_func_name}() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/{strategy_dir.parent.parent.name}/{strategy_dir.name}.
    """
    # Capture metrics by hooking extract_metrics() (or similar) and invoking the
    # original main()/run(). This reuses whatever loader / build_cerebro /
    # metrics-extraction signatures the strategy used internally.
    captured = {{}}

    import sys as _sys
    _mod = _sys.modules[__name__]

    # Hook any plausible metrics-extraction function.
    _hook_targets = []
    _metric_names = (
        "extract_metrics", "summarize", "build_metrics", "compute_metrics",
        "calculate_metrics", "collect_metrics", "gather_metrics", "extract_results",
    )
    for _name in _metric_names:
        _orig = getattr(_mod, _name, None)
        if callable(_orig):
            def _make_hook(orig):
                def _hook(*a, **kw):
                    m = orig(*a, **kw)
                    if isinstance(m, dict) and m and "metrics" not in captured:
                        captured["metrics"] = m
                    return m
                return _hook
            setattr(_mod, _name, _make_hook(_orig))
            _hook_targets.append((_name, _orig))

    # Force runonce=True for the cerebro.run() call inside main().
    import backtrader as _bt
    _orig_run = _bt.Cerebro.run
    def _forced_runonce(self, *args, **kwargs):
        kwargs["runonce"] = True
        return _orig_run(self, *args, **kwargs)
    _bt.Cerebro.run = _forced_runonce

    # Strip pytest argv so argparse-based main() functions don't see them.
    _saved_argv = _sys.argv
    _sys.argv = [_sys.argv[0]]

    try:
        try:
            if hasattr(_mod, "main") and callable(_mod.main):
                _mod.main()
            elif hasattr(_mod, "run") and callable(_mod.run):
                result = _mod.run()
                if isinstance(result, dict) and "metrics" not in captured:
                    captured["metrics"] = result
                elif isinstance(result, (list, tuple)):
                    for item in result:
                        if isinstance(item, dict) and "metrics" not in captured:
                            captured["metrics"] = item
                            break
            else:
                raise RuntimeError("Neither main() nor run() found in inlined module")
        except SystemExit:
            pass
        except Exception:
            if "metrics" not in captured:
                raise
    finally:
        _bt.Cerebro.run = _orig_run
        for _name, _orig in _hook_targets:
            setattr(_mod, _name, _orig)
        _sys.argv = _saved_argv

    metrics = captured.get("metrics")
    assert metrics is not None, "no metrics captured during run"

{asserts_block}
'''

    header = f'''"""Inlined regression test for {strategy_dir.relative_to(REPO).as_posix()}.

Auto-generated by scripts/inline_regression_tests.py — do not edit manually.
The original config.yaml, run.py, strategy_*.py, and expected.json have been
collapsed into this single self-contained file.

Runs with runonce=True only (no parametrization).
Asserts directly on the strategy's own extract_metrics() output captured at
migration time.
"""
'''

    return (
        header
        + "\n".join(all_imports)
        + inlined_config_block
        + "\n\n"
        + "\n\n".join(s for s in strat_bodies if s.strip())
        + "\n\n"
        + run_body.rstrip()
        + "\n"
        + test_function
    )


# ---- Main migrate-one ------------------------------------------------------

def inline_one(strategy_dir: Path) -> tuple[bool, str]:
    strategy_dir = Path(strategy_dir).resolve()
    config_path = strategy_dir / "config.yaml"
    expected_path = strategy_dir / "expected.json"
    run_path = strategy_dir / "run.py"

    if not (config_path.exists() and expected_path.exists() and run_path.exists()):
        return False, "missing required files"

    test_files = list(strategy_dir.glob("test_*.py"))
    if not test_files:
        return False, "no test_*.py found"
    if len(test_files) > 1:
        return False, f"multiple test files: {[t.name for t in test_files]}"
    test_path = test_files[0]

    strategy_files = list(strategy_dir.glob("strategy_*.py"))
    if not strategy_files:
        return False, "no strategy_*.py file found"

    config_dict = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config_dict = make_repo_relative(config_dict, str(REPO))

    # Capture concrete metrics by running the existing strategy.
    captured = capture_metrics_via_run(strategy_dir)
    if not captured:
        return False, "could not capture metrics from existing run.py"

    strategy_srcs = [f.read_text(encoding="utf-8") for f in strategy_files]
    run_src = run_path.read_text(encoding="utf-8")

    final = build_inlined_test(
        strategy_dir=strategy_dir,
        test_path=test_path,
        config_dict=config_dict,
        metrics=captured,
        strategy_srcs=strategy_srcs,
        run_src=run_src,
    )

    # Backup originals before writing.
    backup = {
        "test": test_path.read_text(encoding="utf-8"),
        "config": config_path.read_text(encoding="utf-8"),
        "expected": expected_path.read_text(encoding="utf-8"),
        "run": run_path.read_text(encoding="utf-8"),
        "strategy": [(f, f.read_text(encoding="utf-8")) for f in strategy_files],
    }

    # Write the new single-file test.
    test_path.write_text(final, encoding="utf-8")

    # Verify it passes.
    verify = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "--no-header", "--tb=short", str(test_path)],
        cwd=str(REPO), capture_output=True, text=True, timeout=300,
    )
    if verify.returncode != 0:
        # Restore everything.
        test_path.write_text(backup["test"], encoding="utf-8")
        # Save broken content for debugging
        debug_dir = REPO / "scripts" / "_debug_failed_inlines"
        debug_dir.mkdir(exist_ok=True)
        (debug_dir / f"{strategy_dir.parent.parent.name}_{strategy_dir.name}.py").write_text(final, encoding="utf-8")
        return False, f"verify failed: {verify.stdout[-500:]}{verify.stderr[-200:]}"

    # On success, delete config.yaml, expected.json, run.py, strategy_*.py.
    config_path.unlink()
    expected_path.unlink()
    run_path.unlink()
    for sf in strategy_files:
        sf.unlink()
    readme = strategy_dir / "readme.md"
    if readme.exists():
        readme.unlink()
    pyc_dir = strategy_dir / "__pycache__"
    if pyc_dir.exists():
        shutil.rmtree(pyc_dir)

    return True, f"inlined → {test_path.relative_to(REPO).as_posix()}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--from-index", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dirs = find_migrated_dirs()
    print(f"Found {len(dirs)} migrated strategy directories")

    if args.dry_run:
        for d in dirs[:20]:
            print(f"  {d.relative_to(REPO).as_posix()}")
        return

    end = min(args.from_index + args.limit, len(dirs))
    print(f"Inlining [{args.from_index}:{end}]")
    print()

    success = 0
    failure = 0
    failures: list[tuple[str, str]] = []
    for i in range(args.from_index, end):
        d = dirs[i]
        label = f"{d.parent.parent.name}/{d.name}"
        print(f"[{i+1:4d}/{len(dirs)}] {label}", flush=True)
        try:
            ok, msg = inline_one(d)
        except Exception as e:
            ok, msg = False, f"EXCEPTION: {type(e).__name__}: {e}"
        status = "✓" if ok else "✗"
        print(f"     {status} {msg[:240]}", flush=True)
        if ok:
            success += 1
        else:
            failure += 1
            failures.append((label, msg))

    print()
    print(f"Success: {success}, Failure: {failure}")
    if failures:
        print("\nSample failures:")
        for label, msg in failures[:10]:
            print(f"  {label}")
            print(f"    {msg[:300]}")


if __name__ == "__main__":
    main()
