"""Focused contracts for the bounded multi-target Alpha003 preflight."""

import math
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "run_iteration50_live_factor_benchmark.py"


def _load_benchmark_module():
    spec = spec_from_file_location("iteration50_live_factor_capacity", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_twenty_target_profile_keeps_the_frozen_generator_contract(tmp_path):
    module = _load_benchmark_module()
    args = module._parse_args(
        ["--mode", "native", "--smoke", "--output", str(tmp_path / "default.json")]
    )

    assert args.assets == 20
    assert module._validate_cli(args)[0] == module.DEFAULT_SMOKE_GRIDS
    assert module._target_ids(args.assets) == tuple("ASSET%02d" % i for i in range(20))
    assert module._source_generator_sha256("alpha003") == (
        "e5825a532fbcc32191b64a6bfd4c68cdbb4fff1cf494a0ff6ecc155770badbd8"
    )
    for asset_index, grid_index in ((0, 0), (19, 63), (7, 101)):
        assert module._event_values_for_count(asset_index, grid_index, 20) == module._event_values(
            asset_index, grid_index
        )


def test_eighty_seven_targets_are_reported_and_hash_as_a_distinct_input(tmp_path):
    module = _load_benchmark_module()
    args = module._parse_args(
        ["--mode", "build", "--assets", "87", "--smoke", "--output", str(tmp_path / "87.json")]
    )
    targets = module._target_ids(args.assets)
    open_values = [module._event_values_for_count(i, 0, args.assets)["open"] for i in range(87)]
    volume_positions = [
        module._event_values_for_count(i, 0, args.assets)["volume"] for i in range(87)
    ]

    assert module._validate_cli(args)[0] == module.DEFAULT_SMOKE_GRIDS
    assert args.assets == 87
    assert len(targets) == len(set(targets)) == 87
    assert targets[0] == "ASSET00" and targets[-1] == "ASSET86"
    assert len(set(open_values)) == len(set(volume_positions)) == 87
    for grid_index in range(24):
        for asset_index in range(87):
            row = module._event_values_for_count(asset_index, grid_index, 87)
            assert row["open"] == 100.0 + (asset_index * 7 + grid_index * 3) % 87
            expected_volume_position = (asset_index * 13 + grid_index * 7) % 87
            phase = (asset_index + 1) * (grid_index + 1) * 0.08
            assert row["volume"] == (
                1000.0 + expected_volume_position + 0.05 * math.sin(phase * 0.73)
            )
    assert module._source_generator_sha256("alpha003", target_count=87) != (
        module._source_generator_sha256("alpha003")
    )


@pytest.mark.parametrize("asset_count", (3, 7, 13, 91))
def test_asset_generator_keeps_each_small_universe_rankable(asset_count):
    module = _load_benchmark_module()
    expected_rank_set = {(rank + 1) / asset_count for rank in range(asset_count)}
    open_by_asset = [[] for _ in range(asset_count)]
    volume_by_asset = [[] for _ in range(asset_count)]

    for grid_index in range(asset_count):
        rows = [
            module._event_values_for_count(asset_index, grid_index, asset_count)
            for asset_index in range(asset_count)
        ]
        open_values = [row["open"] for row in rows]
        volume_values = [row["volume"] for row in rows]
        open_ranks = module._average_ranks(open_values)
        volume_ranks = module._average_ranks(volume_values)

        assert len(set(open_values)) == asset_count
        assert len(set(volume_values)) == asset_count
        assert set(open_ranks) == expected_rank_set
        assert set(volume_ranks) == expected_rank_set
        for asset_index, row in enumerate(rows):
            open_by_asset[asset_index].append(row["open"])
            volume_by_asset[asset_index].append(row["volume"])

    assert all(len(set(values)) > 1 for values in open_by_asset)
    assert all(len(set(values)) > 1 for values in volume_by_asset)


@pytest.mark.parametrize("asset_count", (0, 1, 257, -1))
def test_asset_count_outside_bounded_alpha003_range_is_rejected(asset_count, tmp_path):
    module = _load_benchmark_module()
    args = module._parse_args(
        [
            "--mode",
            "native",
            "--assets",
            str(asset_count),
            "--smoke",
            "--output",
            str(tmp_path / ("invalid-%d.json" % asset_count)),
        ]
    )

    with pytest.raises(module.BenchmarkFailure, match="asset_count_out_of_range"):
        module._validate_cli(args)


def test_capacity_gate_limits_scale_with_the_reported_target_count():
    module = _load_benchmark_module()
    report = {
        "profile": {"kind": "SMOKE_COMPOSITION", "scenario": "standard", "target_count": 87},
        "capacities": {
            "source_rows_retained_max": 87,
            "configured_window_bars_per_member": 64,
            "retained_receipts_at_end": 87 * 64,
        },
    }

    _, failures = module._check_gates(report)
    assert "profile_target_count_out_of_range" not in failures
    assert "source_leaf_retained_more_than_one_member_row_per_asset" not in failures
    assert "cohort_receipts_exceeded_configured_rolling_window" not in failures

    report["capacities"]["source_rows_retained_max"] = 88
    report["capacities"]["retained_receipts_at_end"] = 87 * 64 + 1
    _, failures = module._check_gates(report)
    assert "source_leaf_retained_more_than_one_member_row_per_asset" in failures
    assert "cohort_receipts_exceeded_configured_rolling_window" in failures


def test_windows_rss_reader_uses_pointer_sized_handle_and_typed_api(monkeypatch):
    import ctypes
    from ctypes import wintypes

    module = _load_benchmark_module()
    handle_value = 0x12345678ABCDEF01

    class FakeFunction:
        def __init__(self, callback):
            self.callback = callback
            self.argtypes = None
            self.restype = None
            self.calls = []

        def __call__(self, *args):
            self.calls.append(args)
            return self.callback(*args)

    get_current_process = FakeFunction(lambda: ctypes.c_void_p(handle_value))

    def populate_memory_info(process, counters_pointer, size):
        assert process.value == handle_value
        counters = counters_pointer._obj
        assert size == counters.cb
        counters.WorkingSetSize = 987654321
        return 1

    get_process_memory_info = FakeFunction(populate_memory_info)
    libraries = {
        "kernel32": type("Kernel32", (), {"GetCurrentProcess": get_current_process})(),
        "psapi": type("Psapi", (), {"GetProcessMemoryInfo": get_process_memory_info})(),
    }

    def fake_windll(name, *, use_last_error):
        assert use_last_error is True
        return libraries[name]

    monkeypatch.setattr(ctypes, "WinDLL", fake_windll, raising=False)

    assert module._read_windows_working_set_bytes() == 987654321
    assert get_current_process.argtypes == []
    assert get_current_process.restype is wintypes.HANDLE
    assert get_process_memory_info.argtypes[0] is wintypes.HANDLE
    assert issubclass(get_process_memory_info.argtypes[1]._type_, ctypes.Structure)
    assert get_process_memory_info.argtypes[2] is wintypes.DWORD
    assert get_process_memory_info.restype is wintypes.BOOL
    assert len(get_current_process.calls) == len(get_process_memory_info.calls) == 1


def test_windows_rss_reader_rejects_failed_native_query(monkeypatch):
    import ctypes

    module = _load_benchmark_module()

    class FakeFunction:
        def __init__(self, callback):
            self.callback = callback
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self.callback(*args)

    get_current_process = FakeFunction(lambda: ctypes.c_void_p(0x12345678ABCDEF01))
    get_process_memory_info = FakeFunction(lambda *_args: 0)
    libraries = {
        "kernel32": type("Kernel32", (), {"GetCurrentProcess": get_current_process})(),
        "psapi": type("Psapi", (), {"GetProcessMemoryInfo": get_process_memory_info})(),
    }
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda name, *, use_last_error: libraries[name],
        raising=False,
    )

    with pytest.raises(module.BenchmarkFailure, match="rss_sampling_failed"):
        module._read_windows_working_set_bytes()
