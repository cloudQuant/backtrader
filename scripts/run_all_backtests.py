#!/usr/bin/env python3
from __future__ import annotations

import csv
import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from strategies.benchmark_metrics import BENCHMARK_METRIC_KEYS, canonicalize_metric_payload, write_benchmark_result

OUT_DIR = REPO_ROOT / "artifacts" / "python_backtest_run"
LOG_DIR = OUT_DIR / "logs"
BENCHMARK_CSV = OUT_DIR / "benchmark_python_summary.csv"
EXCEL_PATH = OUT_DIR / "python_strategy_backtest_results.xlsx"
BENCHMARK_RESULTS_DIR = OUT_DIR / "benchmark_strategy_results"
CACHE_PATH = OUT_DIR / "strategy_source_hashes.json"
MAX_WORKERS = min(os.cpu_count() or 6, 12)
COMMAND_TIMEOUT = int(os.environ.get("BACKTEST_COMMAND_TIMEOUT", "180"))
ENGINE_RESULT_JSON = {
    "python": "backtest_result.json",
    "cpp": "cpp_result.json",
}
ENGINE_RUN_FILE = {
    "python": "run.py",
    "cpp": "run_cpp.py",
}
HASH_CACHE_VERSION = 1
SOURCE_SUFFIXES = {
    "python": {".py", ".yaml", ".yml"},
    "cpp": {".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".cmake", ".txt", ".yaml", ".yml", ".py"},
}
SKIP_SOURCE_DIRS = {"__pycache__", ".pytest_cache", "build", "bin", ".cache"}
SKIP_SOURCE_FILES = {"backtest_result.json", "cpp_result.json", "validation_report.json"}

OPTIONAL_METRIC_COLUMNS = {"contracts"}
REQUIRED_METRIC_COLUMNS = [
    key
    for key in BENCHMARK_METRIC_KEYS
    if key != "engine" and key not in OPTIONAL_METRIC_COLUMNS
]

COMMON_COLUMNS = [
    "source_group",
    "strategy_id",
    "strategy_name",
    "strategy_type",
    "strategy_dir",
    "status",
    "return_code",
    "elapsed_sec",
    "symbol",
    "timeframe",
    "data_used",
    "data_file",
    "fromdate",
    "todate",
    "rows",
    "read_time_sec",
    "run_time_sec",
    "total_time_sec",
    "bar_num",
    "buy_count",
    "sell_count",
    "win_count",
    "loss_count",
    "sum_profit",
    "trade_num",
    "total_trades",
    "sharpe_ratio",
    "annual_return",
    "max_drawdown",
    "return_rate",
    "stop_count",
    "contracts",
    "final_value",
    "log_path",
    "error",
]


def rel(path: Path | str | None) -> str:
    if not path:
        return ""
    p = Path(path)
    try:
        return str(p.resolve().relative_to(REPO_ROOT))
    except Exception:
        return str(path)


def clean_value(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat(sep=" ")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return value


def parse_number(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return clean_value(value)
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"none", "nan"}:
        return None
    if lowered in {"inf", "+inf", "infinity", "+infinity"}:
        return None
    if lowered in {"-inf", "-infinity"}:
        return None
    text = text.replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        return value


def normalize_metric_key(raw_key: str) -> str:
    key = raw_key.strip().lower()
    key = key.lstrip("-").strip()
    key = re.sub(r"[^a-z0-9_\u4e00-\u9fff]+", "_", key)
    key = re.sub(r"_+", "_", key).strip("_")
    aliases = {
        "processed_bars": "rows",
        "bars": "rows",
        "rows": "rows",
        "bar_num": "bar_num",
        "buy_entries": "buy_count",
        "buy_entry_count": "buy_count",
        "buy_signals": "buy_count",
        "buy_count": "buy_count",
        "sell_entries": "sell_count",
        "sell_entry_count": "sell_count",
        "sell_signals": "sell_count",
        "sell_count": "sell_count",
        "closed_trades": "total_trades",
        "total_closed_trades": "total_trades",
        "trade_count": "total_trades",
        "trade_num": "trade_num",
        "total_trades": "total_trades",
        "won": "win_count",
        "won_trades": "win_count",
        "win_count": "win_count",
        "lost": "loss_count",
        "lost_trades": "loss_count",
        "loss_count": "loss_count",
        "sum_profit": "sum_profit",
        "final_value": "final_value",
        "end_value": "final_value",
        "return": "return_rate",
        "return_rate": "return_rate",
        "total_return_pct": "return_rate",
        "annual_return": "annual_return",
        "sharpe": "sharpe_ratio",
        "sharpe_ratio": "sharpe_ratio",
        "max_drawdown": "max_drawdown",
        "max_drawdown_pct": "max_drawdown",
        "stop_count": "stop_count",
        "contracts": "contracts",
        "read_time_sec": "read_time_sec",
        "run_time_sec": "run_time_sec",
        "total_time_sec": "total_time_sec",
        "fromdate": "fromdate",
        "todate": "todate",
        "买入次数": "buy_count",
        "卖出次数": "sell_count",
        "总交易数": "total_trades",
        "盈利次数": "win_count",
        "亏损次数": "loss_count",
        "胜率": "win_rate",
        "最终权益": "final_value",
    }
    if key == "total_return":
        return "total_return_decimal"
    return aliases.get(key, key)


def parse_metrics_from_output(output: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^-?\s*([^:=：]+?)\s*[:=：]\s*(.+?)\s*$", stripped)
        if not match:
            continue
        key = normalize_metric_key(match.group(1))
        value_text = match.group(2).strip()
        value = parse_number(value_text)
        if key == "total_return_decimal":
            number = parse_number(value_text)
            if isinstance(number, (int, float)):
                metrics["return_rate"] = number * 100.0
            continue
        if key == "return_rate" and "%" not in value_text and match.group(1).strip().lower().lstrip("-").strip() == "total return":
            number = parse_number(value_text)
            if isinstance(number, (int, float)):
                value = number * 100.0
        if key in {
            "rows",
            "bar_num",
            "buy_count",
            "sell_count",
            "win_count",
            "loss_count",
            "sum_profit",
            "trade_num",
            "total_trades",
            "final_value",
            "return_rate",
            "annual_return",
            "sharpe_ratio",
            "max_drawdown",
            "stop_count",
            "contracts",
            "read_time_sec",
            "run_time_sec",
            "total_time_sec",
            "fromdate",
            "todate",
        }:
            metrics[key] = value
    return metrics


def canonicalize_engine_metrics(payload: Any, engine: str) -> dict[str, Any]:
    metrics = canonicalize_metric_payload(payload, engine=engine)
    if metrics:
        metrics["engine"] = engine
    return metrics


def parse_json_metrics_from_output(output: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for match in re.finditer(r"\{", output):
        try:
            loaded, _ = decoder.raw_decode(output[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            candidates.append(loaded)
    return candidates[-1] if candidates else {}


def introspect_strategy_metrics(run_file: Path, env: dict[str, str]) -> dict[str, Any]:
    snippet = r'''
import importlib.util
import inspect
import json
import math
import sys
from pathlib import Path

run_file = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(run_file.parent))
spec = importlib.util.spec_from_file_location("_strategy_run_module", run_file)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

result = None
if hasattr(module, "run"):
    sig = inspect.signature(module.run)
    params = sig.parameters
    if "plot" in params:
        result = module.run(plot=False)
    elif len(params) == 1 and hasattr(module, "load_config"):
        result = module.run(module.load_config())
    elif len(params) == 0:
        result = module.run()
elif hasattr(module, "main"):
    result = module.main()

metrics = {}
strat = None
if isinstance(result, tuple) and result:
    if isinstance(result[0], list) and result[0]:
        strat = result[0][0]
    elif result and hasattr(result[0], "broker"):
        strat = result[0]
    if len(result) > 1 and isinstance(result[1], dict):
        metrics.update(result[1])
elif isinstance(result, list) and result:
    strat = result[0]

if strat is not None:
    pass

try:
    config = module.load_config() if hasattr(module, "load_config") else {}
except Exception:
    config = {}
data_cfg = (config.get("data") or {}) if isinstance(config, dict) else {}
for src, dst in [("fromdate", "fromdate"), ("todate", "todate")]:
    if src in data_cfg:
        metrics.setdefault(dst, data_cfg[src])

def clean(value):
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value

print("__METRICS_JSON__" + json.dumps({k: clean(v) for k, v in metrics.items()}, default=str, ensure_ascii=False))
'''
    try:
        proc = subprocess.run(
            [sys.executable, "-c", snippet, str(run_file)],
            cwd=run_file.parent,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=COMMAND_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {}
    for line in reversed((proc.stdout or "").splitlines()):
        if line.startswith("__METRICS_JSON__"):
            try:
                loaded = json.loads(line[len("__METRICS_JSON__") :])
                return loaded if isinstance(loaded, dict) else {}
            except Exception:
                return {}
    return {}


def first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def pct_from_decimal(value: Any) -> Any:
    number = to_float(value)
    if number is None:
        return value
    return number * 100.0


def resolve_config_path(base_dir: Path, value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    path = Path(text)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return rel(path)


def flatten_data_files(base_dir: Path, data_cfg: dict[str, Any]) -> tuple[str, str]:
    entries: list[str] = []

    def add(label: str, value: Any) -> None:
        if isinstance(value, str):
            entries.append(f"{label}={resolve_config_path(base_dir, value)}")
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                add(f"{label}[{idx}]", item)
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                add(f"{label}.{sub_key}", sub_value)

    for key, value in data_cfg.items():
        lowered = str(key).lower()
        if lowered in {"file", "files", "assets"} or lowered.endswith("_file") or lowered.endswith("_files"):
            add(str(key), value)

    data_file = "; ".join(entries)
    data_used_parts = []
    if data_cfg.get("symbol"):
        data_used_parts.append(str(data_cfg.get("symbol")))
    if data_cfg.get("timeframe"):
        data_used_parts.append(str(data_cfg.get("timeframe")))
    if data_file:
        data_used_parts.append(data_file)
    return " | ".join(data_used_parts), data_file


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        return loaded if isinstance(loaded, dict) else {}
    except Exception as exc:
        return {"_config_error": str(exc)}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle) or {}


def load_hash_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {"version": HASH_CACHE_VERSION, "entries": {}}
    try:
        loaded = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": HASH_CACHE_VERSION, "entries": {}}
    if not isinstance(loaded, dict):
        return {"version": HASH_CACHE_VERSION, "entries": {}}
    loaded.setdefault("version", HASH_CACHE_VERSION)
    loaded.setdefault("entries", {})
    return loaded


def save_hash_cache(cache: dict[str, Any]) -> None:
    cache["version"] = HASH_CACHE_VERSION
    cache["updated_at"] = datetime.now().isoformat(sep=" ", timespec="seconds")
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe_log_name(strategy_dir: Path) -> str:
    relative = strategy_dir.relative_to(REPO_ROOT)
    return "__".join(relative.parts) + ".log"


def is_source_candidate(path: Path, engine: str) -> bool:
    if not path.is_file():
        return False
    if path.name in SKIP_SOURCE_FILES:
        return False
    if any(part in SKIP_SOURCE_DIRS for part in path.parts):
        return False
    if engine == "python" and "cpp" in path.relative_to(path.parents[1]).parts:
        return False
    if path.name == ENGINE_RUN_FILE[engine]:
        return True
    if engine == "python" and path.name == "run_cpp.py":
        return False
    if engine == "python" and path.parent.name == "cpp":
        return False
    return path.suffix.lower() in SOURCE_SUFFIXES[engine]


def strategy_source_files(strategy_dir: Path, engine: str) -> list[Path]:
    files: set[Path] = set()
    if engine == "python":
        for candidate in strategy_dir.iterdir():
            if is_source_candidate(candidate, engine):
                files.add(candidate)
    else:
        for name in (ENGINE_RUN_FILE[engine], "config.yaml"):
            candidate = strategy_dir / name
            if is_source_candidate(candidate, engine):
                files.add(candidate)
        cpp_dir = strategy_dir / "cpp"
        if cpp_dir.exists():
            for candidate in cpp_dir.rglob("*"):
                if is_source_candidate(candidate, engine):
                    files.add(candidate)
    return sorted(files, key=lambda path: rel(path))


CPP_CORE_LIB = REPO_ROOT / ".back_trader_cpp_core_build" / "libback_trader_cpp_core.a"
SHARED_CONTRACT_SOURCE_FILES = [
    REPO_ROOT / "strategies" / "benchmark_metrics.py",
]


def strategy_source_hash(strategy_dir: Path, engine: str, *, core_lib_identity: str | None = None) -> tuple[str, list[str]]:
    digest = hashlib.sha256()
    files = strategy_source_files(strategy_dir, engine)
    for shared_file in SHARED_CONTRACT_SOURCE_FILES:
        if shared_file.exists():
            files.append(shared_file)
    files = sorted(set(files), key=lambda path: rel(path))
    rel_files = [rel(path) for path in files]
    for path, rel_path in zip(files, rel_files):
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    # For C++ runs, include the prebuilt core library identity so that a core
    # rebuild correctly invalidates the per-strategy cache.
    if engine == "cpp":
        if core_lib_identity is not None:
            digest.update(b"core_lib\0")
            digest.update(core_lib_identity.encode("utf-8"))
        elif CPP_CORE_LIB.exists():
            stat = CPP_CORE_LIB.stat()
            digest.update(b"core_lib\0")
            digest.update(f"{stat.st_size}:{int(stat.st_mtime)}".encode("utf-8"))
    return digest.hexdigest(), rel_files


def result_metrics_from_file(result_path: Path, engine: str) -> dict[str, Any]:
    if not result_path.exists():
        return {}
    try:
        metrics = canonicalize_engine_metrics(load_json(result_path), engine)
    except Exception:
        return {}
    if metrics:
        write_benchmark_result(result_path, metrics)
    return metrics


def build_strategy_row(
    strategy_dir: Path,
    engine: str,
    metrics: dict[str, Any],
    *,
    status: str,
    return_code: Any,
    elapsed_sec: Any,
    log_path: Path | str | None,
    error: str = "",
) -> dict[str, Any]:
    config_path = strategy_dir / "config.yaml"
    if not config_path.exists():
        nested_configs = sorted(strategy_dir.glob("*/config.yaml"))
        if len(nested_configs) == 1:
            config_path = nested_configs[0]
    config = load_yaml(config_path)
    data_cfg = config.get("data", {}) if isinstance(config.get("data", {}), dict) else {}
    strategy_cfg = config.get("strategy", {}) if isinstance(config.get("strategy", {}), dict) else {}
    data_used, data_file = flatten_data_files(strategy_dir, data_cfg)
    if status == "success" and config.get("_config_error"):
        error = f"config parse warning: {config['_config_error']}"

    row = {
        "source_group": "strategies",
        "strategy_id": first_present(strategy_cfg, "id"),
        "strategy_name": first_present(strategy_cfg, "name") or strategy_dir.name,
        "strategy_type": first_present(strategy_cfg, "type") or strategy_dir.parent.name,
        "strategy_dir": rel(strategy_dir),
        "status": status,
        "return_code": return_code,
        "elapsed_sec": elapsed_sec,
        "symbol": first_present(data_cfg, "symbol"),
        "timeframe": first_present(data_cfg, "timeframe"),
        "data_used": data_used,
        "data_file": data_file,
        "fromdate": first_present(data_cfg, "fromdate", "start", "start_date"),
        "todate": first_present(data_cfg, "todate", "end", "end_date"),
        "rows": first_present(metrics, "rows", "bars"),
        "bar_num": first_present(metrics, "bar_num"),
        "buy_count": first_present(metrics, "buy_count"),
        "sell_count": first_present(metrics, "sell_count"),
        "win_count": first_present(metrics, "win_count", "won"),
        "loss_count": first_present(metrics, "loss_count", "lost"),
        "sum_profit": first_present(metrics, "sum_profit"),
        "trade_num": first_present(metrics, "trade_num"),
        "total_trades": first_present(metrics, "total_trades", "trade_count"),
        "sharpe_ratio": first_present(metrics, "sharpe_ratio"),
        "annual_return": first_present(metrics, "annual_return"),
        "max_drawdown": first_present(metrics, "max_drawdown"),
        "return_rate": first_present(metrics, "return_rate", "total_return_pct"),
        "stop_count": first_present(metrics, "stop_count"),
        "contracts": first_present(metrics, "contracts"),
        "final_value": first_present(metrics, "final_value"),
        "read_time_sec": first_present(metrics, "read_time_sec"),
        "run_time_sec": first_present(metrics, "run_time_sec"),
        "total_time_sec": first_present(metrics, "total_time_sec"),
        "log_path": rel(log_path),
        "error": error,
    }
    return {key: clean_value(value) for key, value in row.items()}


def run_one_strategy(run_file: Path, engine: str = "python") -> dict[str, Any]:
    strategy_dir = run_file.parent
    log_suffix = safe_log_name(strategy_dir)
    if engine != "python":
        log_suffix = f"{engine}__{log_suffix}"
    log_path = LOG_DIR / log_suffix
    result_path = strategy_dir / ENGINE_RESULT_JSON[engine]
    before_mtime = result_path.stat().st_mtime if result_path.exists() else None
    python_result_path = strategy_dir / ENGINE_RESULT_JSON["python"]
    protect_python_result = engine == "cpp"
    python_result_existed = python_result_path.exists() if protect_python_result else False
    python_result_snapshot = python_result_path.read_bytes() if python_result_existed else None
    started = time.time()
    env = os.environ.copy()
    inherited_pythonpath = [
        path
        for path in sys.path
        if path and Path(path).exists() and path != str(REPO_ROOT)
    ]
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT), *inherited_pythonpath, env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    env["MPLBACKEND"] = "Agg"
    start_perf = time.perf_counter()
    timed_out = False
    try:
        proc = subprocess.run(
            [sys.executable, str(run_file.name)],
            cwd=strategy_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=COMMAND_TIMEOUT,
            check=False,
        )
        output = proc.stdout or ""
        return_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        output += f"\n[TIMEOUT] exceeded {COMMAND_TIMEOUT}s\n"
        return_code = 124

    if protect_python_result:
        try:
            if python_result_existed:
                current = python_result_path.read_bytes() if python_result_path.exists() else None
                if current != python_result_snapshot:
                    python_result_path.write_bytes(python_result_snapshot or b"")
                    output += "\n[INFO] Restored Python benchmark backtest_result.json after cpp run.\n"
            elif python_result_path.exists():
                python_result_path.unlink()
                output += "\n[INFO] Removed cpp-created backtest_result.json to protect Python benchmark contract.\n"
        except OSError as exc:
            output += f"\n[WARN] Failed to protect Python benchmark backtest_result.json: {exc}\n"

    elapsed = time.perf_counter() - start_perf
    log_path.write_text(output, encoding="utf-8", errors="replace")

    metrics: dict[str, Any] = {}
    stale_metrics: dict[str, Any] = {}
    result_is_fresh = False
    if result_path.exists():
        after_mtime = result_path.stat().st_mtime
        result_is_fresh = after_mtime >= started - 1.0 and (before_mtime is None or after_mtime >= before_mtime)
        try:
            loaded_metrics = canonicalize_engine_metrics(load_json(result_path), engine)
        except Exception as exc:
            loaded_metrics = {"result_json_error": str(exc)}
        if result_is_fresh:
            metrics = loaded_metrics
        else:
            stale_metrics = loaded_metrics
    if return_code == 0 and not metrics:
        metrics = canonicalize_engine_metrics(parse_json_metrics_from_output(output), engine)
    if return_code == 0 and not metrics:
        metrics = canonicalize_engine_metrics(parse_metrics_from_output(output), engine)
    if return_code == 0 and not metrics and engine == "python":
        metrics = canonicalize_engine_metrics(introspect_strategy_metrics(run_file, env), engine)
    if return_code == 0 and not metrics:
        metrics = stale_metrics
    if return_code == 0 and metrics and "result_json_error" not in metrics:
        write_benchmark_result(result_path, metrics)

    status = "timeout" if timed_out else ("success" if return_code == 0 and metrics else "failed")
    error = ""
    if status != "success":
        error = "".join(output.splitlines(True)[-20:]).strip()
        if not error and return_code == 0 and not metrics:
            error = "missing or stale backtest_result.json"
    return build_strategy_row(
        strategy_dir,
        engine,
        metrics,
        status=status,
        return_code=return_code,
        elapsed_sec=elapsed,
        log_path=log_path,
        error=error,
    )


def discover_strategy_runs() -> list[Path]:
    return sorted((REPO_ROOT / "strategies").glob("*/*/run.py"))


def discover_engine_runs(engine: str) -> list[Path]:
    return sorted((REPO_ROOT / "strategies").glob(f"*/*/{ENGINE_RUN_FILE[engine]}"))


def resolve_strategy_filters(engine: str, filters: list[str] | None) -> list[Path]:
    if not filters:
        return discover_engine_runs(engine)
    all_runs = discover_engine_runs(engine)
    selected: list[Path] = []
    for item in filters:
        path = Path(item)
        if not path.is_absolute():
            path = REPO_ROOT / path
        candidates: list[Path] = []
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = [path / ENGINE_RUN_FILE[engine]]
        else:
            candidates = [
                run_file
                for run_file in all_runs
                if item in rel(run_file.parent)
            ]
        for candidate in candidates:
            if candidate.exists() and candidate.name == ENGINE_RUN_FILE[engine] and candidate not in selected:
                selected.append(candidate)
    return sorted(selected)


def cached_strategy_row(
    run_file: Path,
    engine: str,
    cache_entries: dict[str, Any],
    *,
    force: bool,
    core_lib_identity: str | None = None,
) -> dict[str, Any]:
    strategy_dir = run_file.parent
    rel_dir = rel(strategy_dir)
    source_hash, source_files = strategy_source_hash(strategy_dir, engine, core_lib_identity=core_lib_identity)
    result_path = strategy_dir / ENGINE_RESULT_JSON[engine]
    cached_entry = cache_entries.get(rel_dir, {}) if isinstance(cache_entries.get(rel_dir), dict) else {}

    # Fast path: hash match — skip stat'ing all source files entirely
    cache_hit = False
    if not force:
        if (
            cached_entry.get("source_hash") == source_hash
            and cached_entry.get("result_json") == rel(result_path)
            and result_path.exists()
        ):
            metrics = result_metrics_from_file(result_path, engine)
            if metrics:
                cache_hit = True

    # Fallback: mtime comparison (slower, but catches manual result updates)
    if not force and not cache_hit and result_path.exists():
        metrics = result_metrics_from_file(result_path, engine)
        if metrics:
            source_paths = [REPO_ROOT / item for item in source_files]
            latest_source_mtime = max((p.stat().st_mtime for p in source_paths if p.exists()), default=0.0)
            if engine == "cpp" and CPP_CORE_LIB.exists():
                latest_source_mtime = max(latest_source_mtime, CPP_CORE_LIB.stat().st_mtime)
            if result_path.stat().st_mtime >= latest_source_mtime:
                cache_hit = True

    if cache_hit:
        row = build_strategy_row(
            strategy_dir,
            engine,
            metrics,
            status="success",
            return_code=0,
            elapsed_sec=0.0,
            log_path=cached_entry.get("log_path", ""),
        )
        row["_cache_status"] = "cached"
    else:
        row = run_one_strategy(run_file, engine=engine)
        row["_cache_status"] = "ran"
    row["_source_hash"] = source_hash
    row["_source_files"] = source_files
    row["_result_json"] = rel(result_path)
    return row


# Lock for thread-safe progress counter
_progress_lock = threading.Lock()
_progress_counter = 0
_progress_total = 0


def _run_one_with_progress(
    run_file: Path,
    engine: str,
    cache_entries: dict[str, Any],
    *,
    force: bool,
    core_lib_identity: str | None,
) -> dict[str, Any]:
    global _progress_counter
    row = cached_strategy_row(run_file, engine, cache_entries, force=force, core_lib_identity=core_lib_identity)
    with _progress_lock:
        _progress_counter += 1
        idx = _progress_counter
    category = Path(row.get("strategy_dir", "")).parent.name
    cache_status = row.get("_cache_status", "ran")
    elapsed = row.get("elapsed_sec", 0.0)
    print(
        f"[{engine}] {idx}/{_progress_total} {category}/{Path(row['strategy_dir']).name} {row['status']} {cache_status} elapsed={elapsed:.2f}s",
        flush=True,
    )
    return row


def run_all_strategies(engine: str = "python", strategy_filters: list[str] | None = None, *, force: bool = False) -> list[dict[str, Any]]:
    global _progress_counter, _progress_total
    run_files = resolve_strategy_filters(engine, strategy_filters)
    cache = load_hash_cache()
    entries = cache.setdefault("entries", {})
    engine_entries = entries.setdefault(engine, {})

    # Precompute core library identity once (avoids N stat calls)
    core_lib_identity: str | None = None
    if engine == "cpp" and CPP_CORE_LIB.exists():
        stat = CPP_CORE_LIB.stat()
        core_lib_identity = f"{stat.st_size}:{int(stat.st_mtime)}"

    mode = "force" if force else "incremental"
    _progress_counter = 0
    _progress_total = len(run_files)
    print(f"[{engine}] discovered {len(run_files)} {ENGINE_RUN_FILE[engine]} files mode={mode} workers={MAX_WORKERS}", flush=True)

    # Phase 1: fast partition — separate cached from needs-run without reading file contents
    # This lets us skip thread pool overhead for cached strategies entirely
    cached_rows: list[dict[str, Any]] = []
    needs_run: list[Path] = []

    if not force:
        for run_file in run_files:
            strategy_dir = run_file.parent
            rel_dir = rel(strategy_dir)
            cached_entry = engine_entries.get(rel_dir, {}) if isinstance(engine_entries.get(rel_dir), dict) else {}
            result_path = strategy_dir / ENGINE_RESULT_JSON[engine]

            if not result_path.exists():
                needs_run.append(run_file)
                continue

            # Path 1: hash exact match (fast — no mtime checks needed)
            source_hash, source_files = strategy_source_hash(strategy_dir, engine, core_lib_identity=core_lib_identity)
            hash_match = (
                cached_entry.get("source_hash") == source_hash
                and cached_entry.get("result_json") == rel(result_path)
            )

            # Path 2: mtime fallback — result newer than all sources (handles rebuilt core lib)
            mtime_ok = False
            if not hash_match:
                source_paths = [REPO_ROOT / item for item in source_files]
                latest_source_mtime = max((p.stat().st_mtime for p in source_paths if p.exists()), default=0.0)
                if engine == "cpp" and CPP_CORE_LIB.exists():
                    latest_source_mtime = max(latest_source_mtime, CPP_CORE_LIB.stat().st_mtime)
                mtime_ok = result_path.stat().st_mtime >= latest_source_mtime

            if hash_match or mtime_ok:
                metrics = result_metrics_from_file(result_path, engine)
                if metrics:
                    row = build_strategy_row(
                        strategy_dir, engine, metrics,
                        status="success", return_code=0, elapsed_sec=0.0,
                        log_path=cached_entry.get("log_path", ""),
                    )
                    row["_cache_status"] = "cached"
                    row["_source_hash"] = source_hash
                    row["_source_files"] = source_files
                    row["_result_json"] = rel(result_path)
                    cached_rows.append(row)
                    continue

            needs_run.append(run_file)
    else:
        needs_run = list(run_files)

    print(f"[{engine}] cache hit={len(cached_rows)} need run={len(needs_run)}", flush=True)
    _progress_counter = len(cached_rows)
    _progress_total = len(run_files)

    # Phase 2: run strategies that need execution — per-strategy parallelism (not per-category)
    ran_rows: list[dict[str, Any]] = []
    if needs_run:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(
                    _run_one_with_progress, run_file, engine, engine_entries,
                    force=force, core_lib_identity=core_lib_identity,
                ): run_file
                for run_file in needs_run
            }
            for future in as_completed(futures):
                run_file = futures[future]
                try:
                    row = future.result()
                except Exception as exc:
                    strategy_dir = run_file.parent
                    row = {
                        "source_group": "strategies",
                        "strategy_type": strategy_dir.parent.name,
                        "strategy_name": strategy_dir.name,
                        "strategy_dir": rel(strategy_dir),
                        "status": "failed",
                        "return_code": None,
                        "elapsed_sec": None,
                        "error": str(exc),
                        "_cache_status": "ran",
                    }
                    with _progress_lock:
                        _progress_counter += 1
                    print(f"[{engine}] {_progress_counter}/{_progress_total} {strategy_dir.name} EXCEPTION: {exc}", flush=True)
                ran_rows.append(row)

    rows = cached_rows + ran_rows
    rows.sort(key=lambda row: str(row.get("strategy_dir", "")))

    # Update cache entries
    for row in rows:
        if row.get("status") != "success":
            continue
        rel_dir = str(row.get("strategy_dir", ""))
        if not rel_dir:
            continue
        engine_entries[rel_dir] = {
            "source_hash": row.get("_source_hash"),
            "source_files": row.get("_source_files", []),
            "result_json": row.get("_result_json"),
            "log_path": row.get("log_path", ""),
            "last_status": row.get("status"),
            "last_cache_status": row.get("_cache_status", ""),
            "updated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        }
    save_hash_cache(cache)
    return rows


def run_benchmark_aggregate() -> tuple[int, float, str]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "benchmarks" / "tools" / "strategy_benchmark_runner.py"),
        "--examples-root",
        str(REPO_ROOT / "benchmarks" / "strategies"),
        "--engines",
        "python",
        "--workers",
        str(MAX_WORKERS),
        "--repeats",
        "1",
        "--skip-build",
        "--aggregate-csv",
        str(BENCHMARK_CSV),
        "--results-dir",
        str(BENCHMARK_RESULTS_DIR),
        "--command-timeout",
        str(COMMAND_TIMEOUT),
    ]
    log_path = LOG_DIR / "benchmarks_aggregate.log"
    print("[benchmarks] starting Python-only aggregate", flush=True)
    start = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    elapsed = time.perf_counter() - start
    log_path.write_text(proc.stdout or "", encoding="utf-8", errors="replace")
    print(f"[benchmarks] aggregate done rc={proc.returncode} elapsed={elapsed:.2f}s csv={rel(BENCHMARK_CSV)}", flush=True)
    return proc.returncode, elapsed, rel(log_path)


def benchmark_strategy_file(strategy_name: str) -> Path | None:
    strategy_dir = REPO_ROOT / "benchmarks" / "strategies" / strategy_name
    candidates = [strategy_dir / f"{strategy_name}.py"]
    candidates.extend(sorted(p for p in strategy_dir.glob("*.py") if not p.name.startswith("pybind_") and p.name != "run_performance_benchmark.py"))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def parse_datetime_ctor(text: str, name: str) -> str:
    pattern = re.compile(rf"{name}\s*=\s*datetime\.datetime\((\d{{4}}),\s*(\d{{1,2}}),\s*(\d{{1,2}})(?:,\s*(\d{{1,2}}),\s*(\d{{1,2}}),\s*(\d{{1,2}}))?")
    match = pattern.search(text)
    if not match:
        return ""
    year, month, day, hour, minute, second = match.groups()
    if hour is None:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d} 00:00:00"
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d} {int(hour):02d}:{int(minute):02d}:{int(second):02d}"


def resolve_benchmark_data(script_path: Path, filename: str) -> str:
    search_paths = [
        script_path.parent / filename,
        script_path.parent.parent / filename,
        REPO_ROOT / filename,
        REPO_ROOT / "datas" / filename,
        REPO_ROOT / "tests_python" / "datas" / filename,
        script_path.parent / "datas" / filename,
    ]
    for path in search_paths:
        if path.exists():
            return rel(path)
    return filename


def parse_benchmark_metadata(strategy_name: str) -> dict[str, Any]:
    script_path = benchmark_strategy_file(strategy_name)
    if script_path is None:
        return {"strategy_dir": rel(REPO_ROOT / "benchmarks" / "strategies" / strategy_name)}
    text = script_path.read_text(encoding="utf-8", errors="replace")
    data_files = []
    for pattern in [r"resolve_data_path\(\s*['\"]([^'\"]+)['\"]", r"dataname\s*=\s*['\"]([^'\"]+)['\"]"]:
        for match in re.finditer(pattern, text):
            value = match.group(1)
            if value not in data_files:
                data_files.append(value)
    resolved_files = [resolve_benchmark_data(script_path, value) for value in data_files]
    data_desc_match = re.search(r"^\s*Data:\s*(.+)$", text, flags=re.MULTILINE)
    data_desc = data_desc_match.group(1).strip() if data_desc_match else ""
    timeframe = "D1" if re.search(r"daily|day", data_desc, flags=re.IGNORECASE) else ""
    if re.search(r"minute|min", data_desc, flags=re.IGNORECASE):
        timeframe = "intraday"
    return {
        "strategy_dir": rel(script_path.parent),
        "data_used": data_desc or "; ".join(resolved_files),
        "data_file": "; ".join(resolved_files),
        "fromdate": parse_datetime_ctor(text, "fromdate"),
        "todate": parse_datetime_ctor(text, "todate"),
        "timeframe": timeframe,
    }


def load_benchmark_rows(aggregate_rc: int, aggregate_elapsed: float, aggregate_log_path: str) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    if not BENCHMARK_CSV.exists():
        return [], pd.DataFrame()
    raw = pd.read_csv(BENCHMARK_CSV)
    rows: list[dict[str, Any]] = []
    for _, record in raw.iterrows():
        item = record.to_dict()
        strategy_name = str(item.get("strategy", ""))
        meta = parse_benchmark_metadata(strategy_name)
        status = item.get("status") or ("success" if item.get("return_code") == 0 else "failed")
        row = {
            "source_group": "benchmarks/strategies",
            "strategy_id": "",
            "strategy_name": strategy_name,
            "strategy_type": "benchmark",
            "strategy_dir": meta.get("strategy_dir", ""),
            "status": status,
            "return_code": item.get("return_code"),
            "elapsed_sec": item.get("script_elapsed_sec"),
            "symbol": "",
            "timeframe": meta.get("timeframe", ""),
            "data_used": meta.get("data_used", ""),
            "data_file": meta.get("data_file", ""),
            "fromdate": meta.get("fromdate", ""),
            "todate": meta.get("todate", ""),
            "rows": item.get("python_rows"),
            "read_time_sec": item.get("python_read_time_sec"),
            "run_time_sec": item.get("python_run_time_sec"),
            "total_time_sec": item.get("python_total_time_sec"),
            "bar_num": item.get("python_bar_num"),
            "buy_count": item.get("python_buy_count"),
            "sell_count": item.get("python_sell_count"),
            "win_count": item.get("python_win_count"),
            "loss_count": item.get("python_loss_count"),
            "sum_profit": item.get("python_sum_profit"),
            "trade_num": item.get("python_trade_num"),
            "total_trades": item.get("python_total_trades") if not pd.isna(item.get("python_total_trades")) else item.get("python_trade_num"),
            "sharpe_ratio": item.get("python_sharpe_ratio"),
            "annual_return": item.get("python_annual_return"),
            "max_drawdown": item.get("python_max_drawdown"),
            "return_rate": item.get("python_return_rate"),
            "stop_count": item.get("python_stop_count"),
            "contracts": item.get("python_contracts"),
            "final_value": item.get("python_final_value"),
            "log_path": aggregate_log_path,
            "error": item.get("error") or (f"benchmark aggregate rc={aggregate_rc}" if aggregate_rc else ""),
        }
        rows.append({key: clean_value(value) for key, value in row.items()})
    return rows, raw


def missing_metric_reason(row: pd.Series, field: str) -> str:
    if field == "sharpe_ratio":
        trade_num = to_float(row.get("trade_num"))
        total_trades = to_float(row.get("total_trades"))
        return_rate = to_float(row.get("return_rate"))
        if (trade_num or 0.0) == 0.0 and (total_trades or 0.0) == 0.0 and (return_rate or 0.0) == 0.0:
            return "undefined: no trades and flat equity curve"
    if field == "annual_return":
        final_value = to_float(row.get("final_value"))
        if final_value is not None and final_value <= 0:
            return "undefined: non-positive final portfolio value"
    return ""


def write_excel(strategy_rows: list[dict[str, Any]], benchmark_rows: list[dict[str, Any]], benchmark_raw: pd.DataFrame, aggregate_info: dict[str, Any], excel_path: Path = EXCEL_PATH) -> None:
    all_rows = benchmark_rows + strategy_rows
    all_df = pd.DataFrame(all_rows)
    for col in COMMON_COLUMNS:
        if col not in all_df.columns:
            all_df[col] = ""
    all_df = all_df[COMMON_COLUMNS]
    strategies_df = all_df[all_df["source_group"] == "strategies"].copy()
    benchmarks_df = all_df[all_df["source_group"] == "benchmarks/strategies"].copy()
    failures_df = all_df[all_df["status"] != "success"].copy()
    successful_strategies_df = strategies_df[strategies_df["status"] == "success"].copy()
    missing_rows = []
    for _, row in successful_strategies_df.iterrows():
        missing_fields = []
        for field in REQUIRED_METRIC_COLUMNS:
            if field not in successful_strategies_df.columns:
                missing_fields.append(field)
                continue
            value = row.get(field)
            if value is None or value == "" or (isinstance(value, float) and math.isnan(value)):
                missing_fields.append(field)
        if missing_fields:
            reasons = [
                reason
                for reason in (missing_metric_reason(row, field) for field in missing_fields)
                if reason
            ]
            missing_rows.append({
                "strategy_dir": row.get("strategy_dir", ""),
                "strategy_name": row.get("strategy_name", ""),
                "strategy_type": row.get("strategy_type", ""),
                "missing_count": len(missing_fields),
                "missing_fields": ",".join(missing_fields),
                "missing_reasons": "; ".join(dict.fromkeys(reasons)),
                "log_path": row.get("log_path", ""),
            })
    missing_fields_df = pd.DataFrame(missing_rows)
    missing_summary_rows = []
    for field in REQUIRED_METRIC_COLUMNS:
        missing_count = 0
        for _, row in successful_strategies_df.iterrows():
            value = row.get(field)
            if value is None or value == "" or (isinstance(value, float) and math.isnan(value)):
                missing_count += 1
        missing_summary_rows.append({
            "field": field,
            "missing_successful_strategies": missing_count,
            "successful_strategies": len(successful_strategies_df),
        })
    missing_summary_df = pd.DataFrame(missing_summary_rows)
    summary_rows = [
        {"metric": "generated_at", "value": datetime.now().isoformat(sep=" ", timespec="seconds")},
        {"metric": "engine", "value": aggregate_info.get("engine", "python")},
        {"metric": "max_workers", "value": MAX_WORKERS},
        {"metric": "command_timeout_sec", "value": COMMAND_TIMEOUT},
        {"metric": "excel_path", "value": rel(excel_path)},
        {"metric": "benchmark_csv", "value": rel(BENCHMARK_CSV)},
        {"metric": "benchmark_return_code", "value": aggregate_info.get("return_code")},
        {"metric": "benchmark_elapsed_sec", "value": aggregate_info.get("elapsed_sec")},
        {"metric": "benchmark_log", "value": aggregate_info.get("log_path")},
        {"metric": "benchmark_rows", "value": len(benchmark_rows)},
        {"metric": "benchmark_success", "value": int((benchmarks_df["status"] == "success").sum()) if not benchmarks_df.empty else 0},
        {"metric": "benchmark_failed", "value": int((benchmarks_df["status"] != "success").sum()) if not benchmarks_df.empty else 0},
        {"metric": "strategy_rows", "value": len(strategy_rows)},
        {"metric": "strategy_success", "value": int((strategies_df["status"] == "success").sum()) if not strategies_df.empty else 0},
        {"metric": "strategy_failed", "value": int((strategies_df["status"] != "success").sum()) if not strategies_df.empty else 0},
        {"metric": "strategy_ran", "value": aggregate_info.get("strategy_ran", 0)},
        {"metric": "strategy_cached", "value": aggregate_info.get("strategy_cached", 0)},
        {"metric": "force", "value": aggregate_info.get("force", False)},
        {"metric": "hash_cache", "value": rel(CACHE_PATH)},
        {"metric": "strategy_success_with_missing_fields", "value": len(missing_fields_df)},
        {"metric": "all_rows", "value": len(all_df)},
        {"metric": "all_success", "value": int((all_df["status"] == "success").sum()) if not all_df.empty else 0},
        {"metric": "all_failed", "value": int((all_df["status"] != "success").sum()) if not all_df.empty else 0},
    ]
    summary_df = pd.DataFrame(summary_rows)
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="summary", index=False)
        all_df.to_excel(writer, sheet_name="all_results", index=False)
        strategies_df.to_excel(writer, sheet_name="strategies", index=False)
        benchmarks_df.to_excel(writer, sheet_name="benchmarks", index=False)
        failures_df.to_excel(writer, sheet_name="run_failures", index=False)
        missing_fields_df.to_excel(writer, sheet_name="missing_fields", index=False)
        missing_summary_df.to_excel(writer, sheet_name="missing_field_summary", index=False)
        if not benchmark_raw.empty:
            benchmark_raw.to_excel(writer, sheet_name="benchmark_raw", index=False)


def main() -> int:
    global MAX_WORKERS, COMMAND_TIMEOUT
    parser = argparse.ArgumentParser(description="Run strategy backtests with incremental caching and export canonical metrics.")
    parser.add_argument(
        "--engine",
        choices=sorted(ENGINE_RUN_FILE),
        default="python",
        help="Runtime to execute. python runs run.py and writes backtest_result.json; cpp runs run_cpp.py and writes cpp_result.json.",
    )
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help=f"Number of parallel strategy workers (default: {MAX_WORKERS}).")
    parser.add_argument("--command-timeout", type=int, default=COMMAND_TIMEOUT, help="Per-strategy timeout in seconds.")
    parser.add_argument(
        "--strategy",
        action="append",
        help="Optional strategy directory, run file, or path substring. Can be provided multiple times.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore source hash cache and rerun all selected strategies.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only check cache status without running any strategy. Prints how many would run vs cached.",
    )
    parser.add_argument(
        "--include-benchmarks",
        action="store_true",
        help="Also run benchmarks/strategies Python aggregate before strategies.",
    )
    args = parser.parse_args()
    if args.include_benchmarks and args.engine != "python":
        parser.error("--include-benchmarks is only supported with --engine python")
    MAX_WORKERS = args.workers
    COMMAND_TIMEOUT = args.command_timeout
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    BENCHMARK_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Dry-run mode: just report cache status without executing anything
    if args.dry_run:
        run_files = resolve_strategy_filters(args.engine, args.strategy)
        cache = load_hash_cache()
        entries = cache.setdefault("entries", {})
        engine_entries = entries.setdefault(args.engine, {})
        core_lib_identity: str | None = None
        if args.engine == "cpp" and CPP_CORE_LIB.exists():
            stat = CPP_CORE_LIB.stat()
            core_lib_identity = f"{stat.st_size}:{int(stat.st_mtime)}"
        cached_count = 0
        need_run_count = 0
        for run_file in run_files:
            strategy_dir = run_file.parent
            rel_dir = rel(strategy_dir)
            cached_entry = engine_entries.get(rel_dir, {}) if isinstance(engine_entries.get(rel_dir), dict) else {}
            result_path = strategy_dir / ENGINE_RESULT_JSON[args.engine]
            if not result_path.exists():
                need_run_count += 1
                continue
            source_hash, source_files = strategy_source_hash(strategy_dir, args.engine, core_lib_identity=core_lib_identity)
            hash_match = (
                cached_entry.get("source_hash") == source_hash
                and cached_entry.get("result_json") == rel(result_path)
            )
            mtime_ok = False
            if not hash_match:
                source_paths = [REPO_ROOT / item for item in source_files]
                latest_source_mtime = max((p.stat().st_mtime for p in source_paths if p.exists()), default=0.0)
                if args.engine == "cpp" and CPP_CORE_LIB.exists():
                    latest_source_mtime = max(latest_source_mtime, CPP_CORE_LIB.stat().st_mtime)
                mtime_ok = result_path.stat().st_mtime >= latest_source_mtime
            if hash_match or mtime_ok:
                cached_count += 1
            else:
                need_run_count += 1
        print(f"[dry-run] engine={args.engine} total={len(run_files)} cached={cached_count} need_run={need_run_count} force={args.force}")
        return 0

    start = time.perf_counter()
    if args.include_benchmarks:
        benchmark_rc, benchmark_elapsed, benchmark_log_path = run_benchmark_aggregate()
    else:
        benchmark_rc, benchmark_elapsed, benchmark_log_path = 0, 0.0, ""
    strategy_rows = run_all_strategies(engine=args.engine, strategy_filters=args.strategy, force=args.force)
    if args.include_benchmarks:
        benchmark_rows, benchmark_raw = load_benchmark_rows(benchmark_rc, benchmark_elapsed, benchmark_log_path)
    else:
        benchmark_rows, benchmark_raw = [], pd.DataFrame()
    aggregate_info = {
        "engine": args.engine,
        "return_code": benchmark_rc,
        "elapsed_sec": benchmark_elapsed,
        "log_path": benchmark_log_path,
        "strategy_ran": sum(1 for row in strategy_rows if row.get("_cache_status") == "ran"),
        "strategy_cached": sum(1 for row in strategy_rows if row.get("_cache_status") == "cached"),
        "force": args.force,
    }
    excel_path = EXCEL_PATH if args.engine == "python" else OUT_DIR / f"{args.engine}_strategy_backtest_results.xlsx"
    write_excel(strategy_rows, benchmark_rows, benchmark_raw, aggregate_info, excel_path=excel_path)
    total_elapsed = time.perf_counter() - start
    success_count = sum(1 for row in strategy_rows + benchmark_rows if row.get("status") == "success")
    failed_count = len(strategy_rows) + len(benchmark_rows) - success_count
    ran_count = aggregate_info["strategy_ran"]
    cached_count = aggregate_info["strategy_cached"]
    print(
        f"[done] engine={args.engine} excel={rel(excel_path)} rows={len(strategy_rows) + len(benchmark_rows)} "
        f"success={success_count} failed={failed_count} ran={ran_count} cached={cached_count} "
        f"elapsed={total_elapsed:.2f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
