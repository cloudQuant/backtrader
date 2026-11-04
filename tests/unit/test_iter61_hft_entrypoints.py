"""Offline entrypoint contracts for the 002/003 HFT examples.

These tests execute the CLI wrappers in-process with synthetic data paths and
engine substitutes. They do not exercise a real hftbacktest installation.
"""

import dataclasses
import importlib
import importlib.util
import json
from pathlib import Path
import runpy
import sys
import types
import urllib.error

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "backtest"
ENTRIES = (
    ("002_hft_alignment_demo", "run_hftbacktest.py"),
    ("002_hft_alignment_demo", "compare.py"),
    ("002_hft_alignment_demo", "compare_all.py"),
    ("003_hft_notebook_examples", "run_hftbacktest.py"),
    ("003_hft_notebook_examples", "compare.py"),
)


def _load_common(monkeypatch, directory):
    path = EXAMPLES / directory / "common.py"
    spec = importlib.util.spec_from_file_location("common", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "common", module)
    spec.loader.exec_module(module)
    return module


def _fake_engine_import(monkeypatch, common, problem=None):
    real_import = common.importlib.import_module
    engine = types.SimpleNamespace(BacktestAsset=object(), HashMapMarketDepthBacktest=object())
    orders = types.SimpleNamespace(BUY=1, GTX=2, LIMIT=3, PARTIALLY_FILLED=4, SELL=5)
    if problem == "missing-api":
        del engine.BacktestAsset

    def fake_import(name, *args, **kwargs):
        if name == "hftbacktest":
            if problem == "missing-package":
                raise ModuleNotFoundError("synthetic missing hftbacktest")
            if problem == "missing-transitive":
                raise ModuleNotFoundError("synthetic missing dependency")
            if problem == "engine-bug":
                raise RuntimeError("synthetic engine initialization failure")
            return engine
        if name == "hftbacktest.order":
            return orders
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(common.importlib, "import_module", fake_import)


def _run_cli(monkeypatch, path, *args):
    monkeypatch.setattr(sys, "argv", [str(path), *map(str, args)])
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(path), run_name="__main__")
    return caught.value.code


@pytest.mark.parametrize(("directory", "entry"), ENTRIES)
@pytest.mark.parametrize("problem", ("missing-package", "missing-transitive", "missing-api"))
def test_hft_entrypoints_block_missing_engine_before_running(
    tmp_path, monkeypatch, capsys, directory, entry, problem
):
    common = _load_common(monkeypatch, directory)
    comparison = importlib.import_module("backtrader.brokers.hft.binance_bbo_compare")
    monkeypatch.setattr(
        comparison,
        "run_binance_bbo_hftbacktest_strategy",
        lambda **kwargs: pytest.fail("hft engine was called"),
    )
    monkeypatch.setattr(
        comparison,
        "compare_binance_bbo_strategy",
        lambda **kwargs: pytest.fail("comparison was called"),
    )
    _fake_engine_import(monkeypatch, common, problem)
    monkeypatch.chdir(tmp_path)
    option = "--data-dir" if directory.startswith("002") else "--data-root"
    assert _run_cli(monkeypatch, EXAMPLES / directory / entry, option, "missing") == 2
    output = capsys.readouterr().out
    assert "BLOCKED" in output
    assert "hftbacktest" in output


@pytest.mark.parametrize(("directory", "entry"), ENTRIES)
def test_hft_entrypoints_block_missing_relative_input(
    tmp_path, monkeypatch, capsys, directory, entry
):
    common = _load_common(monkeypatch, directory)
    comparison = importlib.import_module("backtrader.brokers.hft.binance_bbo_compare")
    monkeypatch.setattr(
        comparison,
        "run_binance_bbo_hftbacktest_strategy",
        lambda **kwargs: pytest.fail("hft engine was called"),
    )
    monkeypatch.setattr(
        comparison,
        "compare_binance_bbo_strategy",
        lambda **kwargs: pytest.fail("comparison was called"),
    )
    _fake_engine_import(monkeypatch, common)
    monkeypatch.chdir(tmp_path)
    option = "--data-dir" if directory.startswith("002") else "--data-root"
    assert _run_cli(monkeypatch, EXAMPLES / directory / entry, option, "missing") == 2
    output = capsys.readouterr().out
    assert "BLOCKED: missing data" in output
    assert "missing" in output


