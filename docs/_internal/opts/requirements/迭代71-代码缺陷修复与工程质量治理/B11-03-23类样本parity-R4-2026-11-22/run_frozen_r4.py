"""Bind expanded per-class parity scan to fixed inputs and an isolated Git tree."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRIVER = HERE / "parity_harness_frozen_r4.py"
VERIFY = HERE / "verify_snapshot_r3.py"
STATIC = HERE / "static_review_r3.py"
RESULT = HERE / "expanded_attested_r4_20261122.json"
INVENTORY = HERE / "static_review_attested_r4_20261122.json"
RECEIPT = HERE / "expanded_attested_r4_receipt_20261122.json"
PINS = {
    DRIVER: "2f128a288b4b3544f66cd3d1e1278a11d25fa3282507ec902bca656cd0733dfa",
    VERIFY: "9d2b735b36609ad0b6e77af5a58dceebaf91f3b4161bef1a6c53319873d10b26",
    STATIC: "52ea6cf31ae3ac7ebccb05d2f6c1562b671a6176f562d1c97c65ec70a80e9928",
}
CLASSES = (
    "CandleStopColor",
    "CCIWoodiesIndicator",
    "CGOscillator",
    "ClosePriceFractals",
    "ColorHMA",
    "ColorMetroWprIndicator",
    "ColorX2MA",
    "DarvasBoxesSystem",
    "DotsIndicator",
    "EFDistanceIndicator",
    "EmaRsiVa",
    "EnvelopesJpAlonso",
    "F2aAOIndicator",
    "FatlFilter",
    "FineTuningMA",
    "FisherOrgV1",
    "FisherOrgV1Sign",
    "ForceDiverSign",
    "ForceIndexEMA",
    "ForceIndexEma",
    "ForecastOscilator",
    "FractalAMAMBK",
    "FRASMAv2Indicator",
)
CASES = ["r4_" + name for name in CLASSES] + [
    "derivative_short_history",
    "unreviewed_example",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


assert not any(p.exists() for p in (RESULT, INVENTORY, RECEIPT)), "output exists"
assert all(sha(path) == pin for path, pin in PINS.items())
verify_pre = subprocess.run(
    [sys.executable, "-B", str(VERIFY)],
    cwd=HERE,
    check=True,
    capture_output=True,
    text=True,
    timeout=20,
).stdout.strip()
static_raw = subprocess.check_output(
    [sys.executable, "-B", str(STATIC)], cwd=HERE, timeout=20
)
static = json.loads(static_raw)
assert [row["class"] for row in static["rows"]] == list(CLASSES)
assert len(set(CASES)) == len(CASES)
for row in static["rows"]:
    assert sha(HERE / "snapshot_r3" / row["source"]) == row["sha256"]
with INVENTORY.open("xb") as out:
    out.write(static_raw)
args = [sys.executable, "-B", str(DRIVER)]
for case in CASES:
    args.extend(("--case", case))
args.extend(("--timeout", "15", "--out", str(RESULT)))
completed = subprocess.run(
    args, cwd=HERE, capture_output=True, text=True, timeout=900, check=True
)
verify_post = subprocess.run(
    [sys.executable, "-B", str(VERIFY)],
    cwd=HERE,
    check=True,
    capture_output=True,
    text=True,
    timeout=20,
).stdout.strip()
assert all(sha(path) == pin for path, pin in PINS.items()) and verify_pre == verify_post
result = json.loads(RESULT.read_text(encoding="utf8"))
assert [item["case"] for item in result["cases"]] == CASES
for item, row in zip(result["cases"], static["rows"]):
    assert item["case_spec"][1] == row["class"]
    assert item["case_spec"][0] == "backtrader.indicators.contrib." + row["module"]
assert len({item["case_spec"][1] for item in result["cases"][: len(CLASSES)]}) == len(
    CLASSES
)
receipt = {
    "driver_sha256": PINS[DRIVER],
    "verify_sha256": PINS[VERIFY],
    "static_sha256": PINS[STATIC],
    "runner_sha256": sha(Path(__file__)),
    "result_sha256": sha(RESULT),
    "static_inventory_sha256": sha(INVENTORY),
    "verify_pre": verify_pre,
    "verify_post": verify_post,
    "driver_returncode": completed.returncode,
    "driver_stderr": completed.stderr,
    "case_statuses": [
        (item["case"], item["comparison"]["status"]) for item in result["cases"]
    ],
}
with RECEIPT.open("x", encoding="utf8", newline="\n") as out:
    json.dump(receipt, out, indent=2)
    out.write("\n")
print(json.dumps(receipt, indent=2))
