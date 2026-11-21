"""Exercise report classification without starting Cerebro."""

from copy import deepcopy

from parity_harness_frozen_r4 import CASES, EXTRA_CLASSES, compare

base = {
    "status": "completed",
    "denied": [],
    "actual_mode": "next",
    "minperiod": 3,
    "lines": {
        "first": [float(i) for i in range(128)],
        "second": ["nan"] * 2 + [0.0] * 126,
    },
}
other = deepcopy(base)
other["actual_mode"] = "once"
assert compare("arrows_finite", base, other)["status"] == "parity_sample"
changed = deepcopy(other)
changed["lines"]["second"][0] = 1.0
assert compare("arrows_finite", base, changed)["status"] == "values_mismatch"
changed = deepcopy(other)
changed["lines"]["first"].pop()
assert compare("arrows_finite", base, changed)["status"] == "line_layout_mismatch"
changed = deepcopy(other)
changed["minperiod"] = 4
assert compare("arrows_finite", base, changed)["status"] == "minperiod_mismatch"
changed = deepcopy(other)
changed["actual_mode"] = "next"
assert compare("arrows_finite", base, changed)["status"] == "mode_not_exercised"
changed = deepcopy(other)
changed["denied"] = ["operation:socket.connect"]
assert compare("arrows_finite", base, changed)["status"] == "denied_caught"
all_nan = deepcopy(base)
all_nan["lines"]["second"] = ["nan"] * 128
other_nan = deepcopy(all_nan)
other_nan["actual_mode"] = "once"
assert (
    compare("arrows_finite", all_nan, other_nan)["status"]
    == "inconclusive_all_nonfinite"
)
assert (
    compare("arrows_finite", {"status": "timeout"}, other)["next_status"] == "timeout"
)
short = {
    "status": "insufficient_history",
    "required": 201,
    "available": 128,
    "denied": [],
}
assert compare("arrows_finite", short, short)["status"] == "insufficient_history"
different = dict(short, required=202)
assert compare("arrows_finite", short, different)["status"] == "minperiod_mismatch"
denied_short = dict(short, denied=["operation:socket.connect"])
assert compare("arrows_finite", short, denied_short)["status"] == "denied_caught"
invalid = dict(short, required=128)
assert (
    compare("arrows_finite", invalid, invalid)["status"]
    == "inconsistent_short_history_report"
)
unsupported = dict(short, required="201")
assert (
    compare("arrows_finite", unsupported, unsupported)["status"]
    == "minperiod_unsupported_type"
)
long_left, long_right = deepcopy(base), deepcopy(other)
long_left["minperiod"] = long_right["minperiod"] = 129
assert (
    compare("arrows_finite", long_left, long_right)["status"] == "insufficient_history"
)
assert len({"r4_" + cls for _, cls in EXTRA_CLASSES}) == len(EXTRA_CLASSES) == 23
assert CASES["r4_ForceIndexEMA"][1] == "ForceIndexEMA"
assert CASES["r4_ForceIndexEma"][1] == "ForceIndexEma"
assert CASES["r4_ForceIndexEMA"][0] != CASES["r4_ForceIndexEma"][0]
print("14 comparator and 4 identity checks passed")
