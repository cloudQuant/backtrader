"""Verify reduced public snapshot against fixed Git archive without Git writes."""

import hashlib
import io
import subprocess
import tarfile
from pathlib import Path

HEAD = "c5fc2e7e954eae104d4acae5accdd9bf30e9c44d"
snapshot = Path(__file__).resolve().parent / "snapshot_r3"
paths = [
    ":(glob)backtrader/*.py",
    ":(exclude)backtrader/store.py",
    "backtrader/_cerebro",
    ":(glob)backtrader/indicators/*.py",
    "backtrader/feeds/__init__.py",
    "backtrader/feeds/barrier.py",
    "backtrader/feeds/pandafeed.py",
    "backtrader/brokers/__init__.py",
    "backtrader/brokers/bbroker.py",
    "backtrader/sizers/fixedsize.py",
    "backtrader/utils",
    ":(exclude)backtrader/utils/runtime_redaction.py",
    "backtrader/notifications",
]
for name in (
    "adxdmi",
    "ai_acceleration_deceleration_oscillator",
    "altr_trend_signal_v22",
    "aroon_horn_sign_indicator",
    "arrows_curves_indicator",
    "asimmetric_stoch_nr_indicator",
    "atr_normalize_histogram",
    "average_change_candle",
    "blau_t_stoch_i",
    "blau_tvi",
    "breakout_bars_trend_v2",
    "bsi_indicator",
    "bulls_power",
    "derivative_indicator",
    "candle_stop_color",
    "cci_woodies_indicator",
    "cg_oscillator",
    "close_price_fractals",
    "color_hma",
    "color_metro_wpr_indicator",
    "color_x2_ma",
    "darvas_boxes_system",
    "dots_indicator",
    "ef_distance_indicator",
    "ema_rsi_va",
    "envelopes_jp_alonso",
    "f2a_ao_indicator",
    "fatl_filter",
    "fine_tuning_ma",
    "fisher_org_v1",
    "fisher_org_v1_sign",
    "force_index_ema",
    "force_index_ema_2",
    "forecast_oscilator",
    "fractal_amambk",
    "frasm_av2_indicator",
):
    paths.append(f"backtrader/indicators/contrib/{name}.py")
raw = subprocess.check_output(
    [
        "git",
        "-C",
        "D:/source_code/backtrader",
        "archive",
        "--format=tar",
        HEAD,
        "--",
        *paths,
    ]
)
expected = {}
with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
    for member in archive.getmembers():
        if member.isfile():
            expected[member.name] = archive.extractfile(member).read()
actual = {
    p.relative_to(snapshot).as_posix(): p for p in snapshot.rglob("*") if p.is_file()
}
assert set(actual) == set(expected), "snapshot path set differs"
for name, content in expected.items():
    assert actual[name].read_bytes() == content, f"snapshot bytes differ: {name}"
print(
    "git head",
    HEAD,
    "files",
    len(expected),
    "archive sha256",
    hashlib.sha256(raw).hexdigest(),
)
