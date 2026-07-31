from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from backtrader_mcp.service import BacktraderMCPService
from backtrader_mcp.settings import Settings
from backtrader_mcp.util import sha256_json

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def service_env(tmp_path: Path) -> tuple[BacktraderMCPService, Path, Path]:
    source = tmp_path / "source"
    target = tmp_path / "target"
    state = tmp_path / "state"
    source.mkdir()
    target.mkdir()
    csv_path = source / "prices.csv"
    lines = ["datetime,open,high,low,close,volume"]
    start = date(2023, 1, 1)
    for index in range(180):
        close = 100.0 + index * 0.1 + ((index % 10) - 5) * 0.8
        lines.append(
            f"{start + timedelta(days=index)},{close - 0.2:.4f},{close + 1:.4f},"
            f"{close - 1:.4f},{close:.4f},{1000 + index}"
        )
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    settings = Settings(
        state_root=state,
        source_roots={"market": source},
        target_roots={"strategies": target},
        runtimes={"default": REPOSITORY_ROOT},
        max_run_seconds=30,
    )
    return BacktraderMCPService(settings), source, target


@pytest.fixture()
def registered_dataset(service_env):
    service, source, _ = service_env
    (source / "secondary.csv").write_bytes((source / "prices.csv").read_bytes())
    columns = {
        "datetime": "datetime",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    }
    feeds = [
        {
            "name": name,
            "role": role,
            "symbol": name.upper(),
            "source": {
                "root_id": "market",
                "relative_path": relative_path,
                "source_type": "local_file",
            },
            "format": "generic_csv",
            "timeframe": "days",
            "compression": 1,
            "timezone": "UTC",
            "columns": columns,
        }
        for name, role, relative_path in (
            ("primary", "execution", "prices.csv"),
            ("secondary", "signal", "secondary.csv"),
        )
    ]
    core = {
        "schema_version": "data-spec-v1",
        "feeds": feeds,
        "master_feed": "primary",
        "alignment": {"mode": "intersection", "minimum_overlap": 1.0},
        "transforms": [],
    }
    dataset = service.register_local_dataset({**core, "spec_hash": sha256_json(core)})
    return service, dataset


def canonical_spec(dataset_id: str, archetype: str, profile: str = "python_bundle"):
    feed_count = (
        2
        if archetype
        in {
            "multi_asset_allocation",
            "multi_timeframe",
            "pairs_spread",
        }
        else 1
    )
    return {
        "spec_version": "strategy-spec-v1",
        "name": f"{archetype} example",
        "slug": f"{archetype.replace('_', '-')}-example",
        "category": "strategy",
        "archetype": archetype,
        "output_profile": profile,
        "dataset_id": dataset_id,
        "feeds": [
            {
                "name": "primary" if index == 0 else "secondary",
                "dataset_feed": "primary" if index == 0 else "secondary",
            }
            for index in range(feed_count)
        ],
        "parameters": {"period": 5, "fast": 3, "slow": 7, "rsi_period": 4},
        "entry": {"rule": "template"},
        "exit": {"rule": "template"},
        "sizing": {"mode": "fixed_fraction", "starting_cash": 100000.0},
        "risk": {"commission": 0.001, "live_trading": False},
        "run_modes": ["runonce", "runnext"],
        "allowed_imports": ["backtrader"],
    }
