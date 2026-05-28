from __future__ import annotations

import atexit
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    import backtrader as bt
except ModuleNotFoundError:
    bt = None


COMPARE_ONLY_SCHEMA = [
    "rows",
    "bar_num",
    "buy_count",
    "sell_count",
    "win_count",
    "loss_count",
    "sum_profit",
    "trade_num",
    "total_trades",
    "stop_count",
    "contracts",
    "final_value",
    "sharpe_ratio",
    "annual_return",
    "max_drawdown",
    "return_rate",
]

BENCHMARK_METRIC_KEYS = [
    "rows",
    "bar_num",
    "buy_count",
    "sell_count",
    "win_count",
    "loss_count",
    "sum_profit",
    "trade_num",
    "total_trades",
    "stop_count",
    "contracts",
    "final_value",
    "sharpe_ratio",
    "annual_return",
    "max_drawdown",
    "return_rate",
]
PERFORMANCE_METRIC_KEYS = [
    "read_time_sec",
    "run_time_sec",
    "total_time_sec",
]

_ORIGINAL_CEREBRO_RUN: Any = None
_ORIGINAL_SUBPROCESS_RUN: Any = None
_ORIGINAL_SUBPROCESS_CHECK_CALL: Any = None
_HOOK_CONTEXTS: list[dict[str, Any]] = []
_CPP_HOOK_CONTEXTS: list[dict[str, Any]] = []
_LATEST_METRICS_BY_BASE_DIR: dict[Path, dict[str, Any]] = {}
_LATEST_CPP_METRICS_BY_BASE_DIR: dict[Path, dict[str, Any]] = {}


_BenchmarkAnalyzerBase = bt.Analyzer if bt is not None else object


class BenchmarkMetricsAnalyzer(_BenchmarkAnalyzerBase):
    def start(self) -> None:
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0
        self.trade_num = 0
        self.stop_count = 0

    def next(self) -> None:
        self.bar_num += 1

    def notify_order(self, order: bt.Order) -> None:
        if order.status != order.Completed:
            return
        if order.isbuy():
            self.buy_count += 1
        elif order.issell():
            self.sell_count += 1
        if order.exectype == bt.Order.Stop:
            self.stop_count += 1

    def notify_trade(self, trade: bt.Trade) -> None:
        if not trade.isclosed:
            return
        self.trade_num += 1
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.sum_profit += trade.pnl

    def get_analysis(self) -> dict[str, Any]:
        return {
            "bar_num": self.bar_num,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "sum_profit": self.sum_profit,
            "trade_num": self.trade_num,
            "stop_count": self.stop_count,
        }


def add_benchmark_analyzer(cerebro: Any, name: str = "benchmark") -> None:
    if bt is None:
        raise RuntimeError("backtrader is required to install Python benchmark analyzers")
    cerebro.addanalyzer(BenchmarkMetricsAnalyzer, _name=name)


def clean_metric_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return value.isoformat(sep=" ")
        except TypeError:
            return value.isoformat()
    return value


def compare_only_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: clean_metric_value(metrics.get(key)) for key in COMPARE_ONLY_SCHEMA}


def compact_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return compare_only_metrics(metrics)


def nested_get(mapping: Any, *keys: str, default: Any = None) -> Any:
    current = mapping
    for key in keys:
        if current is None:
            return default
        if isinstance(current, dict):
            current = current.get(key, default)
        elif hasattr(current, key):
            current = getattr(current, key)
        else:
            return default
    return current


def finite_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _first_numeric(mapping: dict[str, Any], *keys: str) -> float | None:
    return finite_or_none(_first_present(mapping, *keys))


