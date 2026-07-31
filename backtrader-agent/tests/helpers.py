import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def write_price_csv(
    path: Path,
    *,
    rows: int = 40,
    include_signal: bool = True,
    price_offset: float = 0.0,
) -> Path:
    header = "date,open,high,low,close,volume,openinterest"
    if include_signal:
        header += ",signal"
    lines = [header]
    for index in range(rows):
        day = index + 1
        date = f"2024-01-{day:02d}" if day <= 31 else f"2024-02-{day - 31:02d}"
        close = 100.0 + price_offset + index
        row = (
            f"{date},{close - 0.5:.2f},{close + 1:.2f},{close - 1:.2f},"
            f"{close:.2f},{1000 + index},0"
        )
        if include_signal:
            row += f",{1 if index % 4 < 2 else -1}"
        lines.append(row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_adapter_price_csv(
    path: Path,
    adapter: str,
    *,
    rows: int = 40,
    price_offset: float = 0.0,
) -> Path:
    """Write the native, offline text shape accepted by one P0 adapter."""

    delimiter = "\t" if adapter == "mt5_csv" else ","
    headers = {
        "generic_csv": [
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "openinterest",
        ],
        "backtrader_csv": [
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "openinterest",
        ],
        "yahoo_csv": ["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"],
        "mt5_csv": ["<DATE>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>", "<TICKVOL>"],
        "pandas": [
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "openinterest",
        ],
        "pandas_custom_lines": [
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "openinterest",
            "signal",
        ],
    }
    lines = [delimiter.join(headers[adapter])]
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for index in range(rows):
        timestamp = start + timedelta(days=index)
        close = 100.0 + price_offset + index
        date_values = {
            "generic_csv": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "backtrader_csv": timestamp.strftime("%Y-%m-%d"),
            "yahoo_csv": timestamp.strftime("%Y-%m-%d"),
            "mt5_csv": timestamp.strftime("%Y.%m.%d %H:%M:%S"),
            "pandas": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pandas_custom_lines": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        values = [
            date_values[adapter],
            f"{close - 0.5:.2f}",
            f"{close + 1:.2f}",
            f"{close - 1:.2f}",
            f"{close:.2f}",
        ]
        if adapter == "yahoo_csv":
            values.extend([f"{close:.2f}", str(1000 + index)])
        elif adapter == "mt5_csv":
            values.append(str(1000 + index))
        else:
            values.extend([str(1000 + index), "0"])
        if adapter == "pandas_custom_lines":
            values.append(str(1 if index % 4 < 2 else -1))
        lines.append(delimiter.join(values))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def data_spec(relative_path: str = "prices.csv") -> dict:
    return {
        "schema_version": "dataset-manifest-v1",
        "name": "fixture-prices",
        "feeds": [
            {
                "feed_id": "primary",
                "name": "primary",
                "role": "execution",
                "root_id": "input",
                "relative_path": relative_path,
                "format": "generic_csv",
                "datetime_format": "%Y-%m-%d",
                "timeframe": "Days",
                "compression": 1,
                "timezone": "UTC",
                "bar_semantics": "close",
                "columns": {
                    "datetime": "date",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "volume": "volume",
                    "openinterest": "openinterest",
                    "signal": "signal",
                },
            }
        ],
        "alignment": {"mode": "intersection", "minimum_overlap": 1},
    }


def strategy_spec(
    dataset_id: str,
    *,
    archetype: str = "single_data_indicator",
    profile: str = "python_bundle",
) -> dict:
    return {
        "spec_version": "strategy-spec-v1",
        "name": "Fixture Momentum",
        "slug": "fixture_momentum",
        "category": "trend_following",
        "archetype": archetype,
        "output_profile": profile,
        "dataset_id": dataset_id,
        "feeds": [{"name": "primary", "role": "execution"}],
        "parameters": {
            "fast_period": {"type": "integer", "default": 5, "minimum": 2},
            "slow_period": {"type": "integer", "default": 12, "minimum": 3},
        },
        "entry": "long when the fast signal is above the slow signal",
        "exit": "close when the fast signal is below the slow signal",
        "sizing": {"kind": "fixed", "stake": 1},
        "risk": {"max_position": 1},
        "cash": 100000.0,
        "commission": 0.001,
        "analyzers": ["TradeAnalyzer", "DrawDown", "SharpeRatio", "SQN"],
        "run_modes": ["runonce", "runnext"],
        "allowed_imports": ["backtrader", "json", "os", "math"],
        "non_goals": ["live trading"],
        "open_questions": [],
    }


def dump_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
