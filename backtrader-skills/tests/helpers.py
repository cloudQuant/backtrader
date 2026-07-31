from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

from backtrader_skills.data import DataRegistry
from backtrader_skills.runtime import RuntimePaths


def isolated_target(tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    repository = Path(__file__).resolve().parents[2]
    (target / "backtrader").symlink_to(repository / "backtrader", target_is_directory=True)
    return target


def write_market_csv(path: Path, *, phase: float = 0.0, rows: int = 96) -> Path:
    lines = ["datetime,open,high,low,close,volume,openinterest"]
    start = date(2024, 1, 1)
    for index in range(rows):
        close = 100.0 + math.sin(index / 4.0 + phase) * 8.0 + index * 0.04
        opening = close - math.sin(index / 3.0) * 0.5
        high = max(opening, close) + 1.0
        low = min(opening, close) - 1.0
        lines.append(
            f"{start + timedelta(days=index)},{opening:.8f},{high:.8f},"
            f"{low:.8f},{close:.8f},{1000 + index},0"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def register_dataset(
    target: Path,
    data_root: Path,
    *,
    feed_count: int = 1,
) -> dict:
    registry = DataRegistry(RuntimePaths(target))
    registry.add_root(data_root, root_id="prices")
    feeds = []
    for index in range(feed_count):
        name = f"asset{index}"
        file_name = f"{name}.csv"
        write_market_csv(data_root / file_name, phase=index * 0.7)
        feeds.append(
            {
                "name": name,
                "symbol": name.upper(),
                "role": "execution" if index == 0 else "signal",
                "tradable": index == 0,
                "source": {
                    "root_id": "prices",
                    "relative_path": file_name,
                    "source_type": "local_file",
                },
                "format": "generic_csv",
                "columns": {},
                "timeframe": "days",
                "compression": 1,
                "timezone": "UTC",
                "transforms": [],
            }
        )
    return registry.register(
        {
            "schema_version": "data-spec-v1",
            "feeds": feeds,
            "master_feed": "asset0",
            "alignment": "intersection",
            "minimum_overlap": 0.9,
            "license": "test-only",
            "sensitivity": "public",
        }
    )