_COMPARE_ONLY_ALIASES: dict[str, tuple[str, ...]] = {
    "rows": ("rows", "bars", "bars_base", "bars_m15", "bars_daily", "processed_bars"),
    "bar_num": ("bar_num", "rows", "bars", "bars_base", "bars_m15", "bars_daily", "processed_bars"),
    "buy_count": ("buy_count", "buy_entries", "buy_entry_count", "buy_signals"),
    "sell_count": ("sell_count", "sell_entries", "sell_entry_count", "sell_signals"),
    "win_count": ("win_count", "won", "won_trades"),
    "loss_count": ("loss_count", "lost", "lost_trades"),
    "sum_profit": ("sum_profit",),
    "trade_num": ("trade_num", "closed_trades", "total_closed_trades"),
    "total_trades": ("total_trades", "trade_count", "total_trade_count"),
    "stop_count": ("stop_count",),
    "contracts": ("contracts",),
    "final_value": ("final_value", "end_value"),
    "sharpe_ratio": ("sharpe_ratio", "sharpe"),
}
_COMPARE_ONLY_SOURCE_KEYS = {
    alias
    for aliases in _COMPARE_ONLY_ALIASES.values()
    for alias in aliases
} | {
    "annual_return",
    "annual_return_pct",
    "max_drawdown",
    "max_drawdown_pct",
    "return_rate",
    "total_return_pct",
    "return_pct",
}


def _flatten_metric_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        if isinstance(payload, tuple):
            for item in reversed(payload):
                flattened = _flatten_metric_payload(item)
                if flattened:
                    return flattened
        return {}
    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        return metrics
    return payload


def _annual_return_reference(source: dict[str, Any]) -> float | None:
    return_rate = _first_numeric(source, "return_rate", "total_return_pct", "return_pct")
    periods = _first_numeric(source, "rows", "bar_num", "bars", "bars_base", "bars_m15", "bars_daily", "processed_bars")
    if return_rate is None or periods is None or periods <= 0:
        return None
    total_return = 1.0 + return_rate / 100.0
    if total_return <= 0.0:
        return None
    try:
        reference = math.expm1(math.log(total_return) / periods * 252.0)
    except (ValueError, OverflowError):
        return None
    return reference if math.isfinite(reference) else None


def _choose_nearest_annual_candidate(candidates: list[float], reference: float | None) -> float:
    finite_candidates = [candidate for candidate in candidates if math.isfinite(candidate)]
    if not finite_candidates:
        return candidates[0]
    if reference is None or not math.isfinite(reference):
        return finite_candidates[0]
    return min(finite_candidates, key=lambda candidate: (abs(candidate - reference), abs(candidate)))


def _normalize_annual_return_value(
    value: float,
    *,
    engine: str | None = None,
    pct_label: bool = False,
    reference: float | None = None,
) -> float:
    if pct_label:
        return value / 100.0 if engine == "cpp" else value
    if engine == "cpp":
        return value * 100.0
    return value


def canonicalize_metric_payload(payload: Any, *, engine: str | None = None) -> dict[str, Any]:
    source = _flatten_metric_payload(payload)
    if not source:
        return {}

    already_canonical = set(source).issubset(set(COMPARE_ONLY_SCHEMA))
    has_compare_signal = any(key in source for key in _COMPARE_ONLY_SOURCE_KEYS)
    metrics: dict[str, Any] = {}

    for target, keys in _COMPARE_ONLY_ALIASES.items():
        value = _first_present(source, *keys)
        if value is not None:
            metrics[target] = value

    win_count = finite_or_none(metrics.get("win_count"))
    loss_count = finite_or_none(metrics.get("loss_count"))
    if win_count is not None and loss_count is not None:
        closed_trade_count = int(win_count + loss_count)
        trade_num = finite_or_none(metrics.get("trade_num"))
        if "trade_num" not in metrics:
            metrics["trade_num"] = closed_trade_count

    if "stop_count" not in metrics and has_compare_signal:
        metrics["stop_count"] = 0

    if "sum_profit" not in metrics:
        trade_num = finite_or_none(metrics.get("trade_num"))
        if trade_num == 0:
            metrics["sum_profit"] = 0.0

    annual_reference = _annual_return_reference(source)
    annual_return = _first_numeric(source, "annual_return")
    annual_return_pct = _first_numeric(source, "annual_return_pct")
    if annual_return_pct is not None:
        metrics["annual_return"] = _normalize_annual_return_value(
            annual_return_pct,
            engine=engine,
            pct_label=True,
            reference=annual_reference,
        )
    elif annual_return is not None:
        metrics["annual_return"] = annual_return

    max_drawdown = _first_numeric(source, "max_drawdown")
    if max_drawdown is not None:
        if "return_rate" in source or "annual_return" in source:
            metrics["max_drawdown"] = max_drawdown
        else:
            metrics["max_drawdown"] = max_drawdown / 100.0
    else:
        max_drawdown_pct = _first_numeric(source, "max_drawdown_pct")
        if max_drawdown_pct is not None:
            metrics["max_drawdown"] = max_drawdown_pct / 100.0

    return_rate = _first_numeric(source, "return_rate", "total_return_pct", "return_pct")
    if return_rate is not None:
        metrics["return_rate"] = return_rate

    if not metrics and not has_compare_signal:
        return {}
    return compare_only_metrics(metrics)