@pytest.mark.parametrize("directory", ("002_hft_alignment_demo", "003_hft_notebook_examples"))
def test_engine_runtime_error_is_not_misreported_as_missing(
    tmp_path, monkeypatch, capsys, directory
):
    common = _load_common(monkeypatch, directory)
    importlib.import_module("backtrader.brokers.hft.binance_bbo_compare")
    _fake_engine_import(monkeypatch, common, "engine-bug")
    monkeypatch.chdir(tmp_path)
    option = "--data-dir" if directory.startswith("002") else "--data-root"
    with pytest.raises(RuntimeError, match="synthetic engine initialization failure"):
        _run_cli(monkeypatch, EXAMPLES / directory / "run_hftbacktest.py", option, "missing")
    assert "BLOCKED" not in capsys.readouterr().out


@pytest.mark.parametrize("directory", ("002_hft_alignment_demo", "003_hft_notebook_examples"))
def test_invalid_strategy_is_a_parser_error_not_a_dependency_block(
    tmp_path, monkeypatch, capsys, directory
):
    _load_common(monkeypatch, directory)
    monkeypatch.chdir(tmp_path)
    assert (
        _run_cli(monkeypatch, EXAMPLES / directory / "run_hftbacktest.py", "--strategy", "bad") == 2
    )
    captured = capsys.readouterr()
    assert "invalid choice" in captured.err
    assert "BLOCKED" not in captured.out


@dataclasses.dataclass
class _EngineResult:
    fills: tuple = ()
    balance: float = 100.0
    position: float = 0.0
    num_trades: int = 0


@dataclasses.dataclass
class _Comparison:
    backtrader: _EngineResult = dataclasses.field(default_factory=_EngineResult)
    hftbacktest: _EngineResult = dataclasses.field(default_factory=_EngineResult)
    matches: dict = dataclasses.field(default_factory=dict)


@pytest.mark.parametrize(("directory", "entry"), ENTRIES)
def test_hft_entrypoints_use_relative_input_from_callers_cwd(
    tmp_path, monkeypatch, capsys, directory, entry
):
    common = _load_common(monkeypatch, directory)
    comparison = importlib.import_module("backtrader.brokers.hft.binance_bbo_compare")
    _fake_engine_import(monkeypatch, common)
    monkeypatch.chdir(tmp_path)
    data_root = tmp_path / "input"
    if directory.startswith("002"):
        paths = common.default_paths(data_root)
        option = "--data-dir"
    else:
        paths = common.default_paths(common.DEFAULT_STRATEGY, data_root)
        option = "--data-root"
    for name in ("orderbook", "ticks", "market_data"):
        paths[name].parent.mkdir(parents=True, exist_ok=True)
        paths[name].touch()

    seen = []

    def fake_run(**kwargs):
        seen.append(kwargs)
        return _Comparison()

    monkeypatch.setattr(comparison, "run_binance_bbo_hftbacktest_strategy", fake_run)
    monkeypatch.setattr(comparison, "compare_binance_bbo_strategy", fake_run)
    monkeypatch.setattr(comparison, "engine_result_to_json", lambda result: "{}")
    assert _run_cli(monkeypatch, EXAMPLES / directory / entry, option, "input") == 0
    assert seen
    for call in seen:
        assert call["market_data_path"].resolve() == paths["market_data"]
        assert call["orderbook_path"].resolve() == paths["orderbook"]
        assert call["tick_path"].resolve() == paths["ticks"]
    payload = json.loads(capsys.readouterr().out)
    if entry == "compare_all.py":
        assert len(payload["results"]) == len(seen)


