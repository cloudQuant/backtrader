#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures as futures
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


WORKER_COMMAND = "__worker__"
DEFAULT_TEST_ROOT = Path("tests/functional/strategies_regression")
EXCEPTION_LINE_PATTERN = re.compile(
    r"^(TypeError|AttributeError|ValueError|IndexError|KeyError|"
    r"ModuleNotFoundError|ImportError|AssertionError|FileNotFoundError|RuntimeError):"
)


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / "backtrader").is_dir():
            return parent
    raise RuntimeError("Cannot find backtrader repository root")


def is_same_or_child(path: Path, parent: Path) -> bool:
    try:
        resolved_path = path.resolve()
        resolved_parent = parent.resolve()
    except OSError:
        return False
    return resolved_path == resolved_parent or resolved_parent in resolved_path.parents


def cleaned_env(repo_root: Path, keep_repo_pythonpath: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    if keep_repo_pythonpath:
        pythonpath_parts = [str(repo_root), env.get("PYTHONPATH", "")]
        env["PYTHONPATH"] = os.pathsep.join(item for item in pythonpath_parts if item)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return env
    pythonpath = env.get("PYTHONPATH", "")
    if pythonpath:
        kept = []
        for item in pythonpath.split(os.pathsep):
            if not item:
                continue
            if is_same_or_child(Path(item), repo_root):
                continue
            kept.append(item)
        if kept:
            env["PYTHONPATH"] = os.pathsep.join(kept)
        else:
            env.pop("PYTHONPATH", None)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def clean_sys_path(repo_root: Path) -> None:
    kept = []
    for item in sys.path:
        if not item:
            continue
        if is_same_or_child(Path(item), repo_root):
            continue
        kept.append(item)
    sys.path[:] = kept


def run_command(command: list[str], cwd: Path, timeout: int, env: dict[str, str] | None = None) -> int:
    print("=" * 80, flush=True)
    print("Running:", " ".join(command), flush=True)
    print("CWD:", cwd, flush=True)
    print("=" * 80, flush=True)
    result = subprocess.run(command, cwd=str(cwd), env=env, timeout=timeout, check=False)
    print("Exit code:", result.returncode, flush=True)
    return result.returncode


def backtrader_location(repo_root: Path, keep_repo_pythonpath: bool = False) -> str:
    code = (
        "import backtrader; "
        "print(getattr(backtrader, '__version__', 'unknown')); "
        "print(getattr(backtrader, '__file__', 'unknown'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd="/tmp",
        env=cleaned_env(repo_root, keep_repo_pythonpath=keep_repo_pythonpath),
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    return output or f"backtrader import failed with code {result.returncode}"


def collect_test_files(test_root: Path) -> list[Path]:
    return sorted(path for path in test_root.rglob("test*.py") if path.is_file())


def resolve_existing_path(repo_root: Path, default_test_root: Path, target: str) -> Path:
    selected_path = Path(target)
    if selected_path.is_absolute():
        return selected_path

    repo_relative = repo_root / selected_path
    if repo_relative.exists():
        return repo_relative

    return default_test_root / selected_path


def load_failure_targets_from_report(repo_root: Path, report_path: Path) -> list[str]:
    resolved_report = report_path.resolve() if report_path.is_absolute() else (repo_root / report_path).resolve()
    payload = json.loads(resolved_report.read_text(encoding="utf-8"))
    failures = payload.get("failures")
    if not isinstance(failures, list):
        raise ValueError(f"Report has no 'failures' list: {resolved_report}")

    targets = []
    for item in failures:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if isinstance(path, str) and path:
            targets.append(path)

    if not targets:
        raise ValueError(f"Report contains no failure paths: {resolved_report}")
    return targets


def collect_selected_test_files(repo_root: Path, default_test_root: Path, targets: list[str]) -> list[Path]:
    collected: list[Path] = []
    seen: set[Path] = set()

    for target in targets:
        resolved = resolve_existing_path(repo_root, default_test_root, target)
        if not resolved.exists():
            raise FileNotFoundError(f"Target does not exist: {target} -> {resolved}")

        if resolved.is_dir():
            current_files = collect_test_files(resolved)
            if not current_files:
                raise ValueError(f"No regression test files found under: {resolved}")
        elif resolved.is_file():
            current_files = [resolved]
        else:
            raise ValueError(f"Unsupported target path: {resolved}")

        for test_file in current_files:
            canonical = test_file.resolve()
            if canonical in seen:
                continue
            seen.add(canonical)
            collected.append(canonical)

    return sorted(collected, key=lambda path: str(path.relative_to(repo_root)))


def tail(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def decode_process_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def parse_worker_payload(stdout: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("status") in {"passed", "failed"}:
            payload = parsed
    return payload


def extract_root_error(stderr: str) -> str:
    for line in reversed(stderr.splitlines()):
        stripped = line.strip()
        if EXCEPTION_LINE_PATTERN.match(stripped):
            return stripped
    return ""


def run_one_test(
    script_path: Path,
    test_file: Path,
    repo_root: Path,
    timeout: int,
    use_current_backtrader: bool,
) -> dict[str, Any]:
    started = time.time()
    command = [
        sys.executable,
        str(script_path),
        WORKER_COMMAND,
        str(test_file),
        str(repo_root),
        "1" if use_current_backtrader else "0",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=str(test_file.parent),
            env=cleaned_env(repo_root, keep_repo_pythonpath=use_current_backtrader),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        payload = parse_worker_payload(result.stdout)
        record = {
            "path": str(test_file.relative_to(repo_root)),
            "returncode": result.returncode,
            "seconds": round(time.time() - started, 3),
            "stdout_tail": tail(result.stdout, 4000),
            "stderr_tail": tail(result.stderr, 4000),
        }
        for key in (
            "status",
            "error_type",
            "error",
            "root_error",
            "process_command",
            "process_stdout_tail",
            "process_stderr_tail",
            "assertion_message",
        ):
            if key in payload:
                record[key] = payload[key]
        return record
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return {
            "path": str(test_file.relative_to(repo_root)),
            "returncode": 124,
            "error_type": "TimeoutExpired",
            "seconds": round(time.time() - started, 3),
            "stdout_tail": tail(stdout, 2000),
            "stderr_tail": tail(stderr, 4000),
        }


def run_tests(
    script_path: Path,
    repo_root: Path,
    test_files: list[Path],
    workers: int,
    timeout: int,
    use_current_backtrader: bool,
) -> list[dict[str, Any]]:
    print("=" * 80, flush=True)
    if test_files:
        print(f"First test: {test_files[0].relative_to(repo_root)}", flush=True)
        print(f"Last test:  {test_files[-1].relative_to(repo_root)}", flush=True)
    print(f"Total test files: {len(test_files)}", flush=True)
    print(f"Workers: {workers}", flush=True)
    print(f"Per-test timeout: {timeout}s", flush=True)
    print("=" * 80, flush=True)

    results = []
    passed = 0
    failed = 0
    started = time.time()

    with futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                run_one_test,
                script_path,
                test_file,
                repo_root,
                timeout,
                use_current_backtrader,
            ): test_file
            for test_file in test_files
        }
        for index, future in enumerate(futures.as_completed(future_map), 1):
            result = future.result()
            results.append(result)
            if result["returncode"] == 0:
                passed += 1
            else:
                failed += 1
            if index % 25 == 0 or index == len(test_files):
                elapsed = round(time.time() - started, 1)
                print(
                    f"PROGRESS completed={index} passed={passed} failed={failed} elapsed_sec={elapsed}",
                    flush=True,
                )

    return sorted(results, key=lambda item: item["path"])


def write_report(repo_root: Path, output_path: Path | None, results: list[dict[str, Any]], started_at: str, duration: float) -> Path:
    failures = [item for item in results if item["returncode"] != 0]
    if output_path is None:
        output_dir = repo_root / "logs"
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"current_backtrader_strategy_regression_{stamp}.json"
    else:
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "started_at": started_at,
        "duration_sec": round(duration, 3),
        "total": len(results),
        "passed": len(results) - len(failures),
        "failed": len(failures),
        "failures": failures,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def print_summary(results: list[dict[str, Any]], report_path: Path) -> None:
    failures = [item for item in results if item["returncode"] != 0]
    failure_roots: dict[str, int] = {}
    for item in failures:
        key = (
            item.get("root_error")
            or item.get("assertion_message")
            or item.get("error_type")
            or ("TimeoutExpired" if item["returncode"] == 124 else "UnknownFailure")
        )
        failure_roots[key] = failure_roots.get(key, 0) + 1
    print("=" * 80, flush=True)
    print("Current backtrader strategy regression summary", flush=True)
    print("=" * 80, flush=True)
    print(f"Total:  {len(results)}", flush=True)
    print(f"Passed: {len(results) - len(failures)}", flush=True)
    print(f"Failed: {len(failures)}", flush=True)
    print(f"Report: {report_path}", flush=True)
    if failure_roots:
        print("", flush=True)
        print("Failure root causes:", flush=True)
        for key, count in sorted(failure_roots.items(), key=lambda item: (-item[1], item[0])):
            print(f"  {key}: {count}", flush=True)
    if failures:
        print("", flush=True)
        print("Failed test scripts:", flush=True)
        for item in failures:
            status = "TIMEOUT" if item["returncode"] == 124 else f"EXIT {item['returncode']}"
            detail = item.get("root_error") or item.get("error_type", "unknown")
            print(f"  {item['path']}  [{status}, {detail}, {item['seconds']}s]", flush=True)
    print("=" * 80, flush=True)


def worker_main(argv: list[str]) -> int:
    test_file = Path(argv[0]).resolve()
    repo_root = Path(argv[1]).resolve()
    use_current_backtrader = len(argv) >= 3 and argv[2] == "1"

    module_name = "_official_backtrader_regression_test"
    try:
        spec = importlib.util.spec_from_file_location(module_name, test_file)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load test module: {test_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        _ = use_current_backtrader
        module.BACKTRADER_REPO = repo_root
        expected = module._load_json(module.EXPECTED_PATH)
        actual = module._run_strategy()
        module._assert_metrics(actual, expected)
        print(json.dumps({"status": "passed", "test": str(test_file)}), flush=True)
        return 0
    except BaseException as exc:
        payload: dict[str, Any] = {
            "status": "failed",
            "test": str(test_file),
            "error_type": type(exc).__name__,
            "error": repr(exc),
        }
        if isinstance(exc, AssertionError):
            payload["assertion_message"] = str(exc)
        if isinstance(exc, subprocess.CalledProcessError):
            payload["process_command"] = [str(item) for item in exc.cmd]
            payload["process_stdout_tail"] = tail(decode_process_output(exc.stdout), 12000)
            payload["process_stderr_tail"] = tail(decode_process_output(exc.stderr), 12000)
            payload["root_error"] = extract_root_error(payload["process_stderr_tail"])
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        traceback.print_exc()
        return 1


def resolve_test_root(repo_root: Path, target: str | None, explicit_test_root: str | None) -> Path:
    default_root = repo_root / DEFAULT_TEST_ROOT
    selected = explicit_test_root if explicit_test_root is not None else target
    if selected is None:
        return default_root

    selected_path = Path(selected)
    if selected_path.is_absolute():
        return selected_path

    repo_relative = repo_root / selected_path
    if repo_relative.exists():
        return repo_relative

    return default_root / selected_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run strategy regression scripts against the current project backtrader."
    )
    parser.add_argument(
        "targets",
        nargs="*",
        default=[],
        help="Optional target folders or test paths. Examples: asset_allocation tests/functional/strategies_regression/asset_allocation/test_1_x.py.",
    )
    parser.add_argument(
        "--test-root",
        default=None,
        help="Explicit regression test root, relative to repo root or absolute path. If omitted, defaults to tests/functional/strategies_regression.",
    )
    parser.add_argument(
        "--from-report",
        type=Path,
        default=None,
        help="Load failure paths from a previous JSON report and rerun only those failed tests.",
    )
    parser.add_argument("--workers", type=int, default=7, help="Number of concurrent workers.")
    parser.add_argument("--timeout", type=int, default=240, help="Timeout per test script in seconds.")
    parser.add_argument("--pip-timeout", type=int, default=900, help="Timeout for pip install commands in seconds.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON report output path.")
    parser.add_argument(
        "--use-current-backtrader",
        action="store_true",
        help="Legacy compatibility flag. The current project backtrader is always used.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = find_repo_root()
    script_path = Path(__file__).resolve()
    test_root = resolve_test_root(repo_root, None, args.test_root)

    requested_targets = list(args.targets)
    if args.from_report is not None:
        requested_targets.extend(load_failure_targets_from_report(repo_root, args.from_report))

    if requested_targets:
        test_files = collect_selected_test_files(repo_root, test_root, requested_targets)
    else:
        if not test_root.exists():
            print(f"Test root does not exist: {test_root}", file=sys.stderr, flush=True)
            return 2
        test_files = collect_test_files(test_root)

    if not test_files:
        print("No regression test files selected.", file=sys.stderr, flush=True)
        return 2

    started_at = datetime.now().isoformat(timespec="seconds")
    started = time.time()
    _ = args.use_current_backtrader
    print("Running regression with current project backtrader", flush=True)
    if args.from_report is not None:
        print(f"Loaded failure targets from report: {args.from_report}", flush=True)
    if args.targets:
        print(f"Explicit targets: {len(args.targets)}", flush=True)
    print(backtrader_location(repo_root, keep_repo_pythonpath=True), flush=True)
    results = run_tests(
        script_path,
        repo_root,
        test_files,
        args.workers,
        args.timeout,
        True,
    )
    duration = time.time() - started
    report_path = write_report(repo_root, args.output, results, started_at, duration)
    print_summary(results, report_path)
    return 1 if any(item["returncode"] != 0 for item in results) else 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == WORKER_COMMAND:
        raise SystemExit(worker_main(sys.argv[2:]))
    raise SystemExit(main())