def infer_rows(frame: Any) -> int | None:
    if frame is None:
        return None
    if isinstance(frame, dict):
        for key in ("data", "aligned_index", "close_df"):
            value = frame.get(key)
            if value is not None:
                try:
                    return len(value)
                except TypeError:
                    pass
        for value in frame.values():
            try:
                return len(value)
            except TypeError:
                continue
        return None
    try:
        return len(frame)
    except TypeError:
        return None


def infer_initial_cash(config: Any, cerebro: Any = None) -> float | None:
    if isinstance(config, dict):
        backtest_cfg = config.get("backtest")
        if isinstance(backtest_cfg, dict) and backtest_cfg.get("initial_cash") is not None:
            return finite_or_none(backtest_cfg.get("initial_cash"))
    broker = getattr(cerebro, "broker", None)
    if broker is not None:
        for attr in ("startingcash", "_startingcash"):
            if hasattr(broker, attr):
                value = finite_or_none(getattr(broker, attr))
                if value is not None:
                    return value
    return None


def infer_rows_from_cerebro(cerebro: Any) -> int | None:
    datas = getattr(cerebro, "datas", None)
    if not datas:
        return None
    try:
        return len(datas[0])
    except TypeError:
        pass
    buflen = getattr(datas[0], "buflen", None)
    if callable(buflen):
        try:
            return int(buflen())
        except (TypeError, ValueError):
            return None
    return None


