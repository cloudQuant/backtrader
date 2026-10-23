"""Measure the unchanged 025/026/027 public main functions, one process per run.

This diagnostic adds coarse nested timers and a 10 Hz Python stack sampler.
It does not replace factor/evaluation code or imply uninstrumented benchmark
acceptance. Use fresh output directories. Example::

    python scripts/profile_factor_examples.py --example 025 --fincore-root D:/source_code/fincore --output D:/temp/factor-025
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import functools
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
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


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", choices=EXAMPLES, required=True)
    parser.add_argument("--fincore-root", type=Path, required=True)
    parser.add_argument("--fincore-revision", help="Git identity of a fixed source archive")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--no-charts", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    fincore_root = args.fincore_root.resolve()
    example_root = ROOT / "examples" / "backtest" / EXAMPLES[args.example]
    sys.path[:0] = [str(ROOT), str(fincore_root), str(example_root)]
    startup = time.perf_counter()
    import numpy as np
    import pandas as pd
    import psutil
    import backtrader as bt
    import backtrader.research as research
    from backtrader.research.factor_strategy import FactorStrategy
    from backtrader.research.sink import MemorySink
    import fincore
    from fincore.factor_analysis import research as fc_research
    from fincore.factor_analysis.research import ResearchEvaluationResult
    from backtrader.research.fincore_adapter import _check_capabilities
    from fincore.report.factor import write_factor_report

    _check_capabilities(fc_research)
    assert callable(write_factor_report)

    if not Path(fincore.__file__).resolve().is_relative_to(fincore_root):
        raise RuntimeError("unexpected fincore source")
    if not Path(bt.__file__).resolve().is_relative_to(ROOT):
        raise RuntimeError("unexpected Backtrader source")
    spec = importlib.util.spec_from_file_location("_profile_example", example_root / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import_seconds = time.perf_counter() - startup
    data_root = ROOT / "tests" / "datas" / "a_stocks"
    manifest = json.loads((data_root / "_metadata" / "manifest.json").read_text("utf-8"))
    input_paths = [data_root / e["file"] for e in manifest["output"]["symbols"]]
    input_paths += [data_root / "_metadata" / name for name in ("manifest.json", "observed_calendar.csv")]
    source_paths = list((ROOT / "backtrader").rglob("*.py"))
    source_paths += list((fincore_root / "fincore").rglob("*.py"))
    source_paths += list(example_root.glob("*.py")) + [example_root / "config.yaml", Path(__file__)]
    pins = {str(p): sha256(p) for p in source_paths + input_paths}
    (output / "input-source-pins.json").write_text(json.dumps(pins, indent=2), "utf-8")
    process = psutil.Process()
    baseline_memory = psutil.virtual_memory()._asdict()
    timers = defaultdict(lambda: {"calls": 0, "inclusive_seconds": 0.0, "exclusive_seconds": 0.0})
    active = []
    events = []
    leaf_samples = Counter()
    project_samples = Counter()
    stack_samples = Counter()
    phase_samples = Counter()
    resources = []
    stop = threading.Event()
    main_thread = threading.get_ident()
    run_started = time.perf_counter()
    log = (output / "stages.jsonl").open("w", encoding="utf-8", buffering=1)

    def wrap(owner, name, label, announce=False):
        original = getattr(owner, name)

        @functools.wraps(original)
        def measured(*positional, **keywords):
            before = time.perf_counter()
            item = [label, before, 0.0]
            active.append(item)
            if announce:
                print("START " + label, flush=True)
            try:
                return original(*positional, **keywords)
            finally:
                elapsed = time.perf_counter() - before
                active.pop()
                if active:
                    active[-1][2] += elapsed
                row = timers[label]
                row["calls"] += 1
                row["inclusive_seconds"] += elapsed
                row["exclusive_seconds"] += elapsed - item[2]
                if announce:
                    event = {"phase": label, "start_seconds": before - run_started,
                             "wall_seconds": elapsed, "rss_bytes": process.memory_info().rss}
                    events.append(event)
                    log.write(json.dumps(event) + "\n")
                    print("END %s %.3fs" % (label, elapsed), flush=True)
        setattr(owner, name, measured)

    wrap(module, "load_daily_panel", "read_csv_panel", True)
    wrap(module, "_run_factor" if args.example == "027" else "_run_native_collection", "collection_total", True)
    wrap(research, "align_to_grid", "align_to_grid")
    wrap(bt.Cerebro, "run", "cerebro_run", True)
    wrap(bt.Cerebro, "_runonce", "engine_runonce", True)
    wrap(bt.Cerebro, "_runnext", "engine_runnext", True)
    wrap(bt.feed.DataBase, "preload", "feed_preload")
    wrap(FactorStrategy, "__init__", "strategy_init", True)
    wrap(FactorStrategy, "_collect_current_grid_point", "collect_grid_points")
    wrap(FactorStrategy, "stop", "strategy_stop", True)
    wrap(MemorySink, "finalize", "sink_finalize", True)
    wrap(research, "write_factor_report", "html_report", True)
    wrap(research, "evaluate_frames", "evaluate_frames", True)
    wrap(fc_research, "evaluate_factor_research", "fincore_evaluate", True)
    wrap(ResearchEvaluationResult, "export", "evaluation_export", True)
    wrap(fc_research, "_write_charts", "evaluation_charts", True)
    wrap(pd.DataFrame, "to_csv", "dataframe_to_csv")

    def sampler():
        while not stop.wait(0.1):
            frame = sys._current_frames().get(main_thread)
            frames = []
            while frame is not None:
                path = frame.f_code.co_filename.replace("\\", "/")
                frames.append("%s:%s:%s" % (path, frame.f_code.co_firstlineno, frame.f_code.co_name))
                frame = frame.f_back
            if frames:
                leaf_samples[frames[0]] += 1
                project = [f for f in frames if ("/backtrader/" in f or "/fincore/" in f)
                           and "/scripts/profile_factor_examples.py:" not in f]
                if project:
                    project_samples[project[0]] += 1
                stack_samples[" <- ".join(frames[:8])] += 1
                phase_samples[active[-1][0] if active else "main_other"] += 1
            if len(resources) == 0 or time.perf_counter() - run_started - resources[-1][0] >= 1:
                mem = process.memory_info()
                cpu = process.cpu_times()
                resources.append([time.perf_counter() - run_started, mem.rss, cpu.user + cpu.system,
                                  psutil.virtual_memory().available])

    thread = threading.Thread(target=sampler, name="factor-profile-sampler", daemon=True)
    command = ["--output-dir", str(output / "example"), "--max-symbols", str(args.max_symbols),
               "--factor-mode", "native", "--data-dir", str(data_root)]
    if not args.no_report:
        command.append("--report")
    if args.no_charts and args.example != "027":
        command.append("--no-charts")
    cpu_before = time.process_time()
    run_started = time.perf_counter()
    thread.start()
    exit_code = None
    try:
        exit_code = module.main(command)
    finally:
        wall = time.perf_counter() - run_started
        cpu = time.process_time() - cpu_before
        stop.set()
        thread.join()
        log.close()
        changed = [path for path, digest in pins.items() if sha256(Path(path)) != digest]
        summary_path = output / "example" / "summary.json"
        result = {
            "schema": 1, "evidence": "SINGLE_RUN_INSTRUMENTED_PUBLIC_MAIN_DIAGNOSTIC",
            "example": args.example, "arguments": command, "exit_code": exit_code,
            "wall_seconds": wall, "process_cpu_seconds": cpu, "preload_import_seconds": import_seconds,
            "peak_rss_bytes": getattr(process.memory_info(), "peak_wset", process.memory_info().rss),
            "timers": dict(timers), "events": events, "resources_1s": resources,
            "samples": sum(leaf_samples.values()), "leaf_samples": leaf_samples.most_common(60),
            "project_samples": project_samples.most_common(60), "stack_samples": stack_samples.most_common(80),
            "phase_samples": phase_samples.most_common(), "source_or_input_changes": changed,
            "summary": json.loads(summary_path.read_text("utf-8")) if summary_path.exists() else None,
            "environment": {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
                            "cpu_logical": psutil.cpu_count(), "pandas": pd.__version__, "numpy": np.__version__,
                            "backtrader": bt.__file__, "fincore": fincore.__file__, "memory_before": baseline_memory,
                            "backtrader_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                            "fincore_head": args.fincore_revision or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=fincore_root, text=True).strip()},
            "limitations": ["Timers are nested; inclusive values must not be summed.",
                            "Sampling uses the GIL and is approximate; no statistical confidence from one run.",
                            "Source/data hashes and instrumentation imports are outside main wall time.",
                            "Output verification and process shutdown are outside main wall time."]}
        (output / "profile.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
        print("PROFILE %s wall=%.3fs cpu=%.3fs exit=%s" % (args.example, wall, cpu, exit_code), flush=True)
        if changed:
            raise RuntimeError("source/data changed during measurement")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