def _load_prepare(monkeypatch):
    monkeypatch.delenv("BINANCE_PUBLIC_DATA_DIR", raising=False)
    path = EXAMPLES / "003_hft_notebook_examples" / "prepare_data.py"
    spec = importlib.util.spec_from_file_location("iter61_prepare_data", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("explicit_skip", (False, True))
def test_prepare_glft_missing_local_source_does_not_download_or_write(
    tmp_path, monkeypatch, capsys, explicit_skip
):
    module = _load_prepare(monkeypatch)
    calls = []
    monkeypatch.setattr(module, "_run_local_downloader", lambda *args: calls.append("local"))
    monkeypatch.setattr(
        module, "_direct_download_futures_daily", lambda *args: calls.append("http")
    )
    monkeypatch.chdir(tmp_path)
    args = [
        "prepare_data.py",
        "--prepare-glft",
        "--data-root",
        "output",
        "--binance-project-root",
        "project",
        "--binance-source-root",
        "source",
    ]
    if explicit_skip:
        args.append("--skip-download")
    monkeypatch.setattr(sys, "argv", args)
    assert module.main() == 2
    assert "BLOCKED" in capsys.readouterr().out
    assert calls == []
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("download", (False, True))
def test_prepare_glft_download_is_explicit(tmp_path, monkeypatch, capsys, download):
    module = _load_prepare(monkeypatch)
    source_root = tmp_path / "source"
    project_root = tmp_path / "project"
    calls = []

    def local_downloader(*args):
        calls.append("local-downloader")

    def direct_download(root, symbol, kind, date):
        calls.append("download-substitute")
        output = module._local_futures_daily_path(root, symbol, kind, date)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"synthetic placeholder")
        return output

    def prepare(data_root, actual_source, actual_project, date, skip_download):
        assert actual_source.resolve() == source_root
        assert actual_project.resolve() == project_root
        path = module._ensure_local_futures_daily(
            actual_source, actual_project, "ETHUSDT", "trades", date, skip_download
        )
        return {"source": str(path)}

    monkeypatch.setattr(module, "_run_local_downloader", local_downloader)
    monkeypatch.setattr(module, "_direct_download_futures_daily", direct_download)
    monkeypatch.setattr(module, "_prepare_glft_dataset", prepare)
    monkeypatch.chdir(tmp_path)
    args = [
        "prepare_data.py",
        "--prepare-glft",
        "--data-root",
        "output",
        "--binance-project-root",
        "project",
        "--binance-source-root",
        "source",
    ]
    if download:
        args.append("--download")
    monkeypatch.setattr(sys, "argv", args)
    code = module.main()
    if download:
        assert code == 0
        assert calls == ["local-downloader", "download-substitute"]
        assert "glft" in json.loads(capsys.readouterr().out)
    else:
        assert code == 2
        assert calls == []
        assert "BLOCKED" in capsys.readouterr().out


def _spot_prepare_cli_args(tmp_path):
    return [
        "prepare_data.py",
        "--prepare-btc-alpha",
        "--download",
        "--data-root",
        str(tmp_path / "output"),
        "--binance-project-root",
        str(tmp_path / "project"),
        "--binance-source-root",
        str(tmp_path / "source"),
    ]


def _http_error(code):
    return urllib.error.HTTPError("https://synthetic.invalid/file", code, "synthetic", {}, None)