def extract_benchmark_metrics(
    strategy: Any,
    cerebro: Any,
    *,
    rows: int | None = None,
    initial_cash: float | None = None,
    read_time_sec: float | None = None,
    run_time_sec: float | None = None,
    total_time_sec: float | None = None,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {"engine": "python"}
    for key, value in {
        "read_time_sec": read_time_sec,
        "run_time_sec": run_time_sec,
        "total_time_sec": total_time_sec,
    }.items():
        if value is not None:
            metrics[key] = value

    benchmark_analyzer = getattr(getattr(strategy, "analyzers", None), "benchmark", None)
    benchmark_analysis = benchmark_analyzer.get_analysis() if benchmark_analyzer is not None else {}
    for key, value in benchmark_analysis.items():
        if value is not None:
            metrics[key] = value

    for attr in (
        "bar_num",
        "buy_count",
        "sell_count",
        "win_count",
        "loss_count",
        "sum_profit",
        "trade_num",
        "stop_count",
        "contracts",
    ):
        if hasattr(strategy, attr):
            metrics[attr] = getattr(strategy, attr)
    if "trade_num" not in metrics and hasattr(strategy, "trade_count"):
        metrics["trade_num"] = getattr(strategy, "trade_count")
    if "rows" not in metrics:
        if "bar_num" in metrics:
            metrics["rows"] = metrics["bar_num"]
        elif rows is not None:
            metrics["rows"] = rows

    trades = getattr(getattr(strategy, "analyzers", None), "trades", None)
    trade_analysis = trades.get_analysis() if trades is not None else {}
    total_closed = nested_get(trade_analysis, "total", "closed")
    total_total = nested_get(trade_analysis, "total", "total")
    if total_total is not None:
        metrics["total_trades"] = total_total
    elif total_closed is not None:
        metrics["total_trades"] = total_closed

    win_count = nested_get(trade_analysis, "won", "total")
    loss_count = nested_get(trade_analysis, "lost", "total")
    if win_count is not None:
        metrics["win_count"] = win_count
    if loss_count is not None:
        metrics["loss_count"] = loss_count

    won_pnl = nested_get(trade_analysis, "won", "pnl", "total")
    lost_pnl = nested_get(trade_analysis, "lost", "pnl", "total")
    if "sum_profit" not in metrics and (won_pnl is not None or lost_pnl is not None):
        metrics["sum_profit"] = (won_pnl or 0.0) + (lost_pnl or 0.0)

    try:
        final_value = float(cerebro.broker.getvalue())
        metrics["final_value"] = final_value
    except Exception:
        final_value = None

    if initial_cash is not None and final_value is not None:
        initial_cash = float(initial_cash)
        if initial_cash:
            metrics["return_rate"] = (final_value / initial_cash - 1.0) * 100.0

    sharpe = getattr(getattr(strategy, "analyzers", None), "sharpe", None)
    sharpe_analysis = sharpe.get_analysis() if sharpe is not None else {}
    sharpe_ratio = finite_or_none(sharpe_analysis.get("sharperatio"))
    if sharpe_ratio is not None:
        metrics["sharpe_ratio"] = sharpe_ratio

    returns = getattr(getattr(strategy, "analyzers", None), "returns", None)
    returns_analysis = returns.get_analysis() if returns is not None else {}
    annual_return = finite_or_none(returns_analysis.get("rnorm"))
    if annual_return is not None:
        metrics["annual_return"] = annual_return

    drawdown = getattr(getattr(strategy, "analyzers", None), "drawdown", None)
    drawdown_analysis = drawdown.get_analysis() if drawdown is not None else {}
    max_drawdown = finite_or_none(nested_get(drawdown_analysis, "max", "drawdown"))
    if max_drawdown is not None:
        metrics["max_drawdown"] = max_drawdown / 100.0

    return compact_metrics(metrics)


def write_benchmark_result(path: str | Path, metrics: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canonical = canonicalize_metric_payload(metrics)
    if not canonical:
        canonical = compact_metrics(metrics)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(canonical, handle, ensure_ascii=False, indent=2)


def load_benchmark_result(path: str | Path, fallback: Any = None) -> dict[str, Any]:
    if fallback is not None:
        metrics = canonicalize_metric_payload(fallback)
        if metrics:
            return metrics
    output_path = Path(path)
    if output_path.exists():
        try:
            return canonicalize_metric_payload(json.loads(output_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    return {}


def collect_benchmark_metrics(
    strategy: Any,
    cerebro: Any,
    *,
    frame: Any = None,
    config: Any = None,
    read_time_sec: float | None = None,
    run_time_sec: float | None = None,
    total_time_sec: float | None = None,
    result_path: str | Path | None = None,
) -> dict[str, Any]:
    metrics = extract_benchmark_metrics(
        strategy,
        cerebro,
        rows=infer_rows(frame),
        initial_cash=infer_initial_cash(config, cerebro),
        read_time_sec=read_time_sec,
        run_time_sec=run_time_sec,
        total_time_sec=total_time_sec,
    )
    if result_path is not None:
        write_benchmark_result(result_path, metrics)
    return metrics


def _has_named_analyzer(cerebro: Any, name: str) -> bool:
    for item in getattr(cerebro, "analyzers", []) or []:
        if isinstance(item, tuple) and len(item) >= 3:
            kwargs = item[2]
            if isinstance(kwargs, dict) and kwargs.get("_name") == name:
                return True
    return False


def _first_data_timeframe(cerebro: Any) -> tuple[Any, int]:
    if bt is None:
        raise RuntimeError("backtrader is required to infer benchmark analyzer timeframe")
    datas = getattr(cerebro, "datas", None) or []
    if not datas:
        return bt.TimeFrame.Days, 1
    data = datas[0]
    timeframe = getattr(data, "_timeframe", bt.TimeFrame.Days)
    compression = getattr(data, "_compression", 1) or 1
    return timeframe, int(compression)


def _annual_factor(timeframe: Any) -> int | None:
    if bt is None:
        raise RuntimeError("backtrader is required to infer benchmark annualization")
    if timeframe == bt.TimeFrame.Minutes:
        return 252 * 24 * 60
    if timeframe == bt.TimeFrame.Days:
        return 252
    if timeframe == bt.TimeFrame.Weeks:
        return 52
    if timeframe == bt.TimeFrame.Months:
        return 12
    return None


def _ensure_benchmark_analyzers(cerebro: Any) -> None:
    if bt is None:
        raise RuntimeError("backtrader is required to install Python benchmark analyzers")
    timeframe, compression = _first_data_timeframe(cerebro)
    factor = _annual_factor(timeframe)
    if not _has_named_analyzer(cerebro, "sharpe"):
        kwargs = {"_name": "sharpe", "timeframe": timeframe, "annualize": True, "riskfreerate": 0.0}
        if factor is not None:
            kwargs["factor"] = factor
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, **kwargs)
    if not _has_named_analyzer(cerebro, "returns"):
        kwargs = {"_name": "returns", "timeframe": timeframe, "compression": compression}
        if factor is not None:
            kwargs["tann"] = factor
        cerebro.addanalyzer(bt.analyzers.Returns, **kwargs)
    if not _has_named_analyzer(cerebro, "drawdown"):
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    if not _has_named_analyzer(cerebro, "trades"):
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    if not _has_named_analyzer(cerebro, "benchmark"):
        add_benchmark_analyzer(cerebro)


def _first_strategy(results: Any) -> Any:
    current = results
    while isinstance(current, (list, tuple)) and current:
        current = current[0]
    return current


def _active_hook_context() -> dict[str, Any] | None:
    return _HOOK_CONTEXTS[-1] if _HOOK_CONTEXTS else None


def _write_latest_or_canonicalized(base_dir: Path) -> None:
    result_path = base_dir / "backtest_result.json"
    metrics = _LATEST_METRICS_BY_BASE_DIR.get(base_dir)
    if metrics:
        write_benchmark_result(result_path, metrics)
        return
    if result_path.exists():
        loaded = load_benchmark_result(result_path)
        if loaded:
            write_benchmark_result(result_path, loaded)


def install_benchmark_metrics_hook(base_dir: str | Path, result_filename: str = "backtest_result.json") -> None:
    if bt is None:
        raise RuntimeError("backtrader is required to install Python benchmark metrics hook")
    base_path = Path(base_dir).resolve()
    context = {
        "base_dir": base_path,
        "result_filename": result_filename,
        "installed_at": time.perf_counter(),
    }
    _HOOK_CONTEXTS.append(context)

    def _atexit_write() -> None:
        _write_latest_or_canonicalized(base_path)

    atexit.register(_atexit_write)

    global _ORIGINAL_CEREBRO_RUN
    if _ORIGINAL_CEREBRO_RUN is not None:
        return

    _ORIGINAL_CEREBRO_RUN = bt.Cerebro.run

    def _benchmark_run(self: Any, *args: Any, **kwargs: Any) -> Any:
        context = _active_hook_context()
        if context is None:
            return _ORIGINAL_CEREBRO_RUN(self, *args, **kwargs)

        _ensure_benchmark_analyzers(self)
        initial_cash = infer_initial_cash(None, self)
        read_time_sec = time.perf_counter() - context["installed_at"]
        run_start = time.perf_counter()
        results = _ORIGINAL_CEREBRO_RUN(self, *args, **kwargs)
        run_time_sec = time.perf_counter() - run_start
        total_time_sec = time.perf_counter() - context["installed_at"]

        strategy = _first_strategy(results)
        if strategy is not None:
            metrics = extract_benchmark_metrics(
                strategy,
                self,
                rows=infer_rows_from_cerebro(self),
                initial_cash=initial_cash,
                read_time_sec=read_time_sec,
                run_time_sec=run_time_sec,
                total_time_sec=total_time_sec,
            )
            base = Path(context["base_dir"])
            _LATEST_METRICS_BY_BASE_DIR[base] = metrics
            write_benchmark_result(base / str(context["result_filename"]), metrics)
        return results

    bt.Cerebro.run = _benchmark_run


def _json_dict_candidates(text: Any) -> list[dict[str, Any]]:
    if isinstance(text, bytes):
        text = text.decode(errors="replace")
    if not isinstance(text, str) or "{" not in text:
        return []
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            loaded, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            candidates.append(loaded)
    return candidates


def _active_cpp_context() -> dict[str, Any] | None:
    return _CPP_HOOK_CONTEXTS[-1] if _CPP_HOOK_CONTEXTS else None


def _record_cpp_stdout_metrics(stdout: Any) -> None:
    context = _active_cpp_context()
    if context is None:
        return
    for candidate in reversed(_json_dict_candidates(stdout)):
        metrics = canonicalize_metric_payload(candidate, engine="cpp")
        if metrics:
            base = Path(context["base_dir"])
            _LATEST_CPP_METRICS_BY_BASE_DIR[base] = metrics
            write_benchmark_result(base / str(context["result_filename"]), metrics)
            return


def _replay_stream(stream: Any, target: Any) -> None:
    if stream in (None, ""):
        return
    try:
        target.write(stream)
    except TypeError:
        target.buffer.write(stream)
    target.flush()


def _patched_subprocess_run(*popenargs: Any, **kwargs: Any) -> subprocess.CompletedProcess:
    if _active_cpp_context() is None or _ORIGINAL_SUBPROCESS_RUN is None:
        return _ORIGINAL_SUBPROCESS_RUN(*popenargs, **kwargs)

    caller_captures = bool(kwargs.get("capture_output")) or kwargs.get("stdout") is not None or kwargs.get("stderr") is not None
    if caller_captures:
        completed = _ORIGINAL_SUBPROCESS_RUN(*popenargs, **kwargs)
        _record_cpp_stdout_metrics(getattr(completed, "stdout", None))
        return completed

    check = bool(kwargs.pop("check", False))
    run_kwargs = dict(kwargs)
    run_kwargs["stdout"] = subprocess.PIPE
    run_kwargs["stderr"] = subprocess.PIPE
    if not any(key in run_kwargs for key in ("text", "encoding", "errors", "universal_newlines")):
        run_kwargs["text"] = True

    completed = _ORIGINAL_SUBPROCESS_RUN(*popenargs, check=False, **run_kwargs)
    _record_cpp_stdout_metrics(getattr(completed, "stdout", None))
    _replay_stream(getattr(completed, "stdout", None), sys.stdout)
    _replay_stream(getattr(completed, "stderr", None), sys.stderr)
    if check and completed.returncode:
        raise subprocess.CalledProcessError(
            completed.returncode,
            completed.args,
            output=getattr(completed, "stdout", None),
            stderr=getattr(completed, "stderr", None),
        )
    return completed


def _patched_subprocess_check_call(*popenargs: Any, **kwargs: Any) -> int:
    kwargs["check"] = True
    return _patched_subprocess_run(*popenargs, **kwargs).returncode


def _write_latest_cpp_or_canonicalized(base_dir: Path, result_filename: str) -> None:
    result_path = base_dir / result_filename
    metrics = _LATEST_CPP_METRICS_BY_BASE_DIR.get(base_dir)
    if metrics:
        write_benchmark_result(result_path, metrics)
        return
    if result_path.exists():
        loaded = load_benchmark_result(result_path)
        if loaded:
            write_benchmark_result(result_path, loaded)


def _restore_cpp_python_benchmark(context: dict[str, Any]) -> None:
    result_path = Path(context["base_dir"]) / "backtest_result.json"
    existed = bool(context.get("python_result_existed"))
    snapshot = context.get("python_result_snapshot")
    try:
        if existed:
            current = result_path.read_bytes() if result_path.exists() else None
            if current != snapshot:
                result_path.write_bytes(snapshot or b"")
        elif result_path.exists():
            result_path.unlink()
    except OSError as exc:
        sys.stderr.write(f"[WARN] Failed to protect Python benchmark backtest_result.json during cpp run: {exc}\n")


def install_cpp_result_contract_hook(base_dir: str | Path, result_filename: str = "cpp_result.json") -> None:
    base_path = Path(base_dir).resolve()
    python_result_path = base_path / "backtest_result.json"
    python_result_existed = python_result_path.exists()
    context = {
        "base_dir": base_path,
        "result_filename": result_filename,
        "python_result_existed": python_result_existed,
        "python_result_snapshot": python_result_path.read_bytes() if python_result_existed else None,
    }
    _CPP_HOOK_CONTEXTS.append(context)

    def _atexit_write() -> None:
        _write_latest_cpp_or_canonicalized(base_path, str(result_filename))
        _restore_cpp_python_benchmark(context)

    atexit.register(_atexit_write)

    global _ORIGINAL_SUBPROCESS_RUN, _ORIGINAL_SUBPROCESS_CHECK_CALL
    if _ORIGINAL_SUBPROCESS_RUN is None:
        _ORIGINAL_SUBPROCESS_RUN = subprocess.run
        subprocess.run = _patched_subprocess_run
    if _ORIGINAL_SUBPROCESS_CHECK_CALL is None:
        _ORIGINAL_SUBPROCESS_CHECK_CALL = subprocess.check_call
        subprocess.check_call = _patched_subprocess_check_call
