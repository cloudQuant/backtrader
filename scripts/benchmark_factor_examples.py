"""Run one factor example in a fresh process on the fixed or full universe."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import functools
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = {
    "025": "025_factor_single",
    "026": "026_factor_multi",
    "027": "027_alpha003_panel_acceptance",
}
SELECTION = Path(
    "docs/_internal/opts/requirements/迭代49-因子分析性能优化/benchmark-500-7col.json"
)
SYMBOLS, DATES = 500, 243
SELECTION_SHA256 = "14f789a9d9e649987b93bc0477a0f94acc5223edd7ccd70166c8ea4b33ba35dc"
ALL_SYMBOLS = 5471
ALL_MANIFEST_SHA256 = "7ac8fea0ceb547e010a139f4a17820f6207f38ab08c762cf19257a0f39ec2cfb"
ALL_CALENDAR_SHA256 = "ebffd7c7a5626a43ea54f5135c86fb0c8c554255e85ee09ba9bfc5e9da324ba1"


def _hash(path: Path) -> dict:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
    return {"sha256": digest.hexdigest(), "size_bytes": size}


def _inside(path: Path, root: Path, *, strict: bool = True) -> bool:
    try:
        path.resolve(strict=strict).relative_to(root.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def _required_source_paths(root: Path, package: str, examples: tuple[str, ...]) -> set[str]:
    required = set()
    package_root = root / package
    if not package_root.is_dir():
        raise ValueError("source package is missing: %s" % package_root)
    required.update(path.relative_to(root).as_posix() for path in package_root.rglob("*.py"))
    public_example_suffixes = {".py", ".md", ".yaml", ".yml", ".json", ".pem"}
    for folder in examples:
        path = root / folder
        if not path.is_dir():
            raise ValueError("example source is missing: %s" % path)
        required.update(item.relative_to(root).as_posix() for item in path.rglob("*")
                        if item.is_file() and item.suffix.lower() in public_example_suffixes
                        and "__pycache__" not in item.parts)
    runner = root / "scripts" / Path(__file__).name
    if package == "backtrader" and runner.is_file():
        required.add(runner.relative_to(root).as_posix())
    return required


def _source_state(root: Path, package: str, examples: tuple[str, ...] = ()) -> tuple[dict, dict]:
    """Hash public inputs from a verified archive manifest or the actual Git tree."""
    root = root.resolve(strict=True)
    manifest_path = root / ".iteration49-source.json"
    if manifest_path.is_file():
        required = _required_source_paths(root, package, examples)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        commit, declared = manifest.get("commit"), manifest.get("files")
        if manifest.get("schema_version") != 1 or not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("invalid .iteration49-source.json identity")
        if not isinstance(declared, dict) or not declared:
            raise ValueError("source snapshot manifest has no file pins")
        pins = {}
        for name, expected in declared.items():
            rel = PurePosixPath(name)
            if not name or "\\" in name or rel.is_absolute() or ".." in rel.parts or not isinstance(expected, dict):
                raise ValueError("unsafe source snapshot pin: %s" % name)
            path = root.joinpath(*rel.parts)
            if not _inside(path, root):
                raise ValueError("source snapshot path escapes root: %s" % name)
            actual = _hash(path)
            if actual != {"sha256": expected.get("sha256"), "size_bytes": expected.get("size_bytes")}:
                raise ValueError("source snapshot pin mismatch: %s" % name)
            pins[rel.as_posix()] = actual
        missing = required - pins.keys()
        if missing:
            raise ValueError("source snapshot omits public input: %s" % sorted(missing)[0])
        identity = {
            "kind": "verified_snapshot_manifest_v1",
            "commit": commit,
            "manifest_sha256": _hash(manifest_path)["sha256"],
            "source_content_sha256": _map_hash(pins),
        }
        return identity, pins

    scopes = [package, *examples]
    if package == "backtrader":
        if (root / "scripts" / Path(__file__).name).is_file():
            scopes.append("scripts/" + Path(__file__).name)
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *scopes],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout
    names = set()
    for raw in listed.split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8")
        path = root.joinpath(*PurePosixPath(name).parts)
        if not path.is_file():
            continue
        if name.startswith(package + "/"):
            names.add(name)
        elif any(name == scope or name.startswith(scope + "/") for scope in examples):
            names.add(name)
        elif package == "backtrader" and name == "scripts/" + Path(__file__).name:
            names.add(name)
    # Git determines the public input set. Ignored output directories and local
    # configs are not source inputs; actual package origins are checked against
    # these pins after import and again after main.
    required = {package + "/__init__.py", *(folder + "/run.py" for folder in examples)}
    if not required.issubset(names):
        raise ValueError("Git source scan omits public input: %s" % sorted(required - names)[0])
    if not names:
        raise ValueError("no public source inputs found under %s" % root)
    pins = {name: _hash(root.joinpath(*PurePosixPath(name).parts)) for name in sorted(names)}
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
        check=True, stdout=subprocess.PIPE, text=True,
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "-C", str(root), "branch", "--show-current"],
        check=True, stdout=subprocess.PIPE, text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all", "--", *scopes],
        check=True, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    ).stdout.splitlines()
    return {
        "kind": "git_worktree",
        "commit": head,
        "branch": branch or None,
        "source_status": status,
        "source_content_sha256": _map_hash(pins),
    }, pins


def _map_hash(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _data_state_fixed500(root: Path, selection_path: Path) -> tuple[dict, dict]:
    root = root.resolve(strict=True)
    selection_path = selection_path.resolve(strict=True)
    if _hash(selection_path)["sha256"] != SELECTION_SHA256:
        raise ValueError("fixed benchmark selection differs from its frozen pin")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if (selection.get("schema"), selection.get("selected_symbol_count"), selection.get("date_count")) != (
        "iteration49.benchmark500.v1", SYMBOLS, DATES
    ):
        raise ValueError("selection is not the fixed 500-symbol x 243-date manifest")
    metadata = root / "_metadata"
    manifest_path, calendar_path = metadata / "manifest.json", metadata / "observed_calendar.csv"
    if not _inside(manifest_path, root) or not _inside(calendar_path, root):
        raise ValueError("shared data metadata escapes the data root")
    pins = {"_metadata/manifest.json": _hash(manifest_path), "_metadata/observed_calendar.csv": _hash(calendar_path)}
    if pins["_metadata/manifest.json"]["sha256"] != selection.get("source_manifest_sha256"):
        raise ValueError("shared data manifest differs from fixed selection")
    if pins["_metadata/observed_calendar.csv"]["sha256"] != selection.get("source_calendar_sha256"):
        raise ValueError("shared calendar differs from fixed selection")
    source = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries, fixed = source.get("output", {}).get("symbols", []), selection.get("entries", [])
    if len(entries) != selection.get("source_symbol_count") or len(fixed) != SYMBOLS:
        raise ValueError("fixed selection has an unexpected symbol count")
    positions = [int(i * len(entries) / float(SYMBOLS)) for i in range(SYMBOLS)]
    symbols = []
    for row, position in zip(fixed, positions):
        entry = entries[position]
        if (row.get("position"), row.get("symbol"), row.get("file")) != (
            position, entry.get("symbol"), entry.get("file")
        ):
            raise ValueError("selection differs from the fixed sampling rule at %s" % position)
        rel = PurePosixPath(row["file"])
        path = root.joinpath(*rel.parts)
        if rel.is_absolute() or ".." in rel.parts or not _inside(path, root):
            raise ValueError("selected CSV path escapes data root")
        actual = _hash(path)
        if actual["sha256"] != row.get("sha256"):
            raise ValueError("selected CSV pin mismatch: %s" % row["file"])
        pins[rel.as_posix()] = actual
        symbols.append(row["symbol"])
    if len(set(symbols)) != SYMBOLS:
        raise ValueError("fixed selection does not contain 500 unique symbols")
    ordered = hashlib.sha256(("\n".join(symbols) + "\n").encode()).hexdigest()
    if ordered != selection.get("ordered_symbols_sha256"):
        raise ValueError("fixed ordered-symbol hash mismatch")
    with calendar_path.open("r", encoding="utf-8-sig", newline="") as stream:
        if sum(1 for _ in csv.DictReader(stream)) != DATES:
            raise ValueError("shared calendar does not contain 243 dates")
    pins["selection:" + selection_path.name] = _hash(selection_path)
    return {
        "universe": "fixed500",
        "symbols": SYMBOLS,
        "dates": DATES,
        "grid_cells": SYMBOLS * DATES,
        "ordered_symbols_sha256": ordered,
        "selection_sha256": pins["selection:" + selection_path.name]["sha256"],
        "files_sha256": _map_hash(pins),
    }, pins


def _manifest_csv_pins(root: Path, entries: list, expected_count: int) -> tuple[list[str], dict]:
    if len(entries) != expected_count:
        raise ValueError("public data manifest has %d symbols, expected %d" % (len(entries), expected_count))
    symbols, pins = [], {}
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("public data manifest contains a malformed symbol row")
        symbol, filename, expected_sha = item.get("symbol"), item.get("file"), item.get("sha256")
        if (not isinstance(symbol, str) or not symbol or not isinstance(filename, str) or
                not filename or Path(filename).name != filename or PurePosixPath(filename).name != filename or
                "\\" in filename or not isinstance(expected_sha, str) or
                not re.fullmatch(r"[0-9a-f]{64}", expected_sha)):
            raise ValueError("public data manifest contains an invalid symbol, filename, or digest")
        path = root / filename
        if not _inside(path, root):
            raise ValueError("public CSV path escapes data root: %s" % filename)
        actual = _hash(path)
        expected_size = item.get("bytes")
        if actual["sha256"] != expected_sha or (expected_size is not None and
                (type(expected_size) is not int or actual["size_bytes"] != expected_size)):
            raise ValueError("public CSV pin mismatch: %s" % filename)
        pins[filename] = actual
        symbols.append(symbol)
    if len(set(symbols)) != expected_count:
        raise ValueError("public data manifest contains duplicate symbols")
    return symbols, pins


def _data_state_all(root: Path) -> tuple[dict, dict]:
    root = root.resolve(strict=True)
    manifest_path = root / "_metadata" / "manifest.json"
    calendar_path = root / "_metadata" / "observed_calendar.csv"
    if not _inside(manifest_path, root) or not _inside(calendar_path, root):
        raise ValueError("shared data metadata escapes the data root")
    pins = {"_metadata/manifest.json": _hash(manifest_path),
            "_metadata/observed_calendar.csv": _hash(calendar_path)}
    if pins["_metadata/manifest.json"]["sha256"] != ALL_MANIFEST_SHA256:
        raise ValueError("full-universe public manifest differs from its frozen pin")
    if pins["_metadata/observed_calendar.csv"]["sha256"] != ALL_CALENDAR_SHA256:
        raise ValueError("full-universe public calendar differs from its frozen pin")
    source = json.loads(manifest_path.read_text(encoding="utf-8"))
    output = source.get("output") if isinstance(source, dict) else None
    entries = output.get("symbols") if isinstance(output, dict) else None
    if (not isinstance(entries, list) or source.get("status") != "complete"
            or output.get("symbol_count") != ALL_SYMBOLS or output.get("csv_file_count") != ALL_SYMBOLS
            or output.get("observed_dates") != DATES):
        raise ValueError("full-universe manifest is not the pinned complete 5471-symbol source")
    symbols, csv_pins = _manifest_csv_pins(root, entries, ALL_SYMBOLS)
    pins.update(csv_pins)
    with calendar_path.open("r", encoding="utf-8-sig", newline="") as stream:
        dates = list(csv.DictReader(stream))
    if len(dates) != DATES or len({row.get("trade_date") for row in dates}) != DATES:
        raise ValueError("shared calendar does not contain 243 unique dates")
    ordered = hashlib.sha256(("\n".join(symbols) + "\n").encode("utf-8")).hexdigest()
    return {
        "universe": "all",
        "symbols": len(symbols),
        "dates": len(dates),
        "grid_cells": len(symbols) * len(dates),
        "ordered_symbols_sha256": ordered,
        "selection_sha256": None,
        "files_sha256": _map_hash(pins),
    }, pins


def _data_state(root: Path, selection_path: Path | None, universe: str = "fixed500") -> tuple[dict, dict]:
    if universe == "all":
        return _data_state_all(root)
    if universe != "fixed500":
        raise ValueError("unknown input universe: %s" % universe)
    if selection_path is None:
        raise ValueError("fixed500 universe requires --selection")
    return _data_state_fixed500(root, selection_path)


class Timers:
    """Coarse nested wall/CPU timers; recursive calls to one label count once."""

    def __init__(self):
        self.rows, self.lock, self.local = {}, threading.Lock(), threading.local()

    def wrap(self, owner, attr, label, after=None):
        original = getattr(owner, attr, None)
        if not callable(original):
            return False
        setattr(owner, attr, self._measured(original, label, after))
        return True

    def aliases(self, target, label):
        refs = [(module, name, "%s.%s" % (modname, name))
                for modname, module in tuple(sys.modules.items())
                for name, value in tuple(getattr(module, "__dict__", {}).items()) if value is target]
        if refs:
            wrapper = self._measured(target, label)
            for module, name, _ in refs:
                setattr(module, name, wrapper)
        return [name for _, _, name in refs]

    def _measured(self, original, label, after=None):
        @functools.wraps(original)
        def measured(*args, **kwargs):
            stack = getattr(self.local, "stack", [])
            self.local.stack = stack
            with self.lock:
                row = self.rows.setdefault(label, {"calls": 0, "recursive_suppressed": 0,
                    "parent_labels": set(), "wall_inclusive_ns": 0, "wall_exclusive_ns": 0,
                    "process_cpu_inclusive_ns": 0, "process_cpu_exclusive_ns": 0})
            if any(item["label"] == label for item in stack):
                with self.lock:
                    row["recursive_suppressed"] += 1
                return original(*args, **kwargs)
            parent = stack[-1] if stack else None
            item = {"label": label, "wall_child_ns": 0, "cpu_child_ns": 0}
            stack.append(item)
            wall0, cpu0 = time.perf_counter_ns(), time.process_time_ns()
            try:
                value = original(*args, **kwargs)
                if after is not None:
                    after(value)
                return value
            finally:
                wall, cpu = time.perf_counter_ns() - wall0, time.process_time_ns() - cpu0
                stack.pop()
                if parent:
                    parent["wall_child_ns"] += wall
                    parent["cpu_child_ns"] += cpu
                with self.lock:
                    if parent:
                        row["parent_labels"].add(parent["label"])
                    row["calls"] += 1
                    row["wall_inclusive_ns"] += wall
                    row["wall_exclusive_ns"] += max(0, wall - item["wall_child_ns"])
                    row["process_cpu_inclusive_ns"] += cpu
                    row["process_cpu_exclusive_ns"] += max(0, cpu - item["cpu_child_ns"])
        return measured

    def json_rows(self):
        return {label: {**row, "parent_labels": sorted(row["parent_labels"])} for label, row in self.rows.items()}


def _origins(bt_root: Path, fc_root: Path, example_module, example_path: Path, pins: dict) -> dict:
    origins = {}
    for name, module in sorted(sys.modules.items()):
        if name == "backtrader" or name.startswith("backtrader."):
            root = bt_root
        elif name == "fincore" or name.startswith("fincore."):
            root = fc_root
        else:
            continue
        origin = getattr(module, "__file__", None)
        if not origin:
            continue
        path = Path(origin).resolve(strict=True)
        if not _inside(path, root):
            raise RuntimeError("module imported outside requested source root: %s" % name)
        rel = path.relative_to(root).as_posix()
        if rel not in pins or _hash(path) != pins[rel]:
            raise RuntimeError("loaded module source is not pinned: %s" % rel)
        origins[name] = str(path)
    if Path(example_module.__file__).resolve(strict=True) != example_path.resolve(strict=True):
        raise RuntimeError("selected example module origin mismatch")
    origins[example_module.__name__] = str(example_path.resolve(strict=True))
    return origins


def _panel_memory_bytes(panel) -> int:
    frames = [panel.get("grid")]
    feeds = panel.get("feeds", {})
    if isinstance(feeds, dict):
        frames.extend(feeds.values())
    return sum(int(frame.memory_usage(index=True, deep=True).sum()) for frame in frames if hasattr(frame, "memory_usage"))


def _example_cli_arguments(example: str, profile: str, output: Path, data_root: Path, symbol_count: int) -> list[str]:
    command = ["--output-dir", str(output / "example"), "--data-dir", str(data_root),
               "--max-symbols", str(symbol_count), "--factor-mode", "native"]
    if profile == "full":
        command.append("--report")
    elif example in ("025", "026"):
        command.append("--no-charts")
    return command


def _atomic_json(path: Path, value: dict) -> None:
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def _publish_report_semantics(root: Path, captured: list) -> list:
    reports = []
    root = root.resolve(strict=True)
    for document, raw_path in captured:
        path = Path(raw_path).resolve(strict=True)
        if not _inside(path, root):
            raise ValueError("captured HTML is outside the example output directory")
        relative = path.relative_to(root).as_posix()
        payload = document.semantic_payload()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        if document.semantic_digest.lower() != digest:
            raise ValueError("ReportDocument digest differs from its semantic payload")
        reports.append({"html_path": relative, "html_sha256": _hash(path)["sha256"],
                        "semantic_payload": json.loads(encoded), "semantic_digest": digest})
    if reports:
        _atomic_json(root / "report_semantics.json", {"schema_version": "factor-report-semantics-v1", "reports": reports})
    return reports


def _observed_engine(phase_rows: dict) -> str | None:
    engines = [
        engine for engine in ("runonce", "runnext")
        if phase_rows.get("engine_" + engine, {}).get("calls", 0) > 0
    ]
    return engines[0] if len(engines) == 1 else ("mixed" if engines else None)


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT, help="Backtrader checkout or verified snapshot")
    parser.add_argument("--fincore-root", type=Path, required=True, help="FinCore checkout or verified snapshot")
    parser.add_argument("--data-root", type=Path, required=True, help="shared a_stocks dataset")
    parser.add_argument("--selection", type=Path, help="frozen selection file for the default fixed500 universe")
    parser.add_argument("--universe", choices=("fixed500", "all"), default="fixed500",
                        help="fixed pinned 500-symbol sample (default) or all 5471 pinned symbols")
    parser.add_argument("--example", choices=tuple(EXAMPLES), required=True)
    parser.add_argument("--profile", choices=("full", "compute"), default="full")
    parser.add_argument("--expected-engine", choices=("runonce", "runnext"),
                        help="assert the observed Cerebro engine; does not select the engine")
    parser.add_argument("--output", type=Path, required=True, help="new result directory")
    parser.add_argument("--diagnostic", action="store_true", help="also time fingerprint, validation and _periodset")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    result_path = output / "result.json"
    wall0, cpu0 = time.perf_counter_ns(), time.process_time_ns()
    result = {"schema": ("iteration49.benchmark-run.v1" if args.universe == "fixed500"
                          else "iteration49.benchmark-run.v2"),
              "evidence": "ONE_FRESH_PROCESS_PUBLIC_MAIN", "input_universe": args.universe,
              "example": args.example, "profile": args.profile, "status": "RUNNER_ERROR",
              "started_utc": datetime.now(timezone.utc).isoformat(), "runner_sha256": _hash(Path(__file__)),
              "example_exit_code": None, "runner_exit_code": 1}
    bt_root, fc_root, data_root = args.source_root.resolve(), args.fincore_root.resolve(), args.data_root.resolve()
    example_root = bt_root / "examples" / "backtest" / EXAMPLES[args.example]
    example_path = example_root / "run.py"
    source_before = fc_before = data_before = {}
    bt_identity = fc_identity = data_identity = selection_path = None
    timers, sampler, psutil, process = None, None, None, None
    stop = threading.Event()
    samples, memory, captured = [], {}, []
    report_module = report_writer = None
    setup_wall = setup_cpu = main_wall = main_cpu = 0
    main_started = None
    try:
        if any(_inside(output, root, strict=False) for root in (bt_root, fc_root, data_root)):
            raise ValueError("--output must be outside source-root, fincore-root and data-root")
        if args.universe == "fixed500":
            raw_selection = (args.selection or ROOT / SELECTION).expanduser()
            if not raw_selection.is_absolute() and not raw_selection.is_file():
                raw_selection = ROOT / raw_selection
            if not raw_selection.is_file() and raw_selection.name == "fixedbenchmark-500.json":
                raw_selection = ROOT / SELECTION
            selection_path = raw_selection.resolve(strict=True)
        elif args.selection is not None:
            raise ValueError("--selection is only valid with --universe fixed500")
        example_scope = tuple("examples/backtest/" + name for name in EXAMPLES.values())
        bt_identity, source_before = _source_state(bt_root, "backtrader", example_scope)
        fc_identity, fc_before = _source_state(fc_root, "fincore")
        data_identity, data_before = _data_state(data_root, selection_path, args.universe)
        result.update({"backtrader_source_before": bt_identity, "backtrader_files_before": source_before,
                       "fincore_source_before": fc_identity, "fincore_files_before": fc_before,
                       "data_identity_before": data_identity, "data_files_before": data_before,
                       "selection_path": None if selection_path is None else str(selection_path),
                       "data_root": str(data_root)})

        setup0, setupc = time.perf_counter_ns(), time.process_time_ns()
        sys.path[:0] = [str(bt_root), str(fc_root), str(example_root)]
        import numpy as np
        import pandas as pd
        import psutil as psutil_module
        import backtrader as bt
        import backtrader.feed
        import backtrader.research as research
        import backtrader.research.factor_strategy as factor_strategy
        import backtrader.research.sink as sink
        import backtrader.research.operators as operators
        import fincore
        import fincore.factor_analysis.models as models
        import fincore.factor_analysis.research as fc_research
        import fincore.report.factor.html as report_html
        from fincore.factor_analysis.research import ResearchEvaluationResult
        spec = importlib.util.spec_from_file_location("_iteration49_example_" + args.example, example_path)
        if spec is None or spec.loader is None:
            raise ImportError("cannot load selected public example: %s" % example_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        psutil, process = psutil_module, psutil_module.Process()
        mem = process.memory_info()
        memory["after_imports_before_main"] = {"rss_bytes": mem.rss,
            "working_set_bytes": getattr(mem, "wset", None), "peak_working_set_bytes": getattr(mem, "peak_wset", None)}
        module_origins = _origins(bt_root, fc_root, module, example_path, {**source_before, **fc_before})
        setup_wall, setup_cpu = time.perf_counter_ns() - setup0, time.process_time_ns() - setupc

        timers = Timers()
        def panel_return(panel):
            now = time.perf_counter_ns()
            info = process.memory_info()
            memory["after_load_daily_panel"] = {"rss_bytes": info.rss,
                "elapsed_main_ns": None if main_started is None else now - main_started}
            if args.diagnostic:
                diagnostic0 = time.perf_counter_ns()
                memory["panel_dataframe_deep_bytes"] = _panel_memory_bytes(panel)
                memory["panel_dataframe_deep_measurement_ns"] = time.perf_counter_ns() - diagnostic0
        targets = [
            (module, "load_daily_panel", "load_daily_panel", panel_return),
            (module, "_run_factor" if args.example == "027" else "_run_native_collection", "collection", None),
            (research, "align_to_grid", "align_to_grid", None),
            (bt.Cerebro, "run", "cerebro_run", None), (bt.Cerebro, "_runonce", "engine_runonce", None),
            (bt.Cerebro, "_runnext", "engine_runnext", None),
            (bt.feed.DataBase, "preload", "feed_preload", None),
            (factor_strategy.FactorStrategy, "__init__", "strategy_init", None),
            (factor_strategy.FactorStrategy, "_collect_current_grid_point", "collect_grid_points", None),
            (factor_strategy.FactorStrategy, "stop", "strategy_stop", None),
            (sink.MemorySink, "finalize", "sink_finalize", None),
            (research, "write_factor_report", "html_report", None),
            (research, "evaluate_frames", "evaluate_frames", None),
            (fc_research, "evaluate_factor_research", "fincore_evaluate", None),
            (ResearchEvaluationResult, "export", "evaluation_export", None),
            (fc_research, "_write_charts", "evaluation_charts", None),
            (pd.DataFrame, "to_csv", "dataframe_to_csv", None),
        ]
        result["phase_targets_installed"] = {label: timers.wrap(owner, name, label, after)
                                              for owner, name, label, after in targets}
        if args.diagnostic:
            fingerprint_source = models.fingerprint_value
            fingerprint_aliases = timers.aliases(fingerprint_source, "diagnostic_fingerprint_value")
            result["diagnostic_sources"] = {
                "fingerprint_value": {"module": fingerprint_source.__module__,
                    "qualname": fingerprint_source.__qualname__,
                    "filename": fingerprint_source.__code__.co_filename,
                    "firstlineno": fingerprint_source.__code__.co_firstlineno,
                    "aliases_wrapped": fingerprint_aliases},
                "validate_factors": timers.wrap(fc_research, "_validate_factors", "diagnostic_validate_factors"),
                "strategy_periodset": timers.wrap(bt.Strategy, "_periodset", "diagnostic_periodset"),
            }
        if args.profile == "full":
            report_module = report_html
            report_writer = report_html.write_factor_html
            def capture(document, target, *positional, **keywords):
                path = report_writer(document, target, *positional, **keywords)
                captured.append((document, Path(path)))
                return path
            report_html.write_factor_html = capture

        command = _example_cli_arguments(args.example, args.profile, output, data_root, data_identity["symbols"])
        result["example_cli_arguments"] = command
        result["expected_engine"] = args.expected_engine
        result["loaded_module_origins_before_main"] = module_origins
        result["environment"] = {"python": sys.version, "executable": sys.executable,
            "platform": platform.platform(), "logical_cpus": psutil.cpu_count(),
            "available_memory_bytes": psutil.virtual_memory().available, "numpy": np.__version__,
            "pandas": pd.__version__, "backtrader_origin": bt.__file__, "fincore_origin": fincore.__file__,
            "resource_sampling_interval_seconds": 0.5,
            "sampling_note": "tree RSS is summed at each sample; sampled tree CPU is approximate; main process CPU is primary",
            "diagnostic_note": "--diagnostic panel deep-memory measurement runs after load_daily_panel returns and is included in main wall/CPU"}

        def sample_resources():
            procs = [process]
            try:
                procs += process.children(recursive=True)
            except psutil.Error:
                pass
            rows, rss, cpu = [], 0, 0.0
            for child in procs:
                try:
                    info, cput = child.memory_info(), child.cpu_times()
                    seconds = cput.user + cput.system
                    rows.append({"pid": child.pid, "rss_bytes": info.rss, "cpu_seconds": seconds})
                    rss += info.rss
                    cpu += seconds
                except psutil.Error:
                    continue
            samples.append({"elapsed_ns": time.perf_counter_ns() - resource_start,
                "tree_rss_bytes": rss, "sampled_tree_cpu_seconds": cpu,
                "available_memory_bytes": psutil.virtual_memory().available, "processes": rows})

        def resource_sampler():
            while not stop.wait(0.5):
                sample_resources()

        resource_start = time.perf_counter_ns()
        sample_resources()
        sampler = threading.Thread(target=resource_sampler, name="factor-benchmark-resources", daemon=True)
        sampler.start()
        main_started = time.perf_counter_ns()
        main_cpu0 = time.process_time_ns()
        try:
            value = module.main(command)
            result["example_exit_code"] = value if type(value) is int else (0 if value is None else 1)
        except BaseException as exc:
            result.update({"exception_type": type(exc).__name__, "exception_message": str(exc),
                           "example_exit_code": 130 if isinstance(exc, KeyboardInterrupt) else 1})
        finally:
            main_wall = time.perf_counter_ns() - main_started
            main_cpu = time.process_time_ns() - main_cpu0
            info = process.memory_info()
            memory["after_main"] = {"rss_bytes": info.rss, "working_set_bytes": getattr(info, "wset", None),
                "peak_working_set_bytes": getattr(info, "peak_wset", None)}
            stop.set()
            sampler.join()
            sample_resources()
            if report_module is not None:
                report_module.write_factor_html = report_writer

        result["summary"] = json.loads((output / "example" / "summary.json").read_text(encoding="utf-8")) \
            if (output / "example" / "summary.json").is_file() else None
        if result["example_exit_code"] == 0:
            summary = result["summary"]
            problems = []
            result["observed_engine"] = _observed_engine(timers.json_rows())
            if args.expected_engine is not None and result["observed_engine"] != args.expected_engine:
                problems.append("observed Cerebro engine does not match --expected-engine")
            if not isinstance(summary, dict) or summary.get("status") != "COMPLETED":
                problems.append("summary is not completed")
            if not isinstance(summary, dict) or (summary.get("symbols"), summary.get("dates")) != (
                    data_identity["symbols"], data_identity["dates"]):
                problems.append("summary grid does not match the selected input universe")
            if args.example == "027" and summary.get("cells") != data_identity["grid_cells"]:
                problems.append("027 factor cell count mismatch")
            if not isinstance(summary, dict) or summary.get("factor_mode") != "native":
                problems.append("summary does not report native mode")
            broker = summary.get("broker") if isinstance(summary, dict) else None
            if not isinstance(broker, dict) or broker.get("submit") != 0 or broker.get("cancel") != 0:
                problems.append("summary broker counts are missing or nonzero")
            if args.example in ("025", "026") and summary.get("evaluation_status") not in ("OK", "PARTIAL"):
                problems.append("evaluation did not complete")
            if args.profile == "full":
                declared = (summary.get("reports", []) if args.example == "026" else [summary.get("report")]) \
                    if isinstance(summary, dict) else []
                report_root = output / "example"
                if not declared or any(not isinstance(path, str) or not
                        (Path(path) if Path(path).is_absolute() else report_root / path).is_file()
                        for path in declared):
                    problems.append("full HTML report output is missing")
                try:
                    result["captured_reports"] = _publish_report_semantics(output / "example", captured)
                    expected = 3 if args.example == "026" else 1
                    if len(result["captured_reports"]) != expected:
                        problems.append("captured report model count mismatch")
                except Exception as exc:
                    problems.append("report semantics capture failed: %s" % type(exc).__name__)
            result["summary_check_errors"] = problems
            result["status"] = "SUMMARY_CHECK_FAILED" if problems else "COMPLETED"
            result["runner_exit_code"] = 1 if problems else 0
        else:
            result["status"], result["runner_exit_code"] = "EXAMPLE_FAILED", result["example_exit_code"] or 1
        result["loaded_module_origins_after_main"] = _origins(bt_root, fc_root, module, example_path, {**source_before, **fc_before})
        result["memory"] = memory
    except BaseException as exc:
        result.update({"status": "RUNNER_EXCEPTION", "runner_exit_code": 130 if isinstance(exc, KeyboardInterrupt) else 1,
                       "exception_type": type(exc).__name__, "exception_message": str(exc)})
    finally:
        stop.set()
        if sampler is not None and sampler.is_alive():
            sampler.join()
        if report_module is not None and report_writer is not None:
            report_module.write_factor_html = report_writer
        result.update({"setup_wall_ns": setup_wall, "setup_process_cpu_ns": setup_cpu,
            "example_main_wall_ns": main_wall, "example_main_process_cpu_ns": main_cpu,
            "phase_timers": {} if timers is None else timers.json_rows(), "resource_samples": samples,
            "resource_peak_tree_rss_bytes": max((row["tree_rss_bytes"] for row in samples), default=None),
            "main_peak_working_set_bytes": memory.get("after_main", {}).get("peak_working_set_bytes"),
            "finished_utc": datetime.now(timezone.utc).isoformat()})
        try:
            if data_identity is not None:
                bt_after, bt_pins_after = _source_state(bt_root, "backtrader", tuple("examples/backtest/" + name for name in EXAMPLES.values()))
                fc_after, fc_pins_after = _source_state(fc_root, "fincore")
                data_after, data_pins_after = _data_state(data_root, selection_path, args.universe)
                changes = []
                for name, before, after in (("backtrader", source_before, bt_pins_after),
                                             ("fincore", fc_before, fc_pins_after), ("data", data_before, data_pins_after)):
                    changes.extend(name + ":" + path for path in set(before) | set(after) if before.get(path) != after.get(path))
                result.update({"backtrader_source_after": bt_after, "fincore_source_after": fc_after,
                               "data_identity_after": data_after, "source_or_input_changes": sorted(changes)})
                if changes or (bt_identity is not None and bt_identity != bt_after) \
                        or (fc_identity is not None and fc_identity != fc_after) \
                        or (data_identity is not None and data_identity != data_after):
                    result["status"], result["runner_exit_code"] = "INPUTS_CHANGED_DURING_RUN", 1
        except BaseException as exc:
            result.update({"status": "POSTCHECK_EXCEPTION", "runner_exit_code": 1,
                           "postcheck_error": type(exc).__name__ + ": " + str(exc)})
        result["cli_total_wall_ns"] = time.perf_counter_ns() - wall0
        result["cli_total_process_cpu_ns"] = time.process_time_ns() - cpu0
        _atomic_json(result_path, result)
    print("BENCHMARK %s %s exit=%s main_wall=%.3fs result=%s" %
          (args.example, args.profile, result["runner_exit_code"], main_wall / 1e9, result_path), flush=True)
    return int(result["runner_exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