@pytest.mark.parametrize(
    "failure",
    (
        PermissionError("synthetic permission failure"),
        _http_error(403),
        urllib.error.URLError("synthetic connection failure"),
        TimeoutError("synthetic timeout"),
    ),
    ids=("permission", "http-403", "connection", "timeout"),
)
def test_prepare_spot_download_failures_are_not_missing_data(
    tmp_path, monkeypatch, capsys, failure
):
    module = _load_prepare(monkeypatch)
    monkeypatch.setattr(module, "_ensure_local_futures_daily", lambda *args: tmp_path / "unused")
    calls = []

    def failed_download(*args):
        calls.append(args[2])
        raise failure

    monkeypatch.setattr(module, "_direct_download_spot_daily", failed_download)
    monkeypatch.setattr(sys, "argv", _spot_prepare_cli_args(tmp_path))
    with pytest.raises(type(failure)) as exc:
        module.main()
    assert exc.value is failure
    assert calls == ["trades"]
    assert "BLOCKED" not in capsys.readouterr().out
    assert not (tmp_path / "output").exists()


def test_prepare_spot_download_local_file_failure_is_not_missing_source(
    tmp_path, monkeypatch, capsys
):
    module = _load_prepare(monkeypatch)
    monkeypatch.setattr(module, "_ensure_local_futures_daily", lambda *args: tmp_path / "unused")
    failure = FileNotFoundError("synthetic failed output write")

    def failed_download(*args):
        raise failure

    monkeypatch.setattr(module, "_direct_download_spot_daily", failed_download)
    monkeypatch.setattr(sys, "argv", _spot_prepare_cli_args(tmp_path))
    with pytest.raises(RuntimeError, match="spot download") as exc:
        module.main()
    assert exc.value.__cause__ is failure
    assert "BLOCKED" not in capsys.readouterr().out


@pytest.mark.parametrize("fallback", ("alternate-daily", "local-monthly", "none"))
def test_spot_download_404_falls_back_or_reports_missing(tmp_path, monkeypatch, fallback):
    module = _load_prepare(monkeypatch)
    calls = []
    monthly = module._local_spot_monthly_candidates(tmp_path, "BTCUSDT", "2024-09-01")[0]
    if fallback == "local-monthly":
        monthly.parent.mkdir(parents=True, exist_ok=True)
        monthly.touch()

    def fake_download(root, symbol, kind, date):
        calls.append(kind)
        if kind == "aggTrades" and fallback == "alternate-daily":
            path = module._local_spot_daily_candidates(root, symbol, date)[1]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
            return path
        raise _http_error(404)

    monkeypatch.setattr(module, "_direct_download_spot_daily", fake_download)
    if fallback == "none":
        with pytest.raises(FileNotFoundError, match="Missing spot source file"):
            module._resolve_local_spot_source(tmp_path, "BTCUSDT", "2024-09-01", False)
    else:
        result = module._resolve_local_spot_source(tmp_path, "BTCUSDT", "2024-09-01", False)
        assert result == (
            monthly
            if fallback == "local-monthly"
            else module._local_spot_daily_candidates(tmp_path, "BTCUSDT", "2024-09-01")[1]
        )
    assert calls == ["trades", "aggTrades"]


def test_spot_missing_source_reports_blocked_when_all_daily_downloads_404(
    tmp_path, monkeypatch, capsys
):
    module = _load_prepare(monkeypatch)
    monkeypatch.setattr(module, "_ensure_local_futures_daily", lambda *args: tmp_path / "unused")

    def not_found(*args):
        raise _http_error(404)

    monkeypatch.setattr(module, "_direct_download_spot_daily", not_found)
    monkeypatch.setattr(sys, "argv", _spot_prepare_cli_args(tmp_path))
    assert module.main() == 2
    assert "BLOCKED: Missing spot source file" in capsys.readouterr().out


def test_spot_missing_source_never_calls_download_without_opt_in(tmp_path, monkeypatch):
    module = _load_prepare(monkeypatch)
    monkeypatch.setattr(
        module, "_direct_download_spot_daily", lambda *args: pytest.fail("unexpected download")
    )
    with pytest.raises(FileNotFoundError, match="Missing spot source file"):
        module._resolve_local_spot_source(tmp_path, "BTCUSDT", "2024-09-01", True)
